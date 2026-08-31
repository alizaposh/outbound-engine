#!/usr/bin/env python3
"""Sync Smartlead unsubscribes into HubSpot as scoped suppressions.

Backlog item "Sync Smartlead unsubscribes to HubSpot", Stage 2 as rewritten by the
cascade policy in config/hubspot-properties.md.

    Smartlead lead.is_unsubscribed -> HubSpot outbound_suppressed + outbound_opt_out_date

**This is not send-safety.** When someone clicks Smartlead's unsubscribe link, Smartlead
suppresses them on its own side immediately and across all future campaigns, with no
action from us. Nobody is at risk of a re-send while this job is not running. What it
fixes is the opt-out reaching HubSpot, which is the authoritative record that reps,
marketing, and the pre-send eligibility gate read.

Six guarantees:

  1. DRY RUN BY DEFAULT. --apply is required to write. In dry run this prints the full
     decision for every unsubscribe, which is what the backlog called Stage 1: verify
     the matching is right before anything is written.
  2. IT NEVER WRITES NATIVE `hs_email_optout`. Scope-matched suppression only, per
     config/hubspot-properties.md: a cold-outbound unsubscribe sets our own scoped,
     reversible flag. The global flag conflates two different consent contexts, is
     effectively irreversible, and is reserved for a human honouring an explicit
     all-email request. HubSpot's Communication Preferences unsubscribe-all endpoint is
     NOT approved for automated use and is not called here.
  3. IT USES THE REAL UNSUBSCRIBE TIMESTAMP, not the time the job happened to run. The
     opt-out date is a compliance record; a late or re-run sync must not restate when
     someone opted out.
  4. THE EARLIEST OPT-OUT DATE WINS. An existing earlier date is never moved later, in
     either direction of comparison. Suppression dates only ever get earlier.
  5. IT IS IDEMPOTENT, which is why it needs no processed-id store. A contact already
     suppressed on or before the unsubscribe date is skipped. Re-running changes nothing
     and re-reading is cheap, so this can run on any schedule without bookkeeping.
  6. AN UNMATCHED EMAIL IS REPORTED, NEVER SILENTLY DROPPED. An unsubscribe Smartlead
     knows about and HubSpot cannot be told about is exactly the case this job exists to
     catch, so it is printed as a distinct outcome and counted in the summary.

Verified against the live API on 2026-08-31 by unsubscribing a throwaway .invalid lead
and reading the record back. Two findings that shaped this:

  - `GET /campaigns/{id}/statistics?email_status=unsubscribed` returns NOTHING after a
    confirmed unsubscribe. The obvious enumeration path does not work.
  - The lead's `status` goes to "BLOCKED", but that is the WRONG signal to use: BLOCKED
    is coarse and also covers bounces, so keying on it would write bounces into HubSpot
    as opt-outs with a false opt-out date. The precise signal is the explicit boolean
    `lead.is_unsubscribed`, with the timestamp in `lead.unsubscribed_client_id_map`.
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
from eligibility import HubSpot, env_token  # noqa: E402
from reply_check import HubSpotWriter, env_value  # noqa: E402

SL_BASE = "https://server.smartlead.ai/api/v1"
READ_PROPS = ["email", "outbound_suppressed", "outbound_opt_out_date", "outbound_status",
              "firstname", "lastname"]


def unsub_timestamp(lead: dict) -> str | None:
    """The earliest unsubscribe time on the lead, as an ISO date.

    Smartlead reports this as `unsubscribed_client_id_map`, a dict of client id to
    timestamp -- observed as {"0": "2026-08-31T18:07:57.976161+00:00"}. Earliest wins
    (guarantee 4), and a lead flagged unsubscribed with no parseable timestamp returns
    None so the caller can decide rather than silently inventing today's date.
    """
    stamps = []
    for v in (lead.get("unsubscribed_client_id_map") or {}).values():
        try:
            stamps.append(dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")))
        except (ValueError, TypeError):
            continue
    return min(stamps).date().isoformat() if stamps else None


def decide(unsub_date: str | None, existing: dict) -> tuple[str, dict, str]:
    """Decide what to do about one unsubscribed lead. Pure, so the rules are testable.

    Returns (outcome, properties to write, human-readable note).
    """
    suppressed = str(existing.get("outbound_suppressed") or "").lower() in ("true", "1")
    held = (existing.get("outbound_opt_out_date") or "")
    held_date = str(held)[:10] if held else None
    status = existing.get("outbound_status") or ""

    # Guarantee 4: the earliest date wins, whichever side it is on.
    date = unsub_date
    if held_date and (not date or held_date < date):
        date = held_date

    # Guarantee 5: nothing to do if already suppressed with a date no later than this.
    if suppressed and held_date and date == held_date:
        return ("already suppressed", {},
                f"suppressed with opt-out date {held_date}; nothing to change")

    props: dict = {"outbound_suppressed": "true"}
    if date:
        props["outbound_opt_out_date"] = date
    note = ""

    # outbound_suppressed is what the eligibility gate reads, so suppression is already
    # fully in force from the line above. That makes the status write purely
    # informational, which is why it yields to a more valuable existing value:
    # overwriting meeting_booked would destroy the record of a booked meeting to restate
    # a suppression the flag above already carries.
    if status == "meeting_booked":
        note = "kept outbound_status=meeting_booked; suppression carried by the flag"
    else:
        props["outbound_status"] = "opted_out"

    if suppressed and held_date and date != held_date:
        note = f"moved opt-out date earlier, {held_date} -> {date}"
    elif not unsub_date:
        note = "Smartlead reported no timestamp; date left as-is rather than invented"
    return ("suppress", props, note)


class Smartlead:
    """Read-only. This job never changes anything in Smartlead."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0

    def get(self, path: str):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(
            f"{SL_BASE}{path}{sep}api_key={self.key}",
            headers={"User-Agent": "outbound-engine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.calls += 1
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"GET {path} -> {e.code}: {(e.read() or b'').decode()[:200]}") from None

    def campaigns(self) -> list[dict]:
        return self.get("/campaigns") or []

    def unsubscribed(self, cid) -> list[dict]:
        """Every lead on this campaign with is_unsubscribed set. Paginated.

        Keyed on the explicit boolean, NOT on status == BLOCKED: see the module
        docstring for why that distinction protects a bounced contact from being
        recorded as an opt-out.
        """
        out, offset = [], 0
        while True:
            d = self.get(f"/campaigns/{cid}/leads?offset={offset}&limit=100")
            rows = d.get("data") or []
            if not rows:
                return out
            for row in rows:
                lead = row.get("lead") or {}
                if lead.get("is_unsubscribed"):
                    out.append(lead)
            offset += len(rows)
            if offset >= int(d.get("total_leads") or 0):
                return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync Smartlead unsubscribes into HubSpot. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE outbound_suppressed / outbound_opt_out_date to HubSpot. "
                         "Without this, nothing is written.")
    ap.add_argument("--campaign", help="one campaign id; default is every campaign")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the date and idempotence rules without any API call")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")
    sl = Smartlead(key)
    print("APPLY: writing scoped suppressions to HubSpot" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")

    campaigns = ([{"id": a.campaign, "name": f"(id {a.campaign})"}] if a.campaign
                 else sl.campaigns())
    if not campaigns:
        print("no campaigns in the account, so there are no unsubscribes to sync yet.")
        return 0

    # email -> (lead, campaign name). Earliest unsubscribe wins if a lead appears on
    # more than one campaign, per guarantee 4.
    found: dict[str, tuple[dict, str]] = {}
    for camp in campaigns:
        leads = sl.unsubscribed(camp.get("id"))
        print(f"campaign {camp.get('id')} {camp.get('name','')!r}: "
              f"{len(leads)} unsubscribed")
        for lead in leads:
            email = (lead.get("email") or "").strip().lower()
            if not email:
                continue
            prev = found.get(email)
            if prev is None or (unsub_timestamp(lead) or "9999") < (
                    unsub_timestamp(prev[0]) or "9999"):
                found[email] = (lead, camp.get("name", ""))

    if not found:
        print("\nno unsubscribes found. Nothing to sync.")
        return 0

    hs_read = HubSpot(env_token())
    writer = HubSpotWriter(env_token(), a.apply)
    contacts = hs_read.search_by_email(sorted(found), READ_PROPS)

    counts = {"suppress": 0, "already suppressed": 0, "unmatched": 0}
    print(f"\n{len(found)} unsubscribed email(s), {len(contacts)} matched in HubSpot\n")
    for email, (lead, camp_name) in sorted(found.items()):
        when = unsub_timestamp(lead)
        existing = contacts.get(email)
        if existing is None:
            counts["unmatched"] += 1
            # Guarantee 6. This is the case the job exists to catch, so it is loud.
            print(f"  UNMATCHED  {email:42} unsubscribed {when or 'date unknown'}")
            print(f"             no HubSpot contact on this email. Suppression cannot "
                  f"be recorded; a human needs to reconcile it.")
            continue
        outcome, props, note = decide(when, existing)
        counts[outcome] += 1
        label = "SUPPRESS " if outcome == "suppress" else "SKIP     "
        print(f"  {label}  {email:42} unsubscribed {when or 'date unknown'}")
        if note:
            print(f"             {note}")
        if props:
            print(f"             {writer.write(existing['hs_object_id'], props)}")

    print(f"\n{counts['suppress']} to suppress, {counts['already suppressed']} already "
          f"current, {counts['unmatched']} unmatched")
    print(f"{sl.calls} Smartlead calls, {hs_read.calls + writer.calls} HubSpot calls")
    if not a.apply:
        print("DRY RUN: nothing was written. Check the matches above, then --apply.")
    if counts["unmatched"]:
        print(f"NOTE: {counts['unmatched']} unsubscribe(s) could not be recorded in "
              "HubSpot. Smartlead is still suppressing them, so no re-send can happen, "
              "but HubSpot does not know. Reconcile these by hand.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    check("timestamp is read out of the client id map",
          unsub_timestamp({"unsubscribed_client_id_map":
                           {"0": "2026-08-31T18:07:57.976161+00:00"}}), "2026-08-31")
    check("earliest of several timestamps wins",
          unsub_timestamp({"unsubscribed_client_id_map":
                           {"0": "2026-08-31T10:00:00+00:00",
                            "1": "2026-03-04T10:00:00+00:00"}}), "2026-03-04")
    check("no timestamp yields None rather than today",
          unsub_timestamp({"unsubscribed_client_id_map": {}}), None)
    check("an unparseable timestamp yields None rather than crashing",
          unsub_timestamp({"unsubscribed_client_id_map": {"0": "last tuesday"}}), None)

    # a fresh suppression
    outcome, props, _ = decide("2026-08-31", {})
    check("a new unsubscribe suppresses", outcome, "suppress")
    check("it writes the real unsubscribe date", props.get("outbound_opt_out_date"),
          "2026-08-31")
    check("it sets the scoped flag", props.get("outbound_suppressed"), "true")
    check("guarantee 2: it never writes the native flag", "hs_email_optout" in props,
          False)
    check("it advances outbound_status", props.get("outbound_status"), "opted_out")

    # guarantee 5, idempotence
    outcome, props, _ = decide("2026-08-31", {"outbound_suppressed": "true",
                                              "outbound_opt_out_date": "2026-08-31"})
    check("re-running changes nothing", (outcome, props), ("already suppressed", {}))

    # Guarantee 4, earliest wins in both directions. Note what "kept" means: when the
    # held date is already the earlier one there is nothing to write, so the correct
    # outcome is the no-op, not a write that restates the same date. Asserting on the
    # properties here is what made these two cases fail the first time -- the code was
    # right and the expectation was wrong.
    outcome, props, _ = decide("2026-08-31", {"outbound_suppressed": "true",
                                              "outbound_opt_out_date": "2026-01-05"})
    check("an existing EARLIER date is kept, by writing nothing",
          (outcome, props), ("already suppressed", {}))
    outcome, props, note = decide("2026-01-05", {"outbound_suppressed": "true",
                                                 "outbound_opt_out_date": "2026-08-31"})
    check("a later held date IS moved earlier", props.get("outbound_opt_out_date"),
          "2026-01-05")
    check("and the move is reported", "moved opt-out date earlier" in note, True)
    outcome, props, _ = decide(None, {"outbound_suppressed": "true",
                                      "outbound_opt_out_date": "2026-01-05"})
    check("no timestamp does not disturb a held date",
          (outcome, props), ("already suppressed", {}))
    _, props, note = decide(None, {})
    check("no timestamp and no held date writes no date at all",
          "outbound_opt_out_date" in props, False)
    check("and says so rather than inventing one", "invented" in note, True)

    # a booked meeting outranks an informational status write
    _, props, note = decide("2026-08-31", {"outbound_status": "meeting_booked"})
    check("meeting_booked is not overwritten", "outbound_status" in props, False)
    check("but suppression still applies", props.get("outbound_suppressed"), "true")
    check("and the choice is explained", "meeting_booked" in note, True)

    # suppressed flag set but no date held: still needs the date written
    _, props, _ = decide("2026-08-31", {"outbound_suppressed": "true"})
    check("a suppressed contact missing its date gets one",
          props.get("outbound_opt_out_date"), "2026-08-31")

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
