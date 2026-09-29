#!/usr/bin/env python3
"""Lifecycle-stage promotion, with the two rules this portal actually enforces.

**THE LABELS DO NOT MATCH THE INTERNAL VALUES IN THIS PORTAL.** `customer` is displayed
as *Outreached* and `opportunity` as *Qualified*. Reading code that writes `customer`
and assuming it marks somebody a paying customer is wrong here, and so is the reverse:
anything outside HubSpot that interprets `lifecyclestage == customer` literally will
miscount 17,891 contacts. Always go through STAGES below rather than a literal.

**HUBSPOT SILENTLY REFUSES A BACKWARD `lifecyclestage` WRITE.** A PATCH to a lower
displayOrder returns HTTP 200, and the response body itself carries the OLD value. The
property history records nothing -- so it is rejected at write time, not reverted
afterwards by a workflow. There is no error to catch, which is why every write here is
READ BACK and why `apply_stage` reports a refusal instead of assuming.

**It is not the "Restrict contacts from moving backwards" setting** -- that governs
pipeline stages and UI actions, and was OFF throughout the investigation on 2026-09-29.
This is platform behaviour specific to `lifecyclestage`, so it cannot be turned off.
The documented way round it is to CLEAR the property and then set it; an empty stage has
no order to move backward from. The engine does not do this, because with the order
above it never needs a backward write -- but it is how a human repairs one by hand.

This was not theoretical when it was found: `reply_check` had been writing Disqualified
on `not_qualified` replies since it was built, and for any DORMANT contact (then at
displayOrder 6, higher than Disqualified's 3) that write had always been a no-op. It
reported success every time.

**RESOLVED 2026-09-29 in HubSpot, not here.** Dormant was re-ordered from 6 to **1**,
between New and Outreached. Verified with real writes (each reverted): New -> Dormant,
Dormant -> Outreached, -> Qualified and -> Disqualified are all accepted. The ~480
Dormant contacts per round can carry a full outcome again, which matters because Dormant
is the re-engagement audience this engine exists for.

Position 1 rather than 0 on purpose. At 0 everything the engine writes still worked, but
**New -> Dormant became backward**, which would silently break anything that marks
inactive contacts Dormant -- the same failure in the other direction. At 1 both hold.

**That fix exposed a second failure, which is why the order is now read LIVE.** The
order was hardcoded here from a 2026-09-25 snapshot. When the portal changed, the code
did not: it went on refusing exactly the promotions the settings change had enabled, and
nothing reported a problem because refusing looks identical to having nothing to do. A
configuration fix that cannot reach the code is not a fix. See refresh().

**The manual remedy for a stage stuck too far forward** is to clear the property and
then set it, since an empty stage has no order to move backward from. The engine does
NOT do this -- it would be circumventing a deliberate portal control -- but it is how a
human repairs one by hand.
"""
from __future__ import annotations

# **READ LIVE, because this table went stale in 24 hours.** It was written 2026-09-25
# from the live property; by 2026-09-29 Dormant had been re-ordered from 6 to 2 and five
# of nine positions were wrong. A stale ORDER is not cosmetic -- order is what decides
# whether a write is attempted at all, so the engine went on refusing Dormant promotions
# that the portal had started accepting. The fix that was made in HubSpot simply did not
# reach the code.
#
# `refresh()` fetches the real order once per process. The table below is the FALLBACK
# for when that call fails, and it is the 2026-09-29 snapshot -- keep it roughly current,
# but nothing should depend on it being exact.
FALLBACK_STAGES: dict[str, tuple[str, int]] = {
    "lead":        ("New", 0),
    "1442770269":  ("Dormant", 1),
    "customer":    ("Outreached", 2),
    "opportunity": ("Qualified", 3),
    "1439306394":  ("Disqualified", 4),
    "1442145964":  ("Deal Created", 5),
    "1439340893":  ("Deal Won", 6),
    "1403597677":  ("Google_Paid Ads_Call Booked", 7),
    "1421690440":  ("Meta_Paid Ads_Call Booked", 8),
}

STAGES: dict[str, tuple[str, int]] = dict(FALLBACK_STAGES)
_REFRESHED = False


def refresh(token: str | None = None, force: bool = False) -> bool:
    """Load the REAL stage order from HubSpot. True if it was read successfully.

    Called once per process by `may_promote`. Cheap (one GET), and the alternative is
    the failure that prompted it: a portal re-order that the code never notices, so a
    settings fix silently does not apply.
    """
    global STAGES, _REFRESHED
    if _REFRESHED and not force:
        return True
    import json as _json
    import urllib.request as _u
    try:
        if token is None:
            import eligibility
            token = eligibility.env_token()
        req = _u.Request(
            "https://api.hubapi.com/crm/v3/properties/contacts/lifecyclestage",
            headers={"Authorization": f"Bearer {token}"})
        with _u.urlopen(req, timeout=20) as r:
            opts = _json.load(r).get("options") or []
        live = {o["value"]: (o.get("label") or o["value"], o.get("displayOrder", 0))
                for o in opts}
        if live:
            drift = [v for v in live if v in FALLBACK_STAGES
                     and live[v][1] != FALLBACK_STAGES[v][1]]
            if drift:
                print(f"    lifecycle: portal order differs from the built-in "
                      f"fallback for {len(drift)} stage(s); using the LIVE order")
            STAGES = live
            _REFRESHED = True
            return True
    except Exception as e:
        # Never fatal. A stale order makes the guard conservative (it refuses writes
        # that might now succeed), which is the safe direction to fail in.
        print(f"    lifecycle: could not read the live stage order "
              f"({type(e).__name__}); using the built-in fallback, which may be stale")
    return False

OUTREACHED = "customer"
QUALIFIED = "opportunity"
DISQUALIFIED = "1439306394"

# Stages the engine must never overwrite even when HubSpot would permit it. These are
# sales outcomes owned by a person, not by an email sequence: a contact somebody has
# moved to Deal Created does not get demoted because an automated follow-up went out.
NEVER_OVERWRITE = {"1442145964", "1439340893", "1403597677", "1421690440"}


def label(value: str) -> str:
    v = (value or "").strip()
    return STAGES.get(v, (v or "(empty)", -1))[0]


def order(value: str) -> int:
    return STAGES.get((value or "").strip(), ("", -1))[1]


def may_promote(current: str, target: str) -> tuple[bool, str]:
    """(should we attempt the write, why not).

    Refusing here rather than letting HubSpot refuse silently is the point: a decision
    made in code is visible in the run log, and a decision made by the portal is not.
    """
    refresh()                                  # live order, not a snapshot
    cur = (current or "").strip()
    tgt = (target or "").strip()
    if tgt not in STAGES:
        return False, f"unknown target stage {tgt!r}"
    if not cur:
        return True, ""                            # unset -> anything is forward
    if cur == tgt:
        return False, f"already {label(cur)}"
    if cur in NEVER_OVERWRITE:
        return False, f"{label(cur)} is a sales outcome the engine does not overwrite"
    if order(cur) > order(tgt):
        # The silent-refusal case. Saying so is the whole value of this function.
        return False, (f"HubSpot refuses backward moves: {label(cur)} "
                       f"(order {order(cur)}) -> {label(tgt)} (order {order(tgt)})")
    return True, ""


def apply_stage(read_stage, write_stage, contact_id: str, target: str,
                current: str | None = None, apply_changes: bool = False) -> str:
    """Promote one contact, VERIFYING the result. Returns a line for the run log.

    `read_stage(contact_id) -> str` and `write_stage(contact_id, value) -> None` are
    injected so this works with each script's own HubSpot client; reply_check,
    sync_sends and sync_meetings all have different ones and none of them should grow
    a second.

    The read-back is not belt-and-braces. It is the ONLY way to know the write landed,
    because a refused write is indistinguishable from an accepted one at the HTTP layer.
    """
    cur = current if current is not None else read_stage(contact_id)
    ok, why = may_promote(cur, target)
    if not ok:
        return f"lifecycle: not set to {label(target)} -- {why}"
    if not apply_changes:
        return f"lifecycle: would set {label(cur)} -> {label(target)}"
    write_stage(contact_id, target)
    got = read_stage(contact_id)
    if (got or "").strip() == target:
        return f"lifecycle: {label(cur)} -> {label(target)}"
    return (f"lifecycle: ** WRITE DID NOT TAKE ** asked for {label(target)}, "
            f"contact is still {label(got)}; HubSpot accepted the call and ignored it")


def _self_test() -> int:
    cases = [
        # (current, target, should_attempt, why-this-case-exists)
        ("lead", OUTREACHED, True, "New -> Outreached is forward"),
        ("lead", QUALIFIED, True, "New -> Qualified is forward"),
        (OUTREACHED, QUALIFIED, True, "Outreached -> Qualified is forward"),
        ("", OUTREACHED, True, "an unset stage can go anywhere"),
        # Was False until the portal re-order on 2026-09-29. Asserting the CURRENT
        # truth, and it is a live assertion: may_promote reads the real order, so this
        # case fails loudly if anyone re-orders Dormant back above Disqualified.
        ("1442770269", DISQUALIFIED, True,
         "Dormant -> Disqualified, accepted since Dormant moved to order 2"),
        ("1442770269", QUALIFIED, True, "Dormant -> Qualified, likewise"),
        ("1442770269", OUTREACHED, True,
         "Dormant -> Outreached, accepted since Dormant moved to order 0"),
        (QUALIFIED, OUTREACHED, False,
         "never demote a Qualified contact because another email went out"),
        ("1442145964", QUALIFIED, False, "Deal Created is a human's call, not ours"),
        ("1439340893", OUTREACHED, False, "Deal Won is never touched"),
        (OUTREACHED, OUTREACHED, False, "no write when it already holds the value"),
    ]
    bad = 0
    for cur, tgt, want, why in cases:
        got, reason = may_promote(cur, tgt)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} {label(cur):<14} -> {label(tgt):<13} "
              f"{'attempt' if got else 'skip':<8} | {why}")
        if not got and reason:
            print(f"         {reason}")

    # apply_stage must REPORT a write that did not take, never report success.
    calls = {}
    def rd(cid): return calls.get(cid, "1442770269")
    def wr(cid, v): calls[cid] = "1442770269"      # simulate the portal ignoring it
    note = apply_stage(rd, wr, "x", DISQUALIFIED, current="lead", apply_changes=True)
    ok = "DID NOT TAKE" in note
    bad += 0 if ok else 1
    print(f"  {'ok  ' if ok else 'WRONG'} a refused write is reported, not assumed")
    print(f"         {note}")

    print(f"\n{len(cases) + 1 - bad}/{len(cases) + 1} lifecycle cases correct")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_self_test() if "--self-test" in sys.argv else 0)
