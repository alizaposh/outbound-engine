#!/usr/bin/env python3
"""Restart sequences that an out-of-office auto-responder froze, once the date arrives.

    HubSpot outbound_resume_after <= today  ->  Smartlead resume  ->  clear the date

**The gap this closes.** Smartlead halts follow-ups on ANY reply, and an auto-responder
is a reply. `out_of_office` therefore ends the sequence exactly as a real answer would.
`reply_check.py` used to leave it there, on the stated grounds that Smartlead had its own
OOO auto-pause with an auto-restart after N days -- an assumption that was never verified
and looks wrong: no such setting is exposed on the campaign object, `stop_lead_settings`
is REPLY_TO_AN_EMAIL, and seven test replies that Smartlead itself labelled out-of-office
all landed COMPLETED rather than PAUSED.

If nothing restarts those leads, **a prospect who was merely on holiday gets email 1 and
is never contacted again.** It is the worst shape of bug this system can have: silent,
because the lead reads COMPLETED just like a genuine non-replier, and it strikes the most
recoverable non-response there is.

So the wait is ours to keep. `reply_check.py` reads the return date out of the
auto-responder (they nearly always give one) and writes `outbound_resume_after`; this job
acts on it when the day comes. Nothing here depends on Smartlead detecting anything --
which matters, because its OOO detection is demonstrably unreliable: it labelled all
seven human test replies as out-of-office.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. IT NEVER RESUMES EARLY. Only a date that has arrived counts. A contact with no date
     is invisible to this job.
  3. IT RE-CHECKS EVERYTHING AT RESUME TIME. An absence is often weeks long, and the date
     was written before it started. Suppression, native opt-out and lifecycle status are
     all read fresh; **a contact who has since genuinely replied is never restarted**,
     which is the failure that would matter most -- mailing a live conversation with
     sequence step 2.
  4. IT ONLY RESUMES `in_sequence`. That is the only status an out-of-office leaves
     behind (the intent deliberately does not advance the lead), so anything else means
     something happened afterwards and this job does not know what.
  5. IDEMPOTENT. The date is CLEARED after a successful resume, so a contact cannot be
     resumed twice and a re-run does nothing.
  6. IT SENDS NO MAIL. It unfreezes a sequence that Smartlead owns and schedules; it has
     no send path and never writes suppression or advances a status.

Runs in the morning heartbeat slot, **AFTER `close_sequences`**, and the order is not
arbitrary. Both jobs look at the same lead, which is `COMPLETED` in Smartlead and still
`in_sequence` in HubSpot, and `outbound_resume_after` is the only thing that tells them
apart. `close_sequences` refuses to close while that date is set; this job CLEARS it.

  close first, then resume  -> the date is present while close_sequences looks, so its
                               guard is active and the lead is safe. Then this job
                               resumes it. Correct.
  resume first, then close  -> this job clears the date, and close_sequences then sees a
                               lead that may still read COMPLETED (Smartlead's status
                               need not update within the same run) with no date left to
                               protect it. It closes the lead we just revived.

So the guard in `close_sequences` and this ordering are two halves of one rule: **the
date must still be set when close_sequences runs.**
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import env_token, env_value  # noqa: E402
from reply_check import HubSpotWriter, Smartlead  # noqa: E402

# Everything decide() needs. Read fresh at resume time -- guarantee 3.
READ_PROPS = ["email", "outbound_status", "outbound_suppressed", "hs_email_optout",
              "outbound_resume_after", "outbound_last_campaign_id"]
# The only status an out-of-office leaves behind, and so the only one that may resume.
RESUMABLE_STATUS = "in_sequence"
DATE_PROP = "outbound_resume_after"


def as_date(value) -> str:
    """A HubSpot date property as `YYYY-MM-DD`, or "" if there isn't one.

    HubSpot is inconsistent about this and both shapes are real: a `date` property comes
    back as epoch MILLISECONDS from the search API and as an ISO string elsewhere.
    Comparing the millis form as a string would sort "1789…" before a date and read as
    long overdue, so every read goes through here.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    if s.isdigit():                       # epoch millis, UTC midnight
        return dt.datetime.fromtimestamp(int(s) / 1000, dt.timezone.utc).date().isoformat()
    return s[:10]


def to_millis(day: str) -> int:
    """`YYYY-MM-DD` as UTC-midnight epoch millis, which is what search filters want."""
    d = dt.date.fromisoformat(day)
    return int(dt.datetime(d.year, d.month, d.day,
                           tzinfo=dt.timezone.utc).timestamp() * 1000)


def decide(props: dict, today: str) -> tuple[str, str]:
    """(outcome, note). Pure, so the safety rules are testable without an API.

    Order matters: consent is checked before lifecycle, so a suppressed contact reports
    as suppressed even if their status also moved on. The reason a human reads should be
    the most important one, not the first one that happened to match.
    """
    due = as_date(props.get(DATE_PROP))
    if not due:
        return "no date", "no outbound_resume_after set"
    if due > today:                                                   # guarantee 2
        return "not due", f"scheduled for {due}, still in the future"

    if str(props.get("outbound_suppressed") or "").lower() in ("true", "1"):
        return "blocked", "outbound_suppressed is true"
    if str(props.get("hs_email_optout") or "").lower() in ("true", "1"):
        return "blocked", "hs_email_optout is true (native opt-out)"

    status = (props.get("outbound_status") or "").strip()
    if status != RESUMABLE_STATUS:                                    # guarantee 4
        # The important member of this set is `replied`. Resuming there would send
        # sequence step 2 into a live conversation, as a persona who is supposedly
        # already talking to them.
        return "moved on", (f"outbound_status is {status or '(empty)'}, not "
                            f"{RESUMABLE_STATUS}; something happened while they were away")
    if not (props.get("outbound_last_campaign_id") or "").strip():
        return "no campaign", "no outbound_last_campaign_id, so there is nothing to resume"
    return "resume", f"due {due}"


def lead_index(sl: Smartlead, cid: str, cache: dict) -> dict:
    """{email: lead_id} for a campaign, fetched once per campaign per run."""
    if cid in cache:
        return cache[cid]
    out, offset = {}, 0
    while True:
        d = sl.get(f"/campaigns/{cid}/leads?offset={offset}&limit=100")
        rows = d.get("data") or []
        if not rows:
            break
        for row in rows:
            lead = row.get("lead") or {}
            em = (lead.get("email") or "").strip().lower()
            if em and lead.get("id"):
                out[em] = lead["id"]
        offset += len(rows)
        if offset >= int(d.get("total_leads") or 0):
            break
    cache[cid] = out
    return out


def due_contacts(hs: HubSpotWriter, today: str) -> list[dict]:
    """Every contact whose resume date has arrived.

    Filtered server-side on the date so this stays cheap as the contact base grows: it
    asks for the handful that are due, never the whole database.
    """
    found, after = [], None
    while True:
        body = {"filterGroups": [{"filters": [
                    {"propertyName": DATE_PROP, "operator": "LTE",
                     "value": to_millis(today)}]}],
                "properties": READ_PROPS, "limit": 100}
        if after:
            body["after"] = after
        d = hs._call("POST", "/crm/v3/objects/contacts/search", body)
        for r in d.get("results") or []:
            p = dict(r.get("properties") or {})
            p["hs_object_id"] = r["id"]
            found.append(p)
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Resume sequences frozen by an out-of-office. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="RESUME in Smartlead and clear the date in HubSpot.")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the safety rules with no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()

    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    sl = Smartlead(key, a.apply)
    hs = HubSpotWriter(env_token(), a.apply)
    print("APPLY: resuming in Smartlead and clearing dates" if a.apply
          else "DRY RUN: nothing will be resumed or written. Re-run with --apply to act.")

    contacts = due_contacts(hs, today)
    if not contacts:
        print(f"\nno contact has a resume date on or before {today}. Nothing to do.")
        return 0
    print(f"\n{len(contacts)} contact(s) due on or before {today}\n")

    counts = {"resume": 0, "blocked": 0, "moved on": 0, "no campaign": 0,
              "not due": 0, "no date": 0, "unmatched": 0}
    cache: dict = {}
    for p in sorted(contacts, key=lambda x: (x.get("email") or "")):
        email = (p.get("email") or "").strip().lower()
        outcome, note = decide(p, today)
        if outcome != "resume":
            counts[outcome] += 1
            print(f"  SKIP     {email:42} {note}")
            continue

        cid = (p["outbound_last_campaign_id"] or "").strip()
        lead_id = lead_index(sl, cid, cache).get(email)
        if not lead_id:
            # Never guess an id: the wrong one restarts a stranger's sequence.
            counts["unmatched"] += 1
            print(f"  UNMATCHED {email:41} due, but not found on campaign {cid}")
            continue

        print(f"  RESUME   {email:42} {note}, campaign {cid}")
        print(f"           smartlead: {sl.resume(cid, lead_id)}")
        # Guarantee 5. Cleared only after the resume call returned without raising, so a
        # failure leaves the date in place and the contact is retried tomorrow.
        print(f"           hubspot:   {hs.write(p['hs_object_id'], {DATE_PROP: ''})}")
        counts["resume"] += 1

    print(f"\n{counts['resume']} resumed, {counts['blocked']} blocked, "
          f"{counts['moved on']} moved on, {counts['unmatched']} unmatched")
    print(f"{sl.calls} Smartlead calls, {hs.calls} HubSpot calls")
    if not a.apply:
        print("DRY RUN: nothing was resumed. Nothing was written.")
    return 0


def _self_test() -> int:
    fails = []
    T = "2026-09-09"

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    base = {"outbound_status": "in_sequence", "outbound_last_campaign_id": "123"}

    # The one thing this job exists to do.
    check("a due contact resumes",
          decide({**base, DATE_PROP: "2026-09-01"}, T)[0], "resume")
    check("due exactly today resumes",
          decide({**base, DATE_PROP: T}, T)[0], "resume")

    # Guarantee 2.
    check("tomorrow does not resume",
          decide({**base, DATE_PROP: "2026-09-10"}, T)[0], "not due")
    check("no date is invisible", decide({**base}, T)[0], "no date")

    # Guarantee 3, and the one that matters most: they answered while away.
    for status in ("replied", "meeting_booked", "opted_out", "bounced", "disqualified",
                   "no_response", ""):
        check(f"{status or '(empty)'} does not resume",
              decide({**base, "outbound_status": status, DATE_PROP: "2026-09-01"}, T)[0],
              "moved on")
    check("suppressed does not resume",
          decide({**base, DATE_PROP: "2026-09-01", "outbound_suppressed": "true"}, T)[0],
          "blocked")
    check("native opt-out does not resume",
          decide({**base, DATE_PROP: "2026-09-01", "hs_email_optout": "true"}, T)[0],
          "blocked")
    # Consent outranks lifecycle in the reported reason.
    check("a suppressed AND moved-on contact reports as blocked",
          decide({DATE_PROP: "2026-09-01", "outbound_status": "replied",
                  "outbound_suppressed": "true"}, T)[0], "blocked")
    # A future date beats every other consideration: not due is not a judgement call.
    check("suppressed but not due is still just not due",
          decide({**base, DATE_PROP: "2026-12-01", "outbound_suppressed": "true"}, T)[0],
          "not due")

    check("no campaign id cannot resume",
          decide({"outbound_status": "in_sequence", DATE_PROP: "2026-09-01"}, T)[0],
          "no campaign")

    # A datetime-shaped value from HubSpot must compare as a date, not a string prefix.
    check("an ISO datetime is truncated to its date",
          decide({**base, DATE_PROP: "2026-09-01T00:00:00Z"}, T)[0], "resume")

    # HubSpot hands `date` properties back as epoch millis from the search API. Read as a
    # raw string, "1788…" sorts below any ISO date and every contact would look overdue.
    check("epoch millis are read as a date, not compared as a string",
          as_date("1788480000000"), "2026-09-04")
    check("a due date in millis resumes",
          decide({**base, DATE_PROP: "1788480000000"}, T)[0], "resume")
    check("a FUTURE date in millis does not resume",
          decide({**base, DATE_PROP: "1798761600000"}, T)[0], "not due")
    check("an empty value is still empty", as_date(None), "")
    # The filter value must be millis too, or HubSpot 400s the search.
    check("to_millis round-trips", as_date(str(to_millis("2026-09-04"))), "2026-09-04")

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
