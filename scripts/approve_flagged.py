#!/usr/bin/env python3
"""Bring already-exported tabs in line with the widened auto-approval rule.

`export_review.AUTO_APPROVE_STATUSES` now covers WARN and the committed fallback, but
the two PriorityLeads tabs were exported under the old rule and carry 232 rows sitting
blank behind a gate that no longer exists. Re-exporting would be the clean way and is
not available: a reviewer may already have touched these tabs, and a re-export would
discard that. So this edits in place, and does exactly three things:

  1. Renames the "Why held" header to "Flags" -- nothing is held any more, and a column
     whose name asserts otherwise is worse than no column.
  2. Sets Approved=Y on rows whose recorded status is now auto-approvable, and ONLY on
     those. A row already marked N by a human is left alone: the widened rule says the
     machine no longer objects, not that a person's objection is overruled.
  3. Personalises the fallback greeting. The 64 fallback rows were exported with
     "Hey there," before the copy was templated; every one of them has a first name in
     the tab, so the greeting is fixed here rather than left to ship nameless.

Dry-run by default; --apply writes.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import backfill_why_held as bf  # noqa: E402  (a1_col)
import export_review as er  # noqa: E402
import review_queue as rq  # noqa: E402

OLD_COLUMN = "Why held"
GREETING = re.compile(r"^Hey there,", re.M)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tab", required=True, action="append",
                    help="review tab to update; repeatable")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    svc, _ = rq.sheets_service()
    sid = er.load_config()["GENERATION_REVIEW_SHEET_ID"]

    for tab in a.tab:
        print(f"\n{tab}")
        grid = svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"'{tab}'").execute(
                num_retries=3).get("values", [])
        if not grid:
            print("  !! empty tab")
            return 1
        header = [h.strip() for h in grid[0]]

        if OLD_COLUMN in header and er.FLAGS_COLUMN not in header:
            i = header.index(OLD_COLUMN)
            print(f"  header {bf.a1_col(i + 1)}1: {OLD_COLUMN!r} -> {er.FLAGS_COLUMN!r}")
            if a.apply:
                svc.spreadsheets().values().update(
                    spreadsheetId=sid, range=f"'{tab}'!{bf.a1_col(i + 1)}1",
                    valueInputOption="RAW",
                    body={"values": [[er.FLAGS_COLUMN]]}).execute(num_retries=3)
            header[i] = er.FLAGS_COLUMN

        i_appr = header.index("Approved")
        i_flags = header.index(er.FLAGS_COLUMN)
        i_first = header.index("first_name")
        i_built = header.index("Built into")
        body_cols = {p: header.index(f"message_{p}_body")
                     for p in (1, 2, 3) if f"message_{p}_body" in header}

        rows = [r + [""] * (len(header) - len(r)) for r in grid[1:]]

        approvals, greetings = {}, {}
        counts = collections.Counter()
        for n, r in enumerate(rows, start=2):
            appr = (r[i_appr] or "").strip().upper()
            flags = (r[i_flags] or "").strip()
            built = (r[i_built] or "").strip()

            if appr == "Y":
                counts["already approved"] += 1
            elif appr == "N":
                # A human said no. The rule change does not reach this.
                counts["left as N (human)"] += 1
            elif built:
                counts["already built -- untouched"] += 1
            elif flags:
                approvals[n] = "Y"
                counts["fallback -> Y" if flags.startswith("fell back")
                       else "length warn -> Y"] += 1
            else:
                counts["blank with no flag -- left"] += 1

            if flags.startswith("fell back"):
                name = (r[i_first] or "").strip() or "there"
                for p, col in body_cols.items():
                    if GREETING.search(r[col] or ""):
                        greetings.setdefault(n, {})[col] = GREETING.sub(
                            f"Hey {name},", r[col])

        for k, v in counts.most_common():
            print(f"    {v:>4}  {k}")
        print(f"    {len(greetings)} fallback rows get a named greeting "
              f"({sum(len(v) for v in greetings.values())} bodies)")

        if not a.apply:
            print("  DRY RUN -- pass --apply to write")
            continue

        data = [{"range": f"'{tab}'!{bf.a1_col(i_appr + 1)}{n}", "values": [[v]]}
                for n, v in approvals.items()]
        data += [{"range": f"'{tab}'!{bf.a1_col(col + 1)}{n}", "values": [[text]]}
                 for n, cols in greetings.items() for col, text in cols.items()]
        for i in range(0, len(data), 500):          # keep each request a sane size
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=sid,
                body={"valueInputOption": "RAW", "data": data[i:i + 500]}
            ).execute(num_retries=3)
        print(f"  wrote {len(approvals)} approvals, "
              f"{sum(len(v) for v in greetings.values())} greeting fixes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
