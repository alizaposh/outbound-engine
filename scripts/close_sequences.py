#!/usr/bin/env python3
"""Close out finished sequences: `in_sequence` -> `no_response` in HubSpot.

Closes the gap that nothing ever moved a lead OFF `in_sequence`.

    Smartlead lead status COMPLETED  ->  HubSpot outbound_status = no_response

**Why this is not cosmetic.** `in_sequence` is a SOFT exclusion in
`config/pre-send-defaults.md`, so gate 2 skips those contacts. Nothing wrote the next
state, which means every contact ever enrolled would sit at `in_sequence` forever and be
**permanently unreachable by any future campaign**. The first campaign would quietly burn
its own list. `no_response` is the state that makes them contactable again.

Five guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. IT ONLY EVER MOVES `in_sequence` -> `no_response`. Any other status is left
     untouched: `replied`, `meeting_booked`, `opted_out`, `bounced` and `disqualified` all
     carry information this job does not have and must not overwrite. A lead who replied
     is COMPLETED in Smartlead too, so this rule is what stops a reply being erased.
  3. IT ACTS ONLY ON SMARTLEAD `COMPLETED`. Not `BLOCKED` (unsubscribed or bounced --
     those belong to the other two syncs and carry stronger states), not `INPROGRESS`,
     not `PAUSED`. A lead mid-sequence must keep its exclusion.
  4. IT NEVER TOUCHES SUPPRESSION. `no_response` is a lifecycle state, not a consent
     decision. `outbound_suppressed` and `hs_email_optout` are not written.
  5. IDEMPOTENT. A contact already `no_response` is skipped, so re-running changes
     nothing.

Runs in the morning heartbeat slot alongside the unsubscribe and bounce syncs.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import HubSpot, env_token, env_value  # noqa: E402
from reply_check import HubSpotWriter  # noqa: E402

SL_BASE = "https://server.smartlead.ai/api/v1"
READ_PROPS = ["email", "outbound_status", "outbound_suppressed"]
# The only Smartlead lead status this acts on. See guarantee 3.
DONE_STATUS = "COMPLETED"
# The only HubSpot status it will move. See guarantee 2.
FROM_STATUS = "in_sequence"
TO_STATUS = "no_response"


def decide(smartlead_status: str, existing: dict) -> tuple[str, dict, str]:
    """(outcome, properties, note). Pure, so the rules are testable without an API."""
    status = (existing.get("outbound_status") or "").strip()
    if (smartlead_status or "").upper() != DONE_STATUS:
        return "not finished", {}, f"Smartlead status is {smartlead_status!r}, not COMPLETED"
    if status == TO_STATUS:
        return "already closed", {}, f"already outbound_status={TO_STATUS}"
    if status != FROM_STATUS:
        # Guarantee 2. A lead who replied is COMPLETED in Smartlead as well, so without
        # this a reply, a booked meeting or an opt-out would be overwritten by a
        # lifecycle tidy-up that knows nothing about any of them.
        return ("leave alone", {},
                f"outbound_status is {status or '(empty)'!r}, not {FROM_STATUS}; it holds "
                f"information this job does not have")
    return "close", {"outbound_status": TO_STATUS}, ""


class Smartlead:
    """Read-only. This job never changes anything in Smartlead."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0

    def get(self, path: str):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(f"{SL_BASE}{path}{sep}api_key={self.key}",
                                     headers={"User-Agent": "outbound-engine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.calls += 1
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"GET {path} -> {e.code}: {(e.read() or b'').decode()[:200]}") from None

    def campaigns(self) -> list[dict]:
        return self.get("/campaigns") or []

    def leads(self, cid) -> list[tuple[str, str]]:
        """[(email, lead status)] for the whole campaign. Paginated."""
        out, offset = [], 0
        while True:
            d = self.get(f"/campaigns/{cid}/leads?offset={offset}&limit=100")
            rows = d.get("data") or []
            if not rows:
                return out
            for row in rows:
                email = ((row.get("lead") or {}).get("email") or "").strip().lower()
                if email:
                    out.append((email, row.get("status") or ""))
            offset += len(rows)
            if offset >= int(d.get("total_leads") or 0):
                return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Move finished sequences to no_response. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE outbound_status=no_response to HubSpot.")
    ap.add_argument("--campaign", help="one campaign id; default is every campaign")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the transition rules with no API calls")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")
    sl = Smartlead(key)
    print("APPLY: writing outbound_status=no_response" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")

    campaigns = ([{"id": a.campaign, "name": f"(id {a.campaign})"}] if a.campaign
                 else sl.campaigns())
    if not campaigns:
        print("no campaigns in the account, so no sequences to close yet.")
        return 0

    finished: dict[str, str] = {}
    for camp in campaigns:
        rows = sl.leads(camp.get("id"))
        done = [(e, s) for e, s in rows if (s or "").upper() == DONE_STATUS]
        by_status: dict[str, int] = {}
        for _, s in rows:
            by_status[s or "(none)"] = by_status.get(s or "(none)", 0) + 1
        print(f"campaign {camp.get('id')} {camp.get('name','')!r}: "
              f"{len(rows)} lead(s) {by_status}")
        for e, s in done:
            finished[e] = s

    if not finished:
        print("\nno finished sequences. Nothing to close.")
        return 0

    hs_read = HubSpot(env_token())
    writer = HubSpotWriter(env_token(), a.apply)
    contacts = hs_read.search_by_email(sorted(finished), READ_PROPS)
    counts = {"close": 0, "already closed": 0, "leave alone": 0, "not finished": 0,
              "unmatched": 0}
    print(f"\n{len(finished)} finished lead(s), {len(contacts)} matched in HubSpot\n")

    for email, sl_status in sorted(finished.items()):
        existing = contacts.get(email)
        if existing is None:
            counts["unmatched"] += 1
            print(f"  UNMATCHED {email:42} finished, but no HubSpot contact")
            continue
        outcome, props, note = decide(sl_status, existing)
        counts[outcome] += 1
        label = {"close": "CLOSED  ", "already closed": "CURRENT ",
                 "leave alone": "KEPT    ", "not finished": "SKIP    "}[outcome]
        print(f"  {label} {email:42} {note or f'{FROM_STATUS} -> {TO_STATUS}'}")
        if props:
            print(f"           {writer.write(existing['hs_object_id'], props)}")

    print(f"\n{counts['close']} closed, {counts['already closed']} already current, "
          f"{counts['leave alone']} left alone, {counts['unmatched']} unmatched")
    print(f"{sl.calls} Smartlead calls, {hs_read.calls + writer.calls} HubSpot calls")
    if not a.apply:
        print("DRY RUN: nothing was written.")
    if counts["close"]:
        print(f"Those contacts are contactable again: {TO_STATUS} is not a soft "
              f"exclusion, so a future campaign can enrol them.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # The one transition this job exists to make.
    outcome, props, _ = decide("COMPLETED", {"outbound_status": "in_sequence"})
    check("a finished non-replier closes",
          (outcome, props), ("close", {"outbound_status": "no_response"}))
    check("guarantee 4: suppression untouched", "outbound_suppressed" in props, False)
    check("guarantee 4: native opt-out untouched", "hs_email_optout" in props, False)

    # Guarantee 2: everything else is information this job does not have.
    for status in ("replied", "meeting_booked", "opted_out", "bounced", "disqualified"):
        outcome, props, _ = decide("COMPLETED", {"outbound_status": status})
        check(f"{status} is left alone", (outcome, props), ("leave alone", {}))
    outcome, props, _ = decide("COMPLETED", {})
    check("an empty status is left alone too", (outcome, props), ("leave alone", {}))

    # Guarantee 3: only COMPLETED.
    for st in ("INPROGRESS", "STARTED", "BLOCKED", "PAUSED", ""):
        outcome, props, _ = decide(st, {"outbound_status": "in_sequence"})
        check(f"Smartlead {st or '(empty)'} does not close",
              (outcome, props), ("not finished", {}))

    # Guarantee 5.
    check("already closed is a no-op",
          decide("COMPLETED", {"outbound_status": "no_response"})[:2],
          ("already closed", {}))

    # The BLOCKED case is worth stating: unsubscribed and bounced leads reach COMPLETED
    # in some flows, and they belong to the other two syncs.
    check("BLOCKED never closes, whatever HubSpot says",
          decide("BLOCKED", {"outbound_status": "in_sequence"})[0], "not finished")

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
