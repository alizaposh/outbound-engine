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

# Populated by ids_from_csv in --leads mode, so the writer can emit the ORIGINAL row for
# each contact rather than a two-column reduction of it. Empty in --list mode, where
# HubSpot is the only source and id+email is genuinely all there is.
ORIGINAL_ROWS: dict[str, dict] = {}
ORIGINAL_FIELDS: list[str] = []

def senders_and_mailboxes() -> tuple[list[str], dict[str, str]]:
    """(sender names lower-cased, sender -> one mailbox), read from config/senders.md.

    **Derived, never hardcoded.** These were literal lists until 2026-09-17, when the
    owner said they would add the rest of the sales team's mailboxes as outbound grows.
    A hardcoded list fails in the worst available way for that: a rep picks the new name
    in the Slack dropdown, `parse_sender` does not recognise it, and their explicit
    request SILENTLY falls back to a three-way split. Nothing errors and the reply reads
    like a success.

    Adding a mailbox to Smartlead and to config/senders.md is now the whole change on the
    engine side; the Slack dropdown is the only other place a name has to appear.

    One mailbox per sender is enough here -- this only identifies WHOSE copy is written.
    create_campaign receives every mailbox belonging to the sender at build time, which
    build_approved resolves from the same file.
    """
    import assemble
    m = assemble.load_sender_map()                       # mailbox -> "Carl"
    by_sender: dict[str, str] = {}
    for box, who in sorted(m.items()):
        by_sender.setdefault(who.strip().lower(), box)
    return sorted(by_sender), by_sender


def owner_to_sender(hs: "HubSpot", senders: list[str]) -> tuple[dict[str, str], list[str]]:
    """(HubSpot owner id -> sender, senders with no matching owner).

    Resolved at RUNTIME by matching each sender's first name against the Owners API,
    rather than kept as a literal id map. Same reasoning as `excluded_owners` in
    config/pre-send-defaults.md, which says to "resolve by name at runtime so an owner
    change can't go unnoticed" -- and the same failure if it is not: a stale id silently
    stops routing that rep's contacts to them, and the split looks fine.

    A sender with no matching owner is RETURNED, not swallowed. They can still be a
    sender; they just cannot receive contacts by rule 2, and a caller that does not say
    so would leave somebody wondering why their own accounts went to a colleague.
    """
    d = hs._call("GET", "/crm/v3/owners?limit=500")
    out, seen = {}, set()
    for o in d.get("results") or []:
        first = (o.get("firstName") or "").strip().lower()
        if first in senders:
            out[str(o.get("id"))] = first
            seen.add(first)
    return out, [s for s in senders if s not in seen]


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


def ids_from_csv(hs: HubSpot, path: pathlib.Path) -> tuple[list[str], list[str]]:
    """Contact ids from a csv. Prefers hs_object_id; falls back to resolving email.

    eligibility.py carries hs_object_id through, so the fallback is for a hand-made file.
    """
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    # **Keep the whole input row.** The first version of this script wrote only
    # hs_object_id and email, which silently discarded first_name, prospect_org, city,
    # vertical and current_competitor -- every field eligibility.py had just assembled.
    # Generation then saw 46 of 46 contacts as "an email address and no other data at
    # all" and refused the batch on the sparse-share ceiling. That guard is the only
    # reason this was caught before 186 contacts of generation ran on stripped input, and
    # the lesson is the narrow one: a script that PARTITIONS rows must not also reshape
    # them.
    for r in rows:
        key = (r.get("hs_object_id") or "").strip() or (r.get("email") or "").strip().lower()
        if key:
            ORIGINAL_ROWS[key] = dict(r)
    if rows:
        ORIGINAL_FIELDS.extend(k for k in rows[0].keys() if k)
    ids, need_lookup = [], []
    for r in rows:
        cid = (r.get("hs_object_id") or "").strip()
        if cid:
            ids.append(cid)
        elif (r.get("email") or "").strip():
            need_lookup.append(r["email"].strip())
    missing = []
    for i in range(0, len(need_lookup), 100):
        chunk = need_lookup[i:i + 100]
        d = hs._call("POST", "/crm/v3/objects/contacts/batch/read",
                     {"idProperty": "email", "properties": ["email"],
                      "inputs": [{"id": e} for e in chunk]})
        found = {}
        for r in d.get("results") or []:
            found[(r.get("properties") or {}).get("email", "").lower()] = r["id"]
        for e in chunk:
            if e.lower() in found:
                ids.append(found[e.lower()])
            else:
                missing.append(e)
    return ids, missing


def assign(contacts: list[dict], senders: list[str], owner_map: dict[str, str],
           rotate: bool = True) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Apply the three rules. Returns (sender -> rows, reason -> count).

    `rotate=False` makes rule 3 send every unassigned contact to ONE sender instead of
    spreading them. Rules 1 and 2 are untouched either way -- a contact with an existing
    outbound_sender, or owned by a sender, still goes to that person.

    **Why the option exists.** A real request arrived for TWO contacts, a reengagement of
    one churned account, with the sender field left blank so it defaulted to split. Split
    would have produced two campaigns for two contacts, each needing its own unsubscribe
    toggles and its own launch in the Smartlead UI, for no benefit whatever: load
    spreading protects domain reputation, and two emails do not threaten a domain. The
    cost of a campaign is a fixed human cost, so below a floor the right number of
    campaigns is one.
    """
    buckets: dict[str, list[dict]] = {s: [] for s in senders}
    why = {"kept (outbound_sender)": 0, "owner is a sender": 0, "least-loaded": 0}
    _single: str | None = None
    # Guarantee 2: a fixed order in, a fixed split out.
    for c in sorted(contacts, key=lambda x: (x.get("email") or "").lower()):
        existing = (c.get("outbound_sender") or "").strip().lower()
        if existing in buckets:
            buckets[existing].append(c)
            why["kept (outbound_sender)"] += 1
            continue
        owner = owner_map.get(str(c.get("hubspot_owner_id") or "").strip())
        if owner:
            buckets[owner].append(c)
            why["owner is a sender"] += 1
            continue
        # Rule 3. min() over a fixed list is a deterministic tie-break.
        if rotate:
            target = min(senders, key=lambda s: (len(buckets[s]), senders.index(s)))
        else:
            # One sender for the whole remainder. Chosen ONCE, from the state before any
            # of the remainder is placed, so the choice cannot drift mid-list.
            if _single is None:
                _single = min(senders, key=lambda s: (len(buckets[s]), senders.index(s)))
            target = _single
        buckets[target].append(c)
        why["least-loaded"] += 1
    return buckets, why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Split a HubSpot list into one CSV per sender. Dry run by default.")
    # Not `required`, because that would make --self-test unrunnable -- the self-test
    # touches no API and needs no list. Checked below instead.
    ap.add_argument("--list", help="HubSpot list id to split")
    # **Split AFTER eligibility, not before.** Splitting the raw list first looked right
    # and balanced the wrong quantity: exclusions do not land evenly, so a 94/55/55 split
    # of list 1902 became 93/44/40 once the gates ran -- Carl carrying more than twice
    # Brooke or Zach, which is most of the load-spreading the split exists to achieve.
    # Feeding the ELIGIBLE csv here balances contacts that will actually be mailed.
    ap.add_argument("--leads", help="csv with an hs_object_id or email column; use this "
                                    "to split an ELIGIBLE list from eligibility.py")
    ap.add_argument("--apply", action="store_true", help="write the CSVs")
    ap.add_argument("--no-rotate", action="store_true",
                    help="send every unassigned contact to ONE sender instead of "
                         "spreading them. For a list too small to be worth a campaign "
                         "per sender; rules 1 and 2 still apply.")
    ap.add_argument("--out-dir", default=str(ROOT / "data"),
                    help="where the per-sender CSVs go")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the assignment rules with no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.list and not a.leads:
        ap.error("one of --list or --leads is required (or use --self-test)")
    if a.list and a.leads:
        ap.error("--list and --leads are alternatives; pass one")

    hs = HubSpot(env_token())
    SENDERS, MAILBOX = senders_and_mailboxes()
    owner_map, no_owner = owner_to_sender(hs, SENDERS)
    print("APPLY: CSVs will be written" if a.apply
          else "DRY RUN: no files written. Re-run with --apply.")
    print(f"senders from config/senders.md: {', '.join(SENDERS)}")
    if no_owner:
        # Reported, not swallowed: these senders can still SEND, they just cannot
        # receive contacts by rule 2, so their own accounts would route elsewhere.
        print(f"  note: no HubSpot owner matches {', '.join(no_owner)}, so rule 2 "
              f"(owner keeps their contacts) cannot apply to them")
    if a.leads:
        ids, missing = ids_from_csv(hs, pathlib.Path(a.leads))
        label = f"csv {pathlib.Path(a.leads).name}"
        if missing:
            print(f"\n  {len(missing)} row(s) had no resolvable contact id and are "
                  f"excluded: {', '.join(missing[:5])}"
                  + (" ..." if len(missing) > 5 else ""))
    else:
        ids = list_members(hs, a.list)
        label = f"list {a.list}"
    contacts = read_contacts(hs, ids)
    print(f"\n{label}: {len(ids)} member(s), {len(contacts)} readable")

    # Guarantee 5.
    no_email = [c for c in contacts if not (c.get("email") or "").strip()]
    contacts = [c for c in contacts if (c.get("email") or "").strip()]
    if no_email:
        print(f"  {len(no_email)} contact(s) have NO email and are excluded; "
              f"they cannot be mailed:")
        for c in no_email[:10]:
            print(f"    id {c['hs_object_id']}")

    buckets, why = assign(contacts, SENDERS, owner_map, rotate=not a.no_rotate)
    if a.no_rotate:
        print("  --no-rotate: unassigned contacts all go to one sender")

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
        stem = a.list or pathlib.Path(a.leads).stem
        path = out / f"split-{stem}-{s}.csv"
        if not a.apply:
            print(f"\n  would write {len(rows)} row(s) -> {path}")
            continue
        if ORIGINAL_FIELDS:
            # --leads: write back exactly the columns that came in.
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=ORIGINAL_FIELDS)
                w.writeheader()
                for c in rows:
                    orig = (ORIGINAL_ROWS.get(c["hs_object_id"])
                            or ORIGINAL_ROWS.get((c.get("email") or "").lower()))
                    if orig is None:
                        raise SystemExit(
                            f"ABORT: no input row for {c.get('email')!r}; refusing to "
                            f"write a partial file.")
                    w.writerow({k: orig.get(k, "") for k in ORIGINAL_FIELDS})
        else:
            # --list: HubSpot membership gives ids and addresses; eligibility enriches.
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["hs_object_id", "email"])
                for c in rows:
                    w.writerow([c["hs_object_id"], c["email"]])
        print(f"\n  wrote {len(rows)} row(s) -> {path}")

    print("\nNext, one run PER SENDER (each becomes its own campaign):")
    for s in SENDERS:
        if buckets[s]:
            stem = a.list or pathlib.Path(a.leads).stem
            print(f"  --leads data/split-{stem}-{s}.csv  --mailbox {MAILBOX[s]}")
    if not a.apply:
        print("\nDRY RUN: nothing was written.")
    return 0


def _self_test() -> int:
    fails = []
    # Fixed locally so the pure cases stay pure -- no senders.md read, no Owners call.
    SENDERS = ["carl", "brooke", "zach"]
    OWNERS = {"89417221": "carl", "89417194": "brooke", "87936331": "zach"}

    def assign_(rows):
        return assign(rows, SENDERS, OWNERS)

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    def C(email, sender="", owner=""):
        return {"email": email, "outbound_sender": sender,
                "hubspot_owner_id": owner, "hs_object_id": email}

    # Rule 1 beats rule 2: a contact Brooke OWNS but Carl already mailed stays with Carl.
    b, _ = assign_([C("a@x.com", sender="carl", owner="89417194")])
    check("rule 1 beats rule 2", [c["email"] for c in b["carl"]], ["a@x.com"])
    check("rule 1 leaves brooke empty", b["brooke"], [])

    # Rule 2: owner mapping.
    b, _ = assign_([C("a@x.com", owner="87936331")])
    check("owner zach -> zach", [c["email"] for c in b["zach"]], ["a@x.com"])

    # An owner who is NOT a sender falls through to rule 3.
    b, w = assign_([C("a@x.com", owner="99999999")])
    check("unknown owner -> least-loaded", w["least-loaded"], 1)

    # Rule 3 from empty is a round robin.
    b, _ = assign_([C(f"{i}@x.com") for i in range(6)])
    check("round robin from empty", [len(b[s]) for s in SENDERS], [2, 2, 2])

    # Rule 3 CORRECTS a skew rather than preserving it -- the whole reason it is
    # least-loaded. 3 pre-owned Carls + 3 free should end 3/2/1... no: free ones go to the
    # emptiest, so brooke and zach fill first.
    rows = [C(f"c{i}@x.com", sender="carl") for i in range(3)] + \
           [C(f"f{i}@x.com") for i in range(3)]
    b, _ = assign_(rows)
    check("least-loaded corrects skew", [len(b[s]) for s in SENDERS], [3, 2, 1])

    # Guarantee 2: stability. Input order must not change the split.
    r1, _ = assign_(rows)
    r2, _ = assign_(list(reversed(rows)))
    check("stable under input order",
          {s: sorted(c["email"] for c in r1[s]) for s in SENDERS},
          {s: sorted(c["email"] for c in r2[s]) for s in SENDERS})

    # Guarantee 3 holds by construction: every contact appends exactly once.
    b, _ = assign_([C(f"{i}@x.com") for i in range(30)])
    check("no duplication", sum(len(b[s]) for s in SENDERS), 30)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
