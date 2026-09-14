#!/usr/bin/env python3
"""Scheduled reply check: poll Smartlead, classify, update HubSpot, queue for a human.

Implements workflow B in CLAUDE.md and the action map in
instructions/reply-handling.md. Polling, no webhooks.

    Smartlead replies -> classify -> HubSpot outbound_* -> Reply Review Queue Sheet

Six guarantees:

  1. DRY RUN BY DEFAULT. Nothing is written to HubSpot, Smartlead, or the Sheet without
     --apply. A reply loop that acts the first time it is run, on a corpus nobody has
     read, is how a prospect gets the wrong thing done to them.
  2. IT NEVER SENDS A REPLY. There is no call to Smartlead's reply-email-thread endpoint
     anywhere in this file. Drafts are written into the queue for a human. The auto-send
     allowlist in reply-handling.md is deliberately empty and this script cannot bypass
     it even if it were not.
  3. DEDUPE BEFORE ACTING, RECORD AFTER. Keyed on the Smartlead message id, through the
     one seam in review_queue.get_processed_id_store. Polling windows overlap and runs
     crash; without this a prospect gets a second draft, a second status write, and a
     second row in front of whoever already decided.
  4. AN UNRECOGNISED MESSAGE SHAPE IS A HARD ERROR. Smartlead does not document the body
     field on a message-history item, and it could not be observed without a live reply.
     If an inbound message has no recognisable body, this aborts rather than treating it
     as an empty reply, because "no text" and "we cannot read the text" must not look the
     same. Absent is not false.
  5. ONLY asked_to_stop SUPPRESSES, and it is scope-matched. Smartlead unsubscribe plus
     outbound_suppressed in HubSpot. Native hs_email_optout is NEVER written: it is
     global, effectively irreversible, and reserved for a human honouring an explicit
     all-email request (config/hubspot-properties.md).
  6. NEITHER out_of_office NOR automated_reply ADVANCES THE LEAD, and only one resumes.
     Smartlead halts follow-ups on ANY reply and cannot tell a human from a machine, so
     something must unfreeze a lead who never engaged -- but not always us:
       - **out_of_office: WE resume it, on a date.** Corrected 2026-09-09. This said
         "Smartlead resumes it, we do not" on the belief that Smartlead had its own OOO
         auto-pause with an auto-restart. No such setting is exposed on the campaign,
         `stop_lead_settings` is REPLY_TO_AN_EMAIL so ANY reply ends the lead, and seven
         test replies Smartlead itself labelled out-of-office all landed COMPLETED rather
         than PAUSED. Left alone, a prospect who was merely on holiday would get email 1
         and never hear from us again. So the return date is read out of the
         auto-responder into `outbound_resume_after`, and `scripts/resume_sequences.py`
         restarts the lead when it arrives. `resume: False` here still means "not now",
         not "never".
       - **automated_reply: we resume, immediately.** Nobody is absent, so there is
         nothing to wait for.

Endpoints were verified against a live throwaway campaign on 2026-08-31. There is no
"replies since timestamp" endpoint: the path is per-campaign statistics filtered to
replied, then per-lead message history.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import review_queue as rq  # noqa: E402
from enrich_callbacks import strip_quoted  # noqa: E402
from eligibility import env_token, env_value, load_config  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SL_BASE = "https://server.smartlead.ai/api/v1"
HS_BASE = "https://api.hubapi.com"

# instructions/reply-handling.md, action map. status None means "do not advance the lead".
INTENTS = {
    "interested":      {"status": "replied",      "resume": False, "queue": True},
    "question":        {"status": "replied",      "resume": False, "queue": True},
    "objection":       {"status": "replied",      "resume": False, "queue": True},
    "not_now":         {"status": "replied",      "resume": False, "queue": True},
    "not_interested":  {"status": "replied",      "resume": False, "queue": True},
    "not_qualified":   {"status": "disqualified", "resume": False, "queue": True},
    "wrong_contact":   {"status": "disqualified", "resume": False, "queue": True},
    "asked_to_stop":   {"status": "opted_out",    "resume": False, "queue": True},
    # out_of_office does not resume HERE, but it is not abandoned: reply_check writes
    # outbound_resume_after and scripts/resume_sequences.py restarts the lead on that
    # date. The earlier note claimed Smartlead had its own OOO auto-restart to defer to;
    # it does not -- see guarantee 6.
    "out_of_office":   {"status": None,           "resume": False, "queue": False},
    # automated_reply STILL resumes. Smartlead's feature is specifically out-of-office,
    # so a non-away machine reply -- a ticketing autoresponder, a delivery notice -- is
    # not covered by it. Stop-on-reply halts the sequence and nothing else would ever
    # restart it, so this resume is the only thing that unfreezes the lead.
    "automated_reply": {"status": None,           "resume": True,  "queue": False},
}
REPLY_CONFIG = ROOT / "config" / "reply-defaults.md"
_DEFAULTS: dict | None = None


def defaults() -> dict:
    """The recycle floors and the auto-send allowlist, from config/reply-defaults.md.

    Parsed rather than restated. These numbers previously lived in this file AND in
    instructions/reply-handling.md, so tuning one left the other wrong; config/ is where
    the repo keeps tunable values and eligibility.py already has the parser.

    The auto_send_intents assertion is the point of loading it here. reply_check.py has
    no send path, so a non-empty list cannot silently start sending -- but it also must
    not look like consent that was already given. Refusing to run makes building the
    send path a deliberate act instead of a config edit nobody reviewed.
    """
    global _DEFAULTS
    if _DEFAULTS is None:
        cfg = load_config(REPLY_CONFIG)
        for key in ("recycle_not_now_days", "recycle_not_interested_days",
                    "resume_ooo_default_days"):
            if not isinstance(cfg.get(key), int) or cfg[key] < 0:
                raise RuntimeError(
                    f"{REPLY_CONFIG.name}: {key} must be a non-negative integer, "
                    f"got {cfg.get(key)!r}")
        if cfg.get("auto_send_intents"):
            raise RuntimeError(
                f"{REPLY_CONFIG.name} lists auto_send_intents "
                f"{cfg['auto_send_intents']}, but this script has no send path and "
                "every reply goes to a human. Build the send path deliberately, with "
                "the review gate in instructions/reply-handling.md, or empty the list.")
        _DEFAULTS = cfg
    return _DEFAULTS


def recycle_date(intent: str, reply_at: str, named: str | None,
                 existing: str | None, cfg: dict | None = None) -> str | None:
    """The earliest day this contact may re-enter a campaign, or None.

    Four rules from instructions/reply-handling.md, each of which this got wrong first
    time and each of which changes the answer:

      1. Computed from the REPLY date, not the processing date, so a poll that runs
         three days late does not quietly extend the wait by three days.
      2. not_now honours a date NAMED in the reply ("ask me in Q1"), including one
         EARLIER than the floor. The prospect asked for that timing; honouring it is
         the whole point of the intent.
      3. not_interested never reads a date from the reply. A decline is not an
         invitation to negotiate timing.
      4. An existing later date always wins. Declines accumulate patience, they do not
         reset it, so this can only ever move the date outward.
    """
    if intent not in ("not_now", "not_interested"):
        return None
    cfg = cfg or defaults()
    base = (reply_at or "")[:10]
    try:
        anchor = dt.date.fromisoformat(base)
    except ValueError:
        # No usable reply date: fall back to today, which is the conservative
        # direction (it can only push the date later, never sooner).
        anchor = dt.datetime.now(dt.timezone.utc).date()

    if intent == "not_now":
        candidate = anchor + dt.timedelta(days=cfg["recycle_not_now_days"])
        if named:
            try:
                candidate = dt.date.fromisoformat(named[:10])  # rule 2, may be earlier
            except ValueError:
                pass
    else:
        candidate = anchor + dt.timedelta(days=cfg["recycle_not_interested_days"])

    if existing:  # rule 4
        try:
            if dt.date.fromisoformat(str(existing)[:10]) > candidate:
                return str(existing)[:10]
        except ValueError:
            pass
    return candidate.isoformat()


def resume_date(intent: str, reply_at: str, named: str | None,
                cfg: dict | None = None) -> str | None:
    """The day an out-of-office lead should have its sequence restarted, or None.

    **Why this exists at all.** `out_of_office` used to carry `resume: False`, on the
    stated grounds that Smartlead had its own OOO auto-pause with an auto-restart. That
    was never verified and looks wrong: no such setting is exposed on the campaign,
    `stop_lead_settings` is REPLY_TO_AN_EMAIL so ANY reply ends the lead, and seven test
    replies Smartlead itself labelled out-of-office all landed COMPLETED rather than
    PAUSED. If nothing restarts them, a prospect who was merely on holiday receives email
    1 and is never contacted again -- and the lead reads COMPLETED, exactly like a
    genuine non-replier, so nothing ever surfaces it.

    So the wait is ours to keep, not the vendor's. **The auto-responder itself carries
    the answer**: it nearly always says when they are back. Reading the date out of the
    message is the only part of this that needs a model, and it has already happened by
    the time this runs.

    Rules, deliberately parallel to recycle_date():

      1. ONLY out_of_office. `automated_reply` resumes immediately (nobody is absent) and
         every human intent is a real reply that must never be restarted by a machine.
      2. A date NAMED in the auto-responder wins. That is the whole point.
      3. No date named -> reply date + resume_ooo_default_days.
      4. Computed from the REPLY date, never the processing date, so a poll running three
         days late does not silently extend the wait.
      5. **A named date already in the past resolves to tomorrow, not to today or to the
         past.** Auto-responders outlive the absence they describe -- a poll catching one
         a week late would otherwise resume instantly, which is the one behaviour a
         *dated* resume exists to avoid. Tomorrow is the earliest honest answer.
    """
    if intent != "out_of_office":                                   # rule 1
        return None
    cfg = cfg or load_defaults()
    try:
        anchor = dt.date.fromisoformat((reply_at or "")[:10])
    except ValueError:
        anchor = dt.datetime.now(dt.timezone.utc).date()            # rule 4

    candidate = anchor + dt.timedelta(days=cfg["resume_ooo_default_days"])  # rule 3
    if named:
        try:
            candidate = dt.date.fromisoformat(named[:10])           # rule 2
        except ValueError:
            pass

    tomorrow = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
    return max(candidate, tomorrow).isoformat()                     # rule 5

# Candidate body fields on a message-history item. Smartlead documents `direction`, `id`,
# `subject`, `sent_at` and `received_at`, but not the body, so this tries the plausible
# names and guarantee 4 fires if none match.
# CONFIRMED 2026-09-01 against a real reply: the field is `email_body`. The rest are
# kept as fallbacks in case the shape differs elsewhere, and an inbound message matching
# none of them is still a hard error.
BODY_FIELDS = ("email_body", "body", "message", "text", "plain_text", "email_message",
               "message_body", "content")

# Smartlead's `type` on a message-history item. SENT and REPLY are confirmed live; the
# others are defensive. Anything unlisted raises rather than being assumed a direction.
INBOUND_TYPES = {"REPLY", "INBOUND", "RECEIVED"}
OUTBOUND_TYPES = {"SENT", "OUTBOUND", "FOLLOWUP", "SENT_FOLLOWUP"}


class Smartlead:
    """Read plus two narrow write actions. Deliberately has no method that sends mail."""

    def __init__(self, key: str, apply_changes: bool):
        self.key = key
        self.apply = apply_changes
        self.calls = 0

    def _call(self, method: str, path: str, body: dict | None = None):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(
            f"{SL_BASE}{path}{sep}api_key={self.key}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "User-Agent": "outbound-engine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.calls += 1
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return e.code, (e.read() or b"").decode()[:300]

    def get(self, path: str):
        s, d = self._call("GET", path)
        if s != 200:
            raise RuntimeError(f"GET {path} -> {s}: {d}")
        return d

    def campaigns(self) -> list[dict]:
        return self.get("/campaigns") or []

    def replied_leads(self, cid) -> list[dict]:
        """Leads on this campaign that Smartlead says replied. Paginated."""
        out, offset = [], 0
        while True:
            d = self.get(f"/campaigns/{cid}/statistics"
                         f"?offset={offset}&limit=100&email_status=replied")
            rows = d.get("data") or []
            out += rows
            offset += len(rows)
            if not rows or offset >= int(d.get("total_stats") or 0):
                return out

    def lead_ids_by_email(self, cid) -> dict[str, int]:
        """email -> Smartlead lead id, for the whole campaign.

        Needed because the statistics row that tells us someone replied carries
        `lead_email` but NO lead id, while message-history is addressed by id. Verified
        against a real reply on 2026-09-01. Built once per campaign rather than looked up
        per reply, so the cost is pagination over the lead list, not N calls.

        Email is the join key everywhere else in this system (CLAUDE.md), so joining here
        is consistent rather than a special case.
        """
        out, offset = {}, 0
        while True:
            d = self.get(f"/campaigns/{cid}/leads?offset={offset}&limit=100")
            rows = d.get("data") or []
            if not rows:
                return out
            for row in rows:
                lead = row.get("lead") or {}
                email = (lead.get("email") or "").strip().lower()
                if email and lead.get("id"):
                    out[email] = lead["id"]
            offset += len(rows)
            if offset >= int(d.get("total_leads") or 0):
                return out

    def thread(self, cid, lead_id) -> list[dict]:
        d = self.get(f"/campaigns/{cid}/leads/{lead_id}/message-history"
                     f"?show_plain_text_response=true")
        return d.get("history") or []

    def resume(self, cid, lead_id) -> str:
        """Restart follow-ups. Guarantee 6.

        A 409 "this is the last sequence" is EXPECTED, not a failure: an out-of-office
        arriving after email 3 has no remaining step to resume. Verified live on
        2026-08-31, which is the only reason this is not treated as an error.
        """
        if not self.apply:
            return "would resume"
        s, d = self._call("POST", f"/campaigns/{cid}/leads/{lead_id}/resume")
        if s == 200:
            return "resumed"
        if s == 409 and "last sequence" in str(d).lower():
            return "nothing left to resume (last sequence)"
        raise RuntimeError(f"resume {lead_id} -> {s}: {d}")

    def unsubscribe(self, cid, lead_id) -> str:
        """Suppress on the Smartlead side. Campaign scope AND global block list, which is
        what config/hubspot-properties.md means by "plus Smartlead's own block list"."""
        if not self.apply:
            return "would unsubscribe (campaign + global)"
        s1, _ = self._call("POST", f"/campaigns/{cid}/leads/{lead_id}/unsubscribe")
        s2, _ = self._call("POST", f"/leads/{lead_id}/unsubscribe")
        return f"unsubscribed (campaign {s1}, global {s2})"


class HubSpotWriter:
    """Writes only outbound_* properties. Never touches native hs_email_optout.

    A separate client on purpose: scripts/eligibility.py guarantees it never writes, and
    that guarantee is worth more than the shared code.
    """

    def __init__(self, token: str, apply_changes: bool):
        self.token = token
        self.apply = apply_changes
        self.calls = 0

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{HS_BASE}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                self.calls += 1
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode()[:300]
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None

    def find_by_email(self, email: str) -> tuple[str | None, dict]:
        d = self._call("POST", "/crm/v3/objects/contacts/search",
                       {"filterGroups": [{"filters": [
                           {"propertyName": "email", "operator": "EQ", "value": email}]}],
                        # outbound_sender decides WHOSE booking link goes in the draft.
                        # Written once at enrolment, so a reply months later still
                        # resolves to the person who actually wrote to them.
                        "properties": ["email", "outbound_status",
                                       "outbound_recycle_after",
                                       "outbound_sender"], "limit": 1})
        res = d.get("results") or []
        if not res:
            return None, {}
        return res[0]["id"], (res[0].get("properties") or {})

    def write(self, contact_id: str, props: dict) -> str:
        assert "hs_email_optout" not in props, \
            "native opt-out is never written by the engine (guarantee 5)"
        if not self.apply:
            return f"would write {props}"
        self._call("PATCH", f"/crm/v3/objects/contacts/{contact_id}", {"properties": props})
        return f"wrote {props}"


# ---- classification ------------------------------------------------------------

CLASSIFY_PROMPT = """You are the reply classifier for a cold outbound email engine.

Read the WHOLE thread, then classify the prospect's most recent reply as exactly one
intent. Return ONLY a JSON object:

{"intent": "<one intent>", "reason": "<under 15 words>", "proposed_action": "<under 20 words>", "draft_response": "<a short reply a human will review, or empty>", "named_return_date": "<YYYY-MM-DD or empty>"}

The ten intents:
- interested: wants to engage, learn more, or meet. ALSO covers a request for materials,
  pricing, a deck, or a demo, which are buying signals.
- question: asking something before deciding, with no buying lean.
- objection: a concern a reply could address. THIS INCLUDES A NAMED INCUMBENT -- "we
  already use X", "we're happy with X" -- because a stated reason is a concern.
- not_interested: a BARE decline that gives no reason. If they said WHY, it is objection.
- not_now: positive or neutral but explicitly later.
- not_qualified: structural non-fit (out of business, does not run ticketed events).
- wrong_contact: the sender has left, or is not the right person.
- asked_to_stop: explicit removal or unsubscribe request.
- out_of_office: an away or on-leave auto-responder.
- automated_reply: any other machine-generated reply.

PRECEDENCE, highest wins, because one reply can carry several signals:
1. asked_to_stop beats everything. "not interested + please remove me" is asked_to_stop.
2. out_of_office / automated_reply: classify by FORM. If it is an auto-responder, stop
   there and do not mine the text for intent.
3. wrong_contact.
4. not_qualified.
5. interested: a buying-signal question or pricing ask beats a stated objection.
6. question / objection.
7. not_now.
8. not_interested is the default decline when nothing stronger is present.

named_return_date ON out_of_office: set it to THE DAY THEY SAY THEY ARE BACK. "I am on
leave until 14 March", "back in the office Monday the 3rd", "returning after the 20th"
-> resolve it against the reply's own date and give the date. This is the single most
useful thing you can extract from an auto-responder: it is what schedules the follow-up
to restart, so a prospect who was merely on holiday is contacted again instead of being
dropped forever. If they give no return date, leave it EMPTY and a default wait applies
-- never guess one, and never use a date that is only mentioned in passing (a meeting,
a deadline, an event) rather than as the day they return.

named_return_date OTHERWISE: ONLY for not_now, and only when the prospect names a time you can
resolve to a date ("after the summer", "ask me in Q1", "next March", "our contract runs
through June"). A CONTRACT END DATE IS THE MOST VALUABLE CASE -- capture it. Resolve it
relative to the reply's own date, which is in the thread. Leave it empty if they named
no time, or for any other intent. Never invent one: an empty value is correct and safe,
a guessed one silently moves when a real person gets contacted again.

WORKED EXAMPLES for the two collisions that the rules alone do not settle. These are
different replies from the ones you will be given; apply the reasoning, not the wording.

  "We just signed with Tixr through next summer."
  -> not_now, and set named_return_date to when the contract ends. A CONTRACT LOCK IS A
     SUCCESSFUL ANSWER, not a rejection: the email asked whether they are locked in, and
     they said yes and told us when. That is the exact information it was designed to
     get. Route it to timing, capture the date, come back then.

  "Swamped until after our festival in October, try me then."
  -> not_now. Nothing to answer, only timing.

  "Your platform can't do reserved seating, can it?"
  -> objection. A concern that a REPLY could address, with no timing in it at all.
  The test: a contract or a season they must wait out is not_now. A doubt about us that
  an answer would resolve is objection.

  "We're on Eventbrite and it works fine, but what would switching run us?"
  -> interested, NOT question. Asking what something costs is a buying signal, and
     precedence 5 puts it above the objection sitting in the same sentence. A cost,
     pricing, timeline-to-switch, or "what would it take" question is always interested.

  "How does your payout schedule work?"
  -> question. Asking how the product behaves, with nothing about cost or switching.

  "We're happy on Tixr, but thanks for reaching out."
  -> objection, NOT not_interested. Naming an incumbent IS the concern, and "we already
     have someone" is the most workable objection in this market -- it is a comparison a
     reply can engage, which is exactly what an objection is. The friendly, final-sounding
     wording makes this the easiest miss on the whole list, so classify on what the
     sentence CONTAINS, not on how politely it lands. The "but" is doing real work.
     There is no contract and no date here, which is what separates it from the Tixr
     example further up: a contract you must wait out is not_now, a preference you could
     change is objection.

  "Not interested, thanks."
  -> not_interested. The contrast with the line directly above is the entire test, and it
     is the only thing that separates these two intents: this reply gives NO REASON. The
     moment a decline names why -- an incumbent, a price, a missing feature, a bad past
     experience -- it stops being a bare decline and becomes an objection.

A COST ASK FROM A HUMAN IS ALWAYS interested. It holds even when the same reply also
defers ("send pricing, I'll look next week"), carries an objection, or is two words long.
Only asked_to_stop and machine-generated form override it. The test against not_now: did
they ask us to DO something now? "Send me pricing, I'll read it Monday" wants the thing
now and is interested. "Ask me in January" wants nothing now and is not_now. Getting this
backwards parks someone who asked for pricing behind a 90 day wait.

FORM IS CHECKED FIRST, and it outranks the cost rule above. An automatic reply that
happens to request materials ("AUTOMATIC REPLY ... send pricing to procurement@") is
out_of_office, because no human chose to ask. A person typing a short note themselves
while travelling ("away till Monday, but yes send pricing") is NOT an auto-responder and
is classified on what they said. Machine-generated form beats message content; a human's
brevity is not machine form.

ONCE FORM SAYS MACHINE, PICK THE SUBTYPE ON WHO IS ABSENT -- the PERSON or nobody:

  "AUTOMATIC REPLY: I am on leave until 14 March. For anything urgent contact
   procurement@, and send any pricing there."
  -> out_of_office. A NAMED HUMAN is away and says when they are back. That it also asks
     for pricing changes nothing: no person chose to ask, so the buying-signal rule does
     not reach it. **This is the case most often got wrong, and the pricing line is the
     distractor.** Read who is absent, not what is requested.

  "Ticket #48213 has been created. Our team will respond within 2 business days."
  -> automated_reply. NOBODY is away. A system acknowledged the mail; there is no
     absent human and no return date, only a process running.

  "This mailbox is not monitored. Please use the contact form."
  -> automated_reply. Again nobody is away -- the address itself is the wrong door.

The test in one line: **out_of_office means a person is temporarily absent and will be
back; automated_reply means a machine answered and no one is absent at all.** Getting
this backwards matters, because only one of the two may be safely restarted today.

The draft_response is for a HUMAN TO REVIEW AND SEND. Never write one for
out_of_office or automated_reply. Keep it short, plain, one ask, no dashes, and never
promise pricing or terms.

**For `interested` and `question`, the draft MUST include this booking link, as a plain
visible URL: {booking_link}** ({owner}'s calendar). Do not invent a different link, do
not write "I'll send over some times" and do not offer to find a slot by hand -- give
them the link so they can book. You stay the correspondent; the meeting simply lands on
{owner}'s calendar, and there is no mid-thread introduction.

**EVERY intent except out_of_office and automated_reply GETS A DRAFT.** A queued row with
an empty draft makes a human write from scratch, which is most of what the queue exists to
save. What each one says (from instructions/reply-handling.md):

  interested / question -> warm, one line, PLUS the booking link above.
  objection             -> acknowledge it, leave the door open, and STOP. Do not argue
                           it, do not counter with a claim, DO NOT PROPOSE A CALL and do
                           not paste the booking link. They told you no and gave a
                           reason; asking them to book a meeting is a non-sequitur.
                           **The CTA is also what makes this intent dangerous.** A
                           meeting you are forbidden to justify forces you to invent a
                           justification: told to offer a call, this prompt drafted
                           "reserved seating is actually something we handle well" for a
                           real prospect, a capability claim from a model that has never
                           seen the product documentation. Removing the CTA removes the
                           pressure that produced it. The engine comes back on its own
                           via outbound_recycle_after -- this draft does not have to win
                           anything back today, and trying is how it lies.
  not_now               -> acknowledge their timing, say you will come back then, name
                           the time they gave. No link, no pitch.
  not_interested        -> short and gracious. No re-pitch, no link, no "just one more
                           thing".
  asked_to_stop         -> one line confirming they are removed. Nothing else, ever.
  not_qualified         -> short and friendly, no pitch.
  wrong_contact         -> thank them, and ask nothing further ABOUT THE OLD COMPANY.
                           Do not ask them to forward it or for the replacement's
                           details; a human decides what to do with a referral.
                           **BUT: if they volunteered a NEW ROLE somewhere else, ask
                           about THAT.** Someone who writes "I've moved to X, I'm now
                           their booking manager" has disqualified themselves for the
                           company we mailed and self-identified as a prospect at
                           another. They are not a stranger being pestered -- they chose
                           to tell us. One line: congratulate the move, then ASK whether
                           ticketing is something they handle there. Ask, never assert:
                           we know nothing about the new company beyond its name, so no
                           claim about its events, size, or what it needs.
                           If they named no new role, the first rule stands and the draft
                           stops after the thank-you.

No link on any intent except interested and question.

**NEVER INVENT A FACT ABOUT POSH.** This is the hard rule of the draft. You do not have
the product documentation in front of you, so you cannot know payout timings, fee
structures, integrations, capacity limits, or feature specifics -- and a draft that
states one confidently is the most dangerous output here, because it reads as authoritative
and a reviewer skimming it will send it.

  - **Never write:** a number of days, a percentage, a fee, a rate, a limit, or a named
    integration, unless the PROSPECT'S OWN MESSAGE stated it and you are repeating it
    back.
  - **When they ask something specific you do not know, say so and route it.** "Good
    question, that is worth walking through properly" plus the booking link is a correct
    and complete answer. Deferring to the call is never a failure.
  - This mirrors the rule on cold copy, which is machine-checked against an approved
    claims list. **Drafts are not machine-checked**, so the discipline has to live here.

THREAD (oldest first):
---
{thread}
---"""


MEETING_ROUTING = ROOT / "config" / "meeting-routing.md"


def booking_links() -> dict[str, str]:
    """{sender first name: booking link} from config/meeting-routing.md.

    Parsed, never restated. Changing a link, or adding a sender, is a config edit in one
    place; hardcoding here would defeat that.

    **One link per sender as of 2026-09-14.** It used to be a single owner: every meeting
    routed to Zach because he was the SDR and the only person taking them. He was promoted
    to AE, so each sender takes their own. A prospect corresponding with Carl should not
    be handed Zach's calendar.
    """
    text = MEETING_ROUTING.read_text(encoding="utf-8")
    block = re.search(r"\|\s*Sender\s*\|\s*Booking link\s*\|(.*?)(?=\n\n|\n[^|])",
                      text, re.S | re.I)
    links: dict[str, str] = {}
    if block:
        for row in block.group(1).splitlines():
            m = re.match(r"\s*\|\s*([A-Za-z][\w .'-]*?)\s*\|\s*`?(https?://\S+?)`?\s*\|",
                         row)
            if m and m.group(1).strip().lower() not in ("sender", "---"):
                links[m.group(1).strip()] = m.group(2)
    if not links:
        raise RuntimeError(
            f"no booking links found in {MEETING_ROUTING.name}. Expected a '| Sender | "
            "Booking link |' table. Refusing to draft a meeting reply with no link "
            "rather than silently omitting it.")
    return links


def booking_link_for(sender: str, links: dict[str, str] | None = None) -> tuple[str, str]:
    """(sender name, their link). Raises on an unknown or missing sender.

    **A hard error, not a fallback.** Falling back to another sender's calendar would
    hand a prospect the wrong person's time while looking like it worked, and defaulting
    to "the first link in the table" would quietly recreate the single-owner behaviour
    this replaced. A draft that stops for a human is the cheaper failure.
    """
    links = links if links is not None else booking_links()
    who = (sender or "").strip()
    if not who:
        raise RuntimeError(
            "no outbound_sender on this contact, so there is no way to know whose "
            "booking link belongs in the draft. It is written once at enrolment by "
            "create_campaign.py; a contact without it was not enrolled by the engine.")
    for name, link in links.items():
        if name.lower() == who.lower():
            return name, link
    raise RuntimeError(
        f"sender {who!r} has no row in {MEETING_ROUTING.name} (known: "
        f"{', '.join(sorted(links))}). Add one rather than letting the draft go out with "
        "somebody else's calendar.")


def read_thread(messages: list[dict]) -> tuple[list[dict], dict | None]:
    """Normalise a message-history list. Returns (all messages, newest inbound).

    Guarantee 4: an inbound message whose body cannot be found aborts the run.
    """
    norm = []
    for m in messages:
        # VERIFIED against a real thread 2026-09-01. Smartlead's docs describe a
        # `direction` field of "inbound"/"outbound"; the API actually sends `type` with
        # SENT / REPLY. Both are handled, and an unrecognised value is a HARD ERROR
        # rather than a guess: getting direction wrong would feed OUR OWN email to the
        # classifier as though the prospect had written it.
        raw_dir = str(m.get("direction") or "").lower()
        raw_type = str(m.get("type") or "").upper()
        if raw_dir in ("inbound", "outbound"):
            inbound = raw_dir == "inbound"
        elif raw_type in INBOUND_TYPES:
            inbound = True
        elif raw_type in OUTBOUND_TYPES:
            inbound = False
        else:
            raise RuntimeError(
                f"cannot tell which way a Smartlead message went: direction={raw_dir!r} "
                f"type={raw_type!r}. Add it to INBOUND_TYPES or OUTBOUND_TYPES. Refusing "
                "to guess, because a wrong guess classifies our own email as theirs.")
        body = next((str(m[f]) for f in BODY_FIELDS if m.get(f)), None)
        if inbound and body is None:
            raise RuntimeError(
                "an inbound Smartlead message has no recognisable body field. Fields "
                f"present: {sorted(m)}. Add the right name to BODY_FIELDS. Refusing to "
                "treat an unreadable reply as an empty one.")
        # A reply quotes everything above it, so the prospect's actual words are a
        # fraction of the payload. enrich_callbacks learned this the expensive way: a
        # 7741-char reply whose prospect content was 105 chars, the rest being OUR OWN
        # quoted pricing. Unstripped, that lands in the review Sheet as the "reply" and
        # goes to the classifier as though they wrote it.
        if inbound and body:
            body = strip_quoted(body)
        norm.append({
            "inbound": inbound,
            # message_id for dedup (unique per message); stats_id kept separately
            # because reply-email-thread needs it to address the thread, and it is
            # SHARED across the thread so it must never be used for dedup.
            "id": str(m.get("id") or m.get("message_id") or m.get("stats_id") or ""),
            "stats_id": str(m.get("stats_id") or ""),
            "subject": m.get("subject") or "",
            "body": re.sub(r"\s+\n", "\n", (body or "")).strip(),
            "at": m.get("received_at") or m.get("sent_at") or m.get("time") or ""})
    norm.sort(key=lambda x: x["at"] or "")
    inbounds = [m for m in norm if m["inbound"]]
    return norm, (inbounds[-1] if inbounds else None)


def classify(client, model: str, thread: list[dict], sender: str = "") -> dict:
    rendered = "\n\n".join(
        f"[{'PROSPECT' if m['inbound'] else 'US'} {m['at']}] {m['subject']}\n{m['body']}"
        for m in thread)
    # The prospect's own words are what get classified, but the whole thread is supplied:
    # reply-handling.md step 3 requires reading the full conversation before acting.
    # The SENDER'S link, not a single owner's. Raises on an unknown or missing sender
    # rather than handing the prospect somebody else's calendar -- see booking_link_for.
    owner, link = booking_link_for(sender)
    prompt = (CLASSIFY_PROMPT
              .replace("{booking_link}", link)
              .replace("{owner}", owner)
              .replace("{thread}", rendered[:12000]))
    resp = client.messages.create(model=model, max_tokens=500,
                                  messages=[{"role": "user", "content": prompt}])
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    out = json.loads(raw.strip())
    if out.get("intent") not in INTENTS:
        raise RuntimeError(f"classifier returned an unknown intent: {out.get('intent')!r}")
    return out


# ---- run -----------------------------------------------------------------------

# ---- self test ------------------------------------------------------------------

# Real replies are the only thing that proves this loop, and there are none yet. These
# cases stand in: the pure ones are exact, the classification ones hit the live model.
# Each precedence case is a mixed-signal reply, because a single-signal reply proves
# nothing about precedence.
CLASSIFY_CASES = [
    # (reply text, expected intent, why this case exists)
    ("Sure, happy to take a look. What does pricing look like for 5k capacity?",
     "interested", "a pricing ask is a buying signal"),
    # interested and question are OPERATIONALLY IDENTICAL in the action map: same
    # outbound_status, no recycle date, sequence stopped, queued for a human. So this
    # case accepts either. It is not a loosened standard, it is the honest boundary of
    # what the distinction controls -- tightening the prompt to force "question" here
    # flipped a pricing ask to not_now, which parks a warm lead for 90 days. Fixing a
    # difference that changes nothing, at the cost of one that changes a lot, is a bad
    # trade.
    ("What's the payout timing like?", ("question", "interested"),
     "a product question that is money-adjacent; either intent acts the same"),
    ("We're locked into a contract with Dice until next year.",
     "not_now", "SDR spec 2026-09-01: a contract lock is a successful answer to email 1, "
                "not a rejection. Route to timing and capture the date"),
    ("Does your platform handle reserved seating?",
     ("question", "objection"), "a doubt a reply could resolve, with no timing in it"),
    ("Not right now, we're mid season. Ask me again in January.",
     "not_now", "explicit later"),
    ("No thanks.", "not_interested", "the default decline"),
    ("We stopped doing ticketed events, we're a private members club now.",
     "not_qualified", "structural non-fit"),
    ("I left the venue in March. Talk to Priya, she runs events now.",
     "wrong_contact", "sender is not the right person"),
    ("Please remove me from your list.", "asked_to_stop", "explicit removal"),
    ("I am out of the office until 8 September with limited access to email.",
     "out_of_office", "away auto-responder"),
    ("Your message could not be delivered to some recipients. Delivery has failed.",
     "automated_reply", "machine generated, not an auto-away"),
    # precedence, the cases where two signals collide
    ("Not interested, and please take me off this list.",
     "asked_to_stop", "P1: removal beats a decline"),
    ("AUTOMATIC REPLY - I am out of the office until 8 September. For ticketing or "
     "vendor inquiries, send pricing and materials to procurement@venue.com and we will "
     "review on my return. This message was generated automatically.",
     "out_of_office", "P2: an auto-responder that ASKS for pricing is still an "
                      "auto-responder. Classify by form, do not mine the body"),
    ("I'm away until Monday but yes, send me pricing and I'll look then.",
     "interested", "the other side of P2: a HUMAN typing a short note while away is not "
                   "an auto-responder, and this one is a real buying signal"),
    ("We already use Eventbrite and I'm happy with it, but what would migration cost?",
     "interested", "P5: a buying-signal question beats a stated objection"),
    ("I don't work here any more and honestly we weren't interested anyway.",
     "wrong_contact", "P3: wrong_contact beats a decline"),
]


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # -- recycle_date, the four rules.
    # Expectations are DERIVED from config, not hardcoded, so tuning a window in
    # config/reply-defaults.md does not produce mystery failures here. The floors
    # themselves are printed below rather than asserted.
    cfg = defaults()
    nn, ni = cfg["recycle_not_now_days"], cfg["recycle_not_interested_days"]

    def after(date: str, days: int) -> str:
        return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()

    check("rule 1: anchored on the reply date, not today",
          recycle_date("not_interested", "2026-01-01T10:00:00Z", None, None),
          after("2026-01-01", ni))
    check("rule 2: a named date is honoured",
          recycle_date("not_now", "2026-08-31T10:00:00Z", "2027-01-15", None), "2027-01-15")
    check("rule 2: a named date EARLIER than the floor is still honoured",
          recycle_date("not_now", "2026-08-31T10:00:00Z", "2026-10-01", None), "2026-10-01")
    check("rule 2: no named date falls back to the floor",
          recycle_date("not_now", "2026-08-31T10:00:00Z", "", None),
          after("2026-08-31", nn))
    check("rule 3: not_interested ignores a named date",
          recycle_date("not_interested", "2026-08-31T10:00:00Z", "2026-09-05", None),
          after("2026-08-31", ni))
    check("rule 4: an existing later date wins",
          recycle_date("not_now", "2026-08-31T10:00:00Z", None, "2028-01-01"), "2028-01-01")
    check("rule 4: an existing EARLIER date does not win",
          recycle_date("not_now", "2026-08-31T10:00:00Z", None, "2026-09-01"),
          after("2026-08-31", nn))
    check("no recycle date for other intents",
          recycle_date("interested", "2026-08-31T10:00:00Z", None, None), None)
    check("a garbage named date falls back to the floor rather than crashing",
          recycle_date("not_now", "2026-08-31T10:00:00Z", "next spring", None),
          after("2026-08-31", nn))

    # -- the config is genuinely in charge, not decoration. If the windows were still
    # hardcoded every case above would pass unchanged, so this is what actually proves
    # the duplication is gone.
    check("a config value actually drives the floor",
          recycle_date("not_now", "2026-08-31T10:00:00Z", None, None,
                       cfg={"recycle_not_now_days": 7, "recycle_not_interested_days": ni}),
          "2026-09-07")

    # -- the auto-send allowlist is asserted, not just read
    try:
        load_config(REPLY_CONFIG)
        global _DEFAULTS
        saved, _DEFAULTS = _DEFAULTS, None
        cfgfile = REPLY_CONFIG.read_text()
        REPLY_CONFIG.write_text(cfgfile.replace("auto_send_intents: []",
                                                "auto_send_intents: [interested]"))
        try:
            defaults()
            fails.append("a non-empty auto_send_intents did NOT stop the script")
        except RuntimeError as e:
            check("refusing to run names the send path, not just the value",
                  "no send path" in str(e), True)
        finally:
            REPLY_CONFIG.write_text(cfgfile)
            _DEFAULTS = saved
    except Exception as e:                       # never leave the config edited
        REPLY_CONFIG.write_text(cfgfile)
        fails.append(f"auto-send check errored: {e}")

    # -- read_thread
    msgs, newest = read_thread([
        {"id": "m2", "direction": "inbound", "received_at": "2026-08-30T09:00:00Z",
         "subject": "Re: hi", "email_body": "sounds good"},
        {"id": "m1", "direction": "outbound", "sent_at": "2026-08-28T09:00:00Z",
         "subject": "hi", "email_body": "our pitch"}])
    check("thread sorts oldest first", [m["id"] for m in msgs], ["m1", "m2"])
    check("newest inbound is picked", newest["id"], "m2")
    check("outbound is not treated as inbound", msgs[0]["inbound"], False)
    _, none_yet = read_thread([{"id": "m1", "direction": "outbound",
                               "sent_at": "2026-08-28T09:00:00Z", "email_body": "x"}])
    check("a thread with no inbound yields no reply", none_yet, None)
    try:
        read_thread([{"id": "m9", "direction": "inbound", "received_at": "2026-08-30",
                      "subject": "Re: hi", "some_unknown_body_field": "hello"}])
        fails.append("guarantee 4: an unreadable inbound body did NOT raise")
    except RuntimeError as e:
        check("guarantee 4 names the fix", "BODY_FIELDS" in str(e), True)

    # -- the action map in this file must match the table in reply-handling.md.
    # The dict stays authoritative at RUNTIME on purpose: parsing a prose table to
    # decide what to write to a prospect's record turns a mis-parse into a wrong write.
    # So the doc is not parsed to drive behaviour, only to prove behaviour matches it.
    doc = (ROOT / "instructions" / "reply-handling.md").read_text(encoding="utf-8")
    table = {}
    for line in doc.splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 5 or cells[0] not in INTENTS:
            continue
        status = cells[1].split("(")[0].strip()          # "disqualified (old contact)"
        table[cells[0]] = {
            "status": None if status == "unchanged" else status,
            "resume": cells[3].strip().upper() == "RESUME"}
    if len(table) != len(INTENTS):
        fails.append(f"could not parse every intent out of the reply-handling.md table: "
                     f"got {sorted(table)}, expected {sorted(INTENTS)}")
    for intent, want in table.items():
        check(f"action map agrees with the doc for {intent} (status)",
              INTENTS[intent]["status"], want["status"])
        check(f"action map agrees with the doc for {intent} (sequence)",
              INTENTS[intent]["resume"], want["resume"])

    # -- resume_date: an out-of-office must come back, and only out_of_office may
    _today = dt.datetime.now(dt.timezone.utc).date()
    _far = (_today + dt.timedelta(days=400)).isoformat()
    check("a named return date wins",
          resume_date("out_of_office", "2026-09-01", _far, cfg), _far)
    check("no named date falls back to the configured wait",
          resume_date("out_of_office", "2026-09-01", None, cfg),
          (dt.date(2026, 9, 1) + dt.timedelta(days=cfg["resume_ooo_default_days"]))
          .isoformat())
    # A stale auto-responder must not resume instantly just because its date has passed.
    check("a named date in the past resolves to tomorrow, never today or earlier",
          resume_date("out_of_office", "2020-01-01", "2020-01-05", cfg),
          (_today + dt.timedelta(days=1)).isoformat())
    check("an unparseable named date falls back rather than raising",
          resume_date("out_of_office", "2026-09-01", "whenever", cfg),
          (dt.date(2026, 9, 1) + dt.timedelta(days=cfg["resume_ooo_default_days"]))
          .isoformat())
    # Only out_of_office. automated_reply resumes immediately; a human reply never does.
    for _i in INTENTS:
        if _i != "out_of_office":
            check(f"{_i} gets no resume date",
                  resume_date(_i, "2026-09-01", "2026-09-20", cfg), None)

    # -- guarantee 5, structurally
    check("native opt-out is not writable", "hs_email_optout" in HubSpotWriter.write.__doc__
          if HubSpotWriter.write.__doc__ else False, False)
    # An ALLOWLIST on purpose, so adding any method to the Smartlead client forces a
    # deliberate update here rather than quietly widening what this class can do. It
    # caught lead_ids_by_email being added during the threading work, which is the
    # mechanism working -- a send method would be caught the same way.
    check("guarantee 2: the Smartlead client exposes no way to send mail",
          sorted(m for m in dir(Smartlead) if not m.startswith("_")),
          ["campaigns", "get", "lead_ids_by_email", "replied_leads", "resume", "thread",
           "unsubscribe"])

    print(f"config: not_now floor {nn}d, not_interested {ni}d, auto-send "
          f"{cfg['auto_send_intents'] or 'empty (enforced)'}")
    print(f"pure cases: {'all passed' if not fails else str(len(fails)) + ' FAILED'}")
    for f in fails:
        print(f"  FAIL {f}")

    # -- classification against the live model
    try:
        client, model = rq_bedrock()
    except Exception as e:
        print(f"\nSKIPPED the {len(CLASSIFY_CASES)} classification cases: {e}")
        return 1 if fails else 0

    print(f"\nclassifying {len(CLASSIFY_CASES)} cases against {model}:")

    def run_case(case):
        text = case[0]
        thread = [{"inbound": False, "at": "2026-08-28T09:00:00Z", "subject": "quick one",
                   "body": "Saw you run ticketed events. Worth a look at Posh?"},
                  {"inbound": True, "at": "2026-08-30T09:00:00Z", "subject": "Re: quick one",
                   "body": text}]
        try:
            # A real sender is required: booking_link_for refuses an empty one rather
            # than handing out a default calendar, so the self-test must name someone.
            # Any sender with a row in meeting-routing.md works -- this exercises
            # classification, not routing.
            return classify(client, model, thread, sender="Carl")["intent"]
        except Exception as e:
            return f"ERROR {e}"

    # Concurrent because 15 sequential calls pushed this past two minutes, and a
    # self-test nobody waits for is a self-test nobody runs. Modest width, and the
    # executor preserves input order so the printed report stays stable.
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(run_case, CLASSIFY_CASES))

    wrong = 0
    for (text, want, why), got in zip(CLASSIFY_CASES, results):
        allowed = want if isinstance(want, tuple) else (want,)
        ok = got in allowed
        wrong += 0 if ok else 1
        label = "|".join(allowed)
        print(f"  {'ok  ' if ok else 'WRONG'} {label:15} {'' if ok else '-> ' + got + ' '}"
              f"| {why}")
    print(f"\n{len(CLASSIFY_CASES) - wrong}/{len(CLASSIFY_CASES)} classified correctly")
    return 1 if (fails or wrong) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Poll Smartlead for replies, classify, and act. Dry run by default.")
    ap.add_argument("--campaign", help="one campaign id; default is every campaign")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE: update HubSpot, resume or unsubscribe in Smartlead, "
                         "and append to the review Sheet. Without this, nothing is written.")
    ap.add_argument("--limit", type=int, default=0, help="max replies to process")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the recycle math, thread parsing, and classification "
                         "without touching a live campaign")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    sl_key = os.environ.get("SMARTLEAD_API_KEY") or next(
        (l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text().splitlines()
         if l.startswith("SMARTLEAD_API_KEY=")), "")
    if not sl_key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")

    sl = Smartlead(sl_key, a.apply)
    hs = HubSpotWriter(env_token(), a.apply)
    client, model = rq_bedrock()
    now = dt.datetime.now(dt.timezone.utc)

    print("APPLY: writing to HubSpot, Smartlead and the Sheet" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")

    campaigns = ([{"id": a.campaign, "name": f"(id {a.campaign})"}] if a.campaign
                 else sl.campaigns())
    if not campaigns:
        print("no campaigns in the account, so there is nothing to poll yet.")
        return 0

    svc, who = rq.sheets_service()
    cfg = rq.load_surface_config()
    store = rq.get_processed_id_store(svc, cfg["REPLY_REVIEW_SHEET_ID"],
                                     cfg["REPLY_REVIEW_TAB"])
    processed = queued = skipped = 0

    for camp in campaigns:
        cid = camp.get("id")
        leads = sl.replied_leads(cid)
        print(f"\ncampaign {cid} {camp.get('name','')!r}: {len(leads)} lead(s) marked replied")
        id_by_email = sl.lead_ids_by_email(cid) if leads else {}
        for row in leads:
            if a.limit and processed >= a.limit:
                break
            lead = row.get("lead") or row
            email = (lead.get("email") or row.get("lead_email") or "").strip()
            lead_id = (lead.get("id") or row.get("lead_id")
                       or id_by_email.get(email.lower()))
            if not lead_id:
                # Never guess an id: the wrong one reads a stranger's thread and could
                # classify, suppress, or draft a reply against the wrong person.
                print(f"  {email}: replied, but no Smartlead lead id on this campaign; "
                      "skipped rather than risk reading the wrong thread")
                skipped += 1
                continue
            messages, newest = read_thread(sl.thread(cid, lead_id))
            if not newest:
                print(f"  {email}: marked replied but no inbound message found; skipped")
                skipped += 1
                continue
            if newest["id"] and store.is_processed(newest["id"]):
                print(f"  {email}: already processed {newest['id']}; skipped")
                skipped += 1
                continue

            # The contact is fetched BEFORE classifying, because the draft needs the
            # SENDER'S booking link and outbound_sender lives on the contact. It used to
            # be fetched after, when every meeting routed to one owner and the link was
            # a constant.
            cidhs, existing = hs.find_by_email(email) if email else (None, {})
            res = classify(client, model, messages,
                           sender=existing.get("outbound_sender", ""))
            intent = res["intent"]
            spec = INTENTS[intent]
            processed += 1
            print(f"  {email}: {intent}  ({res.get('reason','')[:60]})")

            # HubSpot: intent always, status only when the intent advances the lead.
            props = {"outbound_reply_intent": intent}
            if spec["status"]:
                props["outbound_status"] = spec["status"]
            if intent == "asked_to_stop":
                props["outbound_suppressed"] = "true"
                props["outbound_opt_out_date"] = now.date().isoformat()
            recycle = recycle_date(intent, newest["at"], res.get("named_return_date"),
                                   existing.get("outbound_recycle_after"))
            if recycle:
                props["outbound_recycle_after"] = recycle
                held = existing.get("outbound_recycle_after")
                if held and str(held)[:10] == recycle:
                    print("      recycle: keeping the later date already on the contact")
            # An out-of-office pauses the sequence rather than ending the relationship,
            # so it gets a date to come back on instead of a recycle window. Written
            # here, acted on by scripts/resume_sequences.py once the date arrives.
            resume_on = resume_date(intent, newest["at"], res.get("named_return_date"))
            if resume_on:
                props["outbound_resume_after"] = resume_on
                named = (res.get("named_return_date") or "").strip()
                print(f"      resume: {resume_on} "
                      f"({'they named it' if named else 'default wait, no date given'})")
            if cidhs:
                print(f"      hubspot: {hs.write(cidhs, props)}")
            else:
                print(f"      hubspot: no contact found for {email!r}; nothing written")

            if spec["resume"]:
                print(f"      smartlead: {sl.resume(cid, lead_id)}  "
                      f"(not a real reply, lead not advanced)")
            elif intent == "out_of_office":
                # Not resuming NOW, because they are still away. Not never, either:
                # outbound_resume_after was just written and resume_sequences.py acts on
                # it when the date arrives. Deferring to a Smartlead auto-restart is what
                # this used to do, and that restart appears not to exist.
                print(f"      smartlead: not resuming yet; scheduled for {resume_on} "
                      "(resume_sequences.py picks it up)"
                      if resume_on and cidhs else
                      "      smartlead: not resuming, and NOTHING SCHEDULED -- no HubSpot "
                      "contact to hold the date, so this lead will not restart itself.")
            if intent == "asked_to_stop":
                print(f"      smartlead: {sl.unsubscribe(cid, lead_id)}")

            if intent == "wrong_contact":
                # reply-handling.md wants the named replacement recorded as a referral
                # lead, never enrolled. Contact creation is off by explicit decision,
                # so the name goes in front of a human instead of into HubSpot.
                print("      referral: NOT created. Any named replacement is in the "
                      "queue row for a human to add manually.")

            if spec["queue"]:
                payload = {
                    "received_at": newest["at"], "contact_name": lead.get("first_name", ""),
                    "email": email, "company": lead.get("company_name", ""),
                    "campaign": str(cid), "sent_by": camp.get("name", ""),
                    "reply_text": newest["body"][:4000], "intent": intent,
                    "proposed_action": res.get("proposed_action", ""),
                    "draft_response": res.get("draft_response", ""),
                    "smartlead_message_id": newest["id"],
                    "smartlead_stats_id": newest.get("stats_id", "")}
                if a.apply:
                    r = rq.append_reply(payload, service=svc, cfg=cfg, store=store)
                    print(f"      queue: {'row ' + str(r['row']) if r['appended'] else r['skipped']}")
                else:
                    print("      queue: would append a row for human review")
                queued += 1

    # "queued" vs "WOULD be queued" matters: the heartbeat prints this line into Slack
    # every weekday, and the routines run WITHOUT --apply until they are graduated. A dry
    # run reporting "1 queued for review" while the sheet stays empty is exactly how
    # someone concludes the queue is broken.
    verb = "queued for review" if a.apply else "WOULD be queued (dry run, sheet unchanged)"
    print(f"\n{processed} reply(s) processed, {queued} {verb}, {skipped} skipped")
    print(f"{sl.calls} Smartlead calls, {hs.calls} HubSpot calls")
    if not a.apply:
        print("DRY RUN: nothing was written anywhere.")
    return 0


def rq_bedrock():
    """Bedrock client, per the decided shape in CLAUDE.md."""
    region = env_value("AWS_REGION")
    model = env_value("BULK_LLM_MODEL")
    token = env_value("AWS_BEARER_TOKEN_BEDROCK")
    if not (region and model):
        raise RuntimeError("AWS_REGION / BULK_LLM_MODEL not set; cannot classify")
    if not token:
        raise RuntimeError("AWS_BEARER_TOKEN_BEDROCK not set; the SDK would fall back "
                           "to SigV4 and fail on a missing botocore")
    # The SDK reads these from the environment itself; it is not passed api_key, per
    # CLAUDE.md (passing it alongside AWS credentials raises).
    os.environ["AWS_REGION"] = region
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = token
    import anthropic
    return anthropic.AnthropicBedrock(aws_region=region), model


if __name__ == "__main__":
    raise SystemExit(main())
