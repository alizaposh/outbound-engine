#!/usr/bin/env python3
"""Set the per-mailbox daily send cap across every Smartlead mailbox.

    --limit N  ->  max_email_per_day = N on all 12 mailboxes

**Why a script rather than twelve clicks.** The cap is the single biggest deliverability
lever the engine has, it will be raised again as the domains age, and a fleet where some
mailboxes carry 30 and others 15 loads one domain harder than the rest for no reason
anybody intended. Doing it uniformly and repeatably is the whole point.

**The field is `max_email_per_day`, not `message_per_day`.** The API REPORTS the value as
`message_per_day` and REJECTS that name on write -- `"message_per_day" is not allowed`.
Found by probing, and worth recording because reading the response and writing it back is
the obvious approach and it does not work.

Five guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. IT SHOWS THE BEFORE AND AFTER PER MAILBOX, and skips any already at the target, so
     a re-run is a no-op rather than twelve redundant writes.
  3. **IT WARNS ABOVE THE DOCUMENTED CEILING.** `CLAUDE.md` golden rule 4 sets ~30/day
     and says to scale by adding mailboxes, never by spiking existing ones. Above 30 this
     says so and still proceeds -- the ceiling is a decision for the person running
     outbound, not for this script, but it must not be crossed silently.
  4. IT VERIFIES BY READING BACK. A 200 from this endpoint is not proof: `message_per_day`
     is re-read after the writes and any mailbox that did not move is reported.
  5. IT NEVER TOUCHES ANYTHING ELSE. One field. Warmup, from-name and signature are not
     ours to change here.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from create_campaign import api_key  # noqa: E402

SL = "https://server.smartlead.ai/api/v1"
# config/smartlead-defaults.md and CLAUDE.md golden rule 4.
DOCUMENTED_CEILING = 30


def accounts(key: str) -> list[dict]:
    req = urllib.request.Request(f"{SL}/email-accounts?limit=200&api_key={key}",
                                 headers={"User-Agent": "outbound-engine/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read() or b"[]")


def set_limit(key: str, account_id: int, limit: int) -> str:
    req = urllib.request.Request(
        f"{SL}/email-accounts/{account_id}?api_key={key}", method="POST",
        data=json.dumps({"max_email_per_day": limit}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "outbound-engine/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return (json.loads(r.read() or b"{}").get("message") or "ok")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {(e.read() or b'').decode()[:200]}") from None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Set the per-mailbox daily send cap. Dry run by default.")
    ap.add_argument("--limit", type=int, required=True,
                    help="emails per mailbox per day")
    ap.add_argument("--apply", action="store_true", help="actually write it")
    ap.add_argument("--mailbox", help="one address; default is every mailbox")
    a = ap.parse_args(argv)
    if a.limit < 1:
        ap.error("--limit must be at least 1")

    key = api_key()
    rows = accounts(key)
    if a.mailbox:
        rows = [r for r in rows if (r.get("from_email") or "").lower()
                == a.mailbox.lower()]
        if not rows:
            print(f"no mailbox matches {a.mailbox!r}")
            return 1

    print("APPLY: writing the new cap" if a.apply
          else "DRY RUN: nothing written. Re-run with --apply.")
    # Guarantee 3.
    if a.limit > DOCUMENTED_CEILING:
        print(f"\n  !! {a.limit} is above the {DOCUMENTED_CEILING}/day ceiling in "
              f"CLAUDE.md golden rule 4, which says to scale by adding mailboxes rather "
              f"than spiking existing ones.\n     Proceeding, because that call belongs "
              f"to whoever runs outbound -- but update the rule if this is the new "
              f"normal, so the docs and the fleet do not disagree.")

    fleet_before = sum(int(r.get("message_per_day") or 0) for r in rows)
    changed, already, failed = 0, 0, 0
    print(f"\n  {len(rows)} mailbox(es), target {a.limit}/day\n")
    for r in sorted(rows, key=lambda x: x.get("from_email") or ""):
        cur = int(r.get("message_per_day") or 0)
        box = r.get("from_email")
        if cur == a.limit:
            print(f"  CURRENT {box:42} already {cur}")
            already += 1
            continue
        if not a.apply:
            print(f"  WOULD   {box:42} {cur} -> {a.limit}")
            changed += 1
            continue
        try:
            set_limit(key, r["id"], a.limit)
            print(f"  SET     {box:42} {cur} -> {a.limit}")
            changed += 1
        except Exception as e:
            print(f"  FAILED  {box:42} {str(e)[:70]}")
            failed += 1

    print(f"\n{changed} {'changed' if a.apply else 'to change'}, {already} already at "
          f"target, {failed} failed")
    if not a.apply:
        print("DRY RUN: nothing was written.")
        return 0

    # Guarantee 4: a 200 is not proof.
    after = accounts(key)
    if a.mailbox:
        after = [r for r in after
                 if (r.get("from_email") or "").lower() == a.mailbox.lower()]

    wrong = [(r.get("from_email"), r.get("message_per_day")) for r in after
             if int(r.get("message_per_day") or 0) != a.limit]
    fleet_after = sum(int(r.get("message_per_day") or 0) for r in after)
    print(f"\nread back: fleet capacity {fleet_before} -> {fleet_after} emails/day "
          f"across {len(after)} mailbox(es)")
    if wrong:
        print(f"  !! {len(wrong)} mailbox(es) did NOT take the new value:")
        for box, v in wrong:
            print(f"     {box} is {v}")
        return 1
    print("  every mailbox verified at the new cap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
