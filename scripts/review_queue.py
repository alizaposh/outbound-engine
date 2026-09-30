#!/usr/bin/env python3
"""Reply Review Queue: append one row per reply that needs a human decision.

The write path for the human-review gate in instructions/reply-handling.md. The
reply-check workflow calls append_reply(); everything else here supports that.

Sheet ID and tab come from config/review-surfaces.md, never hardcoded.

Three things this module refuses to do:

  1. WRITE THE HUMAN'S COLUMNS. `decision` and `notes` are left empty on every append.
     A queued row must never arrive pre-decided.
  2. QUEUE A NON-REPLY. out_of_office and automated_reply are dropped -- they must not
     advance the lead (reply-handling.md) and must not consume human attention either.
  3. TOUCH THE HEADER ROW. Appends start at row 2; validation is applied to rows 2+.

Auth trap this module exists to avoid: Google's client libraries auto-read
GOOGLE_APPLICATION_CREDENTIALS, which this project does not set. The path lives in
GOOGLE_SERVICE_ACCOUNT_JSON, so credentials are loaded from there explicitly and
passed in. Relying on the default lookup would either fail with a misleading message
or silently authenticate as some unrelated ambient identity.

This never sends email, never writes to HubSpot, and never processes a real reply.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "review-surfaces.md"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Passed to every Sheets call. googleapiclient retries 5xx and rate-limit responses with
# exponential backoff when given num_retries; the default is 0, meaning no retries.
#
# **This is not defensive padding, it cost a real run.** On 2026-09-10 the 09:45
# heartbeat died on a bare `HttpError 503: The service is currently unavailable` from
# Sheets. It was transient -- the very next job in the same run read the SAME spreadsheet
# successfully seconds later -- but `send_replies` runs once a day, so one blip meant
# every approved reply waited another 24 hours. An unattended daily job must survive the
# ordinary flakiness of the APIs it depends on; a human running it by hand would simply
# have re-run it, and the scheduler has no such instinct.
SHEETS_RETRIES = 5

# Order is the contract with the sheet's header row. Index 11/12 (decision, notes) are
# the human's and are always written empty.
# APPEND-ONLY. DECISION_COL and MSG_ID_COL are positional, so inserting rather than
# appending would silently write the human's decision into the wrong column.
COLUMNS = ["received_at", "contact_name", "email", "company", "campaign", "sent_by",
           "reply_text", "intent", "proposed_action", "draft_response", "review_reason",
           "decision", "notes", "smartlead_message_id", "processed_at",
           # Added 2026-09-02 for scripts/send_replies.py. Two DIFFERENT ids, and the
           # difference matters: smartlead_stats_id identifies the THREAD and is what
           # reply-email-thread requires, while smartlead_message_id is unique per
           # message and is what dedup keys on. Using either for the other's job breaks
           # something quietly.
           "smartlead_stats_id", "sent_at",
           # APPENDED, never inserted. DECISION_COL / MSG_ID_COL / STATS_ID_COL below
           # are positional, and so are the ranges every writer builds from them;
           # inserting a column mid-list silently shifts all of them.
           #
           # `cc` is the reviewer's. Added 2026-09-30 to hand a live thread to a
           # colleague: the draft says "I'm connecting you with Rob", and this is what
           # actually puts Rob on the mail. Comma-separated, and Smartlead's
           # reply-email-thread takes it verbatim.
           "cc"]
HUMAN_COLUMNS = ("decision", "notes", "cc")
DECISION_COL = COLUMNS.index("decision")          # 11 -> column L
MSG_ID_COL = COLUMNS.index("smartlead_message_id")  # 13 -> column N
STATS_ID_COL = COLUMNS.index("smartlead_stats_id")  # 15 -> column P
SENT_AT_COL = COLUMNS.index("sent_at")              # 16 -> column Q
DECISION_CHOICES = ["Approve", "Edit & send", "Suppress", "Do not send", "Reclassify"]

# Intents that are not real replies. Kept in sync with instructions/reply-handling.md.
NEVER_QUEUE = {"out_of_office", "automated_reply"}

# review_reason for intents that need a human. not_interested is special-cased per spec:
# the open question on a decline is whether to suppress, and that is a human's call.
REVIEW_REASONS = {
    "not_interested": "suppress?",
    "interested": "buying signal - confirm draft + booking link",
    "question": "answer needs checking before send",
    "objection": "objection handling needs review",
    "not_now": "confirm recycle date",
    "not_qualified": "confirm structural non-fit before disqualifying",
    "wrong_contact": "replacement contact named - needs vetting",
    "asked_to_stop": "confirm suppression + removal wording",
}


# ---- config -------------------------------------------------------------------

def load_surface_config(path: pathlib.Path = CONFIG) -> dict:
    """Read REPLY_REVIEW_* keys out of the fenced block in review-surfaces.md."""
    if not path.exists():
        raise RuntimeError(f"{path} missing: the sheet ID lives there, not in code")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Reply Review Queue.*?```(.*?)```", text, re.S)
    if not m:
        raise RuntimeError(f"{path}: no fenced config block under 'Reply Review Queue'")
    cfg = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            k, v = line.split(":", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for required in ("REPLY_REVIEW_SHEET_ID", "REPLY_REVIEW_TAB"):
        if not cfg.get(required):
            raise RuntimeError(f"{path}: {required} is missing or empty")
    return cfg


# ---- auth ---------------------------------------------------------------------

def _key_path() -> pathlib.Path:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:                                    # fall back to .env (git-ignored)
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("GOOGLE_SERVICE_ACCOUNT_JSON="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not raw:
        raise RuntimeError(
            "KEY MISSING: GOOGLE_SERVICE_ACCOUNT_JSON is not set (env or .env). "
            "Set it to the service-account JSON key path. Note that the Google "
            "libraries read GOOGLE_APPLICATION_CREDENTIALS instead; this project "
            "deliberately does not use that variable.")
    p = pathlib.Path(raw).expanduser()
    if not p.is_file():
        raise RuntimeError(f"KEY MISSING: GOOGLE_SERVICE_ACCOUNT_JSON points at "
                           f"{p}, which does not exist.")
    return p


def sheets_service():
    """Authenticated Sheets client, credentials passed in explicitly.

    Returns (service, client_email) so callers can name the identity in errors -- the
    'is it shared?' question is unanswerable without knowing who to share it with.
    """
    from google.oauth2 import service_account          # imported late: clearer error
    from googleapiclient.discovery import build         # if the deps are absent

    path = _key_path()
    info = json.loads(path.read_text(encoding="utf-8"))
    if info.get("type") != "service_account":
        raise RuntimeError(f"KEY INVALID: {path} is not a service-account key "
                           f"(type={info.get('type')!r})")
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), \
        info.get("client_email", "(unknown)")


def _explain_http_error(e, sheet_id: str, client_email: str) -> RuntimeError:
    """Turn Google's generic 403/404 into which of the two setup steps is missing."""
    status = getattr(getattr(e, "resp", None), "status", None)
    if status == 403:
        return RuntimeError(
            f"NOT SHARED: the service account can authenticate but cannot open sheet "
            f"{sheet_id}. Share the sheet with {client_email} as Editor. "
            f"(If sharing is already done, check the Sheets API is enabled.)")
    if status == 404:
        return RuntimeError(
            f"SHEET NOT FOUND: no sheet with ID {sheet_id} is visible to "
            f"{client_email}. Check REPLY_REVIEW_SHEET_ID in config/review-surfaces.md, "
            f"and that the sheet is shared with that address.")
    return RuntimeError(f"Sheets API error ({status}): {e}")


# ---- dedup: one seam, so the real store can replace it later -------------------

class ProcessedIdStore:
    """Where 'have we already handled this Smartlead message?' is answered.

    This project has NO local database by design (see CLAUDE.md, "Architecture &
    sources of truth"), so the record of what has been handled lives in a system a human
    can open: the queue Sheet itself. This stays an interface so that record can move --
    to a second tab, or to a HubSpot property -- without touching anything else here.
    """

    def is_processed(self, message_id: str) -> bool:
        raise NotImplementedError

    def mark_processed(self, message_id: str, email: str = "", intent: str = "",
                       note: str = "") -> None:
        raise NotImplementedError


class SheetProcessedIds(ProcessedIdStore):
    """Default: the queue sheet is its own record of what has been queued.

    Reads column N (smartlead_message_id). Durable, needs no schema decision, and
    cannot drift from the sheet a human is looking at.

    Reads the queued ids from the review tab AND the machine-handled ids from a second
    "Handled" tab, because a reply can be dealt with without ever needing a human.

    **The Handled tab was added 2026-09-17, and the note it replaces was wrong in a
    specific way worth keeping.** It read: "a reply dropped as out_of_office /
    automated_reply is never queued and so is invisible here. Harmless while the
    allowlist is empty." The allowlist has nothing to do with those two -- they are
    dropped whatever it contains -- so they were reprocessed on EVERY run, for good.
    Observed live: an automated_reply from afromoone@gmail.com came back as
    "1 reply(s) processed" on three consecutive runs.

    What that cost, in order of seriousness:
      * a Bedrock classification per machine reply PER RUN, forever, growing with every
        campaign. Three heartbeats a day against a year of accumulated auto-responders
        is a bill for re-deciding settled questions.
      * "N reply(s) processed" counted the same reply indefinitely, so the number could
        not be read as activity.
      * the real risk: `out_of_office` writes `outbound_resume_after`, and
        `resume_sequences` clears it and restarts the lead. Once the resume date passes,
        reprocessing the same auto-reply re-writes a date that is now in the past, so the
        lead is resumed again on the next run, and the next -- a restart loop on a
        prospect who sent one away message.
    """

    def __init__(self, service, sheet_id: str, tab: str, handled_tab: str = ""):
        self.service, self.sheet_id, self.tab = service, sheet_id, tab
        self.handled_tab = handled_tab or HANDLED_TAB
        self._cache: set[str] | None = None

    def _column(self, tab: str, col: str) -> set[str]:
        try:
            r = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=f"{tab}!{col}2:{col}").execute(num_retries=SHEETS_RETRIES)
        except Exception:
            return set()          # tab not created yet; created on first write
        return {v[0].strip() for v in r.get("values", []) if v and v[0].strip()}

    def _ids(self) -> set[str]:
        if self._cache is None:
            col = chr(ord("A") + MSG_ID_COL)        # N
            self._cache = (self._column(self.tab, col)
                           | self._column(self.handled_tab, "A"))
        return self._cache

    def is_processed(self, message_id: str) -> bool:
        return message_id.strip() in self._ids()

    def mark_processed(self, message_id: str, email: str = "", intent: str = "",
                       note: str = "") -> None:
        """Record a reply that was handled WITHOUT being queued.

        Appended to the Handled tab so the record is somewhere a human can open, which is
        the same constraint the review tab satisfies (CLAUDE.md: no local database). The
        tab is created on first write rather than assumed.
        """
        mid = message_id.strip()
        if self._cache is not None:
            self._cache.add(mid)                    # keep an in-run batch consistent
        if not mid:
            return
        self._ensure_handled_tab()
        self.service.spreadsheets().values().append(
            spreadsheetId=self.sheet_id, range=f"{self.handled_tab}!A1",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [[mid, email, intent,
                              dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                              note]]}).execute(num_retries=SHEETS_RETRIES)

    def _ensure_handled_tab(self) -> None:
        meta = self.service.spreadsheets().get(
            spreadsheetId=self.sheet_id).execute(num_retries=SHEETS_RETRIES)
        if any(sh["properties"]["title"] == self.handled_tab
               for sh in meta.get("sheets", [])):
            return
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": self.handled_tab}}}]}
        ).execute(num_retries=SHEETS_RETRIES)
        self.service.spreadsheets().values().update(
            spreadsheetId=self.sheet_id, range=f"{self.handled_tab}!A1",
            valueInputOption="RAW",
            body={"values": [["smartlead_message_id", "email", "intent",
                              "handled_at", "note"]]}).execute(num_retries=SHEETS_RETRIES)


class MemoryProcessedIds(ProcessedIdStore):
    """For tests only. Forgets everything on exit, so never use it for a real run."""

    def __init__(self, seed=()):
        self._seen = set(seed)

    def is_processed(self, message_id: str) -> bool:
        return message_id.strip() in self._seen

    def mark_processed(self, message_id: str, email: str = "", intent: str = "",
                       note: str = "") -> None:
        self._seen.add(message_id.strip())


def get_processed_id_store(service, sheet_id: str, tab: str) -> ProcessedIdStore:
    """THE SEAM. Swap this body to move the handled-reply record elsewhere (a Handled
    tab, a HubSpot property) -- no local DB, so it stays somewhere a human can open."""
    return SheetProcessedIds(service, sheet_id, tab)


# Replies handled with no human step -- machine auto-responders, and anything auto-sent
# if the allowlist is ever non-empty. Separate from the review tab so the queue a human
# reads stays a list of decisions they actually have to make.
HANDLED_TAB = "Handled (no review)"


# ---- the append function ------------------------------------------------------

def review_reason_for(intent: str, fallback: str = "needs human review") -> str:
    return REVIEW_REASONS.get(intent, fallback)


def append_reply(reply: dict, service=None, cfg=None, store=None,
                 now: dt.datetime | None = None) -> dict:
    """Append one reply to the review queue. Returns a result dict, never raises on
    a normal skip.

    reply keys (all optional except intent + smartlead_message_id):
      received_at, contact_name, email, company, campaign, sent_by, reply_text,
      intent, proposed_action, draft_response, review_reason, smartlead_message_id,
      smartlead_stats_id

    Result: {"appended": bool, "skipped": reason|None, "row": int|None,
             "message_id": str}
    """
    intent = (reply.get("intent") or "").strip()
    msg_id = (reply.get("smartlead_message_id") or "").strip()

    if not msg_id:
        return {"appended": False, "skipped": "no smartlead_message_id (cannot dedup)",
                "row": None, "message_id": ""}
    if intent in NEVER_QUEUE:
        return {"appended": False, "skipped": f"intent {intent} is not a real reply",
                "row": None, "message_id": msg_id}

    cfg = cfg or load_surface_config()
    sheet_id, tab = cfg["REPLY_REVIEW_SHEET_ID"], cfg["REPLY_REVIEW_TAB"]
    client_email = "(unknown)"
    if service is None:
        service, client_email = sheets_service()
    store = store or get_processed_id_store(service, sheet_id, tab)

    if store.is_processed(msg_id):
        return {"appended": False, "skipped": f"already processed: {msg_id}",
                "row": None, "message_id": msg_id}

    now = now or dt.datetime.now(dt.timezone.utc)
    values = {**reply,
              "received_at": reply.get("received_at") or now.isoformat(timespec="seconds"),
              "review_reason": reply.get("review_reason") or review_reason_for(intent),
              "processed_at": now.isoformat(timespec="seconds")}
    row = ["" if c in HUMAN_COLUMNS else str(values.get(c, "") or "") for c in COLUMNS]

    from googleapiclient.errors import HttpError
    try:
        resp = service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=f"{tab}!A2",
            valueInputOption="RAW",
            # OVERWRITE (the default), NOT insertDataOption=INSERT_ROWS. INSERT_ROWS
            # creates a brand-new row, which does NOT inherit the decision column's
            # data validation -- the appended row would land without its dropdown.
            # OVERWRITE writes into the next already-existing empty row, keeping the
            # validation that was applied to rows 2+. Safe here because the queue is
            # append-only: the rows below the last entry are always empty.
            body={"values": [row]}).execute(num_retries=SHEETS_RETRIES)
    except HttpError as e:
        raise _explain_http_error(e, sheet_id, client_email) from None

    written = (resp.get("updates") or {}).get("updatedRange", "")
    m = re.search(r"!\D+(\d+)", written)
    store.mark_processed(msg_id)
    return {"appended": True, "skipped": None,
            "row": int(m.group(1)) if m else None, "message_id": msg_id}


# ---- one-time sheet setup -----------------------------------------------------

def tab_id(service, sheet_id: str, tab: str) -> int:
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute(num_retries=SHEETS_RETRIES)
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == tab:
            return s["properties"]["sheetId"]
    have = [s["properties"]["title"] for s in meta.get("sheets", [])]
    raise RuntimeError(f"tab {tab!r} not found in sheet {sheet_id}; tabs: {have}")


def set_decision_validation(service, sheet_id: str, tab: str) -> None:
    """Dropdown on the decision column, data rows only, invalid entries rejected."""
    gid = tab_id(service, sheet_id, tab)
    req = {"setDataValidation": {
        "range": {"sheetId": gid, "startRowIndex": 1,          # row 2 onward: never the header
                  "startColumnIndex": DECISION_COL,
                  "endColumnIndex": DECISION_COL + 1},
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": v}
                                          for v in DECISION_CHOICES]},
                 "strict": True,        # reject anything not in the list
                 "showCustomUi": True}}}
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id, body={"requests": [req]}).execute(num_retries=SHEETS_RETRIES)


def delete_row(service, sheet_id: str, tab: str, row: int) -> None:
    """Delete one 1-indexed row. Used to clean up the write-path test."""
    if row < 2:
        raise RuntimeError(f"refusing to delete row {row}: row 1 is the header")
    gid = tab_id(service, sheet_id, tab)
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
        {"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                                       "startIndex": row - 1, "endIndex": row}}}]}).execute(num_retries=SHEETS_RETRIES)


def verify_header(service, sheet_id: str, tab: str) -> list[str]:
    r = service.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"{tab}!A1:O1").execute(num_retries=SHEETS_RETRIES)
    got = [c.strip() for c in (r.get("values") or [[]])[0]]
    if got != COLUMNS:
        raise RuntimeError("HEADER MISMATCH: the sheet's header row does not match the "
                           f"expected 15 columns.\n  sheet:  {got}\n  expected: {COLUMNS}")
    return got


# ---- CLI ----------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reply Review Queue setup and checks.")
    ap.add_argument("--check", action="store_true",
                    help="auth + sheet access + header check, no writes")
    ap.add_argument("--set-validation", action="store_true",
                    help="apply the decision dropdown to rows 2+")
    a = ap.parse_args(argv)

    cfg = load_surface_config()
    sheet_id, tab = cfg["REPLY_REVIEW_SHEET_ID"], cfg["REPLY_REVIEW_TAB"]
    service, client_email = sheets_service()
    print(f"authenticated as {client_email}")
    print(f"sheet {sheet_id}, tab {tab}")

    from googleapiclient.errors import HttpError
    try:
        verify_header(service, sheet_id, tab)
        print("header row: 15 columns, matches the expected contract")
    except HttpError as e:
        raise _explain_http_error(e, sheet_id, client_email) from None

    if a.set_validation:
        set_decision_validation(service, sheet_id, tab)
        print(f"decision dropdown applied to rows 2+: {DECISION_CHOICES} (strict)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
