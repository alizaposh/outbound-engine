#!/usr/bin/env python3
"""Promote a contact to `outbound_status = meeting_booked` once they actually book.

    HubSpot engagements_last_meeting_booked  ->  outbound_status = meeting_booked

**Why this exists.** `meeting_booked` is named in `config/hubspot-properties.md` as the
outcome state and is protected from being overwritten in four separate scripts -- and
**nothing ever wrote it.** A prospect who replied, got the booking link, and booked a
meeting stayed `replied` forever. The single metric the engine exists to produce had no
source, so any dashboard counting meetings would have read zero regardless of reality.

The source is native. Every booking link in `config/meeting-routing.md` is a HubSpot
meetings link, specifically so a booking lands in HubSpot and populates
`engagements_last_meeting_booked` without anything of ours being involved. This job reads
that and promotes the outbound status, which is what makes "meetings booked" filterable
and clickable alongside every other outbound metric.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. **THE BOOKING MUST POSTDATE ENROLMENT.** A contact may have booked a meeting years
     ago through a completely different channel; `engagements_last_meeting_booked` is
     native and knows nothing about this engine. Crediting an old booking would inflate
     the one number the engine is judged on, which is worse than reporting nothing. The
     campaign's creation date is the cutoff.
  3. IT ONLY PROMOTES FROM `replied`, `in_sequence` or `no_response`. Those are states a
     booking legitimately supersedes.
  4. IT NEVER OVERWRITES A TERMINAL STATE. `opted_out`, `bounced` and `disqualified` carry
     consent and deliverability facts this job does not have, and a stale booking must not
     resurrect a contact who has since opted out.
  5. IT NEVER TOUCHES SUPPRESSION. A booking is not a consent decision.
  6. IDEMPOTENT. A contact already `meeting_booked` is skipped, so re-running is a no-op.

Runs in the morning heartbeat, after `sync_sends`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import HubSpot, env_token, env_value  # noqa: E402
from reply_check import HubSpotWriter  # noqa: E402

import lifecycle  # noqa: E402

SL_BASE = "https://server.smartlead.ai/api/v1"
BOOKED_PROP = "engagements_last_meeting_booked"
READ_PROPS = ["email", "outbound_status", "outbound_suppressed",
              # read so a booking can also promote the lifecycle stage to Qualified
              "lifecyclestage",
              "outbound_last_campaign_id", BOOKED_PROP]
TARGET = "meeting_booked"
# States a booking legitimately supersedes -- guarantee 3.
PROMOTABLE = {"replied", "in_sequence", "no_response", ""}
# States that carry information this job does not have -- guarantee 4.
TERMINAL = {"opted_out", "bounced", "disqualified"}


def as_date(value) -> str:
    """A HubSpot datetime property as YYYY-MM-DD, or "".

    Both shapes are real: epoch millis from the search API, ISO elsewhere. Compared as a
    raw string, millis sort below any ISO date and every booking would look ancient --
    the same trap `resume_sequences.as_date` exists for.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    if s.isdigit():
        return dt.datetime.fromtimestamp(int(s) / 1000, dt.timezone.utc).date().isoformat()
    return s[:10]


def decide(props: dict, enrolled_on: str | None) -> tuple[str, dict, str]:
    """(outcome, properties, note). Pure, so the attribution rules are testable."""
    booked = as_date(props.get(BOOKED_PROP))
    status = (props.get("outbound_status") or "").strip()
    if not booked:
        return "no booking", {}, "no meeting booked in the meetings tool"
    if status == TARGET:
        return "already booked", {}, f"already outbound_status={TARGET}"
    if status in TERMINAL:
        # Guarantee 4. A booking from before an opt-out must not undo the opt-out.
        return ("leave alone", {},
                f"outbound_status is {status}; a booking does not override it")
    if status not in PROMOTABLE:
        return "leave alone", {}, f"outbound_status is {status!r}, not a promotable state"
    if enrolled_on is None:
        # The cutoff could not be read. Guarantee 2 cannot be applied, so no judgement
        # is made -- see Smartlead.created_on for why this is a skip and not a promote.
        return ("cutoff unknown", {},
                "could not read the campaign's creation date; not judging this one")
    if enrolled_on and booked < enrolled_on:
        # Guarantee 2. The single most important rule here: this booking predates our
        # outreach, so it is somebody else's meeting.
        return ("predates enrolment", {},
                f"booked {booked}, enrolled {enrolled_on}; not ours to claim")
    # A booked meeting is the strongest qualification signal the engine ever sees, so
    # it moves the LIFECYCLE stage too (added 2026-09-25). Guarded: a Dormant contact
    # cannot reach Qualified in this portal, and a contact a human has already moved to
    # Deal Created is not demoted by an automated promotion.
    out = {"outbound_status": TARGET}
    cur_stage = (props.get("lifecyclestage") or "").strip()
    can, why_not = lifecycle.may_promote(cur_stage, lifecycle.QUALIFIED)
    note = f"booked {booked}"
    if can:
        out["lifecyclestage"] = lifecycle.QUALIFIED
        note += f"; lifecycle {lifecycle.label(cur_stage)} -> Qualified"
    elif "already" not in why_not:
        note += f"; lifecycle left at {lifecycle.label(cur_stage)} ({why_not})"
    return "promote", out, note


class Smartlead:
    """Read-only; used solely for campaign creation dates."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0
        self._created: dict[str, str] = {}
        self._failed: set[str] = set()

    def created_on(self, cid: str) -> str | None:
        """The campaign's creation date, cached. The enrolment cutoff for guarantee 2."""
        cid = str(cid or "").strip()
        if not cid:
            return ""
        if cid in self._created:
            return self._created[cid]
        try:
            req = urllib.request.Request(
                f"{SL_BASE}/campaigns/{cid}?api_key={self.key}",
                headers={"User-Agent": "outbound-engine/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                self.calls += 1
                d = json.loads(r.read() or b"{}")
            self._created[cid] = str(d.get("created_at") or "")[:10]
        except Exception as e:
            # **A FAILED LOOKUP IS NOT "NO CUTOFF". That distinction was wrong and it
            # cost a false metric.** This used to return "" on any exception, and
            # decide() promotes when the cutoff is unknown -- reasoned as "refusing to
            # record a real meeting because a campaign was tidied up would lose the
            # outcome entirely". The failure direction was backwards.
            #
            # On 2026-09-22 four heartbeat slots fired at once after a day off and
            # Smartlead returned 429s. This swallowed one, returned "", and promoted
            # Stacey Hale to meeting_booked on the strength of a meeting booked
            # 2026-06-02 -- three and a half months before the campaign existed. The
            # engine's headline number went from 0 to 1 because of a rate limit.
            #
            # Inflating the one metric the engine is judged on is strictly worse than
            # missing a real booking for a few hours: the miss self-corrects on the next
            # run, the inflation does not, and nobody re-checks a number that moved in
            # the direction they hoped. A failure now returns None, which decide()
            # treats as "cannot judge -- skip and say so".
            self._failed.add(cid)
            print(f"    !! could not read campaign {cid} ({type(e).__name__}); its "
                  f"contacts are SKIPPED rather than promoted without a cutoff")
            return None
        return self._created[cid]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Promote contacts who booked a meeting. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE outbound_status=meeting_booked to HubSpot.")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the attribution rules with no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()

    hs = HubSpot(env_token())
    writer = HubSpotWriter(env_token(), a.apply)
    sl = Smartlead(env_value("SMARTLEAD_API_KEY") or "")
    print("APPLY: writing outbound_status=meeting_booked" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")

    # Only contacts the engine enrolled. A booking by anyone else is not ours.
    found, after = [], None
    while True:
        body = {"filterGroups": [{"filters": [
                    {"propertyName": "outbound_last_campaign_id",
                     "operator": "HAS_PROPERTY"},
                    {"propertyName": BOOKED_PROP, "operator": "HAS_PROPERTY"}]}],
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
            break

    if not found:
        print("\nno engine-enrolled contact has booked a meeting yet. Nothing to do.")
        print("This is the expected result until an interested reply converts.")
        return 0

    counts = {"promote": 0, "already booked": 0, "leave alone": 0,
              "predates enrolment": 0, "no booking": 0, "cutoff unknown": 0}
    print(f"\n{len(found)} enrolled contact(s) with a booking on record\n")
    for p in sorted(found, key=lambda x: x.get("email") or ""):
        enrolled = sl.created_on(p.get("outbound_last_campaign_id", ""))
        outcome, props, note = decide(p, enrolled)
        counts[outcome] += 1
        label = {"promote": "BOOKED  ", "already booked": "CURRENT ",
                 "leave alone": "KEPT    ", "predates enrolment": "NOT OURS",
                 "no booking": "SKIP    ", "cutoff unknown": "UNKNOWN "}[outcome]
        print(f"  {label} {str(p.get('email'))[:40]:42} {note}")
        if props:
            print(f"           {writer.write(p['hs_object_id'], props)}")

    print(f"\n{counts['promote']} promoted, {counts['already booked']} already current, "
          f"{counts['predates enrolment']} predate enrolment, "
          f"{counts['leave alone']} left alone"
          + (f", ** {counts['cutoff unknown']} UNJUDGED (campaign unreadable) **"
             if counts["cutoff unknown"] else ""))
    print(f"{hs.calls + writer.calls} HubSpot calls, {sl.calls} Smartlead calls")
    if not a.apply:
        print("DRY RUN: nothing was written.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    E = "2026-09-01"          # enrolled
    base = {"outbound_last_campaign_id": "1"}

    check("a booking after enrolment promotes",
          decide({**base, BOOKED_PROP: "2026-09-10", "outbound_status": "replied"}, E)[:2],
          ("promote", {"outbound_status": TARGET,
                       "lifecyclestage": lifecycle.QUALIFIED}))
    check("promotes from in_sequence too",
          decide({**base, BOOKED_PROP: "2026-09-10",
                  "outbound_status": "in_sequence"}, E)[0], "promote")
    check("promotes from no_response",
          decide({**base, BOOKED_PROP: "2026-09-10",
                  "outbound_status": "no_response"}, E)[0], "promote")

    # Guarantee 2, the attribution rule.
    check("a booking BEFORE enrolment is not ours",
          decide({**base, BOOKED_PROP: "2024-03-01",
                  "outbound_status": "replied"}, E)[0], "predates enrolment")
    check("same-day booking counts as ours",
          decide({**base, BOOKED_PROP: E, "outbound_status": "replied"}, E)[0], "promote")
    check("no enrolment date known -> still promoted, not lost",
          decide({**base, BOOKED_PROP: "2024-03-01",
                  "outbound_status": "replied"}, "")[0], "promote")

    # Guarantee 4.
    for st in ("opted_out", "bounced", "disqualified"):
        check(f"{st} is never overwritten by a booking",
              decide({**base, BOOKED_PROP: "2026-09-10",
                      "outbound_status": st}, E)[0], "leave alone")

    # Guarantees 5 and 6.
    outcome, props, _ = decide({**base, BOOKED_PROP: "2026-09-10",
                                "outbound_status": "replied"}, E)
    check("guarantee 5: suppression untouched", "outbound_suppressed" in props, False)
    check("guarantee 6: already booked is a no-op",
          decide({**base, BOOKED_PROP: "2026-09-10",
                  "outbound_status": TARGET}, E)[:2], ("already booked", {}))
    check("no booking is skipped", decide({**base}, E)[0], "no booking")

    # Epoch millis from the search API must compare as a date.
    check("millis are read as a date", as_date("1788480000000"), "2026-09-04")
    check("a millis booking after enrolment promotes",
          decide({**base, BOOKED_PROP: "1788480000000",
                  "outbound_status": "replied"}, E)[0], "promote")

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
