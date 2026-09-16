#!/usr/bin/env python3
"""Apply a mechanical, wording-preserving repair to copy ALREADY in a review tab.

    review tab  ->  repair.split_greeting  ->  same tab, same rows, same words

**Why this exists.** `build_approved` guarantee 2 is that the SHEET is the copy that
ships, so a formatting defect found after export cannot be fixed by patching the
generator — the rows a human is reading and approving are the ones that reach Smartlead.
Regenerating would fix the layout and change the copy, which is not a trade a reviewer
who has already read 558 emails should be asked to make.

**ONLY `split_greeting` IS APPLIED, AND THAT IS A HARD LIMIT.** The full `repair()`
driver is unsafe here: exported bodies already carry their assembled sign-off and CAN-SPAM
footer, and `strip_signoff` exists precisely to remove a sign-off it believes the model
wrote. Running the driver over an exported row would delete the real one. Anything added
to the allowlist below must be provably idempotent on assembled copy.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. **NOT ONE WORD CHANGES.** Asserted per row, not assumed: the repair must leave the
     text identical once whitespace is normalised, or that row is refused and reported.
     This is the whole licence for editing copy a human is mid-review on.
  3. IT WRITES ONLY MESSAGE-BODY CELLS. `Approved`, `Built into`, `Ranking` and
     `Feedback` are a reviewer's own columns and a human's decisions; a formatting pass
     has no business touching them.
  4. IT SKIPS A ROW ALREADY BUILT. A `Built into` stamp means that copy is in a Smartlead
     campaign, so editing the sheet would silently disagree with what is queued to send.
  5. IT NEVER REORDERS OR ADDS ROWS. Writes are per-cell by row number.
  6. IDEMPOTENT. A second run finds nothing, because the repair is a no-op on
     already-correct copy.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import export_review as er  # noqa: E402
import review_queue as rq  # noqa: E402
from build_approved import BUILT_COL, TAB_PATTERN  # noqa: E402
from repair import split_greeting  # noqa: E402

# The allowlist. See the module docstring: adding to this is a correctness decision, not
# a convenience one.
SAFE_REPAIRS = {"greeting_split": split_greeting}
BODY_COLS = ["message_1_body", "message_2_body", "message_3_body"]


def col_letter(idx: int) -> str:
    """0-based column index to an A1 letter."""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def same_words(a: str, b: str) -> bool:
    """Guarantee 2. Whitespace may move; nothing else may."""
    return re.sub(r"\s+", " ", a).strip() == re.sub(r"\s+", " ", b).strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Apply whitespace-only repairs to exported review rows. "
                    "Dry run by default.")
    ap.add_argument("--apply", action="store_true", help="write the corrected cells")
    ap.add_argument("--tab", help="one tab; default is every engine-created tab")
    a = ap.parse_args(argv)

    svc, _ = rq.sheets_service()
    sheet_id = er.load_config()["GENERATION_REVIEW_SHEET_ID"]
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id).execute(
        num_retries=rq.SHEETS_RETRIES)
    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    targets = [a.tab] if a.tab else [t for t in tabs if TAB_PATTERN.match(t)]

    print("APPLY: corrected cells will be written" if a.apply
          else "DRY RUN: nothing written. Re-run with --apply.")
    print(f"repairs applied: {', '.join(sorted(SAFE_REPAIRS))}\n")

    total_fixed = total_built = total_refused = 0
    for tab in targets:
        got = (svc.spreadsheets().values()
               .get(spreadsheetId=sheet_id, range=f"{tab}!A1:AZ")
               .execute(num_retries=rq.SHEETS_RETRIES).get("values") or [])
        if len(got) < 2:
            print(f"  {tab}: empty")
            continue
        hdr = [h.strip() for h in got[0]]
        updates, fixed, built, refused = [], 0, 0, 0
        for n, raw in enumerate(got[1:], start=2):
            row = {h: (raw[i] if i < len(raw) else "") for i, h in enumerate(hdr)}
            if row.get(BUILT_COL, "").strip():
                built += 1                       # guarantee 4
                continue
            for col in BODY_COLS:
                if col not in hdr:
                    continue
                before = row.get(col, "")
                if not before.strip():
                    continue
                after = before
                kinds = []
                for name, fn in SAFE_REPAIRS.items():
                    after, recs = fn(after)
                    kinds += [name] * len(recs)
                if after == before:
                    continue
                if not same_words(before, after):
                    # Guarantee 2. Should be unreachable; refuse rather than trust it.
                    print(f"    REFUSED row {n} {col}: repair changed the wording, not "
                          f"just the spacing. Left untouched.")
                    refused += 1
                    continue
                updates.append({"range": f"{tab}!{col_letter(hdr.index(col))}{n}",
                                "values": [[after]]})
                fixed += 1
                if fixed <= 3:
                    print(f"    row {n} {col}: {before.splitlines()[0][:66]!r}"
                          f"  ({', '.join(sorted(set(kinds)))})")
        note = f", {built} already built (skipped)" if built else ""
        print(f"  {tab}: {fixed} cell(s) to fix{note}"
              + (f", {refused} REFUSED" if refused else ""))
        if updates and a.apply:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={"valueInputOption": "RAW", "data": updates}
            ).execute(num_retries=rq.SHEETS_RETRIES)
            print(f"    wrote {len(updates)} cell(s)")
        total_fixed += fixed
        total_built += built
        total_refused += refused

    print(f"\n{total_fixed} cell(s) {'fixed' if a.apply else 'to fix'}, "
          f"{total_built} row(s) skipped as already built, {total_refused} refused")
    if not a.apply:
        print("DRY RUN: nothing was written.")
    return 1 if total_refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
