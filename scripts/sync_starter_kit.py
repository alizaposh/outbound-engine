#!/usr/bin/env python3
"""Track whether contacts we offered the Starter Kit go on to sign up for a session.

    outbound_starter_kit_offered  +  "Starter Kit" meetings on the contact
        ->  outbound_starter_kit_signed_up      (date of the first session after the offer)
        ->  outbound_starter_kit_session_held   (date of the first such session COMPLETED)

**Why this exists (2026-10-15).** `outbound_starter_kit_offered` counts how often we used
the softer CTA, and "Starter Kit -> meeting" counts a later 1:1 booking. Neither says
whether anyone took the offer itself: came to a session.

**The data, and what it can and cannot say.** The weekly sessions are logged to HubSpot
by Gong as meetings, titled inconsistently ("Posh Starter Kit Session: Go live with
Posh!", "posh starter kit sessions (go live with posh!)", ...), so a title is matched on
"starter kit" in any case. Each meeting is associated with the contacts who SIGNED UP --
a session still in the future already carries its sign-ups. HubSpot does not record who
actually joined; Gong knows, and does not pass it on. So:

  * `signed_up`      -- associated with a Starter Kit session on or after the offer date.
  * `session_held`   -- that session's outcome is COMPLETED. **A proxy for attendance,
                        not confirmed attendance**: they signed up and the session ran.

Decided with Aliza, 2026-10-15, over wiring the Gong API for true attendance.

Five guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. ONLY CONTACTS WE OFFERED. Starts from `outbound_starter_kit_offered`, never from the
     sessions, so a regular Posh host attending is not counted as an outbound win.
  3. ONLY SESSIONS ON OR AFTER THE OFFER. A session before the offer is not ours to claim
     -- the same rule `sync_meetings` applies to a booking that predates enrolment.
  4. CANCELLED SESSIONS NEVER COUNT: outcome CANCELED, or "cancel" in the title (Gong
     renames a cancelled event "... - Meeting Canceled" and leaves the outcome alone).
  5. RECOMPUTED, NOT ACCUMULATED. Both dates are derived fresh each run and written only
     when they differ, so a session cancelled after sign-up clears `signed_up` rather
     than leaving a record of a sign-up that no longer exists.

Runs in the morning heartbeat, after `sync_meetings`. `--setup` creates the two
properties once.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import HubSpot, env_token  # noqa: E402
from reply_check import HubSpotWriter  # noqa: E402

OFFERED = "outbound_starter_kit_offered"
SIGNED_UP = "outbound_starter_kit_signed_up"
HELD = "outbound_starter_kit_session_held"
MEETING_PROPS = ["hs_meeting_title", "hs_meeting_start_time", "hs_meeting_outcome"]

PROPERTY_DEFS = [
    {"name": SIGNED_UP, "label": "Starter Kit Signed Up", "type": "date",
     "fieldType": "date", "groupName": "outbound_engine",
     "description": "Date of the first Posh Starter Kit Session this contact signed up "
                    "for on or after the engine offered it (outbound_starter_kit_offered). "
                    "From the Gong-logged session meetings. Written by "
                    "scripts/sync_starter_kit.py."},
    {"name": HELD, "label": "Starter Kit Session Held", "type": "date",
     "fieldType": "date", "groupName": "outbound_engine",
     "description": "Date of the first Starter Kit session this contact signed up for "
                    "(after our offer) that was marked Completed. A PROXY for attendance: "
                    "HubSpot records sign-ups, not who joined. Written by "
                    "scripts/sync_starter_kit.py."},
]


def is_session(title: str, outcome: str) -> bool:
    """A Starter Kit session that was not cancelled -- guarantee 4."""
    t = (title or "").lower()
    return ("starter kit" in t and "cancel" not in t
            and (outcome or "").upper() != "CANCELED")


def derive(offered: str, meetings: list[dict]) -> dict[str, str]:
    """{SIGNED_UP: date or "", HELD: date or ""}. Pure, so the rules are testable."""
    cut = (offered or "")[:10]
    dates, held = [], []
    for m in meetings:
        start = (m.get("hs_meeting_start_time") or "")[:10]
        if not start or not cut or start < cut:                # guarantee 3
            continue
        if not is_session(m.get("hs_meeting_title"), m.get("hs_meeting_outcome")):
            continue
        dates.append(start)
        if (m.get("hs_meeting_outcome") or "").upper() == "COMPLETED":
            held.append(start)
    return {SIGNED_UP: min(dates) if dates else "", HELD: min(held) if held else ""}


def offered_contacts(hs: HubSpot) -> list[dict]:
    found, after = [], None
    while True:
        body = {"filterGroups": [{"filters": [
                    {"propertyName": OFFERED, "operator": "HAS_PROPERTY"}]}],
                "properties": ["email", OFFERED, SIGNED_UP, HELD], "limit": 100}
        if after:
            body["after"] = after
        d = hs._call("POST", "/crm/v3/objects/contacts/search", body)
        for r in d.get("results") or []:
            found.append({**(r.get("properties") or {}), "hs_object_id": r["id"]})
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return found


def meetings_by_contact(hs: HubSpot, ids: list[str]) -> dict[str, list[dict]]:
    """{contact id: [meeting properties]} in two batched calls per 100 contacts."""
    out: dict[str, list[dict]] = {i: [] for i in ids}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        d = hs._call("POST", "/crm/v4/associations/contacts/meetings/batch/read",
                     {"inputs": [{"id": x} for x in chunk]})
        links = {str(r["from"]["id"]): [str(t["toObjectId"]) for t in r.get("to") or []]
                 for r in d.get("results") or []}
        mids = sorted({m for ms in links.values() for m in ms})
        props: dict[str, dict] = {}
        for j in range(0, len(mids), 100):
            got = hs._call("POST", "/crm/v3/objects/meetings/batch/read",
                           {"inputs": [{"id": x} for x in mids[j:j + 100]],
                            "properties": MEETING_PROPS})
            for r in got.get("results") or []:
                props[r["id"]] = r.get("properties") or {}
        for cid, ms in links.items():
            out[cid] = [props[m] for m in ms if m in props]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Track Starter Kit sign-ups for contacts we offered it. Dry run by "
                    "default.")
    ap.add_argument("--apply", action="store_true", help="WRITE the two dates to HubSpot.")
    ap.add_argument("--setup", action="store_true",
                    help="create the two contact properties (once), then exit")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the matching rules with no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()

    hs = HubSpot(env_token())
    if a.setup:
        for p in PROPERTY_DEFS:
            if hs.property_exists(p["name"]):
                print(f"  exists   {p['name']}")
            elif not a.apply:
                print(f"  WOULD create {p['name']} (re-run with --setup --apply)")
            else:
                hs._call("POST", "/crm/v3/properties/contacts", p)
                print(f"  created  {p['name']}")
        return 0

    missing = [p["name"] for p in PROPERTY_DEFS if not hs.property_exists(p["name"])]
    if missing:
        raise RuntimeError(f"missing HubSpot properties {missing}; run "
                           f"`sync_starter_kit.py --setup --apply` once")

    writer = HubSpotWriter(env_token(), a.apply)
    print("APPLY: writing Starter Kit sign-up dates" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")
    contacts = offered_contacts(hs)
    if not contacts:
        print("\nno contact has been sent the Starter Kit yet. Nothing to do.")
        return 0
    meetings = meetings_by_contact(hs, [c["hs_object_id"] for c in contacts])

    signed = held = changed = 0
    print(f"\n{len(contacts)} contact(s) offered the Starter Kit\n")
    for c in sorted(contacts, key=lambda x: x.get("email") or ""):
        want = derive(c.get(OFFERED, ""), meetings.get(c["hs_object_id"], []))
        signed += bool(want[SIGNED_UP])
        held += bool(want[HELD])
        diff = {k: v for k, v in want.items() if (c.get(k) or "")[:10] != v}
        state = ("HELD    " if want[HELD] else "SIGNED  " if want[SIGNED_UP]
                 else "NOT YET ")
        print(f"  {state} {str(c.get('email'))[:40]:42} offered {(c.get(OFFERED) or '')[:10]}"
              + (f", signed up {want[SIGNED_UP]}" if want[SIGNED_UP] else "")
              + (f", session held {want[HELD]}" if want[HELD] else ""))
        if diff:
            changed += 1
            print(f"           {writer.write(c['hs_object_id'], diff)}")

    print(f"\n{len(contacts)} offered, {signed} signed up, {held} session held, "
          f"{changed} updated")
    if not a.apply:
        print("DRY RUN: nothing was written.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    def m(title, start, outcome="COMPLETED"):
        return {"hs_meeting_title": title, "hs_meeting_start_time": start,
                "hs_meeting_outcome": outcome}

    T = "[Gong] Google Meet: Posh Starter Kit Session: Go live with Posh!"
    check("title variants match in any case",
          [is_session(t, "COMPLETED") for t in
           (T, "[Gong] posh starter kit sessions (go live with posh!)",
            "Mallory and Carl")], [True, True, False])
    check("a title renamed 'Meeting Canceled' never counts",
          is_session("[Gong] posh starter kit sessions - Meeting Canceled", "SCHEDULED"),
          False)
    check("a CANCELED outcome never counts", is_session(T, "CANCELED"), False)
    check("nothing on record -> neither date",
          derive("2026-10-02", []), {SIGNED_UP: "", HELD: ""})
    check("a session BEFORE the offer is not ours",
          derive("2026-10-02", [m(T, "2026-09-29T21:30:00Z")]), {SIGNED_UP: "", HELD: ""})
    check("same-day session counts",
          derive("2026-10-06", [m(T, "2026-10-06T21:30:00Z")]),
          {SIGNED_UP: "2026-10-06", HELD: "2026-10-06"})
    check("signed up for a future session -> signed up, not held",
          derive("2026-10-15", [m(T, "2026-10-20T21:30:00Z", "SCHEDULED")]),
          {SIGNED_UP: "2026-10-20", HELD: ""})
    check("earliest of each, independently",
          derive("2026-10-01", [m(T, "2026-10-20T21:30:00Z", "SCHEDULED"),
                                m(T, "2026-10-06T21:30:00Z", "NO_SHOW"),
                                m(T, "2026-10-13T21:30:00Z")]),
          {SIGNED_UP: "2026-10-06", HELD: "2026-10-13"})
    check("a 1:1 meeting is not a session",
          derive("2026-10-01", [m("Mallory Dawn Spangler and Carl Newmark",
                                  "2026-10-16T19:00:00Z")]), {SIGNED_UP: "", HELD: ""})

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
