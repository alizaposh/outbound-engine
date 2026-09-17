#!/usr/bin/env python3
"""Log engine sends and replies to the HubSpot contact timeline as email engagements.

    Smartlead message history  ->  HubSpot /crm/v3/objects/emails, associated to the contact

**Why this exists, after both vendor paths were ruled out (see
`config/smartlead-defaults.md`).** Smartlead cannot sync HubSpot activity for
API-imported leads, which is every lead this engine sends. HubSpot's BCC-to-CRM only logs
mail from a sender who is a HubSpot seat, and none of the 12 sending mailboxes are seats.
So a rep opening a contact we have mailed sees **no evidence of contact at all** — proven
on campaign 3921033, where 25 sends left every activity field empty. That invites a rep to
mail someone we are mid-sequence with.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required to write anything.
  2. IDEMPOTENT VIA A WATERMARK ON THE CONTACT. `outbound_last_logged_send` holds the
     timestamp of the newest message already logged. Only newer messages are written, so
     re-running never duplicates an engagement. State lives on the contact, not in a local
     store, like everything else here. Clear the property to force a re-log.
  3. THE OWNER IS THE CONTACT'S OWNER, never an invented one. Engine sends land in the
     owning rep's activity feed, which is the point. A contact with no owner gets an
     unowned engagement rather than a fabricated attribution.
  4. DIRECTION IS EXPLICIT AND CHECKED. Our sends log as outgoing, the prospect's replies
     as incoming. Getting this backwards would show a rep that the prospect contacted us,
     which is worse than logging nothing — and is exactly the trap HubSpot's *forwarding*
     address would have created.
  5. IT NEVER CREATES A CONTACT. A Smartlead lead with no HubSpot record is reported and
     skipped. Contact creation is off by standing decision.
  6. IT BACKFILLS. With no watermark, a contact's whole thread is logged, so sends made
     before this existed become visible. That is the one thing BCC could never have done.

**Turn this OFF if Smartlead ever supports HubSpot sync for API-imported leads**, or you
will get every activity twice. `log_sends_enabled` in `config/smartlead-defaults.md`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from create_campaign import load_defaults  # noqa: E402
from eligibility import HubSpot, env_token, env_value  # noqa: E402
from enrich_callbacks import strip_quoted  # noqa: E402

SL_BASE = "https://server.smartlead.ai/api/v1"
READ_PROPS = ["email", "hubspot_owner_id", "outbound_last_logged_send"]
# HubSpot's association type for an email engagement -> contact.
EMAIL_TO_CONTACT = 198

# Guarantee 4. Smartlead's `type` mapped to HubSpot's direction, explicitly, with no
# default: an unrecognised type raises rather than guessing a direction.
DIRECTION = {
    "SENT": "EMAIL",                 # outgoing, from us
    "REPLY": "INCOMING_EMAIL",       # from the prospect
}


def to_millis(ts: str) -> int | None:
    """Smartlead ISO timestamp to HubSpot epoch millis."""
    if not ts:
        return None
    try:
        return int(dt.datetime.fromisoformat(
            str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def newer_than(messages: list[dict], watermark: str | None) -> list[dict]:
    """Messages strictly newer than the watermark, oldest first.

    Guarantee 2. With no watermark every message qualifies, which is what makes the
    backfill fall out of the same code path rather than needing a separate mode.
    """
    cut = to_millis(watermark) if watermark else None
    out = []
    for m in messages:
        ms = to_millis(m.get("time"))
        if ms is None:
            continue
        if cut is None or ms > cut:
            out.append((ms, m))
    return [m for _, m in sorted(out, key=lambda x: x[0])]


def engagement_body(m: dict, contact_id: str, owner: str | None) -> dict:
    """The HubSpot engagement for one Smartlead message."""
    kind = str(m.get("type") or "").upper()
    if kind not in DIRECTION:
        raise RuntimeError(
            f"unrecognised Smartlead message type {kind!r}; refusing to guess a "
            f"direction. Add it to DIRECTION with the correct value — logging an "
            f"outgoing email as incoming tells a rep the prospect contacted us.")
    body = m.get("email_body") or ""
    if kind == "REPLY":
        # The prospect's own words only. A reply quotes our entire message beneath it,
        # and logging that back to the timeline would duplicate our own copy inside
        # their reply.
        body = strip_quoted(body)
    props = {
        "hs_timestamp": to_millis(m.get("time")),
        "hs_email_direction": DIRECTION[kind],
        "hs_email_status": "SENT",
        "hs_email_subject": (m.get("subject") or "")[:250],
        "hs_email_text": body[:60000],
        "hs_email_from_email": m.get("from") or "",
        "hs_email_to_email": m.get("to") or "",
    }
    if owner:
        props["hubspot_owner_id"] = owner       # guarantee 3
    return {"properties": props,
            "associations": [{"to": {"id": contact_id},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                         "associationTypeId": EMAIL_TO_CONTACT}]}]}


class Smartlead:
    """Read-only."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0
        self.retries = 0

    def get(self, path: str, tries: int = 4):
        """One read, retried on a rate limit or a transient server error.

        **Added 2026-09-17, before this job went from one run a day to three.** It costs
        roughly one Smartlead call PER LEAD -- 253 at 247 leads -- so the call volume
        scales with every campaign still ACTIVE, and a 429 previously raised straight out
        of here and failed the whole job. That is the wrong failure for this particular
        job: it is the only thing writing our sends to a HubSpot timeline, so a run lost
        to a rate limit is a day where reps see contacts as untouched.

        Backoff is exponential and deliberately patient rather than tight: nothing here
        is time-critical to the minute, and the point is to finish rather than to finish
        fast. Only 429 and 5xx are retried -- a 404 is a real answer and repeating it
        just wastes the budget.
        """
        sep = "&" if "?" in path else "?"
        for attempt in range(tries):
            req = urllib.request.Request(f"{SL_BASE}{path}{sep}api_key={self.key}",
                                         headers={"User-Agent": "outbound-engine/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    self.calls += 1
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                transient = e.code == 429 or 500 <= e.code < 600
                if not transient or attempt == tries - 1:
                    raise RuntimeError(
                        f"GET {path} -> {e.code}: "
                        f"{(e.read() or b'').decode()[:200]}") from None
                wait = 2 ** attempt
                self.retries += 1
                print(f"    Smartlead {e.code} on {path[:52]}; retrying in {wait}s "
                      f"({attempt + 1}/{tries - 1})")
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == tries - 1:
                    raise RuntimeError(f"GET {path} -> {type(e).__name__}: {e}") from None
                wait = 2 ** attempt
                self.retries += 1
                print(f"    Smartlead {type(e).__name__} on {path[:46]}; retrying in "
                      f"{wait}s ({attempt + 1}/{tries - 1})")
                time.sleep(wait)

    def campaigns(self) -> list[dict]:
        return self.get("/campaigns") or []

    def leads(self, cid) -> list[tuple[str, int]]:
        out, offset = [], 0
        while True:
            d = self.get(f"/campaigns/{cid}/leads?offset={offset}&limit=100")
            rows = d.get("data") or []
            if not rows:
                return out
            for row in rows:
                lead = row.get("lead") or {}
                email = (lead.get("email") or "").strip().lower()
                if email and lead.get("id"):
                    out.append((email, lead["id"]))
            offset += len(rows)
            if offset >= int(d.get("total_leads") or 0):
                return out

    def thread(self, cid, lead_id) -> list[dict]:
        d = self.get(f"/campaigns/{cid}/leads/{lead_id}/message-history"
                     f"?show_plain_text_response=true")
        return d.get("history") or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Log engine sends to HubSpot timelines. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE engagements to HubSpot.")
    ap.add_argument("--campaign", help="one campaign id; default is every campaign")
    ap.add_argument("--limit", type=int, default=0, help="max contacts to process")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the mapping and watermark rules with no API calls")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    cfg = load_defaults()
    if not cfg.get("log_sends_enabled", True):
        print("log_sends_enabled is false in config/smartlead-defaults.md; doing nothing.\n"
              "That switch exists so this can be turned off the day Smartlead supports "
              "HubSpot sync for API-imported leads, rather than double-logging.")
        return 0

    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")
    sl = Smartlead(key)
    tok = env_token()
    hs = HubSpot(tok)
    print("APPLY: writing engagements to HubSpot" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")

    campaigns = ([{"id": a.campaign, "name": f"(id {a.campaign})"}] if a.campaign
                 else sl.campaigns())
    if not campaigns:
        print("no campaigns in the account.")
        return 0

    def hs_call(method, path, body=None):
        req = urllib.request.Request(
            f"https://api.hubapi.com{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}

    logged = skipped = unmatched = current = 0
    for camp in campaigns:
        cid = camp.get("id")
        leads = sl.leads(cid)
        if not leads:
            continue
        contacts = hs.search_by_email([e for e, _ in leads], READ_PROPS)
        print(f"\ncampaign {cid} {camp.get('name','')!r}: {len(leads)} lead(s), "
              f"{len(contacts)} matched in HubSpot")
        for email, lead_id in leads:
            if a.limit and logged >= a.limit:
                break
            c = contacts.get(email)
            if not c:
                unmatched += 1
                print(f"  UNMATCHED {email}: no HubSpot contact, cannot log")
                continue
            msgs = newer_than(sl.thread(cid, lead_id), c.get("outbound_last_logged_send"))
            if not msgs:
                current += 1
                continue
            owner = (c.get("hubspot_owner_id") or "").strip() or None
            kinds = [str(m.get("type") or "?").upper() for m in msgs]
            print(f"  {email}: {len(msgs)} message(s) to log {kinds} "
                  f"owner={owner or '(unowned)'}")
            if not a.apply:
                logged += len(msgs)
                continue
            newest = None
            for m in msgs:
                hs_call("POST", "/crm/v3/objects/emails",
                        engagement_body(m, c["hs_object_id"], owner))
                newest = m.get("time")
                logged += 1
            # Watermark written AFTER the engagements, so a crash mid-contact re-logs
            # rather than silently skipping. A duplicate timeline entry is visible and
            # fixable; a missing one is invisible.
            hs_call("PATCH", f"/crm/v3/objects/contacts/{c['hs_object_id']}",
                    {"properties": {"outbound_last_logged_send": to_millis(newest)}})
            print(f"      logged, watermark -> {newest}")

    print(f"\n{logged} engagement(s) {'written' if a.apply else 'would be written'}, "
          f"{current} contact(s) already current, {unmatched} unmatched")
    # Retries reported, not swallowed. Running three times a day means throttling shows
    # up as a slow job rather than a failed one, and a silently climbing retry count is
    # the signal that the per-lead fetch needs narrowing before the fleet grows again.
    print(f"{sl.calls} Smartlead calls"
          + (f", {sl.retries} retried after a 429/5xx" if sl.retries else ""))
    if not a.apply:
        print("DRY RUN: nothing was written.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # Guarantee 4: direction, the error that would mislead a rep.
    s = engagement_body({"type": "SENT", "time": "2026-09-09T14:00:00Z",
                         "email_body": "our pitch", "subject": "hi",
                         "from": "carl@x.com", "to": "p@y.com"}, "123", "999")
    check("our send is OUTGOING", s["properties"]["hs_email_direction"], "EMAIL")
    check("owner is attached", s["properties"]["hubspot_owner_id"], "999")
    check("associated to the contact",
          s["associations"][0]["to"]["id"], "123")

    r = engagement_body({"type": "REPLY", "time": "2026-09-09T15:00:00Z",
                         "email_body": "interested!\nOn Tue, Sep 1, 2026 at 11:12 AM Carl "
                                       "<c@x.com> wrote:\nour whole pitch quoted back",
                         "subject": "Re: hi", "from": "p@y.com", "to": "carl@x.com"},
                        "123", None)
    check("their reply is INCOMING", r["properties"]["hs_email_direction"],
          "INCOMING_EMAIL")
    check("unowned when the contact has no owner",
          "hubspot_owner_id" in r["properties"], False)
    check("the quoted thread is stripped from a reply",
          "whole pitch quoted back" in r["properties"]["hs_email_text"], False)
    check("the prospect's own words survive",
          "interested!" in r["properties"]["hs_email_text"], True)

    try:
        engagement_body({"type": "WHATEVER", "time": "2026-09-09T15:00:00Z"}, "1", None)
        fails.append("an unknown message type did NOT raise")
    except RuntimeError as e:
        check("the refusal explains the danger", "incoming" in str(e).lower(), True)

    # Guarantee 2: the watermark, and the backfill falling out of it.
    msgs = [{"type": "SENT", "time": "2026-09-01T10:00:00Z"},
            {"type": "REPLY", "time": "2026-09-02T10:00:00Z"},
            {"type": "SENT", "time": "2026-09-03T10:00:00Z"}]
    check("no watermark logs everything (this IS the backfill)",
          len(newer_than(msgs, None)), 3)
    check("a watermark logs only what is newer",
          len(newer_than(msgs, "2026-09-01T10:00:00Z")), 2)
    check("a watermark at the newest logs nothing",
          len(newer_than(msgs, "2026-09-03T10:00:00Z")), 0)
    check("output is oldest first",
          [m["time"] for m in newer_than(msgs, None)],
          ["2026-09-01T10:00:00Z", "2026-09-02T10:00:00Z", "2026-09-03T10:00:00Z"])
    check("a message with no timestamp is skipped, not crashed on",
          len(newer_than([{"type": "SENT", "time": None}], None)), 0)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
