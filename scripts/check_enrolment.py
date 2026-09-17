#!/usr/bin/env python3
"""Is anybody enrolled in two campaigns at once? Read-only audit.

    every lead in every live campaign  ->  any email appearing more than once

**Why this exists.** Three separate layers are supposed to prevent a double enrolment,
and the honest reason for this script is that nobody had ever checked whether they do:

  1. **Smartlead, at upload.** `create_campaign` posts leads with
     `ignore_duplicate_leads_in_other_campaign: True`, so Smartlead itself refuses a lead
     that is already in another campaign and reports the count as
     `already_in_another_campaign`. This is the strongest of the three, because it does
     not depend on any state of ours being correct.
  2. **The eligibility filter.** `outbound_status = in_sequence` is in
     `status_skip_values`, so a contact mid-sequence is excluded before generation.
     Depends on our HubSpot write-back having succeeded.
  3. **`Built into` in the review tab.** Per-row, so an approved row cannot be built
     twice. Depends on the stamp having been written -- and a row built BEFORE that
     column existed is unstamped, which is indistinguishable from unbuilt. That gap
     nearly produced a duplicate campaign on 2026-09-17.

Each layer has a failure path, and they are not independent: 2 and 3 both rely on our own
bookkeeping. So the useful question is not "is a guard configured" but "is anybody
actually in two campaigns", which only Smartlead can answer.

**Smartlead is the source of truth here, not HubSpot.** `outbound_last_campaign_id` holds
the LAST campaign only, so a contact in two campaigns looks identical in HubSpot to a
contact in one. A HubSpot-side check cannot find this class of problem at all.

Read-only. It changes nothing and is safe to run any time.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from create_campaign import api_key  # noqa: E402

SL = "https://server.smartlead.ai/api/v1"
# A lead in a finished campaign is not "enrolled" -- the sequence is over and nothing
# further will send, so the same person appearing in a new campaign is a re-approach
# rather than a collision.
LIVE = ("ACTIVE", "DRAFTED", "PAUSED")


def get(path: str, key: str):
    req = urllib.request.Request(f"{SL}{path}{'&' if '?' in path else '?'}api_key={key}",
                                 headers={"User-Agent": "outbound-engine/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Find contacts enrolled in two campaigns.")
    ap.add_argument("--include-completed", action="store_true",
                    help="count COMPLETED and STOPPED campaigns too. A lead there is "
                         "not receiving anything, so an overlap is a deliberate "
                         "re-approach rather than a collision -- useful to see, but it "
                         "is not the problem this looks for.")
    a = ap.parse_args(argv)
    key = api_key()

    camps = [c for c in (get("/campaigns", key) or [])
             if a.include_completed
             or (c.get("status") or "").upper() in LIVE]
    print(f"{len(camps)} campaign(s) in scope"
          + ("" if a.include_completed else f" (status in {', '.join(LIVE)})") + "\n")

    where: dict[str, list[str]] = collections.defaultdict(list)
    for c in camps:
        cid, name = c["id"], c.get("name") or str(c["id"])
        seen, off = 0, 0
        while True:
            d = get(f"/campaigns/{cid}/leads?offset={off}&limit=100", key)
            rows = d.get("data") or []
            if not rows:
                break
            for row in rows:
                em = ((row.get("lead") or {}).get("email") or "").strip().lower()
                if em:
                    where[em].append(name)
            seen += len(rows)
            off += len(rows)
        print(f"  {cid} {name:38} {(c.get('status') or '').upper():9} {seen} lead(s)")

    dupes = {e: cs for e, cs in where.items() if len(set(cs)) > 1}
    print(f"\n{len(where)} distinct contact(s) across those campaigns")
    if not dupes:
        print("\nNO CONTACT IS IN MORE THAN ONE LIVE CAMPAIGN.")
        print("Smartlead's own upload guard (ignore_duplicate_leads_in_other_campaign) "
              "is\nthe layer that produces this result, and it holds regardless of "
              "whether our\nHubSpot bookkeeping is correct.")
        return 0

    print(f"\n!! {len(dupes)} CONTACT(S) IN MORE THAN ONE LIVE CAMPAIGN:")
    for em, cs in sorted(dupes.items()):
        print(f"   {em:42} {', '.join(sorted(set(cs)))}")
    print("\nWhat to do: pause the lead in the campaign that has sent LEAST, rather than\n"
          "deleting them from either -- deleting a lead loses the reply history the\n"
          "thread is matched on. Then find how they got in twice before enrolling more.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
