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
import hashlib
import http.client
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import repair  # noqa: E402
import lifecycle
import review_queue as rq  # noqa: E402
import validate  # noqa: E402
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
# The same literals and regexes that gate every cold email, now applied to reply drafts
# too. Lazily loaded so importing this module stays cheap and a missing config file
# fails at use rather than at import.
_BANNED_CACHE: tuple | None = None


def banned_lists() -> tuple:
    global _BANNED_CACHE
    if _BANNED_CACHE is None:
        _BANNED_CACHE = validate.load_banned()
    return _BANNED_CACHE


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
                    "resume_ooo_default_days", "recycle_task_lead_days",
                    "recycle_objection_days", "recycle_after_nudge_days"):
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
                 existing: str | None, cfg: dict | None = None,
                 platform: str | None = None) -> str | None:
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

    A FIFTH case was added 2026-09-28: an `objection` that NAMES an incumbent
    ("we have a contract with RA") gets `recycle_objection_days`. Objections used to
    set no date at all, which left the contact held only by the 30-day status=replied
    window -- re-mailable a month after they told us they were committed elsewhere.
    Requires `platform`, because a bare objection with no incumbent ("too expensive")
    is a copy problem rather than a contract and does not earn six months of silence.
    """
    if intent == "objection" and (platform or "").strip():
        pass                                       # handled below
    elif intent not in ("not_now", "not_interested"):
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
    elif intent == "objection":
        candidate = anchor + dt.timedelta(days=cfg["recycle_objection_days"])
        if named:                                  # a date they gave still wins
            try:
                candidate = dt.date.fromisoformat(named[:10])
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
    # `defaults()`, not `load_defaults()`. It read the latter until 2026-09-17 and that
    # name does not exist in this module, so the FIRST out_of_office reply ever received
    # in production crashed the whole reply check with a NameError -- taking the other
    # replies in the same run down with it.
    #
    # Every self-test case passes `cfg` explicitly, so the `cfg or ...` fallback was
    # never once executed by a test. recycle_date, six lines of logic away, has always
    # called defaults() correctly. A passing self-test on a function with an untested
    # default argument is worth exactly nothing.
    cfg = cfg or defaults()
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

    def get(self, path: str, tries: int = 4):
        """One read, retried on a rate limit, a transient 5xx, or a network fault.

        **Added 2026-10-06** after a single Cloudflare 502 on `GET /campaigns` failed the
        whole morning reply check; the same call returned 200 minutes later. Same shape
        as `sync_sends.Smartlead.get`. Reads only: the POSTs go through `_call` unretried,
        so a retry can never repeat a write. A 4xx is a real answer and is not retried.
        """
        for attempt in range(tries):
            try:
                s, d = self._call("GET", path)
            except (OSError, http.client.HTTPException) as e:
                # OSError, not URLError: RemoteDisconnected is a ConnectionResetError.
                if attempt == tries - 1:
                    raise
                s, d = None, f"{type(e).__name__}: {e}"
            if s == 200:
                return d
            transient = s is None or s == 429 or 500 <= s < 600
            if not transient or attempt == tries - 1:
                raise RuntimeError(f"GET {path} -> {s}: {d}")
            wait = 2 ** attempt
            print(f"    Smartlead {s or d} on {path[:52]}; retrying in {wait}s "
                  f"({attempt + 1}/{tries - 1})")
            time.sleep(wait)

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
                        # current_competitor and lifecyclestage are read so the
                        # enrichment can say what it CHANGED, and skip a write when the
                        # value already matches. Without them every reply naming a
                        # platform would rewrite the same value and report it as news.
                        # hubspot_owner_id is read ONLY to check whether one is
                        # already set. A contact with a real owner has a real
                        # relationship with that person; the meeting round robin must
                        # never displace it. See assign_meeting_owner().
                        # company / prospect_org / firstname name the prospect in a
                        # re-engagement task's subject. Without them the subject reads
                        # "Re-engage — said to come back 2027-06-01", which is useless
                        # in a task queue -- and it fails SILENTLY, because .get()
                        # on an unread property returns "" exactly like a blank one.
                        "properties": ["email", "outbound_status",
                                       "outbound_recycle_after", "outbound_sender",
                                       "current_competitor", "lifecyclestage",
                                       "hubspot_owner_id", "company", "prospect_org",
                                       "firstname"],
                        "limit": 1})
        res = d.get("results") or []
        if not res:
            return None, {}
        return res[0]["id"], (res[0].get("properties") or {})

    # --- re-engagement tasks -------------------------------------------------------
    # A stable marker in the BODY, not the subject. The subject carries the prospect's
    # org so a rep can read their task queue, which makes it useless for matching; a
    # human may also rename a task. The body marker is ours and nobody edits it.
    TASK_MARKER = "[outbound-engine:recycle]"
    # task -> contact, from /crm/v4/associations/tasks/contacts/labels
    TASK_TO_CONTACT = 204

    def open_recycle_task(self, contact_id: str) -> str:
        """Id of an existing UNFINISHED engine recycle task on this contact, or "".

        Idempotency matters more here than anywhere else in the reply path: the queue is
        re-read on every heartbeat, three times a day. Without this a single `not_now`
        would grow a new task every run until someone noticed a prospect with forty
        identical reminders -- the same shape as the duplicate-queue-row bug from the
        22 Sep catch-up storm, which is what taught us to check.
        """
        try:
            assoc = self._call(
                "GET", f"/crm/v4/objects/contacts/{contact_id}/associations/tasks")
        except Exception:
            # Cannot prove absence -> assume PRESENT and skip. Creating a duplicate is
            # the worse error: a missing task is visible in the recycle list, a pile of
            # duplicates is noise a rep has to clean up by hand.
            return "unknown"
        ids = [r["toObjectId"] for r in (assoc.get("results") or [])]
        for tid in ids[:50]:
            try:
                task = self._call(
                    "GET", f"/crm/v3/objects/tasks/{tid}"
                           f"?properties=hs_task_body,hs_task_status")
            except Exception:
                continue
            pr = task.get("properties") or {}
            if (self.TASK_MARKER in (pr.get("hs_task_body") or "")
                    and (pr.get("hs_task_status") or "") != "COMPLETED"):
                return str(tid)
        return ""

    def create_task(self, contact_id: str, subject: str, body: str,
                    due_iso: str, owner_id: str) -> str:
        props = {"hs_task_subject": subject[:255],
                 "hs_task_body": body,
                 "hs_task_status": "NOT_STARTED",
                 "hs_task_priority": "MEDIUM",
                 "hs_task_type": "TODO",
                 # Due DATE. HubSpot takes epoch millis; 13:00 UTC keeps it on the
                 # intended day for every US timezone rather than landing the previous
                 # evening for anyone west of London.
                 "hs_timestamp": due_iso}
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        if not self.apply:
            return f"would create task {subject!r} due {due_iso[:10]}"
        r = self._call("POST", "/crm/v3/objects/tasks", {
            "properties": props,
            "associations": [{"to": {"id": contact_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                         "associationTypeId": self.TASK_TO_CONTACT}]}]})
        return f"created task {r.get('id')} due {due_iso[:10]}"

    def write(self, contact_id: str, props: dict) -> str:
        assert "hs_email_optout" not in props, \
            "native opt-out is never written by the engine (guarantee 5)"
        if not self.apply:
            return f"would write {props}"
        self._call("PATCH", f"/crm/v3/objects/contacts/{contact_id}", {"properties": props})
        return f"wrote {props}"


# "with me" / "with myself" immediately before or after the booking link. Deliberately
# narrow -- only the phrase that CLAIMS the calendar is the writer's.
WITH_ME = re.compile(r"\bwith me\b(?=[^.!?]{0,40}(?:here|:|https?://))", re.I)


def name_the_calendar_owner(draft: str, owner: str, sender: str) -> tuple[str, bool]:
    """Rewrite "with me" to "with <owner>" when the calendar is not the sender's.

    **The prompt already says to do this and the model does not.** Told plainly that
    meetings are round-robined and to name the owner when it is not them, it still wrote
    "You can grab some time with me here: <Kate's link>" over Brooke's signature on two
    consecutive tests. Third time this project has landed on the same place: an
    instruction is not a guarantee, so the guarantee goes in code.

    It matters more here than for a dash. The prospect replied to Brooke, is told they
    are booking with Brooke, and lands on Kate's calendar -- on the single warmest reply
    type we get. Getting caught doing that costs the meeting.
    """
    if not owner or not sender or owner.strip().lower() == sender.strip().lower():
        return draft, False
    clean = owner.replace(" (fallback)", "").strip()
    fixed = WITH_ME.sub(f"with {clean}", draft)
    return fixed, fixed != draft


# ---- CRM enrichment from a reply ------------------------------------------------

# A prospect's own words -> the exact `current_competitor` option in HubSpot. The
# property is an ENUMERATION with a fixed option list, which is what makes this safe to
# automate: a value that is not an exact option is rejected by HubSpot, so the worst a
# wrong guess can do is fail loudly rather than write a fiction into the CRM.
#
# Keys are matched against the prospect's text lower-cased, longest key first. The
# options themselves are fetched from HubSpot at runtime and checked against this map on
# startup, so adding an option there without adding an alias here is visible rather than
# silent.
PLATFORM_ALIASES = {
    "resident advisor": "Resident Advisor", "ra": "Resident Advisor",
    "eventbrite": "Eventbrite", "event brite": "Eventbrite", "eb": "Eventbrite",
    "dice": "DICE", "dice.fm": "DICE",
    "shotgun": "Shotgun", "tixr": "Tixr", "luma": "Luma", "lu.ma": "Luma",
    "partiful": "Partiful", "mindbody": "Mindbody", "instagram": "Instagram",
    "seetickets": "Seetickets", "see tickets": "Seetickets",
    "eventim": "Eventim", "markit": "markit", "eventlive": "EventLiveUS",
    "posh": "Posh",
}
# The Disqualified lifecycle stage in THIS portal. Not a name -- an internal id, because
# the labels here are non-standard: `customer` is labelled "Outreached", not "Customer".
# Read them with GET /crm/v3/properties/contacts/lifecyclestage before trusting any of
# them; assuming HubSpot's defaults is how "already a Posh customer" got said out loud
# about a contact that merely had been emailed once.
LIFECYCLE_DISQUALIFIED = lifecycle.DISQUALIFIED

# outbound_status meaning "a named human owns this thread now". Set when a reviewer
# picks "Hand off" on a queue row; honoured here (no draft), by eligibility (never
# re-enrolled) and by sync_meetings (a booking STILL promotes -- a meeting the rep
# closes is the point of handing over, and losing it would understate the outcome).
HANDED_OFF = "handed_off"


def match_platform(said: str, allowed: set[str]) -> str:
    """The prospect's words -> an exact HubSpot option, or "".

    Word-boundary matched so "RA" does not fire on "great" or "contract", which is the
    entire risk with a two-letter alias. Returns "" for anything unrecognised, and that
    is the common case by design: an unmapped platform is left for a human rather than
    approximated.
    """
    t = f" {(said or '').lower().strip()} "
    if not t.strip():
        return ""
    for alias in sorted(PLATFORM_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", t):
            got = PLATFORM_ALIASES[alias]
            return got if got in allowed else ""
    return ""


def competitor_options(hs) -> set[str]:
    """The exact values `current_competitor` accepts, from HubSpot."""
    d = hs._call("GET", "/crm/v3/properties/contacts/current_competitor")
    return {o.get("value") for o in (d.get("options") or []) if o.get("value")}


# ---- classification ------------------------------------------------------------

CLASSIFY_PROMPT = """You are the reply classifier for a cold outbound email engine.

Read the WHOLE thread, then classify the prospect's most recent reply as exactly one
intent. Return ONLY a JSON object:

{"intent": "<one intent>", "reason": "<under 15 words>", "proposed_action": "<under 20 words>", "draft_response": "<a short reply a human will review, or empty>", "named_return_date": "<YYYY-MM-DD or empty>", "named_platform": "<the ticketing platform they say they use, VERBATIM as they wrote it, or empty>", "not_a_fit_reason": "<why they structurally cannot use us, in under 12 words, or empty>"}

The ten intents:
- interested: wants to engage, learn more, or meet. ALSO covers a request for materials,
  pricing, a deck, or a demo, which are buying signals.
- question: asking something before deciding, with no buying lean.
- objection: a concern a reply could address. THIS INCLUDES A NAMED INCUMBENT -- "we
  already use X", "we're happy with X" -- because a stated reason is a concern.
- not_interested: a BARE decline that gives no reason. If they said WHY, it is objection.
  "Thanks, we are good" / "no thanks" / "not for us" are THIS, not objection. Being
  content is not a reason -- there is no concern in it for a reply to address. Drifted
  to objection on 2026-09-22 after objection gained worked examples and not_interested
  had none; the two share a door-open draft, so the tell is the TEXT, not the tone.
- not_now: positive or neutral but explicitly later.
- not_qualified: structural non-fit (out of business, does not run ticketed events).
  **"We built our own platform" is NOT this.** They run ticketed events and are using
  something else to do it, which is an incumbent and therefore an OBJECTION -- the most
  workable one in this market. Classified not_qualified in a real run, which would both
  retire the contact and draft "you're right that this isn't a fit" at a company that is
  exactly the target. A team that built their own tool has already decided ticketing
  matters to them.
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

  "Thank you for contacting the Housing Industry Foundation! To learn more about our
   programs or to find out how to apply for Emergency Housing Assistance, please visit
   our website... our programs support families that reside in California, in either
   the Santa Clara or San Mateo counties. For all others, we recommend calling 211."
  -> automated_reply, and **this is the form most likely to be misread**. A real one
     came in on 2026-09-22 and was classified not_qualified, because the text is full of
     apparent qualification signal: a charity, a narrow geography, nothing about events.
     Mining that was the error. The FORM is decisive and it is unmistakable -- "Thank you
     for contacting [Organisation]!", a description of what the organisation does, a
     redirect to a website or a hotline, and **not one word responding to what we
     actually asked**. Nobody read our email. There is nothing to reply to, and drafting
     a reply to a machine wastes a reviewer's attention.

     Note what is deliberately given up: this organisation plainly is not a prospect,
     and classifying by form means not recording that. That is the trade precedence
     rule 2 already makes, and it is the right one -- a human can disqualify a contact
     in one click, where a reply sent to a no-reply address is gone.

  "Dear friends, thank you for your message. Due to an exceptionally high number of
   incoming messages, I may be slow to respond... Brand Deals, Speaking Opportunities,
   and Other Business Requests: please contact my manager Arjun (arjun@...) and cc his
   assistant. Press Requests: ... Private Individual/Follower: ..."
  -> automated_reply, NOT wrong_contact. A real one came in on 2026-10-08, seven seconds
     after our email, and was classified wrong_contact with a draft to "reach out to
     Arjun", which also marked the contact disqualified. The names in it are a STANDING
     ROUTING MENU addressed to everyone ("Dear friends"), sorted by request category,
     not a person telling US they are the wrong contact. **A redirect inside a
     templated reply is part of the template.** wrong_contact needs a human who read our
     email and pointed elsewhere. "Slow to respond" with no return date is not an
     absence either, so it is not out_of_office.

The test in one line: **out_of_office means a person is temporarily absent and will be
back; automated_reply means a machine answered and no one is absent at all.** Getting
this backwards matters, because only one of the two may be safely restarted today.

The draft_response is for a HUMAN TO REVIEW AND SEND. Never write one for
out_of_office or automated_reply. Keep it short, plain, one ask, no dashes, and never
promise pricing or terms.

ENRICHMENT, and both fields are for the CRM rather than for the draft:

`named_platform`: fill ONLY when the prospect states what they currently use. Copy their
words exactly -- "RA", "we're on Dice", "our own platform" -- and do not expand, guess or
normalise; code maps it to a known platform afterwards and discards anything it cannot
match. A platform WE mentioned in our own email does not count, only what THEY say.
Empty is the correct answer whenever they did not name one, which is most of the time.

`not_a_fit_reason`: fill ONLY for a structural impossibility -- they run no ticketed
events, they have closed, they are a charity with no events. NOT for "not interested",
"bad timing", "happy with our current tool" or any other decision they could reverse.
The test is whether the fact would still be true in a year.

**For `interested` ONLY, the draft MUST include this booking link, as a plain
visible URL: {booking_link}** ({owner}'s calendar).

**NEVER put a booking link in a `question` reply.** Changed 2026-10-02, on a real
thread: a prospect asked "what is it exactly what you want me to as an offering" and
then "Is the a job offering?" -- and both drafts proposed a 30-minute call with Zach.
Someone asking WHAT WE ARE is not ready to put it on a calendar, and answering a
question with a meeting request reads as not having listened. Answer the question, stop,
and let the link come when they show interest. A money-adjacent question ("what does it
cost?") is a BUYING SIGNAL and you classify it `interested`, so it still gets the link
-- that rule is unchanged and this one does not weaken it.

**If that value is a bracketed
placeholder rather than a URL, reproduce it verbatim** -- it means this lead has no
HubSpot record so the right calendar is not knowable, and a reviewer will paste it in.
Never substitute a real link you have seen elsewhere in the thread. Do not invent a
different link, do
not write "I'll send over some times" and do not offer to find a slot by hand -- give
them the link so they can book.

**WHOSE calendar it is matters, and you are told above.** Meetings are round-robined
across the team, so {owner} is usually NOT the person writing:
  - {owner} is the SENDER -> "You can grab some time with me here: {booking_link}"
  - {owner} is SOMEONE ELSE -> name them. "You can grab some time with {owner} on our
    team here: {booking_link}"
Never write "with me" over somebody else's link. The prospect finds out whose calendar
it is the moment they click; the only choice is whether we told them first, and an
unexplained switch reads as a bait and switch on an otherwise warm reply.

**EVERY intent except out_of_office and automated_reply GETS A DRAFT.** A queued row with
an empty draft makes a human write from scratch, which is most of what the queue exists to
save. What each one says (from instructions/reply-handling.md):

  question              -> ANSWER IT, in one or two plain sentences, and STOP. No
                           booking link, no call, no "happy to walk you through it".
                           They asked something specific; the reply that earns the next
                           one answers it. The owner's edit on a real thread:
                             "Hi Angel, no. Posh isn't a job. We're a ticketing
                              platform for event organizers. If you run events and sell
                              tickets, we can help. If that's not you, no worries."
                           Note what that does -- answers plainly, says who it IS for,
                           and gives them an easy exit. No ask at all.

  interested            -> warm, one line, PLUS the booking link above. **Offer the
                           conversation; do not re-pitch.** They already said yes to
                           hearing more, so a claim here can only lose. The owner's edit:
                             "I'm happy to walk you through what Posh has to offer and
                              what we can put together for you. You can grab some time
                              with me here: <link>"
                           The model had added "we help event organizers move away from
                           clunky platforms and take control of their ticketing" --
                           unasked-for positioning AND a swipe at competitors, in a
                           reply to someone who had already said "Tell me more".

  **IF YOU OPEN WITH A GREETING, PUT IT ON ITS OWN LINE.** "Hi Joseph," then a line
  break, then the reply. Not "Hi Joseph, that's awesome to hear" as one run-on line --
  that reads like a chat message, not an email. ONE newline, not a blank line. The
  engine enforces this after you, so writing it correctly only saves a rewrite.

      Hi Joseph,
      That's awesome to hear! I'm happy to walk you through what we can put
      together for you and your events.

  A greeting is optional -- a one-line answer often reads better without one -- but if
  you write one, break the line.

  **US SPELLING, always.** The model wrote "organisations" in a real draft. Posh is a
  New York company writing to US organizers: organize, personalize, recognize, center,
  favorite. Never -ise, -isation or -re.
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
                           **WRITE ONE ANYWAY.** Four prohibitions and no example made
                           the model return an EMPTY draft for every objection, so the
                           owner hand-wrote all of them. Two shapes, and **which one
                           depends on whether they named a CONTRACT**:

                           (a) They named a contract or a renewal -> ask when it ends.
                               "Thanks for letting us know. Would you be interested in
                                reconnecting once your contract is up for renewal?"
                               A question about WHEN is not a pitch and not a meeting,
                               and the renewal date is the single most useful thing an
                               incumbent objection can tell you.

                           (b) Any other objection -> acknowledge and leave the door
                               open, with NO question at all.
                               "Gotcha. Thanks for letting me know. If your plans ever
                                shift, and you need some more ticketing support, feel
                                free to reach out!"

                           **Do not ask about a contract nobody mentioned.** Adding (a)
                           as the only example made the model put "once your contract is
                           up for renewal" on a reply that said merely "we are good,
                           thank you" -- inventing a contract out of an exemplar.

                           **DO NOT WRITE A STARTER KIT INVITE.** Where one belongs, the
                           engine appends it after you, verbatim from config. You are
                           told only so you do not write a second, different version of
                           the same offer. Never mention a Starter Kit, a webinar, a
                           session, a demo or a walkthrough yourself, and never invent a
                           time or a link for one.
  not_now               -> acknowledge their timing, say you will come back then, name
                           the time they gave. No link, no pitch.
  not_interested        -> short and gracious. No re-pitch, no link, no "just one more
                           thing". Leave the door open in one clause, and name the thing
                           THEY named if the thread gives you one. The owner's edit:
                             "Thanks for letting me know. Feel free to reach out if
                              anything changes. All the best with Arte Agave Series."
                           "your events" was what the model wrote; their actual event
                           series was sitting in the signature.
  asked_to_stop         -> one line confirming they are removed. Nothing else, ever.
  not_qualified         -> short and friendly, no pitch. AGREE with them rather than
                           hedging, and name their business. The owner's edit:
                             "Thanks for clarifying, Isaac. We focus on venues and
                              organizers with regular ticketed events, so you're right
                              that this isn't the fit. Best of luck with Bellwoods!"
                           The model wrote "it sounds like we're not the right fit",
                           which hedges a judgement the prospect already made for us,
                           and "organisations", which is both the wrong word for our
                           audience and British spelling.
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

    **A round robin across the whole team as of 2026-09-24**, and the column is headed
    "Meeting owner" rather than "Sender" because those are no longer the same people.
    History: a single owner (Zach, the only person taking meetings), then one link per
    sender when he was promoted, now a pool because sending capacity and meeting
    capacity are different constraints.

    The header is matched on EITHER label. Renaming the column in the config broke this
    parser the first time, and it failed loudly -- "refusing to draft a meeting reply
    with no link" -- which is the right failure but an avoidable one.
    """
    text = MEETING_ROUTING.read_text(encoding="utf-8")
    block = re.search(
        r"\|\s*(?:Sender|Meeting owner)\s*\|\s*Booking link\s*\|(.*?)(?=\n\n|\n[^|])",
        text, re.S | re.I)
    links: dict[str, str] = {}
    if block:
        for row in block.group(1).splitlines():
            m = re.match(r"\s*\|\s*([A-Za-z][\w .'-]*?)\s*\|\s*`?(https?://\S+?)`?\s*\|",
                         row)
            if m and m.group(1).strip().lower() not in ("sender", "---"):
                links[m.group(1).strip()] = m.group(2)
    # "Fallback meeting owner" since 2026-09-24, "Fallback sender" before it. Both
    # accepted: renaming the label in config silently emptied this once, and a missing
    # fallback only shows up on the rare lead that needs one.
    fb = re.search(r"\*\*Fallback (?:sender|meeting owner):\s*`?([A-Za-z][\w .'-]*?)`?\*\*",
                   text)
    if fb:
        links["__fallback__"] = fb.group(1).strip()
    if not links:
        raise RuntimeError(
            f"no booking links found in {MEETING_ROUTING.name}. Expected a '| Sender | "
            "Booking link |' table. Refusing to draft a meeting reply with no link "
            "rather than silently omitting it.")
    return links


def booking_link_for(sender: str, links: dict[str, str] | None = None,
                     contact_email: str = "") -> tuple[str, str]:
    """(sender name, their link), or ("", "") when the sender is UNKNOWABLE.

    **Two different situations, and conflating them cost the whole run once.**

    An EMPTY sender means there is no HubSpot contact for this lead, or it was not
    enrolled by the engine -- a Smartlead-only lead, a hand-uploaded list, a contact
    deleted after enrolment. That is an ordinary fact about the data, it is reachable
    today (the reply-test leads have no HubSpot record at all), and it must NOT raise:
    there is no per-contact try/except in the reply loop, so one such lead would abort
    the run and stop every real prospect's reply being processed. Returns ("", "") and
    the draft goes out without a link for a human to add.

    A NAMED sender with no row is different: somebody added a sender to `senders.md` and
    forgot `meeting-routing.md`. That is a config gap, it affects every contact that
    sender ever mails, and it should be loud. Still raises.

    **Neither case ever falls back to another sender's calendar.** Handing a prospect the
    wrong person's time while looking like it worked is the failure both branches exist
    to prevent, and defaulting to the first row would quietly restore the single-owner
    behaviour this replaced.
    """
    links = links if links is not None else booking_links()
    fallback = links.get("__fallback__", "")
    links = {k: v for k, v in links.items() if k != "__fallback__"}
    who = (sender or "").strip()
    pool = sorted(links)                       # fixed order, so the hash is stable
    if not pool:
        return "", ""
    # **ROUND ROBIN, not sender-matched (2026-09-24).** Who writes and who takes the
    # meeting are now separate questions -- see config/meeting-routing.md. The owner is
    # chosen from the whole pool regardless of which identity sent the email.
    #
    # Keyed on the CONTACT, and deterministic, because this function runs again on every
    # heartbeat: `random()` would show one prospect Kate's calendar on Monday and
    # Caroline's on Tuesday, which reads as a company that cannot keep track of itself.
    # Same reasoning as pick_variant in run_generation.
    if contact_email:
        # **SALTED, and the salt is load-bearing (fixed 2026-09-25).** This used to hash
        # the bare address, which collided with `split_by_sender --batch K/N` -- that
        # selects contacts on `hash % N` of the SAME unsalted string. With N=2 the batch
        # filter consumes the low bit, and because len(pool) is even, `% len(pool)`
        # inherits that parity: batch 1/2 could only ever reach the even-indexed owners
        # (Carl, Henry, Lawrence) and batch 2/2 only the odd (Caroline, Kate, Zach).
        # The 1,314-contact round was silently routing to three of six calendars.
        #
        # Two hashes of one string are only independent if something distinguishes them.
        # `run_generation.pick_variant` takes a `salt` for exactly this reason; this
        # function predated that lesson. Any future per-contact hash needs its own salt.
        idx = int(hashlib.sha256(
            ("meeting-owner:" + contact_email.strip().lower()).encode()).hexdigest(), 16)
        name = pool[idx % len(pool)]
        return name, links[name]
    # No contact email -- a Smartlead-only lead. The sender's own calendar if they have
    # one, otherwise the configured fallback. Not a hash of nothing, which would send
    # every anonymous lead to the same person.
    for name in pool:
        if name.lower() == who.lower():
            return name, links[name]
    for name in pool:
        if name.lower() == fallback.lower():
            return f"{name} (fallback)", links[name]
    return "", ""


# HubSpot owner ids for the meeting-routing names, resolved once per run and matched on
# FIRST NAME -- the same convention `split_by_sender.owner_to_sender()` and
# `pre-send-defaults.excluded_owners` already use, so a rep is identified one way
# everywhere. Cached because the reply loop would otherwise re-fetch per contact.
_OWNER_IDS: dict[str, str] | None = None


def owner_ids(token: str | None = None) -> dict[str, str]:
    """{first name lowercased: owner id} for everyone in the HubSpot owners list."""
    global _OWNER_IDS
    if _OWNER_IDS is not None:
        return _OWNER_IDS
    import urllib.request as _u
    tok = token or env_token()
    req = _u.Request("https://api.hubapi.com/crm/v3/owners?limit=200",
                     headers={"Authorization": f"Bearer {tok}"})
    out = {}
    try:
        with _u.urlopen(req, timeout=30) as r:
            for o in json.load(r).get("results", []):
                fn = (o.get("firstName") or "").strip().lower()
                if fn:
                    out.setdefault(fn, str(o["id"]))
    except (OSError, http.client.HTTPException) as e:
        # OSError, not URLError: http.client.RemoteDisconnected is a
        # ConnectionResetError. This has bitten sync_sends and eligibility already.
        print(f"    !! could not read HubSpot owners ({type(e).__name__}); "
              f"no contact owner will be assigned this run")
    _OWNER_IDS = out
    return out


def assign_meeting_owner(props: dict, existing: dict, owner: str, link: str,
                         draft: str) -> str:
    """Set the contact owner to the person whose calendar the prospect was just sent.

    Added 2026-09-25 on Aliza's call: meetings round-robin across the whole team, so
    without this a prospect books with Kate while the contact record stays unowned and
    nobody is accountable for the relationship.

    THREE CONDITIONS, all necessary:

      1. The draft actually CONTAINS the link. Not the intent label -- the link is
         offered to the classifier on every reply and the model includes it only when
         it is warranted, so the draft text is the ground truth for "was this prospect
         sent someone's calendar". An objection reply that never offers a meeting must
         not reassign the contact.
      2. The contact has NO owner today. 90 of the 1,314 in the first large round were
         owned by people with real relationships (Daniela, Rob, Gabriela and others).
         A round robin must never displace a human's book.
      3. The name resolves to a HubSpot owner id. An unresolvable name is reported and
         skipped rather than written as a blank, which would LOOK like an assignment.

    Assignment happens on REPLY rather than at enrolment, deliberately: ownership then
    means "this rep has a live conversation", instead of putting ~205 cold, unanswered
    contacts into each of six reps' dashboards and owner-based workflows.

    Returns a note for the run log, or "" when nothing was done.
    """
    if not (owner and link and draft and link in draft):
        return ""
    if (existing.get("hubspot_owner_id") or "").strip():
        return ""                                  # condition 2 -- never displace
    oid = owner_ids().get(owner.strip().lower())
    if not oid:
        return (f"owner NOT assigned: {owner!r} has no HubSpot owner record "
                f"(add one, or the meeting lands on an unowned contact)")
    props["hubspot_owner_id"] = oid
    return f"owner -> {owner} ({oid}), whose calendar the draft offers"


def recycle_task_owner(existing: dict, contact_email: str) -> tuple[str, str]:
    """(owner id, why) for a re-engagement task. Aliza's call, 2026-09-25.

    An existing HubSpot owner wins -- that is a real relationship and the person who
    should hear that their contact is ready again. Otherwise the contact's deterministic
    meeting-routing owner takes it, which spreads recycle work across the whole team
    instead of piling every one of them on the two people who happen to own the warmed
    mailboxes. Same rotation, same salt, so the rep who would have taken their meeting
    is the rep who gets the reminder.
    """
    owned = (existing.get("hubspot_owner_id") or "").strip()
    if owned:
        return owned, "existing contact owner"
    who, _link = booking_link_for(existing.get("outbound_sender", ""),
                                  contact_email=contact_email)
    if not who:
        return "", "no owner and no routing match"
    oid = owner_ids().get(who.strip().lower())
    if not oid:
        return "", f"{who} has no HubSpot owner record"
    return oid, f"round-robin -> {who}"


def recycle_task_text(existing: dict, res: dict, recycle: str,
                      reply_excerpt: str, due_note: str = "",
                      basis: str = "default") -> tuple[str, str]:
    """Subject and body for the re-engagement task.

    The body carries WHAT THEY SAID. A task reading "follow up" tells a rep in nine
    months nothing they can act on; their own words, the competitor and the date are
    the whole value of having recorded the reply in the first place.
    """
    org = (existing.get("prospect_org") or existing.get("company")
           or existing.get("firstname") or "").strip()
    comp = (res.get("named_platform") or existing.get("current_competitor") or "").strip()
    # "contract ends" ONLY when the prospect said so. Otherwise the date is our own
    # +90 day floor, and putting it in front of a rep as a contract end is inventing a
    # fact about the account -- the CRM equivalent of a claim the copy validator would
    # reject. An unnamed date gets the honest label.
    when = {"named": f"contract ends {recycle[:10]}",
            "objection": f"on {comp or 'a competitor'}, no renewal date given",
            }.get(basis, f"follow up after {recycle[:10]}")
    subject = f"Re-engage{' ' + org if org else ''} — {when}"
    # The objection wording already names the platform; appending it again produced
    # "on Resident Advisor, no renewal date given (on Resident Advisor)".
    if comp and basis != "objection":
        subject += f" (on {comp})"
    opener = ("They replied with an objection naming their current platform."
              if basis == "objection" else "They replied 'not now'.")
    lines = [f"Outbound re-engagement. {opener}", ""]
    if due_note:
        lines += [due_note[0].upper() + due_note[1:], ""]
    if comp:
        lines.append(f"Currently using: {comp}")
    if reply_excerpt:
        lines += ["", "What they said:", f'"{reply_excerpt.strip()[:600]}"']
    if basis == "named":
        tail = (f"This task is early on purpose -- the point is to talk before the "
                f"renewal is drafted. The engine will not cold-email them until "
                f"{recycle[:10]}; reaching out personally before then is your call.")
    elif basis == "objection":
        tail = (f"They told us they are on {comp or 'another platform'} but gave NO "
                f"renewal date, so {recycle[:10]} is OUR six-month estimate and not "
                f"something they said -- treat it as a prompt to find out when they "
                f"are actually up, not as a known deadline. The engine will not "
                f"cold-email them before then.")
    else:
        tail = (f"They gave no date, so {recycle[:10]} is our own 90-day default "
                f"rather than anything they said. The engine will not cold-email them "
                f"before it.")
    lines += ["", tail, "", HubSpotWriter.TASK_MARKER]
    return subject, "\n".join(lines)


def task_due_date(recycle: str, named: str | None, today: str = "",
                  cfg: dict | None = None) -> tuple[str, str]:
    """(date the task is due, one-line reason). Aliza's request, 2026-09-28.

    A contract end is a DEADLINE, not an appointment. A prospect under contract with
    DICE until June is re-papered before June, so a task landing on the expiry date
    arrives after the decision it was meant to influence. The task moves
    `recycle_task_lead_days` earlier.

    **Only when the prospect NAMED the date.** This is the part that needs care. When
    they said nothing about timing, the recycle date is our own +90 day floor -- a
    guess, not a contract end. Subtracting 90 from a guess makes every vague "not right
    now" a task due today, and a queue where everything is due today is a queue nobody
    reads. So an unnamed date gets no lead time at all.

    Floored at TOMORROW, never the past: "we're locked in through next month" is a real
    answer and it lands inside the lead window.

    The recycle date itself is unchanged. That governs when the ENGINE may cold-email
    them, and three months before a contract ends is still mid-contract; this only
    governs when a human is asked to look.
    """
    cfg = cfg or defaults()
    lead = cfg["recycle_task_lead_days"]
    now = dt.date.fromisoformat(today) if today else dt.datetime.now(dt.timezone.utc).date()
    try:
        end = dt.date.fromisoformat((named or "")[:10])
    except ValueError:
        return recycle, "no date named; task on the recycle date"
    if not lead:
        return recycle, "no lead time configured"
    due = end - dt.timedelta(days=lead)
    if due <= now:
        return (now + dt.timedelta(days=1)).isoformat(), (
            f"contract ends {end.isoformat()}, inside the {lead}-day lead window; "
            f"task due tomorrow")
    return due.isoformat(), (f"contract ends {end.isoformat()}; task {lead} days ahead "
                             f"so the renewal conversation happens first")


_STARTER_KIT: dict[str, str] | None = None


def starter_kit() -> dict[str, str]:
    """{url, when} for the Starter Kit session, from config/meeting-routing.md.

    Parsed rather than restated, like the booking links in the same file. Returns {}
    when the block is absent, which disables the offer rather than raising -- unlike a
    missing BOOKING link, a missing Starter Kit costs a soft CTA and not a meeting, so
    it must not be able to abort a reply run.
    """
    global _STARTER_KIT
    if _STARTER_KIT is not None:
        return _STARTER_KIT
    m = re.search(r"## Starter Kit.*?```(.*?)```",
                  MEETING_ROUTING.read_text(encoding="utf-8"), re.S)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    if not out.get("starter_kit_url"):
        print("    starter kit: no url in config/meeting-routing.md; offer disabled")
        out = {}
    _STARTER_KIT = out
    return out


def wants_starter_kit(intent: str, named_platform: str) -> bool:
    """An objection that names NO recognised competitor -- the case with no path.

    A named platform earns a 180-day cooldown and a dated task, so those prospects are
    already tracked. A bare objection gets a draft and nothing else, and lapses back
    into the mailable pool after 30 days. See config/meeting-routing.md.
    """
    return intent == "objection" and not (named_platform or "").strip()


def add_starter_kit(draft: str, kit: dict[str, str] | None = None) -> tuple[str, bool]:
    """Append the Starter Kit offer if it is not already there. (draft, was_added).

    APPENDED IN CODE on purpose. Every copy rule in this engine that was left to the
    prompt was broken again later -- the greeting blank line, the reply dashes, the beat
    order, "with me" over another person's calendar. The model is told the offer exists
    so it does not invent a competing sentence; the sentence itself is ours.

    Idempotent on the URL, so a re-run or a model that did include it cannot produce it
    twice.
    """
    kit = kit if kit is not None else starter_kit()
    url = (kit.get("starter_kit_url") or "").strip()
    if not url or not draft.strip() or url in draft:
        return draft, False
    when = (kit.get("starter_kit_when") or "").strip()
    sentence = (f"In the meantime, feel free to check out our next Starter Kit session"
                f"{' on ' + when if when else ''} for tips on making the most of Posh! "
                f"Here is the link: {url}")
    return draft.rstrip() + "\n\n" + sentence, True


BOOKING_HOST = "meetings.hubspot.com"


def drop_booking_link(draft: str) -> tuple[str, bool]:
    """Remove the sentence offering a booking link. (draft, removed).

    The prompt is told not to write one on a `question`, and that is not enough -- six
    copy rules in this engine were "fixed" by instruction and broken again later. This
    is the enforcement.

    It removes the whole SENTENCE, not just the URL. Deleting the link alone leaves
    "You can grab some time with Zach here:" dangling, which is worse than the link:
    it promises something and delivers nothing.

    **It refuses rather than mangles.** If removal would leave almost nothing, the
    original is returned unchanged and the caller reports it instead -- a draft gutted
    to "Hi Angel." is not an improvement on one with a stray link, and a reviewer can
    fix a visible problem.
    """
    if BOOKING_HOST not in (draft or ""):
        return draft, False
    out = draft
    # Repeatedly: find the link, cut back to the start of its sentence, forward to the
    # end of the URL. A draft can only hold a couple, but the loop costs nothing.
    for _ in range(4):
        i = out.find(BOOKING_HOST)
        if i < 0:
            break
        start = max((out.rfind(c, 0, i) for c in (".", "!", "?", "\n")), default=-1)
        start = 0 if start < 0 else start + 1
        end = len(out)
        for j in range(i, len(out)):
            if out[j].isspace():
                end = j
                break
        out = out[:start] + out[end:]
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    # A reply that is now just a greeting is not a reply.
    if len(out) < 40:
        return draft, False
    return out, True


# "Hi Joseph," / "Hey Amelia," / "Hello there," at the very start of a draft, glued to
# the body by a space rather than a line break. Anchored to the start: a "Hi" in the
# middle of a sentence is not a greeting.
GREETING_RE = re.compile(r"^(H(?:i|ey|ello)\b[^,\n]{0,40},)[ \t]+(\S)")


def split_reply_greeting(draft: str) -> tuple[str, bool]:
    """Put the greeting on its own line. (draft, changed).

    Aliza's rule, 2026-10-02, from the way she hand-formats every draft she edits:

        Hi Joseph,
        That's awesome to hear! ...

    The engine writes "Hi Angel, great question. We handle ticketing..." -- greeting and
    body as one run-on line, which reads like a chat message rather than an email.

    **ONE newline, not two.** The cold-copy rule in `repair.split_greeting` inserts a
    BLANK line, because a cold email is a composed object and wants the air. A reply is
    a conversation and she writes it tight; this matches what she actually does rather
    than what the other rule does.

    **Leaves an existing break alone**, one newline or two. The complaint is gluing, not
    spacing, and churning drafts that are already fine would make this rule its own
    source of diffs.

    The body's first letter is capitalised, because on its own line it starts a sentence:
    "Hi Angel,\ngreat question" reads as a mistake where "Hi Angel,\nGreat question"
    does not.
    """
    m = GREETING_RE.match(draft or "")
    if not m:
        return draft, False
    greeting, first = m.group(1), m.group(2)
    rest = draft[m.end():]
    return f"{greeting}\n{first.upper()}{rest}", True


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


def classify(client, model: str, thread: list[dict], sender: str = "",
             contact_email: str = "") -> dict:
    rendered = "\n\n".join(
        f"[{'PROSPECT' if m['inbound'] else 'US'} {m['at']}] {m['subject']}\n{m['body']}"
        for m in thread)
    # The prospect's own words are what get classified, but the whole thread is supplied:
    # reply-handling.md step 3 requires reading the full conversation before acting.
    # The SENDER'S link, not a single owner's. Raises on an unknown or missing sender
    # rather than handing the prospect somebody else's calendar -- see booking_link_for.
    # contact_email drives the round robin -- see booking_link_for. Passing it is what
    # makes the choice per PROSPECT and stable; without it every lead falls through to
    # the sender-or-fallback branch, which is the old single-owner behaviour wearing the
    # new code.
    owner, link = booking_link_for(sender, contact_email=contact_email)
    if not link:
        # Only reachable if meeting-routing.md names no fallback sender, or names one
        # with no link row. Keep the honest placeholder for that case rather than
        # inventing a URL; send_replies refuses to send it.
        link = "[NO BOOKING LINK — reviewer must add the sender's own]"
        owner = "the sender"
    prompt = (CLASSIFY_PROMPT
              .replace("{booking_link}", link)
              .replace("{owner}", owner)
              .replace("{thread}", rendered[:12000]))
    # RETRIED, because this call is not guarded by anything above it. There is no
    # per-reply try/except in the loop, so an exception here aborts the whole run and
    # every reply after this one goes unprocessed until the next heartbeat. On
    # 2026-09-30 Bedrock returned 503 on two of three consecutive calls -- with the
    # SDK's own retries on top, that is a sustained wobble rather than a blip, and an
    # unguarded call through it would have silently cost a run.
    #
    # Caught broadly on PURPOSE. The interesting failures here are transport and
    # service-level (503, 429, timeouts, resets) and the SDK wraps them in its own
    # exception types; enumerating those couples this to the SDK's class names, which
    # is the same brittleness as catching URLError and missing RemoteDisconnected. A
    # deterministic error (a bad prompt, a malformed model id) simply fails four times
    # and then raises, which is the old behaviour.
    resp = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=model, max_tokens=500,
                messages=[{"role": "user", "content": prompt}])
            break
        except Exception as e:
            if attempt == 3:
                raise
            wait = 2 ** attempt
            print(f"    model call failed ({type(e).__name__}: {str(e)[:70]}); "
                  f"retry {attempt + 1}/3 in {wait}s")
            time.sleep(wait)
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    out = json.loads(raw.strip())
    # Recorded so the queue row can tell a reviewer the link is NOT the sender's own.
    # Without it the draft looks identical to a correctly-routed one.
    if "(fallback)" in owner:
        out["_link_fallback"] = owner.replace(" (fallback)", "")
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
    # **"Either intent acts the same" stopped being true on 2026-10-02**, when
    # `question` lost the booking link. Still accepted either way, and the tolerance is
    # now a real judgement rather than a shrug: answering "what's the payout timing
    # like?" without a calendar link is a perfectly good reply, and answering it WITH
    # one is also defensible because payout terms are money. The boundary is genuinely
    # blurred here, so both remain correct -- but they no longer produce the same draft.
    ("What's the payout timing like?", ("question", "interested"),
     "money-adjacent product question; both accepted, though they now differ in "
     "whether a booking link is offered"),
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
    # The objection/not_interested boundary. Added after adding worked examples for
    # objection pulled bare declines across with them: a reply carrying no reason has
    # no concern for a draft to address, however politely it is phrased.
    ("Thanks Carl, we are good, thank you.",
     "not_interested", "a contented decline with NO reason is not_interested"),
    # A REAL misclassification, 2026-09-22. Came back not_qualified and was queued with
    # a draft, so a human was asked to reply to a machine. Everything in the text points
    # at a genuine non-fit -- a charity, a narrow geography, no events anywhere -- and
    # mining it was the error. The form is decisive: a templated organisational
    # auto-responder that answers nothing we asked.
    ("Thank you for contacting the Housing Industry Foundation! To learn more about our "
     "programs or to find out how to apply for Emergency Housing Assistance, please "
     "visit our website at www.hifinfo.org. Please note, our programs support families "
     "that reside in California, in either the Santa Clara or San Mateo counties. For "
     "all others in need of assistance, we recommend calling 211.",
     "automated_reply",
     "P2: an ORG auto-responder is classified by form, however much apparent "
     "qualification signal its text carries"),
    # A REAL misclassification, 2026-10-08: came back wrong_contact, so the contact was
    # set disqualified and a human was asked to email the manager named in a template.
    ("Dear friends, Thank you for your message. Due to an exceptionally high number of "
     "incoming messages, I may be slow to respond (and in some cases, may not be able "
     "to personally respond at all). Currently, I am also traveling and researching. "
     "Brand Deals, Speaking Opportunities, and Other Business Requests: Please contact "
     "my manager Arjun (arjun@oddprojects.com) and cc his assistant Erin. Press "
     "Requests: For interview requests, please contact Arjun. Private "
     "Individual/Follower: While I likely won't be able to respond individually, your "
     "support is deeply valued.",
     "automated_reply",
     "P2: a routing menu in a templated reply is not a person redirecting us"),
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
    # Reply dates are relative to TODAY, not hardcoded. A fixed "2026-09-01" passed until
    # the calendar reached 2026-09-15, when 09-01 + 14 days WAS today and the
    # never-resume-before-tomorrow floor moved it -- so the suite broke on a date rather
    # than on a change. A test that fails when nothing was edited trains you to ignore it.
    _recent = (_today - dt.timedelta(days=2)).isoformat()
    check("a named return date wins",
          resume_date("out_of_office", _recent, _far, cfg), _far)
    check("no named date falls back to the configured wait",
          resume_date("out_of_office", _recent, None, cfg),
          (_today - dt.timedelta(days=2)
           + dt.timedelta(days=cfg["resume_ooo_default_days"])).isoformat())
    # A stale auto-responder must not resume instantly just because its date has passed.
    check("a named date in the past resolves to tomorrow, never today or earlier",
          resume_date("out_of_office", "2020-01-01", "2020-01-05", cfg),
          (_today + dt.timedelta(days=1)).isoformat())
    check("an unparseable named date falls back rather than raising",
          resume_date("out_of_office", _recent, "whenever", cfg),
          (_today - dt.timedelta(days=2)
           + dt.timedelta(days=cfg["resume_ooo_default_days"])).isoformat())
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

    # --- contact-owner assignment -------------------------------------------------
    # Offline (no model call). These guard the two ways this can do real damage:
    # displacing a human's contact, and reassigning someone who was never offered a
    # meeting. Both are silent failures in production -- nothing errors, the wrong
    # person simply owns the record -- so they are pinned here rather than trusted.
    _L = "https://meetings.hubspot.com/kate-burge"
    owner_cases = [
        ("link in the final draft, contact unowned -> assign",
         {}, "Kate", _L, f"Grab a time with Kate here: {_L}", True),
        ("no link in the draft -> never reassign on an objection or a decline",
         {}, "Kate", _L, "Understood -- I'll check back next year.", False),
        ("contact already owned -> never displace a human's relationship",
         {"hubspot_owner_id": "89417286"}, "Kate", _L, f"here: {_L}", False),
        ("owner name has no HubSpot record -> report, never write a blank id",
         {}, "Mallory", _L, f"here: {_L}", False),
        ("no owner and no link -> no-op",
         {}, "", "", "whatever", False),
    ]
    owner_wrong = 0
    print()
    for why, existing, owner, link, draft, should in owner_cases:
        props = {}
        try:
            assign_meeting_owner(props, existing, owner, link, draft)
        except Exception as e:                     # a raise here would abort a real run
            print(f"  RAISED {type(e).__name__}: {why}")
            owner_wrong += 1
            continue
        got = "hubspot_owner_id" in props
        ok = got == should and (not got or bool(props["hubspot_owner_id"]))
        owner_wrong += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} owner          | {why}")
    print(f"\n{len(owner_cases) - owner_wrong}/{len(owner_cases)} owner-assignment "
          f"cases correct")

    # --- re-engagement tasks -------------------------------------------------------
    task_wrong = 0
    print()
    _ex = {"prospect_org": "Beretta Music", "outbound_sender": "carl"}
    subj, body_txt = recycle_task_text(
        _ex, {"named_platform": "DICE"}, "2027-06-01",
        "We're with DICE until next summer.", basis="named")
    checks = [
        ("subject names the prospect", "Beretta Music" in subj),
        ("subject carries the date", "2027-06-01" in subj),
        ("a NAMED date is called a contract end", "contract ends" in subj),
        ("body quotes what they said", "until next summer" in body_txt),
        ("body records the competitor", "DICE" in body_txt),
        # Without the marker the idempotency check cannot recognise its own task and
        # every heartbeat creates another one.
        ("body carries the dedup marker", HubSpotWriter.TASK_MARKER in body_txt),
    ]
    # An existing owner is a real relationship and must win over the rotation.
    _owned, _why = recycle_task_owner({"hubspot_owner_id": "89417286"}, "a@b.com")
    checks.append(("existing owner beats the round robin", _owned == "89417286"))

    # --- task DUE DATE: ahead of a named contract end, on the date otherwise --------
    _T = "2026-09-28"
    _d, _ = task_due_date("2027-06-01", "2027-06-01", today=_T)
    checks.append(("a named contract end lands 90 days early", _d == "2027-03-03"))
    # The one that matters most. With no named date the recycle date is our own +90
    # floor -- a guess. Subtracting the lead from a guess would make every vague
    # "not right now" a task due today and drain the queue of meaning.
    _d, _ = task_due_date("2026-12-27", None, today=_T)
    checks.append(("an UNNAMED date gets no lead time", _d == "2026-12-27"))
    _d, _ = task_due_date("2026-12-27", "", today=_T)
    checks.append(("an empty named date gets no lead time", _d == "2026-12-27"))
    _d, _ = task_due_date("2026-11-01", "not a date", today=_T)
    checks.append(("an unparseable date falls back, never raises",
                   _d == "2026-11-01"))
    # A contract ending inside the lead window must not produce a task in the past.
    _d, _ = task_due_date("2026-10-20", "2026-10-20", today=_T)
    checks.append(("a contract ending soon is due tomorrow, never in the past",
                   _d == "2026-09-29"))
    # The real production call passes NO cfg: the local `cfg` in main() is the sheet
    # config, and passing it raised KeyError. Exercise the defaulted path.
    try:
        task_due_date("2027-06-01", "2027-06-01")
        checks.append(("the defaulted-cfg path used in production works", True))
    except Exception as e:
        checks.append((f"the defaulted-cfg path raised {type(e).__name__}", False))
    # A contact with no owner still gets one, from the same rotation as their meeting.
    _rr, _ = recycle_task_owner({"outbound_sender": "carl"}, "a@b.com")
    checks.append(("unowned contact still gets an assignee", bool(_rr)))
    # An UNNAMED date must never be presented to a rep as a contract end. That date is
    # our own +90 default; calling it a contract end puts a fact in the CRM that the
    # prospect never stated.
    _s, _b = recycle_task_text(_ex, {}, "2026-12-27", "not right now",
                               basis="default")
    checks.append(("an unnamed date is NOT called a contract end",
                   "contract ends" not in _s and "follow up after" in _s))
    checks.append(("the body says the date is our default, not theirs",
                   "our own 90-day default" in _b))

    # --- objection naming an incumbent ---------------------------------------------
    # The gap this closes: "we have a contract with RA" is an OBJECTION, not not_now,
    # and objections set no recycle date -- leaving the contact held only by the
    # 30-day replied window and re-mailable a month after they told us.
    _A = "2026-09-21T09:00:00Z"
    _r = recycle_date("objection", _A, None, None, platform="RA")
    checks.append(("a named incumbent earns a 180-day cooldown", _r == "2027-03-20"))
    _r = recycle_date("objection", _A, None, None, platform="")
    checks.append(("a BARE objection earns no cooldown", _r is None))
    _r = recycle_date("objection", _A, "2027-06-01", None, platform="RA")
    checks.append(("a date they DID give still wins", _r == "2027-06-01"))
    _s, _b = recycle_task_text(_ex, {"named_platform": "Resident Advisor"},
                               "2027-03-20", "We have a contract with RA.",
                               basis="objection")
    checks.append(("the objection task names the incumbent, not a fake contract end",
                   "no renewal date given" in _s and "contract ends" not in _s))
    checks.append(("the body calls the date OUR estimate",
                   "our six-month estimate" in _b.lower()))
    checks.append(("the incumbent is not printed twice in the subject",
                   _s.count("Resident Advisor") == 1))
    for why, ok in checks:
        task_wrong += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} task           | {why}")
    print(f"\n{len(checks) - task_wrong}/{len(checks)} re-engagement-task cases correct")

    # --- booking link on a question reply -------------------------------------------
    LINK = "https://meetings.hubspot.com/zach-hickman"
    ql = []
    out, rm = drop_booking_link(
        f"Hi Angel, great question. We handle ticketing and payments for event "
        f"organizers. You can grab some time with Zach here: {LINK}")
    ql.append(("the offer sentence goes, not just the url",
               rm and BOOKING_HOST not in out and "grab some time" not in out))
    ql.append(("the answer before it survives intact",
               "ticketing and payments for event organizers." in out))
    out, rm = drop_booking_link("No link here, just a plain answer about ticketing.")
    ql.append(("a draft with no link is untouched", not rm))
    # Refusing beats mangling: a reply cut down to a greeting is worse than a stray link.
    orig = f"Hi Angel.\n{LINK}"
    out, rm = drop_booking_link(orig)
    ql.append(("it REFUSES when almost nothing would survive",
               not rm and out == orig))
    out, rm = drop_booking_link(
        f"Thanks for asking. Posh handles ticketing for organizers like you. "
        f"Grab time here: {LINK} and also here: {LINK}")
    ql.append(("two links both go", rm and BOOKING_HOST not in out))
    # The source of the rule, in code rather than in the prompt alone.
    _src = __import__("inspect").getsource(main)
    _code = "\n".join(l for l in _src.splitlines() if not l.strip().startswith("#"))
    ql.append(("it is enforced for `question` in main()",
               'if intent == "question":' in _code))
    ql.append(("...before name_the_calendar_owner, which labels a link that STAYS",
               _code.index("drop_booking_link(draft)")
               < _code.index("name_the_calendar_owner(")))
    ql.append(("a refusal is flagged on the row, not swallowed",
               "booking link in a QUESTION reply" in _code))
    q_wrong = 0
    print()
    for why, ok in ql:
        q_wrong += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} questionCTA   | {why}")
    print(f"\n{len(ql) - q_wrong}/{len(ql)} question-CTA cases correct")

    # --- greeting on its own line ---------------------------------------------------
    gl = []
    out, ch = split_reply_greeting("Hi Angel, great question. We handle ticketing.")
    gl.append(("a glued greeting is split", ch and out.startswith("Hi Angel,\n")))
    gl.append(("the body is capitalised on its new line", "\nGreat question." in out))
    # One newline, not two. The cold-copy rule inserts a blank line; a reply is written
    # tight, and this matches how the drafts are hand-formatted.
    gl.append(("ONE newline, not a blank line", "\n\n" not in out))
    _, ch = split_reply_greeting("Hi Joseph, \nThat's awesome to hear!")
    gl.append(("an existing single break is left alone", not ch))
    _, ch = split_reply_greeting("Hi Joseph,\n\nAlready spaced.")
    gl.append(("an existing blank line is left alone", not ch))
    _, ch = split_reply_greeting("Thanks for letting us know. We will circle back.")
    gl.append(("a draft with no greeting is untouched", not ch))
    # "Hi" mid-sentence is not a greeting; the regex is anchored to the start.
    _, ch = split_reply_greeting("They said Hi Angel, which was odd.")
    gl.append(("'Hi' mid-sentence is not treated as a greeting", not ch))
    _src = __import__("inspect").getsource(main)
    _code = "\n".join(l for l in _src.splitlines() if not l.strip().startswith("#"))
    gl.append(("it runs AFTER the rewrites that can change the opening",
               _code.index("split_reply_greeting(draft)")
               > _code.index("name_the_calendar_owner(")
               and _code.index("split_reply_greeting(draft)")
               > _code.index("drop_booking_link(draft)")))
    g_wrong = 0
    print()
    for why, ok in gl:
        g_wrong += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} greeting      | {why}")
    print(f"\n{len(gl) - g_wrong}/{len(gl)} greeting cases correct")

    # --- Starter Kit ----------------------------------------------------------------
    kit_checks = []
    for intent, plat, want, why in (
            ("objection", "", True, "a bare objection gets it -- the case with no path"),
            ("objection", "DICE", False,
             "a NAMED competitor does not: it already has a cooldown and a task"),
            ("interested", "", False, "interested gets the booking link instead"),
            ("question", "", False, "question gets the booking link instead"),
            ("not_interested", "", False, "a decline gets nothing"),
            ("asked_to_stop", "", False, "never to someone who asked us to stop")):
        kit_checks.append((why, wants_starter_kit(intent, plat) == want))
    _d = "Gotcha, thanks for letting me know."
    _out, _added = add_starter_kit(_d)
    kit_checks.append(("the offer is appended", _added and _out != _d))
    kit_checks.append(("the original draft is preserved", _out.startswith(_d)))
    _again, _twice = add_starter_kit(_out)
    kit_checks.append(("idempotent -- never appended twice",
                       not _twice and _again == _out))
    kit_checks.append(("an empty draft is left alone", add_starter_kit("")[0] == ""))
    # The sentence is appended AFTER the banned-phrase check runs, so it never faces
    # the validator in production. This is the only thing standing between a careless
    # config edit and a banned phrase reaching a prospect.
    _lits, _res = banned_lists()
    _f = validate.check_banned("", add_starter_kit("x")[0], literals=_lits,
                               regexes=_res)
    kit_checks.append(("the CONFIGURED sentence carries no banned phrase", not _f))
    kit_wrong = 0
    print()
    for why, ok in kit_checks:
        kit_wrong += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} starterkit     | {why}")
    print(f"\n{len(kit_checks) - kit_wrong}/{len(kit_checks)} Starter Kit cases correct")
    return 1 if (fails or wrong or owner_wrong or task_wrong or kit_wrong or q_wrong or g_wrong) else 0


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
    comp_options = competitor_options(hs)
    store = rq.get_processed_id_store(svc, cfg["REPLY_REVIEW_SHEET_ID"],
                                     cfg["REPLY_REVIEW_TAB"])
    processed = queued = skipped = blocked = handed_off = 0

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
                blocked += 1
                continue
            messages, newest = read_thread(sl.thread(cid, lead_id))
            if not newest:
                print(f"  {email}: marked replied but no inbound message found; skipped")
                blocked += 1
                continue
            if newest["id"] and store.is_processed(newest["id"]):
                print(f"  {email}: already processed {newest['id']}; skipped")
                skipped += 1
                continue

            # (draft cleanup happens just below, after classify returns)
            # The contact is fetched BEFORE classifying, because the draft needs the
            # SENDER'S booking link and outbound_sender lives on the contact. It used to
            # be fetched after, when every meeting routed to one owner and the link was
            # a constant.
            cidhs, existing = hs.find_by_email(email) if email else (None, {})
            # HANDED OFF: a person owns this conversation now, so the engine must not
            # write to it. Checked BEFORE classifying -- there is no point spending a
            # model call, and more importantly no draft must reach the queue where a
            # reviewer might send it on top of whatever the rep has been saying.
            #
            # The reply is still marked processed, so it does not re-surface every
            # heartbeat forever. Losing sight of it is fine: the rep is reading their
            # own inbox, which is the whole point of handing it over.
            if (existing.get("outbound_status") or "").strip() == HANDED_OFF:
                store.mark_processed(newest["id"], email,
                                     f"handed off -- {email} is owned by a rep; "
                                     f"no draft queued")
                print(f"  {email}: HANDED OFF to a rep; not drafting")
                handed_off += 1
                continue
            res = classify(client, model, messages,
                           sender=existing.get("outbound_sender", ""),
                           contact_email=email)
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
            # **CRM ENRICHMENT FROM THE REPLY.** The point is a rep opening this contact
            # in six months and seeing what the prospect actually told us, rather than
            # having to find the thread. Both writes come from the prospect's own words,
            # never from an inference about them.
            #
            # Never from a machine reply: an auto-responder saying "your ticket has been
            # logged" is not a prospect telling us their platform.
            if intent not in ("out_of_office", "automated_reply"):
                said = (res.get("named_platform") or "").strip()
                if said:
                    matched = match_platform(said, comp_options)
                    was = (existing.get("current_competitor") or "").strip()
                    if matched and matched != was:
                        props["current_competitor"] = matched
                        print(f"      enrich: current_competitor "
                              f"{was or '(empty)'} -> {matched}  (they said {said!r})")
                    elif not matched:
                        # Reported, not written. An unrecognised platform is the common
                        # case -- "our own system", a regional tool -- and approximating
                        # it would put a wrong platform into the copy the NEXT campaign
                        # writes, which is worse than knowing nothing.
                        print(f"      enrich: they named {said!r}, which is not a known "
                              f"platform; left unset for a human")
                nf = (res.get("not_a_fit_reason") or "").strip()
                # THREE conditions, and the third is the one that matters. The model
                # supplies the reason, the classifier supplies the intent, and requiring
                # them to agree means one being wrong is not enough to retire a contact.
                #
                # **The third: naming a platform disqualifies the DISQUALIFICATION.**
                # instructions/reply-handling.md is explicit that a named incumbent --
                # "we already use X" -- is an OBJECTION, a concern a reply could address,
                # not a structural non-fit. Tested on a real reply: "we built our own
                # ticketing platform, but thank you" came back not_qualified with the
                # reason "Built and operate their own ticketing platform", which would
                # have retired a perfectly viable prospect for using a competitor. A
                # company that runs ticketed events on their own tool is exactly who
                # this engine exists to talk to.
                if nf and intent == "not_qualified" and not said:
                    # Guarded, not written blind. This wrote straight into `props`
                    # until 2026-09-25, and for a DORMANT contact (displayOrder 6,
                    # above Disqualified's 3) HubSpot accepted the PATCH and ignored
                    # the value -- every such disqualification since this was built
                    # has been a silent no-op that reported success. 481 of the 1,314
                    # contacts in the September round are Dormant.
                    cur_stage = (existing.get("lifecyclestage") or "").strip()
                    can, why_not = lifecycle.may_promote(
                        cur_stage, lifecycle.DISQUALIFIED)
                    if can:
                        props["lifecyclestage"] = lifecycle.DISQUALIFIED
                        print(f"      enrich: lifecyclestage -> Disqualified  ({nf})")
                    else:
                        print(f"      enrich: NOT marking Disqualified -- {why_not}. "
                              f"outbound_status still records the outcome; the stage "
                              f"needs a HubSpot settings change, not a retry")
                elif nf and intent == "not_qualified" and said:
                    print(f"      enrich: NOT disqualifying -- they named {said!r}, so "
                          f"this is an incumbent objection rather than a structural "
                          f"non-fit, whatever the reason says")
            # QUALIFIED on genuine interest (added 2026-09-25, Aliza's call). Only 27
            # contacts portal-wide hold this stage, so it carries real signal; the
            # same guard applies, and a Dormant contact cannot reach it either.
            if intent == "interested":
                cur_stage = (existing.get("lifecyclestage") or "").strip()
                can, why_not = lifecycle.may_promote(cur_stage, lifecycle.QUALIFIED)
                if can:
                    props["lifecyclestage"] = lifecycle.QUALIFIED
                    print(f"      enrich: lifecyclestage "
                          f"{lifecycle.label(cur_stage)} -> Qualified")
                elif "already" not in why_not:
                    print(f"      enrich: not marking Qualified -- {why_not}")
            # `platform` is what lets an objection earn a cooldown; without it a
            # contact who says "we have a contract with RA" is held only by the
            # 30-day replied window and is re-mailable a month later.
            recycle = recycle_date(intent, newest["at"], res.get("named_return_date"),
                                   existing.get("outbound_recycle_after"),
                                   platform=(res.get("named_platform") or ""))
            if recycle:
                props["outbound_recycle_after"] = recycle
                held = existing.get("outbound_recycle_after")
                if held and str(held)[:10] == recycle:
                    print("      recycle: keeping the later date already on the contact")
                # A TASK, not just a date (added 2026-09-25). The property is a GUARD --
                # eligibility refuses to mail them before it -- but nothing ever fired
                # on it, so a prospect who said "come back in June" was only re-approached
                # if somebody happened to pull a list containing them. Silence looked
                # identical to a correct skip. not_now only: a flat decline at +180d is a
                # much colder signal and would swamp the queue.
                # Objections with a named incumbent get a task too (2026-09-28).
                # Its date is OUR estimate, which the wording says out loud.
                if intent in ("not_now", "objection") and cidhs:
                    existing_task = hs.open_recycle_task(cidhs)
                    if existing_task == "unknown":
                        print("      task: could not check for an existing one; "
                              "NOT creating (a duplicate is worse than a late one)")
                    elif existing_task:
                        print(f"      task: {existing_task} already open, left alone")
                    else:
                        oid, why = recycle_task_owner(existing, email)
                        # Due AHEAD of a named contract end, on it otherwise.
                        # NOT the local `cfg` -- that is rq.load_surface_config()
                        # (sheet ids), and passing it here raised KeyError on the
                        # first real not_now. task_due_date reads defaults() itself.
                        _named = bool((res.get("named_return_date") or "").strip())
                        due, due_why = task_due_date(
                            recycle, res.get("named_return_date"))
                        if intent == "objection" and not _named:
                            # No lead time: the date is already a guess, and pulling a
                            # guess 90 days forward does not make it more accurate.
                            basis, due = "objection", recycle
                            due_why = (f"no renewal date given; {recycle} is our "
                                       f"180-day estimate, not their date")
                        else:
                            basis = "named" if _named else "default"
                        subj, body_txt = recycle_task_text(
                            existing, res, recycle, newest.get("body", ""),
                            due_note=due_why, basis=basis)
                        note = hs.create_task(cidhs, subj, body_txt,
                                              f"{due}T13:00:00Z", oid)
                        print(f"      task: {note} -> {why or 'UNASSIGNED'}")
                        print(f"            {due_why}")
            # An out-of-office pauses the sequence rather than ending the relationship,
            # so it gets a date to come back on instead of a recycle window. Written
            # here, acted on by scripts/resume_sequences.py once the date arrives.
            # **Clean the draft in CODE, not by asking.** The classifier prompt has said
            # "no dashes" all along and still produced "Great to hear you're using
            # Posh-we appreciate your business" -- an unspaced em dash -- on a real reply
            # to a real prospect. Same finding as the greeting blank line: an instruction
            # is not a guarantee, so the guarantee belongs here.
            #
            # A wider gap than the dash, and the reason this import exists at all: this
            # module imported NEITHER validate NOR repair, so every reply draft bypassed
            # dash normalisation and the banned-phrase list that all cold copy is held
            # to. A reply can invent a capability just as easily as an opener can.
            #
            # Only normalize_dashes is applied, never the full repair() driver:
            # strip_signoff removes a sign-off it believes the model wrote, and a reply
            # draft legitimately has none yet, while trim_middle_paragraph counts
            # paragraphs in copy that is one or two sentences long.
            draft = res.get("draft_response", "")
            if draft:
                # The calendar may not be the sender's -- meetings round-robin across the
                # team. Say whose it is rather than "with me".
                # A `question` never carries a booking link (2026-10-02). Enforced
                # here because the prompt saying so has never been enough. Done BEFORE
                # name_the_calendar_owner, which exists to label a link that is
                # staying -- running it first would rename a link about to be deleted.
                if intent == "question":
                    stripped, removed = drop_booking_link(draft)
                    if removed:
                        draft = stripped
                        res["draft_response"] = draft
                        print("      draft: booking link removed -- a question gets an "
                              "answer, not a calendar")
                    elif BOOKING_HOST in draft:
                        # Refused because removal would have gutted the draft. Say so
                        # on the row: a reviewer deleting a line is fine, a reviewer
                        # not knowing it is there is not.
                        res["_banned"] = ((res.get("_banned") or "") +
                                          "; booking link in a QUESTION reply -- "
                                          "remove it before sending").lstrip("; ")
                        print("      draft: ** booking link in a question reply and "
                              "too little would survive removing it; flagged **")
                _owner, _link = booking_link_for(existing.get("outbound_sender", ""),
                                                 contact_email=email)
                draft, renamed = name_the_calendar_owner(
                    draft, _owner, existing.get("outbound_sender", ""))
                if renamed:
                    print(f"      draft: calendar belongs to {_owner}, not the sender; "
                          f'"with me" corrected')
                res["draft_response"] = draft
                # Greeting onto its own line. Last of the rewrites on purpose: every
                # step above can change the opening (name_the_calendar_owner rewrites
                # "with me", drop_booking_link can delete the first sentence), so
                # splitting earlier would format a draft that then changed underneath.
                draft, split = split_reply_greeting(draft)
                if split:
                    print("      draft: greeting put on its own line")
                res["draft_response"] = draft
                fixed, dash_records = repair.normalize_dashes(draft)
                if dash_records:
                    print(f"      draft: normalised {len(dash_records)} dash(es)")
                res["draft_response"] = fixed
                _lits, _res = banned_lists()
                findings = validate.check_banned(
                    "", fixed, literals=_lits, regexes=_res)
                # `severity`, not `level`. Written as getattr(f, "level", "") first,
                # which silently returned "" for every finding and made this whole check
                # a no-op -- the failure mode a defaulted getattr always risks: it turns
                # a wrong field name into a clean pass instead of an error.
                hard = [f for f in findings if f.severity == validate.FAIL]
                if hard:
                    # Reported on the row, never silently stripped: a banned phrase in a
                    # draft is a signal about the draft, and a reviewer has to see it.
                    res["_banned"] = "; ".join(
                        getattr(f, "detail", "")[:80] for f in hard)
                    print(f"      draft: BANNED PHRASE -- {res['_banned']}")
                # Checked against the FINAL draft, after every rewrite above, because
                # the question is what the prospect will actually receive.
                # The Starter Kit, for an objection naming no known competitor --
                # the one case that otherwise gets a draft and no path at all.
                # Appended in code; see config/meeting-routing.md.
                if wants_starter_kit(intent, res.get("named_platform") or ""):
                    kitted, added = add_starter_kit(res["draft_response"])
                    if added:
                        res["draft_response"] = kitted
                        print("      draft: Starter Kit offer appended (objection with "
                              "no named competitor)")
                note = assign_meeting_owner(props, existing, _owner, _link,
                                            res.get("draft_response", ""))
                if note:
                    print(f"      {note}")
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
                # Say so when the booking link is NOT the sender's own. The draft looks
                # identical either way, so without this a reviewer has no way to know
                # the prospect is being pointed at the fallback calendar.
                if res.get("_banned"):
                    payload["review_reason"] = (
                        f"{rq.review_reason_for(intent)} — DRAFT CONTAINS A BANNED "
                        f"PHRASE: {res['_banned']}. Rewrite before approving.")
                if res.get("_link_fallback"):
                    payload["review_reason"] = (
                        f"{rq.review_reason_for(intent)} — booking link is "
                        f"{res['_link_fallback']}'s (FALLBACK: this lead has no HubSpot "
                        f"contact, so the real sender is unknown). Substitute the "
                        f"sender's own link if you know it.")
                if a.apply:
                    r = rq.append_reply(payload, service=svc, cfg=cfg, store=store)
                    print(f"      queue: {'row ' + str(r['row']) if r['appended'] else r['skipped']}")
                else:
                    print("      queue: would append a row for human review")
                queued += 1
            else:
                # **A reply handled with no human step still has to be RECORDED.**
                # Otherwise nothing dedupes it: the queue sheet is the processed-id
                # store, and a reply that is never queued never lands there, so it is
                # re-read, re-classified and re-acted on every single run. Observed on
                # 2026-09-17 -- one automated_reply reported "1 reply(s) processed" on
                # three consecutive runs, each one paying for a fresh Bedrock call to
                # re-decide a settled question.
                #
                # It matters most for out_of_office: that writes outbound_resume_after,
                # resume_sequences clears it and restarts the lead, and reprocessing then
                # re-writes a date already in the past -- restarting the same prospect
                # again on the next run, and the next.
                if a.apply:
                    store.mark_processed(newest["id"], email=email, intent=intent,
                                         note=res.get("reason", "")[:120])
                    print("      recorded: handled, no human step needed")
                else:
                    print("      recorded: would mark handled (no human step needed)")

    # "queued" vs "WOULD be queued" matters: the heartbeat prints this line into Slack
    # every weekday, and the routines run WITHOUT --apply until they are graduated. A dry
    # run reporting "1 queued for review" while the sheet stays empty is exactly how
    # someone concludes the queue is broken.
    verb = "queued for review" if a.apply else "WOULD be queued (dry run, sheet unchanged)"
    # `skipped` and `blocked` are reported separately because they mean opposite
    # things. A lead stays marked "replied" in Smartlead for good, so every run re-reads
    # every reply it has ever handled and skips it: that count only ever grows and is the
    # healthy steady state. `blocked` is a reply the engine could NOT read -- no Smartlead
    # lead id, or no inbound message on the thread -- which is a real prospect whose reply
    # nobody has seen. Summed into one number, the second is invisible behind the first,
    # and gets more invisible every week as the dedup count climbs.
    print(f"\n{processed} reply(s) processed, {queued} {verb}, "
          f"{skipped} already handled"
          # Reported separately, never folded into "already handled". These are live
          # conversations the engine chose to stay out of, and that is a different
          # fact from a duplicate it had already seen.
          + (f", {handed_off} handed off to a rep" if handed_off else "")
          + (f", ** {blocked} COULD NOT BE READ **" if blocked else ""))
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
