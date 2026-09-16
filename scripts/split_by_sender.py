#!/usr/bin/env python3
"""Partition a HubSpot list into one CSV per sender, honouring existing ownership.

    HubSpot list  ->  carl.csv + brooke.csv + zach.csv  ->  three pipeline runs

**Why this exists.** The intake takes ONE mailbox per submission, because a Smartlead
campaign has one sending identity (`create_campaign` guarantee 5, enforced again by
`build_approved`, which refuses a review tab whose approved rows span senders). Splitting
a list by hand is where a multi-sender round goes wrong: a contact lands in two
submissions and gets two campaigns, or a rep's own account is written to by somebody
else's persona.

**The assignment rule, highest precedence first:**

  1. `outbound_sender` already set -> that sender, always. It is WRITE ONCE
     (`config/hubspot-properties.md`): a prospect who heard from Carl in March must hear
     from Carl in September, because switching persona mid-relationship reads as a boiler
     room and discards the only continuity a cold thread has. This rule is not a
     preference and nothing below may override it.
  2. HubSpot owner is one of the three senders -> that sender. The rep who owns the
     relationship is the one whose name should be on the email; a prospect who knows Zach
     hearing from Brooke is a worse first impression than either alone.
  3. Otherwise -> the sender with the FEWEST contacts so far, ties broken by a fixed
     order.

Rule 3 is least-loaded rather than a strict rotation, and that is deliberate. A strict
round robin over the leftovers is only balanced if rules 1 and 2 left the three senders
even, and they never do -- today all 61 existing assignments are Carl. Rotating on top of
that skew would preserve it, which defeats the point of spreading load across mailboxes.
With equal starting counts least-loaded IS a round robin.

Five guarantees:

  1. DRY RUN BY DEFAULT. `--apply` writes the CSVs.
  2. **STABLE.** Contacts are sorted by email before assignment, so the same list gives
     the same split every time. Re-running must not reassign anyone: `outbound_sender` is
     write-once, so a reshuffle between a dry run and the real run would hand a prospect
     to a second persona.
  3. **NO CONTACT IN TWO FILES.** Asserted before anything is written, because the
     failure it prevents -- two campaigns, two sequences, one prospect -- is invisible
     until the prospect complains.
  4. IT WRITES NOTHING TO HUBSPOT. `outbound_sender` is set by `create_campaign` at
     enrolment, which is the only place that should own it.
  5. NO EMAIL, NO ROW. A contact with no address cannot be mailed and is reported, not
     silently dropped into a file.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import HubSpot, env_token  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# HubSpot owner id -> sender first name, lower case. Read from /crm/v3/owners; kept here
# rather than looked up so the mapping is reviewable and a renamed owner cannot silently
# change who signs an email.
OWNER_TO_SENDER = {
    "89417221": "carl",
    "89417194": "brooke",
    "87936331": "zach",
}
SENDERS = ["carl", "brooke", "zach"]      # also the tie-break order for rule 3
MAILBOX = {"carl": "carl.newmark@vibeposhvip.com",
           "brooke": "brooke.carrobis@vibeposhvip.com",
           "zach": "zach.hickman@vibeposhvip.com"}
READ = ["email", "firstname", "lastname", "outbound_sender", "hubspot_owner_id"]


def list_members(hs: HubSpot, list_id: str) -> list[str]:
    ids, after = [], None
    while True:
        path = f"/crm/v3/lists/{list_id}/memberships?limit=100"
        if after:
            path += f"&after={after}"
        d = hs._call("GET", path)
        ids += [str(r["recordId"]) for r in (d.get("results") or [])]
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return ids


def read_contacts(hs: HubSpot, ids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(ids), 100):
        d = hs._call("POST", "/crm/v3/objects/contacts/batch/read",
                     {"inputs": [{"id": x} for x in ids[i:i + 100]],
                      "properties": READ})
        for r in d.get("results") or []:
            p = dict(r.get("properties") or {})
            p["hs_object_id"] = r["id"]
            out.append(p)
    return out


def assign(contacts: list[dict]) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Apply the three rules. Returns (sender -> rows, reason -> count)."""
    buckets: dict[str, list[dict]] = {s: [] for s in SENDERS}
    why = {"kept (outbound_sender)": 0, "owner is a sender": 0, "least-loaded": 0}
    # Guarantee 2: a fixed order in, a fixed split out.
    for c in sorted(contacts, key=lambda x: (x.get("email") or "").lower()):
        existing = (c.get("outbound_sender") or "").strip().lower()
        if existing in buckets:
            buckets[existing].append(c)
            why["kept (outbound_sender)"] += 1
            continue
        owner = OWNER_TO_SENDER.get(str(c.get("hubspot_owner_id") or "").strip())
        if owner:
            buckets[owner].append(c)
            why["owner is a sender"] += 1
            continue
        # Rule 3. min() over a fixed list is a deterministic tie-break.
        target = min(SENDERS, key=lambda s: (len(buckets[s]), SENDERS.index(s)))
        buckets[target].append(c)
        why["least-loaded"] += 1
    return buckets, why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Split a HubSpot list into one CSV per sender. Dry run by default.")
    # Not `required`, because that would make --self-test unrunnable -- the self-test
    # touches no API and needs no list. Checked below instead.
    ap.add_argument("--list", help="HubSpot list id to split")
    ap.add_argument("--apply", action="store_true", help="write the CSVs")
    ap.add_argument("--out-dir", default=str(ROOT / "data"),
                    help="where the per-sender CSVs go")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the assignment rules with no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.list:
        ap.error("--list is required (or use --self-test)")

    hs = HubSpot(env_token())
    print("APPLY: CSVs will be written" if a.apply
          else "DRY RUN: no files written. Re-run with --apply.")
    ids = list_members(hs, a.list)
    contacts = read_contacts(hs, ids)
    print(f"\nlist {a.list}: {len(ids)} member(s), {len(contacts)} readable")

    # Guarantee 5.
    no_email = [c for c in contacts if not (c.get("email") or "").strip()]
    contacts = [c for c in contacts if (c.get("email") or "").strip()]
    if no_email:
        print(f"  {len(no_email)} contact(s) have NO email and are excluded; "
              f"they cannot be mailed:")
        for c in no_email[:10]:
            print(f"    id {c['hs_object_id']}")

    buckets, why = assign(contacts)

    # Guarantee 3. Asserted, not assumed.
    seen: dict[str, str] = {}
    for s, rows in buckets.items():
        for c in rows:
            e = (c["email"] or "").lower()
            if e in seen:
                raise SystemExit(
                    f"ABORT: {e} is in both {seen[e]} and {s}. Two campaigns would mail "
                    f"one prospect. Nothing written.")
            seen[e] = s

    print("\nassignment reasons:")
    for k, v in why.items():
        print(f"  {v:5}  {k}")
    print("\nsplit:")
    for s in SENDERS:
        print(f"  {len(buckets[s]):5}  {s:7} -> {MAILBOX[s]}")
    print(f"  {sum(len(v) for v in buckets.values()):5}  total")

    out = pathlib.Path(a.out_dir)
    for s in SENDERS:
        rows = buckets[s]
        if not rows:
            print(f"\n  {s}: 0 contacts, no file")
            continue
        path = out / f"split-{a.list}-{s}.csv"
        if not a.apply:
            print(f"\n  would write {len(rows)} row(s) -> {path}")
            continue
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["hs_object_id", "email"])
            for c in rows:
                w.writerow([c["hs_object_id"], c["email"]])
        print(f"\n  wrote {len(rows)} row(s) -> {path}")

    print("\nNext, one run PER SENDER (each becomes its own campaign):")
    for s in SENDERS:
        if buckets[s]:
            print(f"  --leads data/split-{a.list}-{s}.csv  --mailbox {MAILBOX[s]}")
    if not a.apply:
        print("\nDRY RUN: nothing was written.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    def C(email, sender="", owner=""):
        return {"email": email, "outbound_sender": sender,
                "hubspot_owner_id": owner, "hs_object_id": email}

    # Rule 1 beats rule 2: a contact Brooke OWNS but Carl already mailed stays with Carl.
    b, _ = assign([C("a@x.com", sender="carl", owner="89417194")])
    check("rule 1 beats rule 2", [c["email"] for c in b["carl"]], ["a@x.com"])
    check("rule 1 leaves brooke empty", b["brooke"], [])

    # Rule 2: owner mapping.
    b, _ = assign([C("a@x.com", owner="87936331")])
    check("owner zach -> zach", [c["email"] for c in b["zach"]], ["a@x.com"])

    # An owner who is NOT a sender falls through to rule 3.
    b, w = assign([C("a@x.com", owner="99999999")])
    check("unknown owner -> least-loaded", w["least-loaded"], 1)

    # Rule 3 from empty is a round robin.
    b, _ = assign([C(f"{i}@x.com") for i in range(6)])
    check("round robin from empty", [len(b[s]) for s in SENDERS], [2, 2, 2])

    # Rule 3 CORRECTS a skew rather than preserving it -- the whole reason it is
    # least-loaded. 3 pre-owned Carls + 3 free should end 3/2/1... no: free ones go to the
    # emptiest, so brooke and zach fill first.
    rows = [C(f"c{i}@x.com", sender="carl") for i in range(3)] + \
           [C(f"f{i}@x.com") for i in range(3)]
    b, _ = assign(rows)
    check("least-loaded corrects skew", [len(b[s]) for s in SENDERS], [3, 2, 1])

    # Guarantee 2: stability. Input order must not change the split.
    r1, _ = assign(rows)
    r2, _ = assign(list(reversed(rows)))
    check("stable under input order",
          {s: sorted(c["email"] for c in r1[s]) for s in SENDERS},
          {s: sorted(c["email"] for c in r2[s]) for s in SENDERS})

    # Guarantee 3 holds by construction: every contact appends exactly once.
    b, _ = assign([C(f"{i}@x.com") for i in range(30)])
    check("no duplication", sum(len(b[s]) for s in SENDERS), 30)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
