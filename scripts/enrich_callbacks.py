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

# hs_meeting_outcome is lowercase in the API: scheduled, completed, rescheduled,
# "no show", canceled. A meeting that did not happen is not an interaction.
MEETING_OUTCOME_DEAD = {"no show", "canceled", "cancelled"}

OUT_COLUMNS = ELIGIBLE_COLUMNS + ["callback_tier", "callback_detail",
                                  "callback_source_id", "callback_last_date"]
REVIEW_COLUMNS = ["email", "hs_object_id", "callback_tier", "callback_detail",
                  "callback_source_id", "callback_last_date", "interaction_kind",
                  "evidence", "skipped_reason"]

MODEL_ENV = "BULK_LLM_MODEL"
MAX_DETAIL_CHARS = 4000     # trim engagement bodies before sending to the model


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


def is_two_way(eng: dict) -> tuple[bool, str]:
    """Did a real two-way interaction happen? Returns (yes, human-readable reason)."""
    t = eng["_type"]
    if t == "meetings":
        outcome = (eng.get("hs_meeting_outcome") or "").strip().lower()
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


def pick_detail_source(engagements: list[dict], notes: list[dict]) -> tuple[dict | None, str]:
    """The most recent two-way engagement that actually carries written detail.

    Notes attached to the contact are searched too, since reps often log the substance
    as a note rather than in the call body.
    """
    def text_of(e) -> str:
        for k in ("hs_meeting_body", "hs_call_body", "hs_email_text", "hs_note_body"):
            v = (e.get(k) or "").strip()
            if v:
                return v
        return ""

    candidates = [(e, text_of(e)) for e in engagements]
    candidates += [(n, text_of(n)) for n in notes]
    with_text = [(e, txt) for e, txt in candidates if len(txt) >= 25]
    if not with_text:
        return None, ""
    with_text.sort(key=lambda pair: _ts(pair[0].get("hs_timestamp")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                   reverse=True)
    return with_text[0][0], with_text[0][1][:MAX_DETAIL_CHARS]


EXTRACT_PROMPT = """You are extracting a factual detail from a CRM engagement record so
a salesperson can reference it in an email opener.

Return ONLY a JSON object:
{"detail": "<short faithful paraphrase, or empty string>"}

Rules, in order of importance:
1. FAITHFUL ONLY. Paraphrase what is written. Never add, infer, upgrade, or embellish.
   "Left a voicemail" must never become "we chatted".
2. If the record holds no reusable, concrete detail about the contact's situation,
   return an empty string. Vague admin text ("logged a call", "sent info", "follow up
   next week") is NOT a reusable detail.
3. One clause, under 20 words. No greeting, no pitch, no CTA.
4. Do not name a competitor or a figure unless the record names it.

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
        return detail if 0 < len(detail) <= 200 else ""
    except Exception:
        return ""


def classify(timeline: dict[str, list[dict]], client=None, model: str = "") -> dict:
    """-> {tier, detail, source_id, last_date, interaction_kind, evidence, skipped_reason}"""
    blank = {"callback_tier": "none", "callback_detail": "", "callback_source_id": "",
             "callback_last_date": "", "interaction_kind": "", "evidence": "",
             "skipped_reason": ""}

    engagements = [e for t in ("meetings", "calls", "emails") for e in timeline.get(t, [])]
    notes = timeline.get("notes", [])
    if not engagements and not notes:
        return {**blank, "skipped_reason": "no engagements on the timeline"}

    two_way, rejected = [], []
    for e in engagements:
        ok, why = is_two_way(e)
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

    src, text = pick_detail_source([e for e, _ in two_way], notes)
    if src is None:
        return {**base, "callback_tier": "soft",
                "callback_source_id": str(newest.get("_id", "")),
                "skipped_reason": "real interaction, no reusable detail logged"}

    if client is None:
        return {**base, "callback_tier": "soft",
                "callback_source_id": str(src.get("_id", "")),
                "skipped_reason": "detail present but no LLM client (soft only)"}

    detail = extract_detail(client, model, src.get("_type", "record"), text)
    if not detail:
        return {**base, "callback_tier": "soft",
                "callback_source_id": str(src.get("_id", "")),
                "skipped_reason": "model found no reusable detail"}
    return {**base, "callback_tier": "specific", "callback_detail": detail,
            "callback_source_id": str(src.get("_id", ""))}


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


if __name__ == "__main__":
    raise SystemExit(main())
