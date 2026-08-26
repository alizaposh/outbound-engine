#!/usr/bin/env python3
"""Prior-interaction callbacks: read a contact's HubSpot timeline, decide whether a
GENUINE two-way interaction happened, and emit a callback the generator can open
email 1 with.

Feeds §9 "Prior-interaction callbacks" in instructions/message-generation.md, which
already holds the writing rules. This script only does retrieval and classification.

Pipeline seam (deliberate, see CLAUDE.md):
    eligibility.py -> eligible.csv -> THIS -> eligible-enriched.csv -> run_generation.py
run_generation.py stays HubSpot-free; the callback rides the CSV. No local store: the
callback is recomputed each run, so it cannot go stale.

Four guarantees:

  1. READ-ONLY. Nothing here writes to HubSpot. Same guarantee as eligibility.py, and
     the client is imported from it so auth, retry, and pacing are not reimplemented.
  2. A PRIOR SEND IS NOT A PRIOR CONVERSATION. An outbound email with no reply is NOT
     an interaction. hs_email_direction == INCOMING_EMAIL is the crux: that is a reply
     from the contact. Many of these leads are old records with ignored outreach, and
     "good to reconnect" on a one-way send reads false.
  3. A VOICEMAIL IS NOT A CHAT. Only a CONNECTED call counts. No-answer, busy,
     voicemail, and wrong-number are not interactions.
  4. UNCERTAIN MEANS NONE. Any doubt returns tier "none" and the generator writes a
     cold open. A missing callback costs nothing; a fabricated one costs the lead.

Property names and enum values below were confirmed against HubSpot's current API
docs (2026-08-25), not assumed.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import ELIGIBLE_COLUMNS, HubSpot, env_token  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RATE_PAUSE = 0.12

# ---- HubSpot engagement contract (confirmed against docs 2026-08-25) -----------

# Association reads. The v3 path is what the working eligibility client already speaks;
# v4 moved to /crm/objects/2026-03/... and is not needed for a simple per-contact read.
ENGAGEMENT_TYPES = ("meetings", "calls", "emails", "notes")

PROPS = {
    "meetings": ["hs_timestamp", "hs_meeting_title", "hs_meeting_body",
                 "hs_meeting_outcome", "hs_meeting_start_time"],
    "calls":    ["hs_timestamp", "hs_call_title", "hs_call_body",
                 "hs_call_status", "hs_call_disposition", "hs_call_direction"],
    "emails":   ["hs_timestamp", "hs_email_subject", "hs_email_text",
                 "hs_email_direction", "hs_email_status"],
    "notes":    ["hs_timestamp", "hs_note_body"],
}

# hs_email_direction: EMAIL (we sent it), INCOMING_EMAIL (the contact replied),
# FORWARDED_EMAIL. Only INCOMING_EMAIL is two-way.
EMAIL_INBOUND = "INCOMING_EMAIL"

# hs_call_disposition is a GUID, not a label. Only "Connected" is a conversation.
# Everything else here is explicitly NOT one, and is listed so the intent is legible.
CALL_DISPOSITION = {
    "f240bbac-87c9-4f6e-bf70-924b57d47db7": ("connected", True),
    "b2cf5968-551e-4856-9783-52b3da59a7d0": ("left voicemail", False),
    "a4c4c377-d246-4b32-a13b-75a56a4cd0ff": ("left live message", False),
    "73a0d17f-1163-4015-bdd5-ec830791da20": ("no answer", False),
    "9d9162e7-6cf3-4944-bf63-4dff82258764": ("busy", False),
    "17b47fee-58de-441e-a44c-c6300d46f273": ("wrong number", False),
}
# hs_call_status. COMPLETED alone does not mean anyone spoke: a voicemail is a
# completed call. Disposition decides; status only rules out calls that never happened.
CALL_STATUS_DEAD = {"CANCELED", "FAILED", "NO_ANSWER", "BUSY", "QUEUED", "RINGING",
                    "CONNECTING", "CALLING_CRM_USER", "IN_PROGRESS"}

# hs_meeting_outcome real values, read off the portal's own property definition:
# SCHEDULED, COMPLETED, RESCHEDULED, NO_SHOW, CANCELED. HubSpot's docs say lowercase
# with a space ("no show"); the API returns UPPERCASE_UNDERSCORE. Compared normalized,
# because matching the documented spelling would have let NO_SHOW through as a genuine
# interaction, which is precisely the false "good to reconnect" this exists to prevent.
MEETING_OUTCOME_DEAD = {"NO_SHOW", "CANCELED", "CANCELLED", "RESCHEDULED"}

# In this portal SCHEDULED is the default and nobody updates it (77 of the 100 most
# recent meetings; COMPLETED appears zero times). So "outcome == COMPLETED" cannot be
# the test for whether a meeting happened. The timestamp is: a meeting dated in the
# future has definitionally not happened yet, whatever its outcome says.
FUTURE_GRACE = dt.timedelta(hours=12)   # a meeting today is not yet a memory

OUT_COLUMNS = ELIGIBLE_COLUMNS + ["callback_tier", "callback_detail",
                                  "callback_source_id", "callback_last_date"]
REVIEW_COLUMNS = ["email", "hs_object_id", "callback_tier", "callback_detail",
                  "callback_source_id", "callback_last_date", "interaction_kind",
                  "evidence", "skipped_reason"]

MODEL_ENV = "BULK_LLM_MODEL"
# Gong call transcripts land in notes and run 20k+ chars, opening with small talk
# ("Rep: beep... had to do the groceries"). A 4000-char cap cut the substance off
# entirely, so the model saw only chit-chat and returned nothing.
MAX_DETAIL_CHARS = 16000


# ---- fetching -----------------------------------------------------------------

class Timeline(HubSpot):
    """Read-only engagement reads layered on eligibility.py's client."""

    def associated_ids(self, contact_id: str, obj: str, limit: int = 50) -> list[str]:
        d = self._call("GET", f"/crm/v3/objects/contacts/{contact_id}"
                              f"/associations/{obj}?limit={limit}")
        return [r["toObjectId"] if "toObjectId" in r else r["id"]
                for r in d.get("results", [])]

    def read_objects(self, obj: str, ids: list[str]) -> list[dict]:
        """Batch-read properties. Batches of 100, HubSpot's cap."""
        out = []
        props = PROPS[obj]
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            d = self._call("POST", f"/crm/v3/objects/{obj}/batch/read",
                           {"properties": props,
                            "inputs": [{"id": str(x)} for x in chunk]})
            for r in d.get("results", []):
                p = dict(r.get("properties") or {})
                p["_id"], p["_type"] = r["id"], obj
                out.append(p)
            time.sleep(RATE_PAUSE)
        return out

    def timeline(self, contact_id: str) -> dict[str, list[dict]]:
        got = {}
        for obj in ENGAGEMENT_TYPES:
            try:
                ids = self.associated_ids(contact_id, obj)
                got[obj] = self.read_objects(obj, ids) if ids else []
            except RuntimeError as e:
                # A missing scope must not look like "no history": that would turn
                # every contact cold and silently disable the whole feature.
                raise RuntimeError(
                    f"cannot read {obj} for contact {contact_id}: {e}\n"
                    f"This usually means a missing scope. Engagement reads need "
                    f"crm.objects.contacts.read plus sales-email-read for emails.") from None
        return got


# ---- classification -----------------------------------------------------------

def _ts(v) -> dt.datetime | None:
    if not v:
        return None
    s = str(v)
    try:
        if s.isdigit():
            return dt.datetime.fromtimestamp(int(s) / 1000, dt.timezone.utc)
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (ValueError, OSError):
        return None


def _norm_outcome(v) -> str:
    return (v or "").strip().upper().replace(" ", "_")


def is_two_way(eng: dict, now: dt.datetime | None = None) -> tuple[bool, str]:
    """Did a real two-way interaction happen? Returns (yes, human-readable reason)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    t = eng["_type"]
    when = _ts(eng.get("hs_timestamp"))
    # Nothing in the future is a memory. Applies to every type: a booked-but-unheld
    # meeting is the common case, and it must never produce "good to reconnect".
    if when and when > now - FUTURE_GRACE:
        return False, f"{t[:-1]} is not in the past ({when.date()})"
    if t == "meetings":
        outcome = _norm_outcome(eng.get("hs_meeting_outcome"))
        if outcome in MEETING_OUTCOME_DEAD:
            return False, f"meeting {outcome}"
        return True, f"meeting ({outcome or 'no outcome set'})"
    if t == "calls":
        disp = (eng.get("hs_call_disposition") or "").strip().lower()
        status = (eng.get("hs_call_status") or "").strip().upper()
        label, connected = CALL_DISPOSITION.get(disp, ("unknown disposition", False))
        if connected:
            return True, "connected call"
        if disp:
            return False, f"call: {label}"
        # No disposition logged. COMPLETED is not evidence anyone spoke, so this is
        # exactly the "when in doubt" case.
        return False, f"call with no disposition (status {status or 'unset'})"
    if t == "emails":
        direction = (eng.get("hs_email_direction") or "").strip().upper()
        if direction == EMAIL_INBOUND:
            return True, "inbound email (contact replied)"
        return False, f"outbound email ({direction or 'no direction'}), not a conversation"
    return False, "note only"      # a note is context, never itself an interaction


# Meeting bodies in this portal are the booking tool's own description, not rep notes:
# "Quick 15-min demo to get you set up as a Posh Organizer. Looking forward!" plus a
# join link and form answers. Left unfiltered, that yields a "specific" callback built
# from our own calendar copy, and "get you set up as a Posh Organizer" would imply the
# prospect is already a customer. These lines are stripped before anything is extracted.
BOILERPLATE = re.compile(
    r"(join link[^\n]*|https?://\S+|meet\.google\.com\S*|zoom\.us/\S+|"
    r"looking forward!?|quick \d+.?min demo[^.]*\.|"
    r"to get you set up as a posh organizer)", re.I)
HTML_TAG = re.compile(r"<[^>]+>")

# Trust order for a detail source. Rep-written and prospect-written text first; the
# calendar description last, because it is the one nobody typed for this conversation.
SOURCE_TRUST = {"notes": 0, "calls": 1, "emails": 2, "meetings": 3}


def clean_body(raw: str) -> str:
    """Strip HTML, links, and calendar boilerplate. What remains is what a human
    actually wrote about this contact, which is the only thing safe to paraphrase."""
    txt = HTML_TAG.sub(" ", raw or "")
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&")
    txt = BOILERPLATE.sub(" ", txt)
    return re.sub(r"\s+", " ", txt).strip()


MAX_SOURCES_TRIED = 4       # cap the cheap-LLM calls per contact


def detail_sources(engagements: list[dict], notes: list[dict]) -> list[tuple[dict, str]]:
    """Candidate detail sources, best first.

    Returns a LIST, not one pick: ranking by trust alone meant a single unhelpful
    top-ranked source (a transcript full of small talk) blocked richer text further
    down, and the contact silently fell back to soft. The caller tries these in order
    until one yields a usable detail.
    """
    def text_of(e) -> str:
        for k in ("hs_note_body", "hs_call_body", "hs_email_text", "hs_meeting_body"):
            v = (e.get(k) or "").strip()
            if v:
                return clean_body(v)
        return ""

    candidates = [(e, text_of(e)) for e in engagements] + [(n, text_of(n)) for n in notes]
    with_text = [(e, txt[:MAX_DETAIL_CHARS]) for e, txt in candidates if len(txt) >= 25]
    with_text.sort(key=lambda pair: (
        SOURCE_TRUST.get(pair[0].get("_type", ""), 9),
        -(_ts(pair[0].get("hs_timestamp")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)).timestamp()))
    return with_text[:MAX_SOURCES_TRIED]


# Screens the model's output. Added after a live dry-run returned 12/12 "specific",
# almost all of it scheduling chatter ("confirmed call for tomorrow at 10:00 am EST")
# or facts about OUR team ("Abby left Posh, Will Heyman is now the contact"). Both are
# specific and faithful, and both are unusable: the first is stale the day after it was
# logged, the second would leak our staffing to a prospect. Specific is not the same as
# reusable, and the prompt alone did not hold that line.
# Matched CONTEXTUALLY, not on bare keywords. A first pass rejected on the word
# "confirmed" alone and threw away a genuinely good detail ("13 confirmed 2025 events").
# What makes a detail unusable is a time/day reference or a scheduling ACTION, not a
# word that also has an ordinary adjectival use.
DETAIL_REJECT = re.compile(
    r"("
    # a specific day or clock time: stale the moment the log is a week old
    r"\b(tomorrow|today|yesterday|next week|this week)\b|"
    # Day names only after a scheduling preposition: bare day names appear in brand
    # names, and "Sunday cleaning YouTube series" is a real prospect detail, not a date.
    r"\b(on|for|this|next|last|by)\s+(monday|tuesday|wednesday|thursday|friday|"
    # ...and not a recurring cadence: "on Sunday nights" and "on Sundays" describe how
    # they run events, which is exactly the kind of fact worth referencing.
    r"saturday|sunday)\b(?!s)(?!\s+(nights?|mornings?|afternoons?|evenings?))|"
    r"\b\d{1,2}\s*(:\d{2})?\s*(a\.?m\.?|p\.?m\.?)\b|"
    r"\b(est|edt|pst|pdt|cst|cdt|utc|gmt)\b|"
    # a scheduling action, i.e. logistics rather than a fact about their business
    r"\b(confirmed|scheduled|rescheduled|reschedul\w+|booked|accepted|agreed)\s+"
    r"(a\s+|the\s+|to\s+|for\s+|meeting|call|demo|time|chat)|"
    r"\b(call|meeting|demo)\s+(for|at|on)\s|"
    r"\b(looping in|added to the call|invited to the call|calendar invite)\b|"
    # facts about US, never to be echoed to a prospect
    r"\bleft posh\b|\bpoint of contact\b|\bhanded? off\b|"
    r"\bperformance review\b|\bpartnership document\b"
    r")", re.I)

EXTRACT_PROMPT = """You are extracting a REUSABLE FACT ABOUT THE PROSPECT'S BUSINESS from
a CRM record, so a salesperson can reference it months later in an email opener.

Return ONLY a JSON object:
{"detail": "<short faithful paraphrase, or empty string>"}

ACCEPT only facts about the prospect and their events that stay true over time:
  - what platform they use and how they feel about it
  - their event volume, cadence, venues, verticals, audience
  - a constraint or priority they described (exclusivity, payouts, growth)

REJECT (return an empty string) anything that is:
  - SCHEDULING or LOGISTICS. "confirmed for tomorrow at 10am", "rescheduled", "looping
    in a colleague", "call booked". This is stale the day after it is logged and reads
    unhinged in an email months later.
  - ABOUT OUR OWN TEAM OR PROCESS. Who owns the account, who left, internal reviews,
    partnership docs, handoffs. Never echo our staffing back to a prospect.
  - VAGUE ADMIN. "logged a call", "sent info", "follow up next week".
  - A CALENDAR DESCRIPTION we wrote ourselves, e.g. a demo invite blurb.

Other rules:
1. FAITHFUL ONLY. Paraphrase what is written. Never add, infer, upgrade, or embellish.
   "Left a voicemail" must never become "we chatted".
2. One clause, under 20 words. No greeting, no pitch, no CTA.
3. Do not name a competitor or a figure unless the record names it.
4. When the record holds nothing that fits ACCEPT, return an empty string. That is the
   expected outcome for most records and costs nothing.

Record type: {kind}
Record text:
---
{text}
---"""


def extract_detail(client, model: str, kind: str, text: str) -> str:
    """One cheap-LLM call. Any failure returns empty, which downgrades to soft."""
    try:
        resp = client.messages.create(
            model=model, max_tokens=200,
            messages=[{"role": "user",
                       "content": EXTRACT_PROMPT.replace("{kind}", kind).replace("{text}", text)}])
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        detail = (json.loads(raw.strip()).get("detail") or "").strip()
        if not (0 < len(detail) <= 200):
            return ""
        # Belt and braces over the prompt: a scheduling or internal-team detail is
        # specific but not reusable, so it must not become a callback.
        if DETAIL_REJECT.search(detail):
            return ""
        return detail
    except Exception:
        return ""


def classify(timeline: dict[str, list[dict]], client=None, model: str = "",
             now: dt.datetime | None = None) -> dict:
    """-> {tier, detail, source_id, last_date, interaction_kind, evidence, skipped_reason}"""
    blank = {"callback_tier": "none", "callback_detail": "", "callback_source_id": "",
             "callback_last_date": "", "interaction_kind": "", "evidence": "",
             "skipped_reason": ""}

    engagements = [e for t in ("meetings", "calls", "emails") for e in timeline.get(t, [])]
    notes = timeline.get("notes", [])
    if not engagements and not notes:
        return {**blank, "skipped_reason": "no engagements on the timeline"}

    now = now or dt.datetime.now(dt.timezone.utc)
    two_way, rejected = [], []
    for e in engagements:
        ok, why = is_two_way(e, now)
        (two_way if ok else rejected).append((e, why))

    if not two_way:
        reasons = "; ".join(sorted({why for _, why in rejected})) or "no qualifying engagement"
        return {**blank, "skipped_reason": f"nothing two-way: {reasons}"}

    two_way.sort(key=lambda pair: _ts(pair[0].get("hs_timestamp")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                 reverse=True)
    newest, kind = two_way[0]
    last = _ts(newest.get("hs_timestamp"))
    base = {**blank,
            "callback_last_date": last.date().isoformat() if last else "",
            "interaction_kind": kind,
            "evidence": f"{len(two_way)} two-way engagement(s); newest {kind}"}

    sources = detail_sources([e for e, _ in two_way], notes)
    if not sources:
        return {**base, "callback_tier": "soft",
                "callback_source_id": str(newest.get("_id", "")),
                "skipped_reason": "real interaction, no reusable detail logged"}

    if client is None:
        return {**base, "callback_tier": "soft",
                "callback_source_id": str(sources[0][0].get("_id", "")),
                "skipped_reason": "detail present but no LLM client (soft only)"}

    # Try sources best-first; the first usable detail wins. Most records yield nothing,
    # which is the expected outcome and costs only a soft callback.
    for src, text in sources:
        detail = extract_detail(client, model, src.get("_type", "record"), text)
        if detail:
            return {**base, "callback_tier": "specific", "callback_detail": detail,
                    "callback_source_id": str(src.get("_id", ""))}
    return {**base, "callback_tier": "soft",
            "callback_source_id": str(sources[0][0].get("_id", "")),
            "skipped_reason": f"no reusable detail in {len(sources)} candidate source(s)"}


# ---- run ----------------------------------------------------------------------

def bedrock_client():
    """Same pattern as run_generation.py. Returns (client, model) or (None, '')."""
    region, model = os.environ.get("AWS_REGION"), os.environ.get(MODEL_ENV)
    if not region or not model:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("AWS_REGION=") and not region:
                region = line.split("=", 1)[1].strip()
            if line.startswith(f"{MODEL_ENV}=") and not model:
                model = line.split("=", 1)[1].strip()
        if region:
            os.environ.setdefault("AWS_REGION", region)
    if not region or not model:
        return None, ""
    import anthropic
    return anthropic.AnthropicBedrock(aws_region=region), model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch and classify prior-interaction callbacks. Read-only.")
    ap.add_argument("--eligible", required=True, type=pathlib.Path,
                    help="eligible.csv from scripts/eligibility.py")
    ap.add_argument("--out", type=pathlib.Path, help="eligible-enriched.csv")
    ap.add_argument("--review-out", type=pathlib.Path, help="annotated review CSV")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify and write ONLY the review CSV; nothing feeds generation")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-llm", action="store_true",
                    help="skip detail extraction; every real interaction becomes soft")
    a = ap.parse_args(argv)

    rows = list(csv.DictReader(a.eligible.open(encoding="utf-8")))
    if a.limit:
        rows = rows[:a.limit]
    if not rows:
        print("no rows in input", file=sys.stderr)
        return 1

    hs = Timeline(env_token())
    client, model = (None, "") if a.no_llm else bedrock_client()
    if client is None and not a.no_llm:
        print("NOTE: no Bedrock client (AWS_REGION / BULK_LLM_MODEL unset). "
              "Running soft-only: real interactions classify as 'soft', never 'specific'.")

    stamp = dt.datetime.now(dt.timezone.utc).date().isoformat()
    out_rows, review_rows, counts = [], [], {}
    for i, row in enumerate(rows, 1):
        cid = (row.get("hs_object_id") or "").strip()
        if not cid:
            res = {"callback_tier": "none", "callback_detail": "", "callback_source_id": "",
                   "callback_last_date": "", "interaction_kind": "", "evidence": "",
                   "skipped_reason": "no hs_object_id (not in HubSpot, nothing to read)"}
        else:
            res = classify(hs.timeline(cid), client, model)
        counts[res["callback_tier"]] = counts.get(res["callback_tier"], 0) + 1
        out_rows.append({**{k: row.get(k, "") for k in ELIGIBLE_COLUMNS},
                         **{k: res[k] for k in ("callback_tier", "callback_detail",
                                                "callback_source_id", "callback_last_date")}})
        review_rows.append({"email": row.get("email", ""), "hs_object_id": cid,
                            **{k: res.get(k, "") for k in REVIEW_COLUMNS[2:]}})
        print(f"  [{i}/{len(rows)}] {row.get('email','')[:38]:38} "
              f"{res['callback_tier']:8} {res.get('interaction_kind') or res.get('skipped_reason','')[:50]}")

    review = a.review_out or ROOT / "reviews" / f"callbacks-{stamp}.csv"
    review.parent.mkdir(parents=True, exist_ok=True)
    with review.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(review_rows)
    print(f"\nreview CSV (eyeball every 'specific' against its source): {review}")
    print("tiers: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    if a.dry_run:
        print("\nDRY RUN: no enriched CSV written, nothing reaches generation.")
        return 0

    out = a.out or ROOT / "reviews" / f"eligible-enriched-{stamp}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nenriched CSV -> {out}")
    print(f"next: scripts/run_generation.py --contacts {out} --mailbox <mailbox>")
    return 0




# ---- self-test ----------------------------------------------------------------
# Every case below is a REAL detail the model produced during the 2026-08-26 live
# dry-run. 10 of 12 were unusable, which is why the code screen exists at all.
#   ./.venv/bin/python scripts/enrich_callbacks.py --self-test

DETAIL_SCREEN_CASES = [
    # (detail, expect_rejected, why)
    ("DJ Mike's content focuses on nostalgic nineties R&B and hip-hop, targeting "
     "mid-to-late twenties audience; started Sunday cleaning YouTube series three years "
     "ago that grew to 1M+ views.", False,
     "real prospect fact; 'Sunday cleaning' is a brand name, not a date"),
    ("Fun & Flirty has 13 confirmed 2025 events; some venues require exclusive ticketing "
     "platforms, but they plan 12 additional shows with full control over Posh ticketing.",
     False, "real prospect fact; 'confirmed' here is an adjective, not a scheduling act"),
    ("Abby left Posh and Will Heyman is now the primary point of contact; a call was "
     "scheduled for 1:30 p.m. the next day.", True, "our staffing, never echo to a prospect"),
    ("Meeting confirmed for tomorrow 10:00 am EST; Cyrus requested Pouya be invited to "
     "the call.", True, "scheduling logistics, stale immediately"),
    ("Cyrus confirmed tomorrow 10:00 am works for the call; also looping in Pouya.", True,
     "scheduling logistics"),
    ("Agreed to call tomorrow at 10:00 am EST", True, "scheduling logistics"),
    ("Confirmed meeting for tomorrow at 10:00 am EST after rescheduling from original "
     "time.", True, "scheduling logistics"),
    ("H2 2024 performance review scheduled for January 15, 2025", True, "our internal process"),
    ("Added suggestions to Posh x HQ2 2026 Partnership document", True, "our internal doc"),
    ("Accepted meeting with Themba Daniels scheduled for Tuesday, August 26, 2025 at "
     "3pm EDT", True, "scheduling logistics plus an internal name"),
    ("They run about one event a month and are on Eventbrite, happy with it but curious "
     "about payouts.", False, "the ideal case"),
    ("Runs a monthly warehouse series on Sunday nights with roughly 300 attendees.",
     False, "'Sunday nights' is their cadence, not an appointment"),
]


def _self_test() -> int:
    failures = 0
    for detail, expect_rejected, why in DETAIL_SCREEN_CASES:
        rejected = bool(DETAIL_REJECT.search(detail))
        ok = rejected == expect_rejected
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {'REJECT' if rejected else 'KEEP  '} "
              f"(want {'REJECT' if expect_rejected else 'KEEP  '})  {why}")
        if not ok:
            print(f"         {detail[:100]}")
    print(f"\n{len(DETAIL_SCREEN_CASES) - failures}/{len(DETAIL_SCREEN_CASES)} "
          f"detail-screen cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(main())
