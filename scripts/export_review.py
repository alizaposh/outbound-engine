#!/usr/bin/env python3
"""Push a generation run's CSV to the Generation Review Sheet for the sales team.

The last step of workflow A in CLAUDE.md: drafts are exported so humans can score them,
and their feedback becomes rules in config/ rather than hand-edits to individual emails.

Sheet ID, tab, and the column contract come from config/review-surfaces.md.

Three things this refuses to do:

  1. WRITE THE HUMAN'S COLUMN. `Approved` is left empty on every row, exactly as
     decision/notes are on the reply queue. A row must never arrive pre-approved.
  2. TOUCH THE HEADER ROW. The tab's header is read and treated as authoritative, and
     rows are mapped to it BY NAME. Reviewers edit these sheets, so a positional copy
     against a fixed contract would silently shift every value past the edit.
  3. APPEND TO A TAB THAT ALREADY HAS ROWS, unless --allow-append is passed. One tab per
     run is what makes a before/after copy comparison possible, so silently mixing two
     runs into one tab would destroy the comparison.

Read-only with respect to HubSpot and Smartlead: this only reads a local CSV.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import assemble  # noqa: E402
import review_queue as rq  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "review-surfaces.md"

# The layout this was written against. NOT enforced: the sheet is authoritative and
# rows are mapped by column NAME, read from the tab's own header. Reviewers edit these
# sheets -- the two always-empty message_2_subject / message_3_subject columns were
# deleted by hand once emails 2 and 3 became threaded replies -- and a positional copy
# against a stale contract would have shifted every value right of the change.
SHEET_COLUMNS_REFERENCE = [
    "hs_object_id", "Seller", "first_name", "last_name", "email", "job_title",
    "persona", "persona_basis", "platform_known", "current_competitor",
    "estimated_gmv_usd", "vertical", "validation", "generation_error", "attempts",
    "repairs_applied", "sequence_findings", "bedrock_message_id",
    "message_1_subject", "message_1_body", "message_2_subject", "message_2_body",
    "message_3_subject", "message_3_body",
]
HUMAN_COLUMNS = ("Approved",)

# **AUTO-APPROVAL OF CLEAN ROWS, decided 2026-09-24.** A row the validator scored PASS
# arrives with Approved already set to Y; anything else arrives blank and still needs a
# person. This reverses the old "a row must never arrive pre-approved", and the evidence
# is the reason rather than convenience.
#
# On the 186-contact round the owner read and approved every row. 178 were PASS. But 14
# emails that FAIL today's checks shipped from that batch, plus 33 carrying "Hey There"
# with a capital T -- all human-approved at the time, all caught later by checks written
# afterwards. **Reading 186 emails was not what was catching defects.** The checks were,
# once they existed. Asking a person to read 8,400 would not change that; it would just
# cost more.
#
# What a human is still asked to read is the 4% the machine is unsure about, which is
# where their judgement actually beats a regex.
#
# The residual risk is honest and unfixed: a NOVEL defect class, one no check knows to
# look for, now ships without anyone reading it. Every defect found so far became a
# check, so the exposure shrinks over time -- but it is not zero, and the mitigation is
# to keep auditing shipped copy periodically rather than to assume PASS means perfect.
AUTO_APPROVE_CLEAN = True
# **WIDENED 2026-09-24 to include WARN and the fallback**, by decision of the person
# doing the reviewing, after the first 1,314-contact round put 232 rows behind a gate
# neither of us could justify:
#
#   WARN -- 168 rows. Every finding across all of them, checked exhaustively rather
#   than sampled, was `length`: email 2 a few words under 40, email 1 a median of 6
#   over 75. Length is documented as "a target and never a gate"; holding a row for it
#   contradicted the rulebook. No WARN row carried a claim, banned-phrase or structural
#   finding -- those are FAILs, and a FAIL is retried, never shipped.
#
#   GENERATION_FAILED_FALLBACK -- 64 rows of pre-approved static copy. It is committed,
#   human-written and already reviewed; asking a human to re-approve copy a human wrote
#   is a gate with no reader on the other side.
#
# FAIL still never auto-approves, and an unrecognised status still goes to a person.
AUTO_APPROVE_STATUSES = ("PASS", "WARN", "GENERATION_FAILED_FALLBACK")

# The Approved dropdown. A dropdown rather than a free-text field so the value is always
# one the engine recognises: a typo ("Yes " with a space, "yep", "APPROVE") in a
# write-in column means a row a human believes is approved that build_approved.py will
# silently skip. `strict` rejects anything off the list, so that cannot happen.
#
# "Y" first because it is the default position in the dropdown and the one used most.
APPROVED_CHOICES = ["Y", "N"]
SELLER_COLUMN = "Seller"
FLAGS_COLUMN = "Flags"

# Always empty since emails 2 and 3 became threaded replies (they inherit the thread
# subject and must not invent one). A human deleted these two by hand from the existing
# tabs, so a tab this script CREATES must not reintroduce them -- otherwise every
# generated tab arrives with two dead columns a reviewer then deletes again.
DEAD_COLUMNS = ("message_2_subject", "message_3_subject")

# What a REVIEWER actually needs, and nothing else (2026-09-11, Aliza's call).
#
# A created tab used to carry all 24 reference columns -- persona, persona_basis,
# platform_known, validation, generation_error, attempts, repairs_applied,
# sequence_findings, bedrock_message_id, hs_object_id. Those are engine diagnostics: they
# are how a failure gets debugged, and they are noise to a sales rep scoring copy. A rep
# reading 24 columns to find four is a rep who stops reading.
#
# The diagnostics are NOT lost. Every one stays in the run's CSV under `reviews/`, which
# is the file to open when something needs explaining. The Sheet is the review surface,
# not the archive.
#
# **Ranking (X/5) and Feedback were REMOVED on 2026-09-17**, by decision of the person
# doing the reviewing. They were kept through the earlier column trim on the argument that
# a reviewer needs somewhere to respond -- and after three real rounds neither was ever
# filled in. Feedback arrived as edits to the copy itself and as messages, which is
# richer than a cell and is what actually became rules in config/. Two empty columns on
# every row imply an expectation nobody had.
NEW_TAB_COLUMNS = [
    "Seller", "first_name", "last_name", "email",
    "message_1_subject", "message_1_body", "message_2_body", "message_3_body",
    # `Approved` is the machine-readable trigger: scripts/build_approved.py reads it and
    # builds a DRAFTED campaign from the rows marked Y. Before it existed the approval
    # lived in a Slack message and the campaign got built because someone remembered to
    # run a command -- a step that can be forgotten is not a gate.
    "Approved",
    # What the validator noticed, on every row it noticed anything about -- INCLUDING
    # auto-approved ones. Added when 232 rows sat in front of a reviewer with no stated
    # objection, because the finding existed in the validator and died there.
    #
    # It deliberately survived those rows becoming auto-approved. Approval stopped being
    # the question, but "which of these 1,314 are fallbacks?" is still a question worth
    # being able to answer by sorting a column, and the alternative is re-deriving it
    # from a CSV the way I had to the first time.
    "Flags",
    # Stamped by build_approved.py with the campaign a row was built into. EMPTY means
    # "approved but not yet built", which is what makes per-row dedup possible: a tab
    # can be approved in batches and each batch gets its own campaign, instead of the
    # second batch being silently skipped because the tab already had one.
    "Built into",
]


def load_config(path: pathlib.Path = CONFIG) -> dict:
    """Read GENERATION_REVIEW_* out of the fenced block in review-surfaces.md."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Generation Review.*?```(.*?)```", text, re.S)
    if not m:
        raise RuntimeError(f"{path}: no fenced config block under 'Generation Review'")
    cfg = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            k, v = line.split(":", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for req in ("GENERATION_REVIEW_SHEET_ID", "GENERATION_REVIEW_TAB"):
        if not cfg.get(req):
            raise RuntimeError(f"{path}: {req} is missing or empty")
    return cfg



def set_approved_validation(svc, sheet_id: str, tab: str) -> None:
    """Make the Approved column a strict Y/N dropdown, data rows only.

    Mirrors `review_queue.set_decision_validation`. **`strict` is the point, not the
    dropdown.** A free-text approval column accepts "Yes ", "yep", "APPROVED" and a stray
    space, none of which `build_approved.py` recognises — so a reviewer would mark a row
    approved, watch nothing happen, and have no way to see why. Rejecting the value at
    entry makes that impossible rather than merely unlikely.

    Header row excluded: row 1 is the contract with the exporter and is never validated.
    """
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id).execute(
        num_retries=rq.SHEETS_RETRIES)
    gid = next((s["properties"]["sheetId"] for s in meta["sheets"]
                if s["properties"]["title"] == tab), None)
    if gid is None:
        raise RuntimeError(f"tab {tab!r} not found when setting validation")
    hdr = (svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"{tab}!A1:AZ1")
           .execute(num_retries=rq.SHEETS_RETRIES).get("values") or [[]])[0]
    if "Approved" not in hdr:
        return
    col = hdr.index("Approved")
    svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
        {"setDataValidation": {
            "range": {"sheetId": gid, "startRowIndex": 1,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": v}
                                              for v in APPROVED_CHOICES]},
                     "strict": True,
                     "showCustomUi": True}}}]}
        ).execute(num_retries=rq.SHEETS_RETRIES)


def seller_for(mailbox: str) -> str:
    """Sender first name for the run's mailbox, from config/senders.md.

    An unmapped mailbox is a hard failure here for the same reason assembly aborts on
    one: a blank Seller column makes a reviewer guess who supposedly sent the email.
    """
    smap = assemble.load_sender_map()
    name = smap.get(mailbox.strip().lower())
    if not name:
        raise RuntimeError(
            f"mailbox {mailbox!r} is not in config/senders.md. Known: "
            f"{', '.join(sorted(smap)) or '(none)'}")
    if assemble.is_placeholder_sender(name):
        raise RuntimeError(f"mailbox {mailbox!r} still maps to placeholder {name!r}")
    return name


def to_sheet_row(csv_row: dict, seller: str, header: list[str]) -> list[str]:
    """One row in the order the TAB's header defines, not a fixed contract."""
    out = []
    verdict = str(csv_row.get("validation", "") or "").strip().upper()
    auto = AUTO_APPROVE_CLEAN and verdict in AUTO_APPROVE_STATUSES
    for col in header:
        if col == "Approved":
            # Pre-filled ONLY for a clean row. A reviewer can still change it either
            # way: the sheet is the copy that ships, so un-approving here removes the
            # row from the build exactly as it always did.
            out.append("Y" if auto else "")
        elif col == FLAGS_COLUMN:
            # The sheet's header word differs from the CSV's field name, so this needs
            # its own branch -- the generic fallback below would look up "Why held" in
            # the CSV, miss, and write "" on every row, which is the exact silence this
            # column was added to end.
            out.append(str(csv_row.get("flags", "") or ""))
        elif col in HUMAN_COLUMNS:
            out.append("")                      # the reviewer's, always left empty
        elif col == SELLER_COLUMN:
            out.append(seller)
        else:
            out.append(str(csv_row.get(col, "") or ""))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export a generation CSV to the review Sheet.")
    ap.add_argument("--csv", required=True, type=pathlib.Path,
                    help="output of scripts/run_generation.py")
    ap.add_argument("--mailbox", required=True,
                    help="the mailbox the run generated for; fills the Seller column")
    ap.add_argument("--tab", help="override GENERATION_REVIEW_TAB")
    ap.add_argument("--allow-append", action="store_true",
                    help="write into a tab that already has data rows")
    ap.add_argument("--dry-run", action="store_true",
                    help="map and validate, print what would be written, write nothing")
    a = ap.parse_args(argv)

    cfg = load_config()
    sheet_id = cfg["GENERATION_REVIEW_SHEET_ID"]
    tab = a.tab or cfg["GENERATION_REVIEW_TAB"]
    seller = seller_for(a.mailbox)

    rows = list(csv.DictReader(a.csv.open(encoding="utf-8")))
    if not rows:
        print(f"{a.csv} has no rows", file=sys.stderr)
        return 1

    svc, who = rq.sheets_service()
    print(f"authenticated as {who}")
    print(f"sheet {sheet_id}, tab {tab}, seller {seller!r}")

    from googleapiclient.errors import HttpError

    # CREATE THE TAB IF IT IS MISSING, header included.
    #
    # **This script could not be driven by automation until 2026-09-10.** It assumed the
    # tab already existed, which was true for every hand-run export -- Test1..Test12 were
    # all created by a human first -- and false the moment `slack_intake.run_pipeline`
    # started generating a fresh timestamped tab per request. The first real rep
    # submission failed here with Sheets' unhelpful `Unable to parse range:
    # Intake-1914-...!A1:AZ1`, after eligibility, callbacks and generation had all
    # succeeded. Forty-one contacts' copy was written and then had nowhere to go.
    #
    # The header is written from NEW_TAB_COLUMNS, so a generated tab matches what a
    # human actually maintains -- minus the two dead subject columns. The "never writes a header" rule below still
    # holds for a tab that EXISTS: an empty existing tab is a setup mistake and is still
    # refused, because silently populating a tab someone made for another purpose is
    # worse than stopping.
    titles = set()
    try:
        meta = svc.spreadsheets().get(spreadsheetId=sheet_id).execute(
            num_retries=rq.SHEETS_RETRIES)
        titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
    except HttpError as e:
        raise rq._explain_http_error(e, sheet_id, who) from None

    created = False
    if tab not in titles:
        try:
            svc.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}]}
            ).execute(num_retries=rq.SHEETS_RETRIES)
            svc.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f"{tab}!A1", valueInputOption="RAW",
                body={"values": [list(NEW_TAB_COLUMNS)]}
            ).execute(num_retries=rq.SHEETS_RETRIES)
            created = True
            print(f"created tab {tab!r} with a {len(NEW_TAB_COLUMNS)}-column header")
            set_approved_validation(svc, sheet_id, tab)
            print(f"  Approved column is a {'/'.join(APPROVED_CHOICES)} dropdown "
                  f"(strict: anything else is rejected)")
        except HttpError as e:
            raise rq._explain_http_error(e, sheet_id, who) from None

    try:
        got = svc.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{tab}!A1:AZ1").execute(num_retries=rq.SHEETS_RETRIES).get("values", [[]])
        header = [h.strip() for h in (got[0] if got else [])]
        existing = svc.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{tab}!A2:A").execute(num_retries=rq.SHEETS_RETRIES).get("values", [])
    except HttpError as e:
        raise rq._explain_http_error(e, sheet_id, who) from None

    if not header:
        print(f"ABORT: {tab} exists but has no header row. Create the columns first; "
              f"this never writes a header into a tab someone else made.",
              file=sys.stderr)
        return 2
    # Identity columns: without these a reviewer cannot tell whose email a row is.
    missing_key = [c for c in ("email", "message_1_body") if c not in header]
    if missing_key:
        print(f"ABORT: {tab} is missing essential column(s) {missing_key}.",
              file=sys.stderr)
        return 2
    print(f"header row: {len(header)} columns (mapping by name)")
    unfilled = [c for c in header
                if c not in HUMAN_COLUMNS and c != SELLER_COLUMN and c not in rows[0]]
    dropped = [c for c in rows[0] if c not in header]
    if unfilled:
        print(f"  sheet columns the CSV cannot fill (left empty): {unfilled}")
    if dropped:
        print(f"  CSV columns with no sheet column (not exported): {dropped}")
    for c in SHEET_COLUMNS_REFERENCE:
        if c not in header:
            print(f"  note: reference column {c!r} is absent from this tab")

    if existing and not a.allow_append:
        print(f"\nABORT: {tab} already has {len(existing)} data rows. One tab per run "
              f"keeps runs comparable; point --tab at a fresh tab, or pass "
              f"--allow-append to add to this one.", file=sys.stderr)
        return 2

    payload = [to_sheet_row(r, seller, header) for r in rows]
    print(f"\n{len(payload)} rows mapped to {len(header)} columns "
          f"(Approved left empty for the reviewer)")
    if a.dry_run:
        print("\nDRY RUN: nothing written. First row would be:")
        for col, val in zip(header, payload[0]):
            shown = val if len(val) < 60 else val[:57] + "..."
            print(f"  {col:20} {shown!r}")
        return 0

    resp = svc.spreadsheets().values().append(
        spreadsheetId=sheet_id, range=f"{tab}!A2", valueInputOption="RAW",
        body={"values": payload}).execute(num_retries=rq.SHEETS_RETRIES)
    print(f"wrote {(resp.get('updates') or {}).get('updatedRows')} rows to "
          f"{(resp.get('updates') or {}).get('updatedRange')}")
    print(f"\nhttps://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
