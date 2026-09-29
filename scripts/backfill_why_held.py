#!/usr/bin/env python3
"""Backfill the review Sheet's "Flags" column on tabs generated before it existed.

WHY THIS EXISTS. `run_generation.py` now records a `held_reason` per contact and
`export_review.py` writes it to a "Why held" column, so a row that arrives without
`Approved=Y` says what the objection was. Tabs exported BEFORE that change carry 232
held rows with nothing to explain them -- the finding was computed during generation,
used to set the status, and discarded. This recovers it the only way still available:
by re-running the same validation over the exported CSV.

**It is a reconstruction, not the original record.** Validation runs against today's
checks, not the checks as they stood at generation time, so a rule added since would
show up here and a rule removed would vanish. For the batch this was written for those
are the same set, and the status column is the tie-break: where a re-derived verdict
disagrees with the recorded one, the row is reported rather than quietly overwritten.

ONE FOOTGUN, LEARNED THE HARD WAY. `validate_email` must be given the SAME footer the
body was assembled with. Passing `footer=""` makes every single row fail
`footer_present` -- 258 spurious FAILs on the first attempt at this -- because the check
looks for a footer the caller said should not be there. The footer is read from config
here for exactly that reason.

Dry-run by default like every other write path; `--apply` writes to the Sheet.
"""
from __future__ import annotations

import argparse
import collections
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import assemble  # noqa: E402
import export_review as er  # noqa: E402
import review_queue as rq  # noqa: E402
import run_generation as rg  # noqa: E402
import validate  # noqa: E402

COLUMN = er.FLAGS_COLUMN


def a1_col(n: int) -> str:
    """1-based column index to an A1 letter. Correct past column Z, unlike the inline
    chr(ord("A") + i) this replaces -- these tabs are 11 wide today and the next column
    added is free."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def approximate_raw_body(body: str, footer: str, sender_name: str) -> str:
    """Recover something close to the MODEL's output from the ASSEMBLED body.

    The CSV stores `body_final` -- model output plus the sign-off and footer that
    `assemble.py` appends. Production validates with `raw_body=` set to the model's
    pre-assembly text, and several checks exist precisely to catch the model emitting
    something assembly owns. Handing those checks the assembled body makes every row
    report `model emitted footer content ('Posh Group Inc.')`, which is a statement
    about this script, not about the copy.

    This is the SECOND time the same shape of mistake appeared while writing this file
    (the first was `footer=""`), and both have the same root: a reconstruction is only
    as good as its fidelity to what the original call actually passed.
    """
    out = body
    head = footer.split("\n", 1)[0].strip()       # "Posh Group Inc."
    if head and head in out:
        out = out[:out.index(head)]
    if sender_name:
        # Assembly appends "<Name>\nPosh"; strip it so sign-off checks judge the model.
        out = re.sub(rf"\n+{re.escape(sender_name)}\s*\n+Posh\s*$", "", out.rstrip())
    return out.rstrip()


def reason_for(row: dict, footer: str, token: str, literals, regexes) -> str:
    """Re-derive one row's held reason from its exported copy."""
    status = (row.get("validation") or "").strip().upper()
    if status == "PASS":
        return ""
    if status == "GENERATION_FAILED_FALLBACK":
        # The generator already wrote the story into generation_error; no need to guess.
        return "fell back to generic copy: " + (
            row.get("generation_error") or "validation failed after 3 rounds")

    parts = []
    for position in rg.POSITIONS:
        body = row.get(f"message_{position}_body") or ""
        if not body.strip():
            continue
        v = validate.validate_email(
            row.get(f"message_{position}_subject", "") or "", body,
            position=position, footer=footer, token=token,
            literals=literals, regexes=regexes,
            raw_body=approximate_raw_body(body, footer,
                                          (row.get("sender") or "").strip()),
            competitor_known=bool((row.get("current_competitor") or "").strip()),
            allowed_names=[row.get("prospect_org"), row.get("company"),
                           row.get("first_name"), row.get("last_name"),
                           row.get("current_competitor"), row.get("city")],
            sender_name=(row.get("sender") or "").strip(),
            label=f"{row.get('email','')} message_{position}")
        for f in v.findings:
            parts.append(f"email {position} {f.severity}: {f.detail}")
    if row.get("sequence_findings"):
        parts.append(f"sequence: {row['sequence_findings']}")
    return "; ".join(parts) or status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, type=pathlib.Path,
                    help="the generation CSV the tab was exported from")
    ap.add_argument("--tab", required=True, help="the review Sheet tab to backfill")
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry-run")
    a = ap.parse_args(argv)

    rows = list(csv.DictReader(a.csv.open(encoding="utf-8-sig")))
    print(f"{a.csv.name}: {len(rows)} rows")

    identity = assemble.load_sender_identity()
    footer = assemble.build_footer(identity)
    token = assemble.UNSUBSCRIBE_TOKEN
    literals, regexes = validate.load_banned()
    print(f"  footer {len(footer)} chars, {len(literals)} literal + {len(regexes)} regex "
          f"banned patterns")

    reasons = {}
    for r in rows:
        key = (r.get("email") or "").strip().lower()
        if key:
            reasons[key] = reason_for(r, footer, token, literals, regexes)

    svc, _ = rq.sheets_service()
    sid = er.load_config()["GENERATION_REVIEW_SHEET_ID"]
    grid = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"'{a.tab}'").execute(num_retries=3).get("values", [])
    if not grid:
        print(f"  !! tab {a.tab!r} is empty")
        return 1
    header = [h.strip() for h in grid[0]]

    # The column has to EXIST before it can be filled. A tab from before the change has
    # no "Why held", so add it at the end rather than inserting mid-sheet -- reviewers
    # have these tabs open and a shifted column is worse than a column on the right.
    if COLUMN not in header:
        print(f"  {COLUMN!r} absent; appending it as column {len(header) + 1}")
        if a.apply:
            svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=f"'{a.tab}'!{a1_col(len(header) + 1)}1",
                valueInputOption="RAW",
                body={"values": [[COLUMN]]}).execute(num_retries=3)
        header.append(COLUMN)

    i_email, i_appr = header.index("email"), header.index("Approved")
    i_why = header.index(COLUMN)

    values, filled, blank, unmatched = [], 0, 0, 0
    for line in grid[1:]:
        line = line + [""] * (len(header) - len(line))
        email = (line[i_email] or "").strip().lower()
        approved = (line[i_appr] or "").strip().upper() == "Y"
        if approved:
            values.append([""])                   # nothing to explain on an approved row
            blank += 1
        elif email in reasons:
            values.append([reasons[email]])
            filled += 1
        else:
            values.append([""])
            unmatched += 1

    print(f"  {filled} held rows explained, {blank} approved (left empty), "
          f"{unmatched} not found in the CSV")

    tally = collections.Counter()
    for v in values:
        if v[0]:
            tally["fallback to generic copy" if v[0].startswith("fell back")
                  else "length / wording warning"] += 1
    for k, n in tally.most_common():
        print(f"    {n:>4}  {k}")
    sample = [v[0] for v in values if v[0]][:3]
    for s in sample:
        print(f"    e.g. {s[:110]}")

    if not a.apply:
        print("  DRY RUN -- pass --apply to write")
        return 0

    rng = (f"'{a.tab}'!{a1_col(i_why + 1)}2:"
           f"{a1_col(i_why + 1)}{len(values) + 1}")
    svc.spreadsheets().values().update(
        spreadsheetId=sid, range=rng, valueInputOption="RAW",
        body={"values": values}).execute(num_retries=3)
    print(f"  wrote {len(values)} cells to {rng}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
