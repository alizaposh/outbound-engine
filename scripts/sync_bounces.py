#!/usr/bin/env python3
"""Sync Smartlead hard bounces into HubSpot as `outbound_status = bounced`.

Closes the gap recorded in BACKLOG.md: `bounced` is a HARD eligibility gate that nothing
ever wrote, so a dead address stayed fully eligible and was re-enrolled next campaign.

    Smartlead bounced statistics  ->  HubSpot outbound_status = bounced

**Why it matters more than it sounds.** Repeatedly mailing invalid addresses is among the
fastest ways to damage domain reputation, and these domains are weeks old. One
re-enrolment of a dead address is cheap; doing it every campaign is not.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. IT NEVER SETS `outbound_suppressed`. Per config/hubspot-properties.md, suppression
     is OPT-OUT ONLY, written by exactly two things: the unsubscribe sync and the reply
     handler. A bounce is a deliverability fact, not a consent decision, and it is
     already a hard exclusion through `outbound_status`. Conflating the two would file a
     bounce as though the person had asked us to stop.
  3. IT NEVER WRITES NATIVE `hs_email_optout`. Same reasoning, more so.
  4. AN EMPTY RESULT WITH A NON-ZERO BOUNCE COUNT IS A LOUD FAILURE, not a quiet zero.
     The enumeration filter here is the same one that returned NOTHING for unsubscribes
     after a confirmed unsubscribe, which is why sync_unsubscribes.py walks the lead list
     instead. Whether it works for bounces could not be established without a real
     bounce, so this cross-checks itself against the aggregate and says so if they
     disagree.
  5. SOFT BOUNCES MUST NOT PERMANENTLY EXCLUDE ANYONE. A full mailbox is temporary; a
     dead address is not. If the API does not distinguish them, that is REPORTED rather
     than assumed, and `--include-soft` is required to act on rows whose type is unknown.
  6. IDEMPOTENT. A contact already `bounced` is skipped, so re-running changes nothing.

**One asymmetry with the unsubscribe sync, deliberately.** That job declines to overwrite
`outbound_status = meeting_booked`, because `outbound_suppressed` carries the suppression
independently and the status write is only informational. Here `outbound_status` is the
ONLY carrier of the bounce, so declining to write it would mean not recording the bounce
at all. It therefore DOES overwrite, and prints loudly when it overwrites something
valuable so a human can see it happen.
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
from eligibility import HubSpot, env_token, env_value  # noqa: E402
import lifecycle  # noqa: E402
from reply_check import HubSpotWriter  # noqa: E402

SL_BASE = "https://server.smartlead.ai/api/v1"
# Marks a note as ours so a re-run recognises it and does not stack duplicates.
NOTE_MARKER = "[outbound-engine:bounce]"
NOTE_TO_CONTACT = 202          # /crm/v4/associations/notes/contacts/labels
READ_PROPS = ["email", "outbound_status", "outbound_suppressed", "firstname",
              # lifecyclestage is read so --disqualify can be guarded and so the note
              # can say what the stage WAS.
              "lastname", "lifecyclestage"]

# Fields a statistics row might carry describing the bounce. None is documented; these
# are checked so a hard/soft distinction is USED when present rather than ignored.
TYPE_FIELDS = ("bounce_type", "bounce_category", "bounce_reason", "email_status_reason",
               "reason", "bounce_sub_type", "smtp_response")
SOFT_MARKERS = ("soft", "mailbox full", "quota", "temporar", "deferred", "try again",
                "greylist", "out of office", "451", "452", "4.2.2")
HARD_MARKERS = ("hard", "does not exist", "no such user", "unknown user",
                "invalid recipient", "550", "5.1.1", "user unknown", "domain not found")


def classify_bounce(row: dict) -> tuple[str, str]:
    """(kind, evidence) where kind is 'hard', 'soft' or 'unknown'.

    Guarantee 5. A soft bounce is a full mailbox or a temporary refusal and must not
    permanently exclude a contact; a hard bounce is a dead address and must. Nothing in
    the Smartlead docs promises either signal, so an absent one yields 'unknown' and the
    caller refuses to act without --include-soft.
    """
    for f in TYPE_FIELDS:
        v = str(row.get(f) or "").strip()
        if not v:
            continue
        low = v.lower()
        if any(m in low for m in SOFT_MARKERS):
            return "soft", f"{f}={v!r}"
        if any(m in low for m in HARD_MARKERS):
            return "hard", f"{f}={v!r}"
    return "unknown", "no bounce-type field on the row"


def decide(kind: str, existing: dict, include_soft: bool) -> tuple[str, dict, str]:
    """(outcome, properties, note). Pure, so the rules are testable without an API."""
    status = (existing.get("outbound_status") or "").strip()
    if status == "bounced":
        return "already recorded", {}, "already outbound_status=bounced"
    if kind == "soft":
        return ("skip", {},
                "SOFT bounce: temporary, so it must not permanently exclude anyone")
    if kind == "unknown" and not include_soft:
        return ("skip", {},
                "bounce type unknown and --include-soft not given; refusing to "
                "permanently exclude a contact that may have only bounced temporarily")

    props = {"outbound_status": "bounced"}
    note = ""
    # See the module docstring: status is the ONLY carrier of a bounce, so unlike the
    # unsubscribe sync this cannot decline to overwrite. It reports instead.
    if status and status != "bounced":
        note = (f"OVERWRITING outbound_status={status!r} with 'bounced'. Status is the "
                f"only field that records a bounce, so this is unavoidable — but if "
                f"{status!r} mattered, a human should know it is gone.")
    return "record", props, note


def bounce_note_body(email: str, row: dict, kind: str, evidence: str,
                     was_stage: str, campaign: str = "") -> str:
    """The note left on a bounced contact. Written for a human opening the record.

    It says the address is dead, not that the ORGANISATION is a bad fit. That
    distinction matters because --disqualify writes the Disqualified lifecycle stage,
    which elsewhere means a structural non-fit ("they do not run ticketed events").
    A reader who confuses the two will retire a perfectly good account because one
    person's mailbox was deleted.

    It also states the hard/soft uncertainty. Smartlead exposes `is_bounced` and no
    SMTP code, diagnostic or bounce category at all, so "permanent" is an inference
    from the address having failed on first contact -- not something the provider told
    us. A note that hides that would be more confident than the data.
    """
    sent = (row.get("sent_time") or "")[:10]
    lines = [
        f"Email bounced -- this address is not deliverable.",
        "",
        f"Address:  {email}",
        f"Bounced:  first send{f', {sent}' if sent else ''}"
        + (f" (campaign {campaign})" if campaign else ""),
        f"Type:     {kind}" + (f" -- {evidence}" if evidence else ""),
    ]
    if was_stage:
        lines.append(f"Was:      lifecycle {lifecycle.label(was_stage)}")
    lines += [
        "",
        "THIS IS A DATA PROBLEM, NOT A JUDGEMENT ABOUT THE ACCOUNT. The lifecycle "
        "stage is set to Disqualified so the engine stops mailing a dead address; it "
        "does NOT mean the organisation is a bad fit. If someone finds a working "
        "address for this person, clear the stage and they become workable again.",
        "",
        "Smartlead reports no SMTP code or bounce category, so hard vs soft cannot be "
        "confirmed from the provider. Treated as permanent because it failed on first "
        "contact.",
        "",
        NOTE_MARKER,
    ]
    return "\n".join(lines)


def existing_bounce_note(writer, contact_id: str) -> str:
    """Id of a note we already left on this contact, or "". Same reasoning as the
    re-engagement task: this job runs on the morning heartbeat, so without a check a
    single bounce grows a note per day."""
    try:
        assoc = writer._call(
            "GET", f"/crm/v4/objects/contacts/{contact_id}/associations/notes")
    except Exception:
        return "unknown"                  # cannot prove absence -> do not add another
    for nid in [r["toObjectId"] for r in (assoc.get("results") or [])][:50]:
        try:
            n = writer._call("GET", f"/crm/v3/objects/notes/{nid}?properties=hs_note_body")
        except Exception:
            continue
        if NOTE_MARKER in ((n.get("properties") or {}).get("hs_note_body") or ""):
            return str(nid)
    return ""


def write_bounce_note(writer, contact_id: str, body: str) -> str:
    if not writer.apply:
        return "would add a bounce note"
    r = writer._call("POST", "/crm/v3/objects/notes", {
        "properties": {"hs_note_body": body,
                       "hs_timestamp": dt.datetime.now(dt.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%SZ")},
        "associations": [{"to": {"id": contact_id},
                          "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                     "associationTypeId": NOTE_TO_CONTACT}]}]})
    return f"added bounce note {r.get('id')}"


class Smartlead:
    """Read-only. This job never changes anything in Smartlead."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0

    def get(self, path: str):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(f"{SL_BASE}{path}{sep}api_key={self.key}",
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

    def bounced(self, cid) -> list[dict]:
        out, offset = [], 0
        while True:
            d = self.get(f"/campaigns/{cid}/statistics"
                         f"?offset={offset}&limit=100&email_status=bounced")
            rows = d.get("data") or []
            out += rows
            offset += len(rows)
            if not rows or offset >= int(d.get("total_stats") or 0):
                return out

    def bounce_count(self, cid) -> int:
        return int((self.get(f"/campaigns/{cid}/analytics") or {}).get("bounce_count") or 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sync Smartlead bounces into HubSpot. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="WRITE outbound_status=bounced to HubSpot.")
    ap.add_argument("--campaign", help="one campaign id; default is every campaign")
    ap.add_argument("--disqualify", action="store_true",
                    help="ALSO set lifecyclestage=Disqualified and leave a note "
                         "explaining the address is dead. Stops all future enrolment, "
                         "since Disqualified is not in lifecycle_allow.")
    ap.add_argument("--include-soft", action="store_true",
                    help="also act on rows whose bounce type cannot be determined. Off "
                         "by default: a soft bounce is temporary and permanent exclusion "
                         "is not reversible by waiting.")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the classification and decision rules with no API calls")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")
    sl = Smartlead(key)
    print("APPLY: writing outbound_status=bounced" if a.apply
          else "DRY RUN: nothing will be written. Re-run with --apply to act.")

    campaigns = ([{"id": a.campaign, "name": f"(id {a.campaign})"}] if a.campaign
                 else sl.campaigns())
    if not campaigns:
        print("no campaigns in the account, so there are no bounces to sync yet.")
        return 0

    found: dict[str, dict] = {}
    mismatch = False
    for camp in campaigns:
        cid = camp.get("id")
        rows = sl.bounced(cid)
        count = sl.bounce_count(cid)
        print(f"campaign {cid} {camp.get('name','')!r}: "
              f"{len(rows)} bounced row(s), analytics says {count}")
        # Guarantee 4. The filter this relies on is the one that silently returned
        # nothing for unsubscribes, so it is checked against the aggregate every run.
        if count > 0 and not rows:
            mismatch = True
            print(f"  !! analytics reports {count} bounce(s) but the "
                  f"email_status=bounced filter returned NOTHING. That is the same "
                  f"failure the unsubscribe sync hit, and it means this job cannot see "
                  f"bounces on this campaign. Do NOT treat a clean run as 'no bounces'.")
        for r in rows:
            email = (r.get("lead_email") or "").strip().lower()
            if email:
                found[email] = r

    if not found:
        print("\nno bounced rows found." if not mismatch
              else "\nno rows enumerated, but the aggregate disagrees — see above.")
        return 1 if mismatch else 0

    hs_read = HubSpot(env_token())
    writer = HubSpotWriter(env_token(), a.apply)
    contacts = hs_read.search_by_email(sorted(found), READ_PROPS)
    counts = {"record": 0, "skip": 0, "already recorded": 0, "unmatched": 0}
    print(f"\n{len(found)} bounced address(es), {len(contacts)} matched in HubSpot\n")

    for email, row in sorted(found.items()):
        kind, evidence = classify_bounce(row)
        existing = contacts.get(email)
        if existing is None:
            counts["unmatched"] += 1
            print(f"  UNMATCHED {email:42} {kind} bounce ({evidence}); no HubSpot "
                  f"contact, so the bounce cannot be recorded")
            continue
        outcome, props, note = decide(kind, existing, a.include_soft)
        counts[outcome] += 1
        label = {"record": "BOUNCED ", "skip": "SKIP    ",
                 "already recorded": "CURRENT "}[outcome]
        print(f"  {label} {email:42} {kind} bounce ({evidence})")
        if note:
            print(f"           {note}")
        if props:
            print(f"           {writer.write(existing['hs_object_id'], props)}")
        if a.disqualify and outcome in ("record", "already recorded"):
            cid = existing["hs_object_id"]
            was = (existing.get("lifecyclestage") or "").strip()
            can, why_not = lifecycle.may_promote(was, lifecycle.DISQUALIFIED)
            if can:
                print(f"           {writer.write(cid, {'lifecyclestage': lifecycle.DISQUALIFIED})}")
                if a.apply:
                    got = (writer._call(
                        'GET', f"/crm/v3/objects/contacts/{cid}?properties=lifecyclestage"
                        ).get('properties') or {}).get('lifecyclestage', '')
                    if str(got).strip() != lifecycle.DISQUALIFIED:
                        print(f"           ** stage did NOT take -- still "
                              f"{lifecycle.label(got)} **")
            else:
                print(f"           lifecycle unchanged -- {why_not}")
            seen = existing_bounce_note(writer, cid)
            if seen == "unknown":
                print("           note: could not check for an existing one; skipping")
            elif seen:
                print(f"           note: {seen} already present, left alone")
            else:
                body = bounce_note_body(email, row, kind, evidence, was,
                                        str(row.get("campaign_id") or ""))
                print(f"           {write_bounce_note(writer, cid, body)}")

    print(f"\n{counts['record']} recorded, {counts['skip']} skipped, "
          f"{counts['already recorded']} already current, {counts['unmatched']} unmatched")
    print(f"{sl.calls} Smartlead calls, {hs_read.calls + writer.calls} HubSpot calls")
    if not a.apply:
        print("DRY RUN: nothing was written.")
    if counts["skip"]:
        print("Skipped rows are soft or unknown bounces. Re-run with --include-soft only "
              "if you accept permanently excluding a contact that may bounce temporarily.")
    return 1 if mismatch else 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    check("a 550 is hard", classify_bounce({"bounce_reason": "550 user unknown"})[0], "hard")
    check("mailbox full is soft",
          classify_bounce({"bounce_reason": "452 mailbox full"})[0], "soft")
    check("explicit hard type", classify_bounce({"bounce_type": "Hard"})[0], "hard")
    check("explicit soft type", classify_bounce({"bounce_type": "soft"})[0], "soft")
    check("no type field is unknown", classify_bounce({"lead_email": "a@b.com"})[0],
          "unknown")

    # A hard bounce on a fresh contact records.
    outcome, props, _ = decide("hard", {}, False)
    check("hard bounce records", (outcome, props), ("record", {"outbound_status": "bounced"}))
    check("guarantee 2: never suppresses", "outbound_suppressed" in props, False)
    check("guarantee 3: never native opt-out", "hs_email_optout" in props, False)

    # Guarantee 5.
    check("soft bounce is skipped", decide("soft", {}, False)[0], "skip")
    check("soft stays skipped even with --include-soft",
          decide("soft", {}, True)[0], "skip")
    check("unknown is skipped by default", decide("unknown", {}, False)[0], "skip")
    check("unknown records with --include-soft", decide("unknown", {}, True)[0], "record")

    # Guarantee 6.
    check("already bounced is a no-op",
          decide("hard", {"outbound_status": "bounced"}, False)[:2],
          ("already recorded", {}))

    # The asymmetry: it DOES overwrite, and says so.
    outcome, props, note = decide("hard", {"outbound_status": "meeting_booked"}, False)
    check("a bounce overwrites meeting_booked", props.get("outbound_status"), "bounced")
    check("and reports the overwrite", "OVERWRITING" in note, True)
    check("naming what was lost", "meeting_booked" in note, True)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
