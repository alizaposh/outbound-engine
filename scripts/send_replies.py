#!/usr/bin/env python3
"""Send the replies a human approved in the Reply Review Queue Sheet.

Closes the gap recorded in BACKLOG.md: the queue offered `Approve` and `Edit & send` as
decisions and nothing read that column, so the dropdown implied an automation that did
not exist.

    Sheet row marked Approve/Edit & send  ->  POST /campaigns/{id}/reply-email-thread

**This is the only thing in the repo that sends mail to a prospect**, so read the
guarantees before changing it.

Seven guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required. Nothing leaves the building without it.
  2. A HUMAN DECISION IS THE ONLY TRIGGER. A row sends only if its `decision` cell reads
     `Approve` or `Edit & send`. No intent, score or model output can cause a send. This
     is NOT the `auto_send_intents` allowlist, which is empty and stays empty: that would
     send with no human at all, and it remains a separate deliberate decision.
  3. IT SENDS THE SHEET'S TEXT, READ AT SEND TIME. Not the model's original draft. A
     person who fixes a draft and watches the original go out will never trust the queue
     again.
  4. IDEMPOTENT, AND BIASED TOWARDS NOT SENDING. The row is stamped `sending` BEFORE the
     request and rewritten to `sent` or `FAILED` after. A crash mid-flight therefore
     leaves `sending`, which blocks a retry and asks for a human, because a duplicate
     reply from a supposed person is worse than a missing one.
  5. SUPPRESSION IS RE-CHECKED AT SEND TIME. A reply queued Monday and approved Thursday
     may have opted out in between, and the queue row cannot know that.
  6. ONE REPLY PER THREAD PER RUN, so a sheet edited twice cannot fan out.
  7. IT NEVER WRITES `decision` OR `notes`. Those are the human's columns.

Endpoint contract, probed live 2026-09-02 with an unresolvable id so nothing could send:
`reply-email-thread` requires exactly **`email_stats_id`** and **`email_body`**. The
documented `reply_message_id` / `reply_email_time` fields are not required and are not
what addresses the thread.

**`email_stats_id` is the `stats_id`, NOT the `message_id`.** They are easy to confuse and
each breaks something different: `stats_id` is shared across a whole thread and addresses
it, `message_id` is unique per message and is what dedup keys on. Swapping them either
threads a reply wrong or makes dedup fail open.
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
import review_queue as rq  # noqa: E402
from eligibility import HubSpot, env_token, env_value  # noqa: E402

SL_BASE = "https://server.smartlead.ai/api/v1"
SENDING_DECISIONS = {"approve", "edit & send", "edit and send"}
SUPPRESSION_PROPS = ["email", "outbound_suppressed", "hs_email_optout", "outbound_status"]


def col_letter(i: int) -> str:
    """0-based index to A1 column. Two letters once past Z."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def is_suppressed(props: dict) -> str | None:
    """Reason this contact must not be emailed, or None.

    Mirrors gate 1 of the pre-send filter: the engine's own flag OR HubSpot's native
    opt-out OR a terminal status. Reading only one under-suppresses.
    """
    if str(props.get("outbound_suppressed") or "").lower() in ("true", "1"):
        return "outbound_suppressed is true"
    if str(props.get("hs_email_optout") or "").lower() in ("true", "1"):
        return "hs_email_optout is true (native opt-out)"
    status = (props.get("outbound_status") or "").lower()
    if status in ("opted_out", "bounced"):
        return f"outbound_status is {status}"
    return None


def send_reply(campaign_id: str, stats_id: str, body: str, key: str) -> tuple[bool, str]:
    """POST the reply. Returns (definitely_failed, detail).

    Note the asymmetry: True means we KNOW it did not send. A timeout or an unreadable
    response returns False, meaning "assume it went", because guarantee 4 prefers a
    missing reply over a duplicate one.
    """
    req = urllib.request.Request(
        f"{SL_BASE}/campaigns/{campaign_id}/reply-email-thread?api_key={key}",
        method="POST",
        data=json.dumps({"email_stats_id": stats_id, "email_body": body}).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "outbound-engine/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = (r.read() or b"").decode()[:200]
            return False, f"HTTP {r.status} {payload}"
    except urllib.error.HTTPError as e:
        # A 4xx is a definite refusal: nothing was sent.
        return True, f"HTTP {e.code} {(e.read() or b'').decode()[:200]}"
    except Exception as e:
        # Timeout or transport failure: it MAY have arrived. Treated as sent.
        return False, f"{type(e).__name__}: {e} (ambiguous, treated as sent)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Send replies approved in the review Sheet. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="actually send. Without this, nothing is sent or stamped.")
    ap.add_argument("--limit", type=int, default=0, help="max replies to send")
    ap.add_argument("--row", type=int, help="only this sheet row number")
    a = ap.parse_args(argv)

    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")

    svc, who = rq.sheets_service()
    cfg = rq.load_surface_config()
    sid, tab = cfg["REPLY_REVIEW_SHEET_ID"], cfg["REPLY_REVIEW_TAB"]

    hdr_rng = f"{tab}!A1:{col_letter(len(rq.COLUMNS) - 1)}1"
    hdr = (svc.spreadsheets().values().get(spreadsheetId=sid, range=hdr_rng)
           .execute().get("values") or [[]])[0]
    idx = {h: i for i, h in enumerate(hdr)}
    missing = [c for c in ("decision", "draft_response", "campaign",
                           "smartlead_stats_id", "sent_at", "email") if c not in idx]
    if missing:
        raise RuntimeError(
            f"the queue tab is missing column(s) {missing}. Sending needs them; "
            "re-run the header update rather than guessing positions.")

    rows = (svc.spreadsheets().values()
            .get(spreadsheetId=sid, range=f"{tab}!A2:{col_letter(len(hdr)-1)}")
            .execute().get("values") or [])
    print("APPLY: replies will be SENT" if a.apply
          else "DRY RUN: nothing will be sent or stamped. Re-run with --apply to send.")
    print(f"{len(rows)} row(s) in {tab!r}\n")

    def cell(r, name):
        i = idx[name]
        return (r[i] if i < len(r) else "").strip()

    hs = HubSpot(env_token())
    sent = skipped = failed = capped = 0
    seen_threads: set[str] = set()

    for n, row in enumerate(rows, start=2):
        if a.row and n != a.row:
            continue
        decision = cell(row, "decision").lower()
        email = cell(row, "email")
        if decision not in SENDING_DECISIONS:
            continue
        if cell(row, "sent_at"):
            print(f"  row {n} {email}: already stamped {cell(row,'sent_at')!r}; skipped")
            skipped += 1
            continue
        body = cell(row, "draft_response")
        stats_id = cell(row, "smartlead_stats_id")
        campaign = cell(row, "campaign")
        problems = []
        if not body:
            problems.append("draft_response is empty")
        if not stats_id:
            problems.append("no smartlead_stats_id (queued before it was captured?)")
        if not campaign:
            problems.append("no campaign id")
        if stats_id and stats_id in seen_threads:            # guarantee 6
            problems.append("a reply to this thread was already sent in this run")
        if problems:
            print(f"  row {n} {email}: SKIPPED, {'; '.join(problems)}")
            skipped += 1
            continue

        # The cap sits HERE, below the well-formedness checks and above the send, so a
        # capped row is one that would genuinely have gone out. Counting it rather than
        # breaking out of the loop is the point: `--limit` is what the unattended
        # heartbeat run uses, and a cap that stops quietly would leave approved replies
        # unsent with nothing in the Slack report to say so.
        if a.limit and sent >= a.limit:
            capped += 1
            continue

        # Guarantee 5. The row was written when the reply arrived; consent can change.
        found = hs.search_by_email([email], SUPPRESSION_PROPS) if email else {}
        props = found.get(email.lower(), {})
        if props:
            reason = is_suppressed(props)
            if reason:
                print(f"  row {n} {email}: REFUSING, {reason}. Approved in the sheet, but "
                      "consent changed after it was queued.")
                skipped += 1
                continue
        else:
            print(f"  row {n} {email}: no HubSpot contact, so suppression cannot be "
                  "checked; sending anyway because Smartlead holds the block list too")

        print(f"  row {n} {email}: decision={decision!r} thread={stats_id[:8]}… "
              f"{len(body)} chars")
        print(f"      {body[:110]}{'…' if len(body) > 110 else ''}")
        if not a.apply:
            print("      would stamp 'sending', send, then stamp 'sent'")
            sent += 1
            seen_threads.add(stats_id)
            continue

        stamp_rng = f"{tab}!{col_letter(idx['sent_at'])}{n}"
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        def stamp(value):
            svc.spreadsheets().values().update(
                spreadsheetId=sid, range=stamp_rng, valueInputOption="RAW",
                body={"values": [[value]]}).execute()

        # Guarantee 4: claim the row BEFORE sending. If this process dies mid-request the
        # row reads "sending", which blocks a retry and asks a human to check.
        stamp(f"sending {now}")
        seen_threads.add(stats_id)
        definitely_failed, detail = send_reply(campaign, stats_id, body, key)
        if definitely_failed:
            stamp(f"FAILED {now}: {detail[:80]}")
            print(f"      FAILED (nothing sent): {detail}")
            failed += 1
        else:
            stamp(f"sent {now}")
            print(f"      sent. {detail}")
            sent += 1

    print(f"\n{sent} sent, {skipped} skipped, {failed} failed"
          + (f", {capped} over the cap" if capped else ""))
    if capped:
        print(f"{capped} approved row(s) NOT sent: the --limit {a.limit} cap was reached. "
              "They are untouched and go out on the next run. If that number is a "
              "surprise, check whether the decision column was drag-filled by mistake "
              "BEFORE raising the cap.")
    if not a.apply:
        print("DRY RUN: nothing was sent. Nothing was stamped.")
    if failed:
        print("A FAILED row was NOT sent. Fix the cause, clear its sent_at cell, re-run.")
    print("A row left reading 'sending' means a run died mid-request. Check the thread in "
          "Smartlead before clearing it: the reply may or may not have gone.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
