#!/usr/bin/env python3
"""Campaign intake from Slack: a rep posts a HubSpot list, the engine takes it from there.

Implements the request channel decided in `CLAUDE.md`: "A stakeholder posts the campaign
audience (a lead source reference) + a short brief as a Slack message. That message *is*
the campaign brief."

    Slack message with a HubSpot list  ->  eligibility -> generation -> review link

**It stops before sending, deliberately, and cannot be made not to.** Golden rule 1
requires recorded human approval, and two per-campaign settings (HubSpot activity logging,
Optimize Email Delivery) have no API at all. So the automated part ends with a review link
in the thread; a human approves, and `create_campaign.py` produces a DRAFTED campaign that
a human then launches.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required to post anything or run the pipeline.
  2. STATE LIVES IN THE SLACK THREAD, not in a database. A request with a bot reply has
     been handled, and the reply carries a machine-readable tag. This follows the same
     rule as the rest of the engine: everything it needs to remember lives somewhere a
     human can open and read. No local store to lose, and the audit trail is the
     conversation itself.
  3. ONE REPLY PER REQUEST PER STATE. A request cannot be processed twice, because the
     acknowledgement it would post is the same thing that marks it done.
  4. CAPACITY IS CHECKED BEFORE WORK, NOT AFTER. Over the ceiling, the request is queued
     with its position and picked up on a later run. Note what the ceiling is FOR:
     Smartlead already paces sends at 15/mailbox/day, so this is not flood protection --
     it decides whether to START a campaign, which matters while domains are young.
  5. A LIST THAT YIELDS NO ELIGIBLE LEADS IS REPORTED, NOT SILENTLY DROPPED. The rep gets
     told why, per exclusion reason, because "nothing happened" is the worst possible
     answer to a request.
  6. IT NEVER CREATES A HUBSPOT CONTACT. A list member with no usable record is reported.
     Contact creation is off by standing decision.

**Prerequisites, both outside this script:**
  - Slack scopes `channels:history` (read the channel) and `channels:read`. The bot holds
    only `chat:write` today, which is why this fails loudly rather than mysteriously.
  - `SLACK_REQUEST_CHANNEL` in `.env`, and the bot invited to that channel.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from create_campaign import load_defaults  # noqa: E402
from eligibility import env_value  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
SL_BASE = "https://server.smartlead.ai/api/v1"

# Machine-readable status tags. Visible in the thread on purpose: a human reading the
# channel should see the same state the engine sees.
TAG_ACCEPTED = "[engine:accepted]"
TAG_QUEUED = "[engine:queued]"
TAG_REJECTED = "[engine:rejected]"
# Posted the moment a request is picked up, BEFORE generation runs. Added 2026-09-17
# because a rep submitting a list heard nothing at all until the whole pipeline finished
# -- eligibility, callbacks, generation and export -- which is minutes of work reached
# only at the next heartbeat slot. From their side that is indistinguishable from the
# form being broken, and the honest fix is to say "seen" before saying "done".
#
# **Deliberately NON-TERMINAL.** engine_status returns the latest tag and only ACCEPTED
# and REJECTED stop a request being reconsidered, so a run that dies mid-generation
# leaves `working` behind and the next slot picks the request up again. Making it
# terminal would have been the dangerous choice: a crash would silently strand the
# request forever, marked as though it were in hand.
TAG_WORKING = "[engine:working]"
ALL_TAGS = (TAG_ACCEPTED, TAG_QUEUED, TAG_REJECTED, TAG_WORKING)

# A HubSpot list, however a rep pastes it: a full URL, "list 1764", or a bare id.
LIST_PATTERNS = (
    re.compile(r"objectLists/(\d+)"),
    re.compile(r"/lists/(\d+)"),
    re.compile(r"\blist[ :#]+(\d+)\b", re.I),
    re.compile(r"^\s*(\d{3,})\s*$", re.M),
)


# Canonical form labels, produced by a Slack Workflow Builder form. Parsed strictly so
# a rep's submission maps to the prompt the same way every time -- free text is accepted
# as a fallback, but the form is what keeps it uniform.
FORM_LABELS = {
    "list": ("hubspot list", "list", "hubspot list url", "audience"),
    "angle": ("angle", "campaign angle", "theme", "messaging angle", "copy direction"),
    "notes": ("notes", "context", "anything else"),
    # Who asked. Names the review tab so a rep can find their own request among many.
    # **The Workflow Builder form does not send this yet** -- its submission is a
    # bot_message with `user: None` and a body carrying only List, Angle and Notes, so
    # the submitter is genuinely not recoverable from Slack. Add a "Your name" field to
    # the form and this starts working; until then the tab falls back to the list id.
    "requester": ("requested by", "your name", "name", "rep", "requester", "submitted by"),
    # Which identity signs the copy. Aliases included so rewording the Workflow Builder
    # form does not silently drop the field and fall back to the default.
    "sender": ("sender", "who should this come from", "from", "sending as",
               "who sends this", "sender split"),
}

def known_senders() -> tuple[tuple[str, ...], dict[str, str]]:
    """(sender names, sender -> one mailbox) from config/senders.md. Cached per process.

    **Derived, never hardcoded.** This was a literal tuple until 2026-09-17, when the
    owner said the rest of the sales team's mailboxes would be added as outbound grows.
    A literal fails silently for exactly that: the new name goes in the Slack dropdown,
    `parse_sender` does not recognise it, and the rep's explicit "all from me" request
    falls back to a three-way split with a reply that reads like a success. Adding the
    mailbox to Smartlead and to config/senders.md is now the whole engine-side change.

    Only these identities can send: a rep who is a HubSpot owner but has no warmed
    mailbox -- Caroline, Gabriela, Rob today -- has no way to be the From address, which
    is why the form lists senders explicitly rather than offering "send it all from me".
    """
    global _SENDER_CACHE
    if _SENDER_CACHE is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import assemble
        # Departed senders keep their mailbox rows -- existing threads still sign with
        # their name -- but must never be assigned somebody new.
        # Departed OR still warming: both mean 'no new contacts', and calling the
        # combined helper is what stops one being honoured and the other forgotten.
        gone = assemble.unassignable_senders()
        by_sender: dict[str, str] = {}
        for box, who in sorted(assemble.load_sender_map().items()):
            n = who.strip().lower()
            if n in gone:
                continue
            by_sender.setdefault(n, box)
        _SENDER_CACHE = (tuple(sorted(by_sender)), by_sender)
    return _SENDER_CACHE


_SENDER_CACHE = None
# Below this many ELIGIBLE contacts, a defaulted split collapses to one campaign.
#
# 60 because that is roughly what ONE sender carries comfortably: 4 mailboxes at the
# per-mailbox daily cap, so a list this size never strains a single identity and
# spreading it buys no reputation protection at all. What it does buy is extra work --
# every campaign needs its own unsubscribe toggles and its own launch in the Smartlead UI,
# both of which have no API.
#
# Applied ONLY when the sender field was blank. A rep who explicitly chose "split across
# all three" gets exactly that, however small the list: overriding a stated choice is a
# different thing from picking a sensible default, and only the second is ours to make.
SPLIT_FLOOR = 60

SPLIT_WORDS = ("split", "all", "all three", "round robin", "round-robin", "rotate",
               "spread", "everyone")


# Mon-Fri, 09:00-17:59 local. An hour past the 17:00 send window so a list submitted at
# the end of the day still gets drafted the same day.
BUSINESS_DAYS, BUSINESS_HOURS = range(0, 5), range(9, 18)


def in_business_hours(now: dt.datetime | None = None) -> bool:
    n = now or dt.datetime.now()
    return n.weekday() in BUSINESS_DAYS and n.hour in BUSINESS_HOURS


# Eligibility reason -> a sentence a rep can act on.
#
# **The raw reasons are written for whoever is debugging a run, not for Slack.** "1
# skipped, lifecycle customer" was posted to a rep who then had to ask what it meant --
# and he could not tell from it whether the contact was a paying customer, a data
# problem, or something he should go and fix. The strings stay as they are in the
# annotated CSV, where a debugger wants the property name; only the Slack boundary is
# translated.
#
# Keys are matched as a PREFIX, because several reasons carry a value: "owned by Rob
# Dong", "lifecycle customer", "recycling until 2026-11-04". Longest key wins, so a
# specific mapping beats a general one.
REASON_PLAIN = {
    # **"customer" is labelled "Outreached" in this portal, NOT "Customer".** Reported
    # to a rep as "already a Posh customer" on 2026-09-17, which was simply untrue: the
    # value means somebody has already reached out. 35,931 contacts sit at it, so
    # getting the sentence wrong misdescribes the largest exclusion the gate applies.
    # Labels come from the portal, not from HubSpot's defaults -- read them with
    # GET /crm/v3/properties/contacts/lifecyclestage before trusting a value's name.
    "lifecycle customer": "already marked Outreached in HubSpot",
    "lifecycle 1439306394": "marked Disqualified in HubSpot",
    "lifecycle": "not at a stage we cold-email (HubSpot lifecycle stage)",
    "in HubSpot sequence": "already in a HubSpot sequence",
    "in sequence": "already mid-sequence with the engine",
    "belongs to": "already assigned to another sender's outreach",
    "owned by": "owned by someone whose contacts we do not cold-email",
    "has CSM": "has a customer success manager, so they are a customer",
    "existing customer (has_group)": "already a Posh customer",
    "opted out (hs_email_optout)": "opted out of all email in HubSpot",
    "opted out (outbound_suppressed)": "opted out of our outreach",
    "opted out": "opted out of email",
    "bounced": "their address bounced previously",
    "replied recently": "replied to us recently, so a human has it",
    "replied (date unknown)": "has replied to us before",
    "replied": "has replied to us before",
    "recycling until": "declined recently; eligible again later",
    "lead status": "their HubSpot lead status is one we skip",
    "no email in input row": "no email address on the record",
}


def plain_reason(reason: str) -> str:
    """A rep-readable version of an eligibility reason, or the reason unchanged.

    Returning the original when nothing matches is deliberate: an unmapped reason should
    look odd in Slack rather than be swallowed or mislabelled, which is how a new
    exclusion gate would otherwise go unnoticed here.
    """
    # Both sides lowered. The keys are written as the reasons appear -- "in HubSpot
    # sequence", "has CSM" -- and comparing a lowered reason against a mixed-case key
    # silently matched nothing for exactly those two, which is the quiet half-failure a
    # prefix map invites.
    r = (reason or "").strip().lower()
    for key in sorted(REASON_PLAIN, key=len, reverse=True):
        if r.startswith(key.lower()):
            return REASON_PLAIN[key]
    return reason.strip()


def review_sheet_url() -> str:
    """A clickable link to the generation review Sheet.

    The accepted reply used to say "Review tab X in the generation review sheet" with NO
    URL, leaving a rep to go and find it. Built from the id in config/review-surfaces.md
    so there is one source of truth for which sheet that is.
    """
    import export_review as er
    sid = er.load_config()["GENERATION_REVIEW_SHEET_ID"]
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit"


def least_loaded_sender() -> tuple[str, str]:
    """(sender, note). The sender carrying the fewest contacts, from HubSpot.

    **This is how "round robin" is honoured while keeping ONE campaign per request.**
    Smartlead rotates leads across a campaign's mailboxes and has no per-lead mailbox
    field -- `email_account_id` on a lead row is rejected outright -- so a single campaign
    holding two senders' copy would send Brooke's email from Carl's mailbox. That is the
    failure create_campaign guarantee 5 exists to prevent, so mixing senders inside one
    campaign is not available at any price.

    Rotating at the REQUEST level gives the same outcome a rep actually wants: one
    campaign to launch, and the load spread across senders over successive requests
    rather than within one.

    Stateless on purpose. The counts come from `outbound_sender` in HubSpot, so the
    balance self-corrects without anything remembering whose turn it is -- and there is no
    local database to hold a turn counter in (CLAUDE.md, "Architecture & sources of
    truth"). Today that reads carl 155 / brooke 46 / zach 46, so the next request goes to
    brooke.
    """
    from eligibility import HubSpot, env_token
    hs = HubSpot(env_token())
    names, _ = known_senders()
    counts = {}
    for n in names:
        counts[n] = hs._call("POST", "/crm/v3/objects/contacts/search",
                             {"filterGroups": [{"filters": [
                                 {"propertyName": "outbound_sender",
                                  "operator": "EQ", "value": n}]}],
                              "properties": ["email"], "limit": 1}).get("total") or 0
    pick = min(names, key=lambda n: (counts[n], names.index(n)))
    spread = ", ".join(f"{n} {counts[n]}" for n in names)
    return pick, f"rotated to {pick} — current spread is {spread}"


def parse_sender(raw: str) -> tuple[str, str, bool]:
    """(sender, note, explicit). sender is one from known_senders(), or "" for a split.

    `explicit` is True only when the rep actually named a mode. It is what separates
    "they asked to split" from "nobody said, so we split", and those must not be treated
    alike -- see SPLIT_FLOOR.

    **Defaults to SPLIT when the field is absent or unreadable**, and says so in the
    note. The alternative default is a named sender, which would quietly load one
    identity with a whole round -- the failure the three-way split exists to avoid. A
    reply that states which mode ran lets a rep correct the next submission.
    """
    names, _ = known_senders()
    pretty = ", ".join(n.title() for n in names)
    v = (raw or "").strip().lower()
    if not v:
        return "", "no sender field given, so the round was split across every sender", False
    for name in names:
        if name in v:
            return name, "", True
    if any(w in v for w in SPLIT_WORDS):
        return "", "", True
    # Names the valid options from config rather than a frozen three, so the message
    # stays true as the team grows.
    return "", (f"sender {raw.strip()!r} is not one of {pretty}, so the round was "
                f"split across every sender"), False


# The angle reaches the generation prompt, so it is capped. A rep pasting three
# paragraphs would crowd out the rulebook, and a topic hint does not need paragraphs.
ANGLE_MAX = 400

# Message subtypes that are never a request. Deliberately an explicit list rather than
# "any subtype": a Slack Workflow Builder form posts with subtype `bot_message`, so
# skipping every subtype meant real form submissions were silently ignored and the form
# could never have worked. Caught by testing the actual path 2026-09-08.
SKIP_SUBTYPES = {
    "channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
    "channel_archive", "channel_unarchive", "bot_add", "bot_remove", "pinned_item",
    "message_changed", "message_deleted", "thread_broadcast", "reminder_add",
}


def is_skippable(m: dict, me: str, my_bot_id: str | None) -> bool:
    """True if this message is ours or channel noise, so not a request.

    Pulled out to be testable: a message posted by our own bot token cannot be used to
    verify this, because it is correctly skipped -- which is exactly how the original
    bug hid. A blanket bot filter dropped Workflow Builder submissions, and the only
    test message available came from our own bot, so the filter looked fine.
    """
    if my_bot_id and m.get("bot_id") == my_bot_id:
        return True
    if m.get("user") and m.get("user") == me:
        return True
    return m.get("subtype") in SKIP_SUBTYPES


def _norm_label(raw: str) -> str:
    """A form label reduced to a comparable key.

    Workflow Builder emits the label bolded, on its own line, and often with a
    parenthetical hint the author wrote for the rep -- "*HubSpot List (URL)*". The
    parenthetical is guidance for a human, not part of the field name, so it is dropped.
    """
    s = re.sub(r"[*_`]", "", raw or "").strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)        # trailing "(URL)", "(optional)"
    s = s.rstrip(":").strip()
    return re.sub(r"\s+", " ", s).lower()


def _clean_value(raw: str) -> str:
    """Strip Slack decoration from a submitted value.

    Slack wraps bare URLs as <https://...> and link-with-text as <url|text>, so a pasted
    HubSpot URL arrives bracketed. Left in place, the list-id patterns still match, but
    the value shown back to the rep would carry the brackets.
    """
    s = (raw or "").strip()
    s = re.sub(r"<([^|>]+)(?:\|[^>]*)?>", r"\1", s)   # <url> and <url|text>
    s = re.sub(r"^[\s*_`]+|[\s*_`]+$", "", s)
    return s


def parse_form(text: str) -> dict | None:
    """Parse a Workflow Builder submission into {list, angle, notes}, or None.

    Handles BOTH layouts, because the tool produces the first one and a hand-written
    message tends to use the second:

        *Label*            <- label alone on a line, value on the next line(s)
        value

        Label: value       <- label and value on one line

    Returns None when no recognised LIST field is present, so the caller can fall back to
    loose parsing. A submission with only an angle is not a request: guessing would queue
    a campaign against nothing.
    """
    known = {name: key for key, names in FORM_LABELS.items() for name in names}
    fields: dict[str, list[str]] = {}
    current: str | None = None

    for line in (text or "").splitlines():
        if not line.strip():
            continue
        # "Label: value" on one line.
        m = re.match(r"^\s*[*_`]{0,3}\s*([A-Za-z][A-Za-z ()/]{1,30}?)\s*[*_`]{0,3}\s*:\s*(.*)$",
                     line)
        if m and _norm_label(m.group(1)) in known:
            current = known[_norm_label(m.group(1))]
            val = _clean_value(m.group(2))
            fields.setdefault(current, [])
            if val:
                fields[current].append(val)
            continue
        # A bolded label alone on its own line; the value follows.
        bare = _norm_label(line)
        if bare in known and not re.search(r"[a-z0-9]\s*:\s*\S", line, re.I):
            current = known[bare]
            fields.setdefault(current, [])
            continue
        if current:
            fields[current].append(_clean_value(line))

    if "list" not in fields:
        return None
    list_id, _ = parse_request(" ".join(fields["list"]))
    if not list_id:
        return None
    angle = " ".join(fields.get("angle", [])).strip()
    if angle.lower() in ("none", "n/a", "-", ""):
        angle = ""
    return {"list_id": list_id, "angle": angle[:ANGLE_MAX],
            "notes": " ".join(fields.get("notes", [])).strip(),
            "requester": " ".join(fields.get("requester", [])).strip(),
            # Raw on purpose: parse_sender decides what it means and, when it cannot,
            # produces the note that tells the rep which mode actually ran.
            "sender_raw": " ".join(fields.get("sender", [])).strip(),
            "form": True}


def parse_request(text: str) -> tuple[str | None, str]:
    """(hubspot list id, brief) from a Slack message.

    The brief is whatever the rep wrote minus the list reference — it is passed through
    to the review tab so the person reviewing copy can see what was asked for.
    """
    text = text or ""
    list_id = None
    for pat in LIST_PATTERNS:
        m = pat.search(text)
        if m:
            list_id = m.group(1)
            break
    brief = text
    if list_id:
        brief = re.sub(r"<?https?://\S*objectLists/\d+\S*>?", "", brief)
        brief = re.sub(r"\blist[ :#]+\d+\b", "", brief, flags=re.I)
    brief = re.sub(r"\s+", " ", brief).strip()
    return list_id, brief


# The band from config/smartlead-defaults.md, "How big should a campaign be". Kept as
# numbers here and prose there; if they ever disagree that file wins.
SIZE_IDEAL = (100, 200)


def size_note(requested: int) -> str:
    """Advice for a rep whose request is unusually small or large, or "".

    **Advisory, never a gate.** A rep who genuinely has 30 leads should get their 30
    leads, and one with 400 should get them across two rounds rather than a refusal --
    so this returns text to say, and nothing that changes what runs. Size is not a
    deliverability risk (Smartlead paces per mailbox whatever the campaign size); it is a
    duration and review-effort question, which is the rep's to weigh.
    """
    lo, hi = SIZE_IDEAL
    if requested < 50:
        return (f"{requested} is on the small side. Approval and the manual Smartlead "
                f"step cost the same per campaign at any size, so {lo}-{hi} gets a lot "
                f"more signal for the same overhead. Worth batching with another ask.")
    if requested > 250:
        return (f"{requested} will run over two weeks and needs the in-flight ceiling "
                f"raised. Two rounds of ~{hi} land sooner and let the first round's "
                f"replies inform the second.")
    return ""


def decide_capacity(in_flight: int, requested: int, ceiling: int) -> tuple[bool, str]:
    """(accept now, reason). Guarantee 4.

    The ceiling counts leads IN FLIGHT, not sends per day. A lead occupies capacity for
    roughly the length of the sequence (about a week at [0, 3, 4] delays), so counting
    daily sends would let a week's worth of campaigns start on the same morning.
    """
    if in_flight + requested <= ceiling:
        return True, f"{in_flight} in flight + {requested} requested <= {ceiling} ceiling"
    return False, (f"{in_flight} in flight + {requested} requested exceeds the {ceiling} "
                   f"ceiling; queued until capacity frees up")


class Slack:
    def __init__(self, token: str, apply_changes: bool):
        self.token = token
        self.apply = apply_changes

    def call(self, method: str, params: dict | None = None, post: bool = False):
        if post:
            req = urllib.request.Request(
                f"https://slack.com/api/{method}", method="POST",
                data=json.dumps(params or {}).encode(),
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json; charset=utf-8"})
        else:
            q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
            req = urllib.request.Request(
                f"https://slack.com/api/{method}?{q}",
                headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read() or b"{}")
        if not d.get("ok"):
            err = d.get("error")
            if err == "missing_scope":
                raise RuntimeError(
                    f"Slack rejected {method}: missing_scope. Intake needs "
                    "`channels:history` and `channels:read` on the bot token; it holds "
                    "only `chat:write` today. Add them under OAuth & Permissions, "
                    "re-install the app, and re-run.")
            if err == "not_in_channel":
                raise RuntimeError(
                    f"Slack rejected {method}: not_in_channel. Invite the bot to the "
                    "request channel.")
            raise RuntimeError(f"Slack {method} failed: {err!r}")
        return d

    def history(self, channel: str, limit: int = 50) -> list[dict]:
        return self.call("conversations.history",
                         {"channel": channel, "limit": limit})["messages"]

    def replies(self, channel: str, ts: str) -> list[dict]:
        return self.call("conversations.replies",
                         {"channel": channel, "ts": ts})["messages"]

    def reply(self, channel: str, ts: str, text: str) -> str:
        if not self.apply:
            return f"would reply in-thread: {text.splitlines()[0][:90]}"
        self.call("chat.postMessage",
                  {"channel": channel, "thread_ts": ts, "text": text}, post=True)
        return "replied in-thread"


def engine_status(replies: list[dict], bot_user_id: str) -> str | None:
    """The most recent engine tag in a thread, or None if the engine has not replied.

    Guarantee 2: this IS the dedup store. A request the engine has accepted carries an
    accepted tag in its own thread, so it can never be processed twice even if the
    channel is re-read from the beginning.
    """
    found = None
    for m in replies:
        if m.get("user") != bot_user_id and m.get("bot_id") is None:
            continue
        for tag in ALL_TAGS:
            if tag in (m.get("text") or ""):
                found = tag
    return found


def in_flight_leads(key: str) -> int:
    """Leads currently inside ACTIVE or DRAFTED campaigns."""
    def g(path):
        # Retried: the capacity check walks every campaign, and on 2026-09-22 it died
        # with a 429 when four heartbeat slots fired at once after a day off.
        import time as _time
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    f"{SL_BASE}{path}{'&' if '?' in path else '?'}api_key={key}",
                    headers={"User-Agent": "outbound-engine/1.0"})
                with urllib.request.urlopen(req, timeout=45) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if not (e.code == 429 or 500 <= e.code < 600) or attempt == 4:
                    raise
                _time.sleep(2 ** attempt)
            except OSError:
                if attempt == 4:
                    raise
                _time.sleep(2 ** attempt)
    total = 0
    for c in g("/campaigns") or []:
        if (c.get("status") or "").upper() not in ("ACTIVE", "DRAFTED", "PAUSED"):
            continue
        d = g(f"/campaigns/{c['id']}/leads?offset=0&limit=1")
        total += int(d.get("total_leads") or 0)
    return total


def list_size(list_id: str) -> int:
    """How many contacts are in the HubSpot list, for the capacity check."""
    from eligibility import env_token
    req = urllib.request.Request(
        f"https://api.hubapi.com/crm/v3/lists/{list_id}",
        headers={"Authorization": f"Bearer {env_token()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    return int((d.get("list") or {}).get("size") or 0)


def run_split_pipeline(list_id: str, brief: str, apply_changes: bool,
                       angle: str = "", requester: str = "",
                       split_explicit: bool = True) -> dict:
    """One submission, one campaign PER SENDER, for the split mode.

    **Eligibility runs ONCE over the whole list, then the eligible set is split.** The
    other order -- split first, then filter each part -- balances the wrong quantity,
    because exclusions do not land evenly: on list 1902 a 94/55/55 split became 93/44/40
    once the gates ran. (It also turned out not to matter much there, Carl owning half
    the list, but the order is still the correct one.)

    Eligibility runs WITHOUT `--sender`, deliberately. Gate 10 soft-excludes contacts
    belonging to a different sender, which is exactly right for named-sender mode and
    exactly wrong here: in split mode a contact already assigned to Carl is not excluded,
    it is routed to Carl. `split_by_sender` rule 1 does that routing.

    **This duplicates rather than refactors `run_pipeline`.** The single-sender path is
    in production and proven -- it is what built the three campaigns on 2026-09-17 --
    and threading a mode through it would put that at risk to save some lines. The shared
    part is the list fetch, which is extracted.
    """
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    work = ROOT / "reviews"
    work.mkdir(exist_ok=True)
    leads = work / f"intake-{list_id}-{stamp}-leads.csv"
    annotated = work / f"intake-{list_id}-{stamp}-annotated.csv"
    elig = work / f"intake-{list_id}-{stamp}-eligible.csv"
    n_leads = fetch_list_leads(list_id, leads)

    who = re.sub(r"[^A-Za-z0-9]", "", (requester or "").split()[0]) if requester else ""
    base = f"{who.title()}-{dt.date.today().isoformat()}" if who else \
           f"List{list_id}-{dt.date.today().isoformat()}"

    out = {"mode": "split", "leads": n_leads, "steps": {}, "tabs": {},
           "eligible": None, "exclusions": {}, "per_sender": {}}
    if not apply_changes:
        out["steps"] = {"eligibility": "would run", "split": "would run",
                        "per-sender generation": "would run"}
        return out

    p = subprocess.run([PY, str(ROOT / "scripts/eligibility.py"), "--leads", str(leads),
                        "--out", str(annotated), "--eligible-out", str(elig)],
                       capture_output=True, text=True, timeout=1800, cwd=ROOT)
    out["steps"]["eligibility"] = "ok" if p.returncode == 0 else "FAILED"
    out["eligibility_output"] = ((p.stdout or "") + (p.stderr or ""))[-1500:]
    if p.returncode != 0:
        return out
    import csv as _csv
    rows = list(_csv.DictReader(annotated.open(encoding="utf-8-sig")))
    out["eligible"] = sum(1 for r in rows if (r.get("decision") or "").upper() == "ELIGIBLE")
    for r in rows:
        if (r.get("decision") or "").upper() != "ELIGIBLE":
            key = (r.get("reason") or "excluded").strip()
            out["exclusions"][key] = out["exclusions"].get(key, 0) + 1
    if not out["eligible"]:
        return out

    # The floor: a DEFAULTED split on a small list becomes one campaign. Rules 1 and 2
    # still route pre-assigned and sender-owned contacts, so continuity is untouched;
    # only the round-robin of the remainder collapses.
    rotate = split_explicit or out["eligible"] >= SPLIT_FLOOR
    if not rotate:
        out["collapsed"] = (f"{out['eligible']} eligible is under the {SPLIT_FLOOR} floor "
                            f"and no sender was named, so this is one campaign rather "
                            f"than one per sender")
        print(f"    {out['collapsed']}")
    p = subprocess.run([PY, str(ROOT / "scripts/split_by_sender.py"),
                        "--leads", str(elig), "--apply", "--out-dir", str(work)]
                       + ([] if rotate else ["--no-rotate"]),
                       capture_output=True, text=True, timeout=900, cwd=ROOT)
    out["steps"]["split"] = "ok" if p.returncode == 0 else "FAILED"
    out["split_output"] = ((p.stdout or "") + (p.stderr or ""))[-1500:]
    if p.returncode != 0:
        return out

    for sender in known_senders()[0]:
        part = work / f"split-{elig.stem}-{sender}.csv"
        if not part.exists():
            continue
        n_part = sum(1 for _ in part.open(encoding="utf-8-sig")) - 1
        if n_part <= 0:
            continue
        mailbox = known_senders()[1][sender]
        enriched = work / f"intake-{list_id}-{stamp}-{sender}-enriched.csv"
        cb = work / f"intake-{list_id}-{stamp}-{sender}-callbacks-review.csv"
        gen = work / f"intake-{list_id}-{stamp}-{sender}-generated.csv"
        tab = f"{base}-{sender.title()}"
        ok = True
        for name, cmd in (
            ("callbacks", [PY, str(ROOT / "scripts/enrich_callbacks.py"),
                           "--eligible", str(part), "--out", str(enriched),
                           "--review-out", str(cb)]),
            ("generation", [PY, str(ROOT / "scripts/run_generation.py"),
                            "--contacts", str(enriched), "--mailbox", mailbox,
                            "--out", str(gen), "--quiet"]
                           + (["--angle", angle] if angle else [])),
            ("export", [PY, str(ROOT / "scripts/export_review.py"), "--csv", str(gen),
                        "--mailbox", mailbox, "--tab", tab]),
        ):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=ROOT)
            out["steps"][f"{sender}:{name}"] = "ok" if r.returncode == 0 else "FAILED"
            out[f"{sender}:{name}_output"] = ((r.stdout or "") + (r.stderr or ""))[-1200:]
            if r.returncode != 0:
                ok = False
                break
        out["per_sender"][sender] = n_part
        if ok:
            out["tabs"][sender] = tab
    return out


def fetch_list_leads(list_id: str, path: pathlib.Path) -> int:
    """HubSpot list -> a two-column leads csv. Returns the member count.

    Shared by both pipelines. The membership endpoint returns record IDS ONLY and
    eligibility.py requires an `email` column -- without it every lead comes back
    "ERROR: no email" and the request fails silently at the first step.
    """
    from eligibility import env_token
    tok = env_token()
    ids, after = [], None
    while True:
        u = (f"https://api.hubapi.com/crm/v3/lists/{list_id}/memberships?limit=100"
             + (f"&after={after}" if after else ""))
        req = urllib.request.Request(u, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        ids += [m["recordId"] for m in d.get("results", [])]
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    pairs = []
    for i in range(0, len(ids), 100):
        body = {"inputs": [{"id": x} for x in ids[i:i + 100]],
                "properties": ["email"]}
        req = urllib.request.Request(
            "https://api.hubapi.com/crm/v3/objects/contacts/batch/read",
            method="POST", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read())
        for res in got.get("results", []):
            em = (res.get("properties") or {}).get("email") or ""
            if em.strip():
                pairs.append((res["id"], em.strip()))
    import csv as _csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(["hs_object_id", "email"])
        w.writerows(pairs)
    return len(ids)


def run_pipeline(list_id: str, brief: str, mailbox: str, apply_changes: bool,
                 angle: str = "", requester: str = "") -> dict:
    """eligibility -> generation -> export. Each step is the existing script, run as a
    subprocess so its own guarantees and refusals stay intact rather than being
    re-implemented here."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    work = ROOT / "reviews"
    work.mkdir(exist_ok=True)
    leads = work / f"intake-{list_id}-{stamp}-leads.csv"
    # TWO files, and mixing them up is the bug this comment exists to prevent.
    #   annotated -- EVERY lead with a `decision` column, for the review Sheet and for
    #                the exclusion breakdown reported back to the rep.
    #   eligible  -- ONLY the ELIGIBLE rows. This is what generation must receive.
    # Until 2026-09-10 the annotated file was passed to `run_generation --contacts`, so
    # copy would have been written for contacts the filter had just excluded -- people
    # mid-sequence, and hard exclusions such as opted-out -- and that copy flows to the
    # review Sheet where it can be approved into a live campaign. It went unnoticed
    # because the only list ever run through here had zero eligible leads, so the
    # zero-eligible guard stopped the run before generation was reached.
    annotated = work / f"intake-{list_id}-{stamp}-annotated.csv"
    elig = work / f"intake-{list_id}-{stamp}-eligible.csv"
    # eligible + prior-interaction callbacks. This, not `elig`, is what generation reads.
    enriched = work / f"intake-{list_id}-{stamp}-enriched.csv"
    cb_review = work / f"intake-{list_id}-{stamp}-callbacks-review.csv"
    gen = work / f"intake-{list_id}-{stamp}-generated.csv"
    # REVIEW TAB NAME: the requester's first name and the date, e.g. "Aliza-2026-09-11".
    # A rep looking for their own request should recognise the tab without decoding a
    # timestamp, which "Intake-1914-20260911-1359" required. The list id moves into the
    # CSV filenames under reviews/, which is where a debugger looks anyway.
    #
    # A same-day second request from the same person gets "-2", rather than overwriting:
    # export_review refuses a tab that already has rows unless --allow-append, so a
    # collision would otherwise fail the run at the last step.
    who = re.sub(r"[^A-Za-z0-9]", "", (requester or "").split()[0]) if requester else ""
    base = f"{who.title()}-{dt.date.today().isoformat()}" if who else \
           f"List{list_id}-{dt.date.today().isoformat()}"
    tab = base
    try:
        import review_queue as _rq
        _svc, _ = _rq.sheets_service()
        _cfg = __import__("export_review").load_config()
        _meta = _svc.spreadsheets().get(
            spreadsheetId=_cfg["GENERATION_REVIEW_SHEET_ID"]).execute(
            num_retries=_rq.SHEETS_RETRIES)
        _titles = {sh["properties"]["title"] for sh in _meta.get("sheets", [])}
        n = 2
        while tab in _titles:
            tab, n = f"{base}-{n}", n + 1
    except Exception as e:
        # Never fail the run over a tab name. A collision surfaces at export instead,
        # which refuses a tab that already has rows -- loud, and after the copy is safe
        # on disk in reviews/.
        print(f"    note: could not check existing tab names ({type(e).__name__}); "
              f"using {tab!r}")

    from eligibility import env_token
    tok = env_token()
    ids, after = [], None
    while True:
        u = (f"https://api.hubapi.com/crm/v3/lists/{list_id}/memberships?limit=100"
             + (f"&after={after}" if after else ""))
        req = urllib.request.Request(u, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        ids += [m["recordId"] for m in d.get("results", [])]
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break

    # The membership endpoint returns record IDS ONLY, and eligibility.py requires an
    # `email` column -- without it every lead comes back "ERROR: no email" and the whole
    # request fails silently at the first step. Fetch the addresses here, batched.
    pairs = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        body = {"inputs": [{"id": x} for x in chunk], "properties": ["email"]}
        req = urllib.request.Request(
            "https://api.hubapi.com/crm/v3/objects/contacts/batch/read",
            method="POST", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            got = json.loads(r.read())
        for res in got.get("results", []):
            email = (res.get("properties") or {}).get("email") or ""
            if email.strip():
                pairs.append((res["id"], email.strip()))
    import csv as _csv
    with leads.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(["hs_object_id", "email"])
        w.writerows(pairs)
    if len(pairs) < len(ids):
        print(f"    note: {len(ids) - len(pairs)} of {len(ids)} list member(s) have no "
              f"email address and cannot be processed")

    steps = [
        ("eligibility", [PY, str(ROOT / "scripts/eligibility.py"), "--leads", str(leads),
                         "--out", str(annotated), "--eligible-out", str(elig),
                         "--sender", mailbox.split(".")[0]]),
        # Prior-interaction callbacks. CLAUDE.md core workflow step 3 calls this
        # "optional" and the automated path simply left it out, so every intake request
        # would have produced cold opens even for contacts we have a real prior
        # conversation with. On a rep's list that is the difference between "Hey Cam,
        # I'm Carl..." and "Hey Cam, I'm Carl. Good to reconnect." -- verified live on
        # five contacts with Gong-logged replies, all of which came back tier `soft`.
        #
        # It is the strongest defence the engine has against sounding machine-written,
        # and it costs one read-only pass. Nothing about it is optional on a list a
        # human will read.
        ("callbacks", [PY, str(ROOT / "scripts/enrich_callbacks.py"), "--eligible",
                       str(elig), "--out", str(enriched),
                       "--review-out", str(cb_review)]),
        ("generation", [PY, str(ROOT / "scripts/run_generation.py"), "--contacts",
                        str(enriched), "--mailbox", mailbox, "--out", str(gen),
                        "--quiet"]
                       + (["--angle", angle] if angle else [])),
        ("export", [PY, str(ROOT / "scripts/export_review.py"), "--csv", str(gen),
                    "--mailbox", mailbox, "--tab", tab]),
    ]
    out = {"tab": tab, "leads": len(ids), "steps": {}, "eligible": None,
           "exclusions": {}}
    if not apply_changes:
        out["steps"] = {n: "would run" for n, _ in steps}
        return out
    for name, cmd in steps:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=ROOT)
        out["steps"][name] = "ok" if p.returncode == 0 else "FAILED"
        out[f"{name}_output"] = ((p.stdout or "") + (p.stderr or ""))[-1500:]
        if p.returncode != 0:
            break
        if name == "eligibility":
            # Guarantee 5. Without this, a list where nobody is eligible falls through to
            # generation, which fails on an empty file, and the rep is told "failed at
            # generation" -- which is both wrong and useless. Observed on a real
            # resubmission of a list already in flight: 35 members, 0 eligible.
            import csv as _csv
            # Counts come from the ANNOTATED file, which is the only one carrying the
            # excluded rows and their reasons. Generation reads `elig`, written directly
            # by --eligible-out.
            #
            # This used to write both to one path and then overwrite it in place with
            # the eligible rows. That was correct about what reached generation, but it
            # destroyed the annotated list in the process -- and core workflow step 2 in
            # CLAUDE.md wants exactly that list preserved, every EXCLUDED contact and its
            # reason, so targeting decisions stay visible. Two paths, no overwrite.
            rows = list(_csv.DictReader(annotated.open(encoding="utf-8")))
            keep = [r for r in rows if (r.get("decision") or "") == "ELIGIBLE"]
            out["eligible"] = len(keep)
            out["annotated_csv"] = str(annotated)
            counts: dict[str, int] = {}
            for r in rows:
                if (r.get("decision") or "") != "ELIGIBLE":
                    reason = r.get("reason") or "(no reason)"
                    counts[reason] = counts.get(reason, 0) + 1
            out["exclusions"] = counts
            if not keep:
                # Every downstream step, or the report claims a step is still pending
                # when it will never run. `callbacks` was added to this list at the same
                # time it was added to `steps`; the two must stay in sync.
                for later in ("callbacks", "generation", "export"):
                    out["steps"][later] = "skipped"
                return out
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read campaign requests from Slack. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="post replies and run the pipeline. Without this, nothing "
                         "is posted and nothing is generated.")
    ap.add_argument("--mailbox", default="carl.newmark@vibeposhvip.com",
                    help="sending mailbox for generated copy; one sender per campaign")
    ap.add_argument("--split-by-sender", action="store_true",
                    help="one campaign PER SENDER instead of one per request. For a "
                         "deliberate multi-sender round run by hand; the scheduled "
                         "intake never uses it, because a rep's single request should "
                         "not become three campaigns to launch.")
    ap.add_argument("--business-hours-only", action="store_true",
                    help="exit immediately outside Mon-Fri 09:00-18:00 local. For a "
                         "every-5-minutes launchd schedule, so the policy lives in code "
                         "where it can be tested rather than in a cron expression.")
    ap.add_argument("--limit", type=int, default=20, help="messages to scan")
    ap.add_argument("--self-test", action="store_true",
                    help="prove parsing and the capacity rule with no API calls")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    # Checked BEFORE any credential or API call, so an off-hours run costs nothing and
    # cannot fail on a missing token. Reps do not submit lists at 3am, and a request that
    # arrives overnight is picked up at 09:00 -- or sooner by the morning heartbeat,
    # which runs intake regardless of this flag.
    if a.business_hours_only and not in_business_hours():
        print(f"outside business hours ({dt.datetime.now():%a %H:%M}); nothing to do.")
        return 0

    token = env_value("SLACK_BOT_TOKEN")
    channel = env_value("SLACK_REQUEST_CHANNEL")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not set")
    if not channel:
        raise RuntimeError(
            "SLACK_REQUEST_CHANNEL not set in .env. Create the request channel, invite "
            "the bot, and put its channel id (starts with C) there. Deliberately not "
            "defaulted to the review channel: campaign requests and approval traffic "
            "should not share a channel.")

    cfg = load_defaults()
    ceiling = int(cfg.get("max_leads_in_flight", 60))
    sl = Slack(token, a.apply)
    who = sl.call("auth.test")
    me, my_bot_id = who["user_id"], who.get("bot_id")
    print("APPLY: will post replies and run the pipeline" if a.apply
          else "DRY RUN: nothing posted, nothing generated.")

    key = env_value("SMARTLEAD_API_KEY")
    flight = in_flight_leads(key) if key else 0
    print(f"capacity: {flight} lead(s) in flight, ceiling {ceiling}\n")

    msgs = sl.history(channel, a.limit)
    handled = queued = rejected = 0
    for m in reversed(msgs):                      # oldest first, so queue order is fair
        # Skip OUR OWN messages, not every app's. Workflow Builder is an app, so a
        # blanket bot filter would drop exactly the submissions this exists to read.
        if is_skippable(m, me, my_bot_id):
            continue
        ts, text = m["ts"], m.get("text") or ""
        status = engine_status(sl.replies(channel, ts), me)
        if status == TAG_ACCEPTED or status == TAG_REJECTED:
            continue                              # guarantee 3

        form = parse_form(text)
        if form:
            list_id, brief, angle = form["list_id"], form["notes"], form["angle"]
            requester = form.get("requester", "")
            sender, sender_note, split_explicit = parse_sender(
                form.get("sender_raw", ""))
        else:
            list_id, brief = parse_request(text)
            requester = ""   # loose free-text path has no form field
            angle = ""
            # Free text carries no Sender field, so it splits. Same default as a form
            # submission that omits it, and for the same reason.
            sender, sender_note, split_explicit = "", (
                "free-text request, so the round was split across every sender"), False
        who = m.get("user", "?")
        if not list_id:
            print(f"  {ts} <@{who}>: no HubSpot list found; rejecting")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} I could not find a HubSpot list in that message.\n"
                  f"Use the campaign request form, or post at minimum "
                  f"`HubSpot list: <url>`. I will pick it up on the next run."))
            rejected += 1
            continue

        try:
            size = list_size(list_id)
        except Exception as e:
            print(f"  {ts} list {list_id}: cannot read it ({e}); rejecting")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} I could not read HubSpot list {list_id}. Check the id "
                  f"and that it is not a private list."))
            rejected += 1
            continue

        ok, why = decide_capacity(flight, size, ceiling)
        note = size_note(size)
        print(f"  {ts} list {list_id} ({size} contacts) "
              f"{'form' if form else 'free text'} angle={angle[:60]!r}")
        print(f"    capacity: {why}")
        if not ok:
            queued += 1
            if status != TAG_QUEUED:              # do not repeat the same message daily
                print("    " + sl.reply(channel, ts,
                      f"{TAG_QUEUED} Received: HubSpot list {list_id}, {size} contacts.\n"
                      f"Holding it — {why}. I will start it automatically once there is "
                      f"room and reply here with the review link."))
            else:
                print("    still queued; not repeating the reply")
            continue

        if note:
            # Said once, at submission, when it can still change what the rep does.
            # Advisory only: an unusual size is never a reason to refuse a request.
            print(f"    size note: {note}")
        # The receipt, before the work. Not repeated if a previous run already said it,
        # for the same reason the queued message is not repeated daily.
        if status != TAG_WORKING:
            print("    " + sl.reply(channel, ts,
                  f"{TAG_WORKING} Got it — HubSpot list {list_id}, {size} contacts"
                  + (f", angle: _{angle}_" if angle else "")
                  + ".\nChecking eligibility and drafting copy now. I will reply here "
                  + "with the review link"
                  + (" (one per sender)" if not sender else "")
                  + " when it is ready."
                  + (f"\n\n_Note on size:_ {note}" if note else "")
                  + (f"\n_Note on sender:_ {sender_note}" if sender_note else "")))
        else:
            print("    already acknowledged on an earlier run; not repeating")
        # NAMED SENDER -> the existing single-sender path, unchanged. It runs eligibility
        # WITH --sender, so gate 10 soft-excludes contacts already assigned to one of the
        # other two. That is what keeps a rep's "all from Brooke" request to ONE campaign
        # while never switching a persona on a prospect mid-relationship: a contact Carl
        # has already mailed is reported as "belongs to carl" rather than quietly moved.
        #
        # SPLIT -> the multi-sender path, one campaign per sender.
        _names, _boxes = known_senders()
        if not sender:
            # **ONE CAMPAIGN PER REQUEST, decided 2026-09-17.** Previously a split
            # produced one campaign PER SENDER, which meant a rep's single request became
            # three campaigns, each needing its own unsubscribe toggles and its own launch
            # in the Smartlead UI. The owner asked for one campaign per request instead.
            #
            # Mixing senders inside one campaign is not an option -- see
            # least_loaded_sender -- so the rotation moves up a level: this request goes
            # entirely to the sender carrying the fewest contacts, and the next one goes
            # to whoever is lowest then.
            #
            # This routes through the SINGLE-SENDER path, which runs eligibility WITH
            # --sender, so gate 10 reports a contact already assigned to someone else as
            # "belongs to carl" rather than moving them. Continuity is preserved by
            # exclusion instead of by splitting the campaign.
            sender, rotate_note = least_loaded_sender()
            sender_note = (sender_note + "; " + rotate_note) if sender_note else rotate_note
            print(f"    sender: {rotate_note} -> one campaign")
        else:
            print(f"    sender: {sender} (named) -> one campaign")
        if a.split_by_sender:
            # Opt-in only, for a deliberate multi-sender round run by hand -- the way the
            # 186-contact round on 2026-09-16 was done. NEVER reached from a Slack
            # request, because a rep's one request should produce one campaign.
            print(f"    --split-by-sender: one campaign per sender across "
                  f"{', '.join(_names)}")
            res = run_split_pipeline(list_id, brief, a.apply, angle=angle,
                                     requester=requester, split_explicit=True)
        else:
            res = run_pipeline(list_id, brief, _boxes[sender], a.apply,
                               angle=angle, requester=requester)
        if res.get("eligible") == 0:
            # Guarantee 5: say WHY, per reason. "Nothing happened" is the worst possible
            # answer to a request, and the reasons are usually actionable -- already in a
            # sequence, already a customer, opted out.
            lines = "\n".join(f"• {n} — {plain_reason(r)}" for r, n in
                               sorted(res["exclusions"].items(), key=lambda x: -x[1]))
            print(f"    0 of {res['leads']} eligible; reporting the reasons")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} HubSpot list {list_id}: none of the "
                  f"{res['leads']} contacts are eligible right now, so nothing was "
                  f"drafted.\n{lines}\n"
                  f"Most of these are reversible — a contact already in a sequence "
                  f"becomes available when it finishes."))
            rejected += 1
            continue
        failed = [k for k, v in res["steps"].items() if v == "FAILED"]
        if failed:
            print(f"    pipeline FAILED at {failed[0]}")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} List {list_id} failed at the {failed[0]} step. "
                  f"Nothing was sent. I have the output; a human needs to look."))
            rejected += 1
            continue
        flight += size                            # so a second request this run sees it
        handled += 1
        tabs_desc = res.get("tab") or ", ".join((res.get("tabs") or {}).values()) or "(none)"
        # One line of eligibility, not a breakdown. The rep needs to know how many made
        # it and roughly why the rest did not; the full per-reason list is already in the
        # annotated CSV and on the zero-eligible path, where it actually changes what
        # they do. Everything the old message carried -- where review happens, that the
        # campaign is built from approved rows, that nothing sends until a human launches
        # -- is true, unchanging, and was being repeated to the same people on every
        # request. That is what made it noise.
        _e, _l = res.get("eligible"), res.get("leads") or 0
        if _e is None:
            elig_line = f"{_l} contact(s)"
        elif _e == _l:
            elig_line = f"all {_l} contact(s) eligible"
        else:
            top = sorted((res.get("exclusions") or {}).items(), key=lambda x: -x[1])
            why = f" — {plain_reason(top[0][0])}" if top else ""
            elig_line = (f"{_e} of {_l} eligible ({_l - _e} skipped{why})")
        print(f"    pipeline: {res['steps']}, review tab(s) {tabs_desc}")
        # The approval sentence here was stale and actively misleading: it read "Reply
        # here with approval and I will build the campaign", which was true when
        # approval lived in a Slack thread. Approval is now the `Approved` column in the
        # review tab, read by scripts/build_approved.py in the morning heartbeat, and
        # per golden rule 1 it is the OUTBOUND OWNER who approves rather than the
        # requesting rep. A rep who replied "approved" in this thread would have been
        # doing nothing at all, and waiting on a campaign that never got built.
        print("    " + sl.reply(channel, ts,
              f"{TAG_ACCEPTED} *{elig_line}* — drafts ready.\n"
              f"{review_sheet_url()}\n"
              f"Tab: *{tabs_desc}*\n"
              f"Review the copy there and mark the rows you approve."))

    print(f"\n{handled} accepted, {queued} queued, {rejected} rejected")
    if not a.apply:
        print("DRY RUN: nothing posted, nothing generated.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # Parsing, in the shapes a rep will actually paste.
    check("full HubSpot URL",
          parse_request("please run https://app.hubspot.com/contacts/50950747/objectLists/1764/filters "
                        "for NYC venues")[0], "1764")
    check("brief survives the URL being stripped",
          parse_request("https://app.hubspot.com/contacts/1/objectLists/1764/filters "
                        "NYC venues on Eventbrite")[1], "NYC venues on Eventbrite")
    check("'list 1764' form", parse_request("run list 1764 please")[0], "1764")
    check("'list: 1764' form", parse_request("list: 1764")[0], "1764")
    check("bare id on its own line", parse_request("1764")[0], "1764")
    check("no list at all", parse_request("can we email some venues?")[0], None)
    # A number inside a sentence must NOT be read as a list id: a rep saying "we did
    # this in 2026" would otherwise queue a campaign against list 2026. The bare-id
    # pattern requires the number alone on a line, which is what makes that safe.
    check("a year in prose is not a list id", parse_request("we did this in 2026")[0], None)
    check("a count in prose is not a list id",
          parse_request("about 250 venues in Austin please")[0], None)
    check("a real list wins over a number in the prose",
          parse_request("last year we did 2026 contacts, now run list 1764")[0], "1764")

    # Capacity. Guarantee 4.
    check("under the ceiling accepts", decide_capacity(25, 30, 60)[0], True)
    check("exactly at the ceiling accepts", decide_capacity(30, 30, 60)[0], True)
    check("over the ceiling queues", decide_capacity(50, 30, 60)[0], False)
    check("an empty account accepts", decide_capacity(0, 60, 60)[0], True)
    check("a single oversized list queues", decide_capacity(0, 500, 60)[0], False)

    # The message filter. This is where the original bug lived: a blanket bot filter
    # dropped Workflow Builder submissions, and it could not be caught with a test
    # message from our own bot because that one is skipped correctly.
    ME, MYBOT = "U_ENGINE", "B_ENGINE"
    wf = {"bot_id": "B_WORKFLOW", "subtype": "bot_message",
          "text": "HubSpot list: 1764"}
    check("a Workflow Builder submission is NOT skipped",
          is_skippable(wf, ME, MYBOT), False)
    check("our own bot reply IS skipped",
          is_skippable({"bot_id": MYBOT, "text": "[engine:accepted]"}, ME, MYBOT), True)
    check("our own user message IS skipped",
          is_skippable({"user": ME, "text": "hi"}, ME, MYBOT), True)
    check("a human message is NOT skipped",
          is_skippable({"user": "U_REP", "text": "HubSpot list: 1764"}, ME, MYBOT), False)
    check("a join notice IS skipped",
          is_skippable({"subtype": "channel_join", "text": "joined"}, ME, MYBOT), True)
    check("an edited message IS skipped",
          is_skippable({"subtype": "message_changed"}, ME, MYBOT), True)
    check("a third-party app with no subtype is NOT skipped",
          is_skippable({"bot_id": "B_OTHER", "text": "HubSpot list: 1764"}, ME, MYBOT),
          False)

    # Guarantee 3 / 2: the thread reply is the store.
    bot = "U123"
    check("no engine reply means unhandled", engine_status([], bot), None)
    check("an accepted tag is found",
          engine_status([{"user": bot, "text": f"{TAG_ACCEPTED} done"}], bot),
          TAG_ACCEPTED)
    check("a human reply is not an engine tag",
          engine_status([{"user": "UHUMAN", "text": f"{TAG_ACCEPTED} nice"}], bot), None)
    check("the LATEST tag wins, so queued->accepted is respected",
          engine_status([{"user": bot, "text": f"{TAG_QUEUED} holding"},
                         {"user": bot, "text": f"{TAG_ACCEPTED} drafted"}], bot),
          TAG_ACCEPTED)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    # A configuration problem should read as one sentence, not a traceback: this runs
    # unattended, and the first thing anyone hits is the missing Slack scope.
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(2) from None
