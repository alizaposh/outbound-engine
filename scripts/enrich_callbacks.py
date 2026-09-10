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
  2. A PRIOR SEND IS NOT A PRIOR CONVERSATION -- but it is not nothing either.
     `hs_email_direction == INCOMING_EMAIL` is still the crux for `soft` and `specific`:
     only a reply earns "good to reconnect", which on a one-way send reads false.
     **A send with no reply now earns the separate `attempt` tier** (added 2026-09-10),
     which licenses "I know we tried to connect" and nothing more. The two claims are
     genuinely different -- one asserts an exchange, the other only that we wrote -- and
     collapsing them was costing an honest opener on every contact a colleague had
     already chased. `attempt` carries a DATE and never a detail: our own logged sends
     are bulk-associated and cannot be trusted per contact (one real body opens "Hey
     David" while attached to two other people), so *that* we wrote is reliable and
     *what* we wrote is not.
  3. ONLY THE PROSPECT'S OWN NEW WORDS ARE READ. An inbound reply carries the whole
     quoted thread beneath it, which is OUR text. One real example ran 7.7k chars of
     which the prospect wrote 105: the rest was our own message including "3% + $1.50
     per ticket" and "a $1M advance, interest-free". Extracting from the full body
     would build a callback out of our own confidential pricing and attribute it to
     them. Everything from the first quote marker onward is discarded.
  4. UNCERTAIN MEANS NONE. Any doubt returns tier "none" and the generator writes a
     cold open. A missing callback costs nothing; a fabricated one costs the lead.

EMAIL ONLY (narrowed 2026-08-26). Calls and meetings are no longer read: we are
unlikely to be cold-emailing anyone we have already taken a call with, so supporting
that path cost real complexity (a mis-documented meeting-outcome enum, calendar
boilerplate, 20k-char Gong transcripts) for a case that barely occurs. Prior EMAIL
conversation is the signal that actually exists on a cold list.

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
ENGAGEMENT_TYPES = ("emails",)

PROPS = {
    "emails": ["hs_timestamp", "hs_email_subject", "hs_email_text",
               "hs_email_direction", "hs_email_status"],
}

# hs_email_direction: EMAIL (we sent it), INCOMING_EMAIL (the contact replied),
# FORWARDED_EMAIL. Only INCOMING_EMAIL is two-way.
EMAIL_INBOUND = "INCOMING_EMAIL"

# A future-dated email is not a memory (a scheduled send, or a bad timestamp).
FUTURE_GRACE = dt.timedelta(hours=12)

# How far back a prior SEND can be and still be worth acknowledging (tier `attempt`).
# A year, because "we tried to reach you" stops being a courtesy and starts being odd
# once the prospect has no memory of it -- and because a three-year-old send says more
# about our CRM than about them. Shorter than this is safe; much longer reads as us
# admitting we have been mailing them for years.
ATTEMPT_MAX_AGE_DAYS = 365

OUT_COLUMNS = ELIGIBLE_COLUMNS + ["callback_tier", "callback_detail",
                                  "callback_source_id", "callback_last_date"]
REVIEW_COLUMNS = ["email", "hs_object_id", "callback_tier", "callback_detail",
                  "callback_source_id", "callback_last_date", "interaction_kind",
                  "evidence", "skipped_reason"]

MODEL_ENV = "BULK_LLM_MODEL"
# A safety bound, not a working limit. Once the quoted thread is stripped, a reply is
# usually a sentence or two: the 7.7k-char example collapsed to 105 chars of the
# prospect's own words. This only guards against an unusually long single message.
MAX_DETAIL_CHARS = 8000


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


def is_two_way(eng: dict, now: dt.datetime | None = None) -> tuple[bool, str]:
    """Did the contact actually write to us? Returns (yes, human-readable reason)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    when = _ts(eng.get("hs_timestamp"))
    if when and when > now - FUTURE_GRACE:
        return False, f"email is not in the past ({when.date()})"
    direction = (eng.get("hs_email_direction") or "").strip().upper()
    if direction == EMAIL_INBOUND:
        return True, "inbound email (contact replied)"
    return False, f"outbound email ({direction or 'no direction'}), not a conversation"


HTML_TAG = re.compile(r"<[^>]+>")

# THE QUOTED THREAD IS OUR TEXT, NOT THEIRS. An inbound reply carries the whole prior
# conversation beneath it. A real example: 7741 chars total, of which the prospect wrote
# the first 105 ("Thanks for sending. We will review along with our other proposals...")
# and the remainder was our own message, including "3% + $1.50 per ticket" and "a $1M
# advance, interest-free". Reading past the first marker would let our own confidential
# pricing become a "callback" attributed to the prospect. Everything from the first
# marker onward is discarded, so only their new words survive.
QUOTE_MARKERS = [
    re.compile(r"^\s*On .{4,80}\bwrote:\s*$", re.M | re.I),   # Gmail / Apple Mail
    # The same attribution when it WRAPS, so "wrote:" is on a later line, or is
    # truncated away entirely. Seen on a real reply 2026-09-01:
    #   "On Tue, Sep 1, 2026 at 11:12 AM Carl Newmark <carl@..."
    # Deliberately anchored on the full date-and-time shape rather than a bare "On ",
    # because over-cutting deletes the prospect's own words -- the failure that matters
    # more than leaving a stray quoted line behind.
    re.compile(r"^\s*On\s+(?:\w{3,9},?\s+)?\w{3,9}\s+\d{1,2},?\s+\d{4}[,]?\s+at\s+"
               r"[\d:]+\s*[AP]?\.?M?\.?", re.M | re.I),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.M | re.I),
    re.compile(r"^\s*_{5,}\s*$", re.M),                        # Outlook divider
    re.compile(r"^\s*From:\s.+$", re.M),                       # Outlook header block
    re.compile(r"^\s*Sent:\s.+$", re.M),
    re.compile(r"^\s*>", re.M),                                 # any quoted line
]
# Mobile signatures: harmless, but they are not content and skew the length floor.
SIGNATURE = re.compile(
    r"^\s*(sent from my \w+|get outlook for \w+|sent via \w+).*$", re.M | re.I)


def strip_quoted(raw: str) -> str:
    """Keep only what the sender typed above the quoted thread."""
    txt = raw or ""
    cut = len(txt)
    for pat in QUOTE_MARKERS:
        m = pat.search(txt)
        if m:
            cut = min(cut, m.start())
    return txt[:cut]


def clean_body(raw: str) -> str:
    """Quoted thread out first, then HTML, then whitespace.

    Order matters: HTML stripping would destroy the ">" and header markers that
    identify where the quoted thread begins, so quoting is removed first.
    """
    txt = strip_quoted(raw or "")
    txt = HTML_TAG.sub(" ", txt)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    txt = SIGNATURE.sub(" ", txt)
    return re.sub(r"\s+", " ", txt).strip()


MAX_SOURCES_TRIED = 4       # cap the cheap-LLM calls per contact


def detail_sources(inbound: list[dict]) -> list[tuple[dict, str]]:
    """Inbound emails carrying enough of the prospect's own text to be worth reading,
    most recent first.

    Returns a LIST, not one pick: a single unhelpful top candidate used to block better
    text further down, and the contact fell back to soft. The caller tries these in
    order until one yields a usable detail.
    """
    scored = []
    for e in inbound:
        txt = clean_body(e.get("hs_email_text") or "")
        if len(txt) >= 25:                     # below this it is "thanks!" and nothing more
            scored.append((e, txt[:MAX_DETAIL_CHARS]))
    scored.sort(key=lambda pair: -( _ts(pair[0].get("hs_timestamp"))
                                    or dt.datetime.min.replace(tzinfo=dt.timezone.utc)).timestamp())
    return scored[:MAX_SOURCES_TRIED]


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

    engagements = list(timeline.get("emails", []))
    if not engagements:
        return {**blank, "skipped_reason": "no logged emails on the timeline"}

    now = now or dt.datetime.now(dt.timezone.utc)
    two_way, rejected = [], []
    for e in engagements:
        ok, why = is_two_way(e, now)
        (two_way if ok else rejected).append((e, why))

    if not two_way:
        # TIER `attempt` (added 2026-09-10). No reply, but we DID write to them.
        #
        # "Good to reconnect" needs a reply and is what guarantee 2 protects. **"I know
        # we tried to connect before" needs only a send, and is true whether or not they
        # answered.** Those are different claims, and collapsing them was costing an
        # honest and useful opener on every contact a colleague has already chased.
        #
        # **The fact only, NEVER the content.** Our own logged sends cannot be trusted
        # per contact: on maxwellsocial.com one body opens "Hey David" while attached to
        # both Patricia and Kyle, and a second opens "Hi Joelle!" on both. Bulk-logged
        # mail with mismatched salutations means "we emailed this contact on <date>" is
        # reliable while "we said X to them" is not. So this tier carries a DATE and no
        # detail, and never reaches the LLM extractor.
        outbound = [(e, _ts(e.get("hs_timestamp"))) for e in engagements
                    if (e.get("hs_email_direction") or "").strip().upper()
                    not in ("", EMAIL_INBOUND)]
        dated = sorted([(t, e) for e, t in outbound if t], reverse=True)
        if dated:
            when, newest_out = dated[0]
            age = (now - when).days
            if 0 <= age <= ATTEMPT_MAX_AGE_DAYS:
                return {**blank, "callback_tier": "attempt",
                        "callback_last_date": when.date().isoformat(),
                        "callback_source_id": str(newest_out.get("_id", "")),
                        "interaction_kind": "outbound email, no reply",
                        "evidence": f"{len(dated)} prior send(s); newest {when.date()}",
                        "skipped_reason": ""}
            reasons = (f"last send was {age} day(s) ago, over the "
                       f"{ATTEMPT_MAX_AGE_DAYS}-day window for referencing an attempt")
            return {**blank, "skipped_reason": reasons}
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

    sources = detail_sources([e for e, _ in two_way])
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
