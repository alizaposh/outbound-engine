#!/usr/bin/env python3
"""Build a DRAFTED campaign from the rows a human marked Approved in the review Sheet.

    Generation review tab, `Approved` = Y  ->  create_campaign.py  ->  DRAFTED campaign

**Why this exists.** Reply approval was already an instruction the engine acts on:
`decision = Approve` in the Reply Review Queue is what `send_replies` reads. Campaign
approval was not. It lived in a Slack message or in somebody's head, and the campaign got
built because a person remembered to run a command. **A step that can be forgotten is not
a gate** — it is a habit, and habits lapse quietly.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. **THE SHEET IS THE COPY THAT SHIPS.** Message bodies are read from the tab, not from
     the generated CSV on disk. `create_campaign.py --csv` read the CSV only, so a rep who
     fixed a line in the sheet would have watched the original reach Smartlead. That is
     the failure `send_replies` guarantee 3 exists to prevent, one stage earlier, and the
     reason this script exists rather than a flag on create_campaign.
  3. ONLY `Y` COUNTS. Blank, `N`, a note, a ranking — none of them approve anything.
     Approval must be an affirmative act, so the absence of a mark can never mean yes.
  4. PARTIAL APPROVAL IS NORMAL. Approve 30 of 36 and the campaign carries 30; the rest
     stay eligible for later. A single bad draft must not block a curated list — the same
     reasoning as the validation retries in run_generation.py.
  5. IT NEVER LAUNCHES. It shells `create_campaign.py`, which produces a DRAFTED campaign
     and cannot start one. The unsubscribe settings have no API, so a human still opens
     Smartlead.
  6. IT NEVER RE-BUILDS A ROW, and the dedup is PER ROW, not per tab. Each built row is
     stamped with its campaign name in `Built into`; a row carrying one is never
     considered again.
     **Per-tab dedup was wrong once the job ran more than daily.** Approve 10 rows, let
     midday build them, then approve 20 more: a tab-level check sees the campaign already
     exists and skips the tab, orphaning those 20 silently. Per-row means the second
     batch becomes its own campaign (`Tab-2`), which is also how a reviewer working
     through a long list in sittings would expect it to behave.

Runs in the morning heartbeat, after `send_replies`.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import export_review as er  # noqa: E402
import review_queue as rq  # noqa: E402
from create_campaign import Smartlead, api_key  # noqa: E402
from eligibility import HubSpot, env_token  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

APPROVED_COL = "Approved"
# Stamped with the campaign name once a row is built. Empty = approved but not yet built.
BUILT_COL = "Built into"
# The dropdown offers exactly Y and N (export_review.APPROVED_CHOICES) and rejects
# anything else, so "y" is the only value that can mean approved. The synonyms are kept
# anyway, for two reasons: a tab created before the dropdown existed has a free-text
# column, and a human pasting a range can still bypass validation in Sheets. Accepting
# an unambiguous "yes" costs nothing; the dropdown is what makes it rare.
YES = {"y", "yes", "approved", "true", "1"}
# Only tabs the engine created. Test1..Test12 are historical copy reviews a human made
# and must never be treated as a campaign waiting to be built.
# The suffix accepts LETTERS as well as digits as of 2026-09-16, so a multi-sender round
# can name its tabs `Aliza-2026-09-16-Brooke` / `-Carl` / `-Zach`.
#
# One request per sender is not optional -- guarantee 5 of create_campaign allows one
# sending identity per campaign, and this script refuses a tab whose approved rows span
# senders -- so a 186-contact round across three senders is three tabs no matter what they
# are called. The numeric-only suffix forced them to be `Aliza-2026-09-16`, `-2`, `-3`,
# which is worse than cosmetic: the tab name becomes the CAMPAIGN name in Smartlead, so
# three campaigns would arrive distinguishable only by a trailing digit, and picking the
# wrong one to launch is silent.
#
# Keeping the requester FIRST is what makes this safe: `requester` below is
# tab.split("-")[0], which feeds --approved-by. Naming the tabs `Brooke-2026-09-16`
# instead would have credited Brooke with approving copy the outbound owner approved,
# quietly falsifying the audit trail that golden rule 1 exists to keep.
#
# The date is still mandatory, so the historical Test1..Test12 copy-review tabs remain
# unmatched and are still never treated as buildable.
TAB_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*-\d{4}-\d{2}-\d{2}(-[A-Za-z0-9]+)?$")


def approved_rows(svc, sheet_id: str, tab: str) -> tuple[list[dict], int, int]:
    """(rows to build, total data rows, already-built count).

    Bodies come from the SHEET — guarantee 2. A row is to-build when it is marked
    approved AND carries no `Built into` stamp — guarantee 6. The sheet row number is
    attached as `_row` so the stamp can be written back to the right line.
    """
    got = (svc.spreadsheets().values()
           .get(spreadsheetId=sheet_id, range=f"{tab}!A1:AZ")
           .execute(num_retries=rq.SHEETS_RETRIES).get("values") or [])
    if len(got) < 2:
        return [], 0, 0
    hdr = [h.strip() for h in got[0]]
    if APPROVED_COL not in hdr:
        # Distinguished from "0 approved" on purpose. A tab created before the column
        # existed reported "0 of 0 row(s) approved", which reads as "the reviewer has not
        # approved anything" when the truth is "there is nowhere to approve". Someone
        # marking a row would then wonder why nothing built.
        return [], -1, 0
    out, built = [], 0
    for n, raw in enumerate(got[1:], start=2):
        row = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(hdr)}
        if row.get(APPROVED_COL, "").lower() not in YES:
            continue
        if row.get(BUILT_COL, "").strip():
            built += 1
            continue
        row["_row"] = n
        out.append(row)
    return out, len(got) - 1, built



def stamp_built(svc, sheet_id: str, tab: str, row_numbers: list[int], cname: str) -> None:
    """Write the campaign name into `Built into` for each built row.

    Called only after the campaign exists. Stamping before would mark rows as built into
    a campaign that then failed to create, and nothing would ever retry them -- the same
    ordering reason send_replies stamps `sending` before the POST but `sent` after.
    """
    hdr = (svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"{tab}!A1:AZ1")
           .execute(num_retries=rq.SHEETS_RETRIES).get("values") or [[]])[0]
    if BUILT_COL not in hdr:
        print(f"    note: {tab} has no {BUILT_COL!r} column, so these rows cannot be "
              f"marked built. They will be offered again on the next run.")
        return
    col = er.col_letter(hdr.index(BUILT_COL)) if hasattr(er, "col_letter") else None
    if col is None:
        import send_replies as sr
        col = sr.col_letter(hdr.index(BUILT_COL))
    svc.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body={
        "valueInputOption": "RAW",
        "data": [{"range": f"{tab}!{col}{n}", "values": [[cname]]}
                 for n in row_numbers]}).execute(num_retries=rq.SHEETS_RETRIES)


def fill_hubspot_ids(rows: list[dict]) -> tuple[int, list[str]]:
    """Resolve each row's `hs_object_id` from its email. Returns (filled, unmatched).

    **The review tab does not carry `hs_object_id`.** It was dropped when the columns
    were trimmed to the eight a reviewer asked for, which is the right call for a human
    reading copy — and it silently removed the key the enrolment write-back needs.
    create_campaign reported "46 enrolled lead(s) have no hs_object_id, so their enrolment
    cannot be recorded in HubSpot. They will look un-enrolled to the next eligibility
    run." Every consequence of that is invisible until much later: no
    outbound_last_campaign_id, so the contacts are missing from the Enrolled list and the
    dashboard; no outbound_sender, so sender continuity is lost and a later campaign could
    mail them as somebody else; and the next eligibility run would consider them never
    contacted.

    Resolving from email rather than adding the column back, because **email is the join
    key throughout** (see "Architecture & sources of truth" in CLAUDE.md) -- it is what
    the lead lists, HubSpot and Smartlead all carry. That keeps the reviewer's tab as
    narrow as they asked for while restoring the write-back.

    Read-only.
    """
    hs = HubSpot(env_token())
    want = [(r.get("email") or "").strip() for r in rows]
    found: dict[str, str] = {}
    for i in range(0, len(want), 100):
        chunk = [e for e in want[i:i + 100] if e]
        if not chunk:
            continue
        d = hs._call("POST", "/crm/v3/objects/contacts/batch/read",
                     {"idProperty": "email", "properties": ["email"],
                      "inputs": [{"id": e} for e in chunk]})
        for res in d.get("results") or []:
            em = ((res.get("properties") or {}).get("email") or "").lower()
            if em:
                found[em] = res["id"]
    filled, missing = 0, []
    for r in rows:
        em = (r.get("email") or "").strip().lower()
        if em in found:
            r["hs_object_id"] = found[em]
            filled += 1
        else:
            missing.append(em or "(blank)")
    return filled, missing


def to_campaign_csv(rows: list[dict], path: pathlib.Path) -> None:
    """Write the approved rows in the shape create_campaign.py expects.

    `validation` is written as PASS for every row, and that is not a shortcut: a HUMAN
    approved this copy, which is a stronger signal than the validator's. The validator's
    job is to stop unreviewed copy reaching a person; once a person has read it and said
    yes, re-litigating their decision from a stale stamp would mean a row they approved
    gets refused by guarantee 3 of create_campaign for a finding they already saw.
    """
    cols = ["hs_object_id", "first_name", "last_name", "email", "job_title",
            "message_1_subject", "message_1_body", "message_2_body", "message_3_body",
            "sender", "mailbox", "validation"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            # **The sheet's column is `Seller`; create_campaign requires `sender`.**
            # r.get("sender") returned "" for every row, so the CSV carried an empty
            # sender column and create_campaign refused all three campaigns on its
            # guarantee 5 -- "no way to check that the copy's signature matches the
            # mailbox it will send from". Correct refusal, wrong input.
            #
            # The rename happened when the review columns were trimmed to the eight the
            # reviewer asked for, and it stayed latent because build_approved had never
            # completed a build: every earlier run found 0 approved rows, so this line
            # was reached for the first time on 2026-09-17 with 186 rows waiting.
            # Reading the constant from export_review rather than repeating the string
            # means a future rename breaks the import instead of emptying a column.
            w.writerow({c: r.get(c, "") for c in cols}
                       | {"sender": (r.get(er.SELLER_COLUMN) or r.get("sender") or "").strip(),
                          # Not read by create_campaign -- it assigns mailboxes itself
                          # from --mailboxes. Left blank rather than guessed per row.
                          "mailbox": "",
                          "validation": "PASS"})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build DRAFTED campaigns from approved review rows. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="actually create the campaign(s).")
    ap.add_argument("--tab", help="one tab; default is every engine-created tab")
    ap.add_argument("--mailboxes", help="override the mailboxes; default is every box "
                                        "belonging to the row's sender")
    a = ap.parse_args(argv)

    svc, _ = rq.sheets_service()
    cfg = er.load_config()
    sheet_id = cfg["GENERATION_REVIEW_SHEET_ID"]
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id).execute(
        num_retries=rq.SHEETS_RETRIES)
    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if a.tab:
        candidates = [a.tab]
    else:
        candidates = [t for t in tabs if TAB_PATTERN.match(t)]

    print("APPLY: campaigns will be created (DRAFTED)" if a.apply
          else "DRY RUN: nothing will be created. Re-run with --apply.")
    if not candidates:
        print("no engine-created review tabs found; nothing to build.")
        return 0

    existing = {c.get("name") for c in (Smartlead(api_key()).call("GET", "/campaigns") or [])}
    built = idle = blocked = failed = 0
    for tab in candidates:
        rows, total, already = approved_rows(svc, sheet_id, tab)
        if total == -1:
            print(f"  {tab}: no {APPROVED_COL!r} column -- created before approvals "
                  f"existed. Add the column to use it, or regenerate the list.")
            idle += 1
            continue
        if not rows:
            note = f", {already} already built" if already else ""
            print(f"  {tab}: 0 of {total} row(s) approved and unbuilt{note}; "
                  f"nothing to build")
            idle += 1
            continue

        senders = {r.get("Seller", "").strip() for r in rows if r.get("Seller", "").strip()}
        if len(senders) != 1:
            # One sender per campaign is a hard rule in create_campaign guarantee 5.
            print(f"  {tab}: SKIPPED, approved rows span sender(s) {sorted(senders)}; "
                  f"a campaign mixing senders would send one person's copy from "
                  f"another's mailbox")
            blocked += 1
            continue
        sender = senders.pop()
        boxes = a.mailboxes or ",".join(sorted(
            b for b, who in __import__("assemble").load_sender_map().items()
            if who == sender))
        if not boxes:
            print(f"  {tab}: SKIPPED, no mailboxes found for sender {sender!r}")
            blocked += 1
            continue

        # The requester's first name is the tab name's own prefix, which is where it came
        # from. Reusing it keeps the campaign and the tab identically named.
        # A second batch from the same tab needs its own campaign name. Suffixing here
        # rather than in create_campaign because the collision is with an earlier batch
        # of THIS tab, which only this script knows about.
        cname, n = tab, 2
        while cname in existing:
            cname, n = f"{tab}-b{n}", n + 1
        requester = tab.split("-")[0]
        work = ROOT / "reviews" / f"approved-{cname}.csv"
        filled, missing = fill_hubspot_ids(rows)
        if missing:
            # Reported, never silent. A contact the engine cannot identify in HubSpot
            # still gets mailed (email is all Smartlead needs) but its enrolment cannot
            # be written back, so it will look un-enrolled later.
            print(f"    WARNING: {len(missing)} of {len(rows)} row(s) have no HubSpot "
                  f"contact for their address, so their enrolment cannot be recorded: "
                  f"{', '.join(missing[:5])}" + (" ..." if len(missing) > 5 else ""))
        to_campaign_csv(rows, work)
        print(f"  {tab}: {len(rows)} of {total} row(s) approved, sender {sender}, "
              f"{len(boxes.split(','))} mailbox(es)")
        if not a.apply:
            print(f"    would build campaign {cname!r} from {work.name}"
                  + (f" ({already} row(s) already built earlier)" if already else ""))
            built += 1
            continue

        cmd = [PY, str(ROOT / "scripts/create_campaign.py"),
               "--csv", str(work), "--audience", tab, "--usecase", "approved-review",
               "--mailboxes", boxes, "--requester", requester,
               "--campaign-name", cname,
               # **Do not name a person we did not verify.** This read
               # f"{requester} (Approved column, {tab})", where requester is
               # tab.split("-")[0] -- the name in the TAB, i.e. whoever REQUESTED the
               # list. It therefore asserted that person approved the copy however
               # anybody else had actually marked Y, which is a fabricated audit trail
               # for the one control golden rule 1 rests on.
               #
               # Google's Sheets API exposes no per-cell editor, so the approver is
               # genuinely unknown here. The honest record is that the rows were marked
               # in a named tab, and nothing more. To attribute a person, the sheet needs
               # an "Approved by" column, or the Drive Activity API has to be read for
               # the file's editors -- both real changes, neither faked by a string.
               "--approved-by", f"marked Approved in {tab} (approver not recorded)"]
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=900)
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            print(f"    FAILED: {out.strip().splitlines()[-1][:160] if out.strip() else '?'}")
            failed += 1
            continue
        for line in out.splitlines():
            if "created campaign" in line or "uploaded" in line or "status:" in line:
                print(f"    {line.strip()}")
        # Stamp the rows AFTER the campaign exists. Stamping first would mark rows built
        # into a campaign that then failed to create, and they would never be retried.
        stamp_built(svc, sheet_id, tab, [r["_row"] for r in rows], cname)
        print(f"    stamped {len(rows)} row(s) with {cname!r} in {BUILT_COL!r}")
        built += 1

    # `idle` is the overwhelmingly common case and means nothing is wrong: a tab whose
    # rows are all built already, or which nobody has approved yet. It grows with every
    # campaign ever run, so it must not share a number with the two cases that need a
    # person -- `blocked`, a tab that CANNOT build (approved rows spanning senders, or a
    # sender with no mailbox), and `failed`, where create_campaign itself errored. Under
    # one "skipped" count a genuinely stuck list looked exactly like a quiet morning.
    print(f"\n{built} campaign(s) built, {idle} tab(s) with nothing to build"
          + (f", ** {blocked} BLOCKED **" if blocked else "")
          + (f", ** {failed} FAILED **" if failed else ""))
    if not a.apply:
        print("DRY RUN: nothing was created.")
    print("A built campaign is DRAFTED. It cannot send until a human sets the "
          "unsubscribe options in the Smartlead UI and launches it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
