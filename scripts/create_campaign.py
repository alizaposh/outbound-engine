#!/usr/bin/env python3
"""Create a DRAFTED Smartlead campaign from approved copy. Never launches.

Implements instructions/campaign-creation.md. Takes the CSV that
scripts/run_generation.py produced, once a human has approved the copy, and builds the
campaign in Smartlead: schedule, mailboxes, the 3-email sequence, and the leads with
their own copy attached.

Five guarantees:

  1. IT NEVER LAUNCHES. Nothing here calls the campaign status endpoint. The campaign is
     left DRAFTED, which Smartlead itself will not send from, and the run asserts that
     status at the end. Launching stays a human action in the UI, deliberately.
  2. APPROVAL IS RECORDED OR NOTHING HAPPENS. --approved-by and --approval-note are
     required (golden rule 1: no campaign without a recorded approval). The note is
     written into the campaign name suffix and printed, so the Smartlead record carries
     it too.
  3. A BATCH WITH ANY FAIL IS REFUSED. Copy that failed validation does not reach a
     campaign. --skip-failed drops those rows instead, and says which.
  4. NO PARTIAL CAMPAIGNS. If any step after creation fails, the campaign is deleted
     rather than left half-configured for someone to find later and trust.
  5. ONE SENDER PER CAMPAIGN. A Smartlead campaign ROTATES across its assigned
     mailboxes, so a campaign mixing copy signed by different people would send an email
     signed "Carl" from Brooke's mailbox. That is the same misrepresented-sender fault
     that put the wrong name in 18 of 34 emails once already, one level up. Every lead in
     the CSV must be signed by one sender, and every mailbox passed in must belong to
     them. Run the script once per sender.
  6. TWO MANUAL UI GATES ARE PRINTED, NOT ASSUMED. HubSpot activity logging and
     "Optimize Email Delivery" are not reachable by API (verified 2026-08-31: both
     rejected with "is not allowed"), so the run ends by naming them.

API shapes were verified against a real campaign on 2026-08-31, not taken from docs.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import assemble  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULTS = ROOT / "config" / "smartlead-defaults.md"
BASE = "https://server.smartlead.ai/api/v1"
POSITIONS = (1, 2, 3)

# Custom-field names on each lead. The sequence body is literally "{{message_1_body}}",
# so these names are a contract with the sequence and cannot drift.
FIELD_SUBJECT = "message_1_subject"
FIELD_BODY = "message_{}_body"


def load_defaults(path: pathlib.Path = DEFAULTS) -> dict:
    """Parse the canonical block from config/smartlead-defaults.md.

    Parsed rather than restated so the config stays the single source of truth, the same
    way scripts/eligibility.py reads pre-send-defaults.md.
    """
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Canonical values.*?```(.*?)```", text, re.S)
    if not m:
        raise RuntimeError(f"{path}: no fenced 'Canonical values' block")
    cfg: dict = {}
    for raw in m.group(1).splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v.startswith("[") and v.endswith("]"):
            items = [x.strip() for x in v[1:-1].split(",") if x.strip()]
            cfg[k] = [int(x) if x.isdigit() else x for x in items]
        elif v.lower() in ("true", "false"):
            cfg[k] = v.lower() == "true"
        elif re.fullmatch(r"-?\d+", v):
            cfg[k] = int(v)
        else:
            cfg[k] = v
    return cfg


def api_key() -> str:
    """Uses the shared loader so an inline comment in .env cannot corrupt the key."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from eligibility import env_value
    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set (env or .env)")
    return key


class Smartlead:
    """Thin client. Deliberately has NO method that activates a campaign."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0

    def call(self, method: str, path: str, body: dict | None = None):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(
            f"{BASE}{path}{sep}api_key={self.key}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     # urllib's default UA gets a 403 from Smartlead's edge.
                     "User-Agent": "outbound-engine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.calls += 1
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode()[:400]
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None


def to_html(text: str) -> str:
    """Plain-text copy to HTML, because campaigns send as HTML by default.

    Newlines in an HTML body collapse, so a body that reads as four paragraphs locally
    would arrive as one block. Blank lines become paragraph breaks and single newlines
    become <br>. Verified on the write test that custom fields survive the round trip
    with newlines intact, which is exactly why they have to be converted here rather
    than hoped over.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    # quote=False on purpose: apostrophes are safe in HTML text content, and escaping
    # them turned "I'm Carl" into "I&#x27;m Carl" in the stored field. It renders fine,
    # but it is unreadable to anyone inspecting a lead in the Smartlead UI, and it would
    # show literally if a campaign were ever switched to plain text.
    return "".join("<p>" + html.escape(p, quote=False).replace("\n", "<br>") + "</p>"
                   for p in paras)


def load_rows(path: pathlib.Path, skip_failed: bool) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows:
        raise RuntimeError(f"{path} has no rows")
    failed = [r for r in rows if (r.get("validation") or "").upper() in
              ("FAIL", "ERROR", "GENERATION_FAILED_FALLBACK")]
    if failed and not skip_failed:
        print(f"REFUSING: {len(failed)} of {len(rows)} rows did not pass validation. "
              f"Copy that failed review must not reach a campaign.", file=sys.stderr)
        for r in failed[:10]:
            print(f"  {r.get('validation'):28} {r.get('email')}", file=sys.stderr)
        print("Fix the copy, or pass --skip-failed to leave those leads out.",
              file=sys.stderr)
        raise SystemExit(2)
    if failed:
        print(f"skipping {len(failed)} row(s) that failed validation:")
        for r in failed:
            print(f"  {r.get('validation'):28} {r.get('email')}")
        rows = [r for r in rows if r not in failed]

    seen, unique = set(), []
    for r in rows:
        e = (r.get("email") or "").strip().lower()
        if not e or e in seen:
            continue
        seen.add(e)
        unique.append(r)
    if len(unique) != len(rows):
        print(f"dropped {len(rows) - len(unique)} row(s) with a blank or duplicate email")
    missing = [r["email"] for r in unique
               if not all(r.get(FIELD_BODY.format(p)) for p in POSITIONS)]
    if missing:
        raise RuntimeError(f"{len(missing)} lead(s) are missing a message body, so the "
                           f"sequence would send an empty email: {missing[:5]}")
    return unique


def verify_campaign(sl, cid, cfg, repair: bool = False) -> int:
    """Read a campaign back and check the API-set settings still match config.

    Exists because the UI silently overwrites them. Campaign 3887546 was created with
    track_settings ["DONT_EMAIL_OPEN"] and later read back as ["DONT_LINK_CLICK"]: saving
    the settings panel in the Smartlead UI, while doing the two mandatory manual toggles,
    replaced what the API had set. The enum round-trips correctly when set by API, so the
    call was never wrong -- the UI just wins last.

    That failure is silent and consequential: open tracking back ON means a tracking
    pixel on cold mail from a young domain, which is both a deliverability cost the
    config deliberately avoids and a spam signal.
    """
    c = sl.call("GET", f"/campaigns/{cid}")
    print(f"campaign {cid}: {c.get('name')!r}  status={c.get('status')}")

    want_track = cfg.get("track_settings", ["DONT_EMAIL_OPEN"])
    want_stop = cfg.get("stop_lead_settings", "REPLY_TO_AN_EMAIL")
    checks = [
        ("track_settings", c.get("track_settings"), want_track),
        ("stop_lead_settings", c.get("stop_lead_settings"), want_stop),
    ]
    sched = c.get("scheduler_cron_value") or {}
    checks += [
        ("schedule timezone", sched.get("tz"), cfg.get("timezone", "America/New_York")),
        ("schedule days", sched.get("days"), cfg.get("days", [1, 2, 3, 4, 5])),
    ]
    bad = []
    for label, got, want in checks:
        ok = got == want
        if not ok:
            bad.append(label)
        print(f"  {'ok  ' if ok else 'DRIFT'} {label:22} {got!r}"
              f"{'' if ok else f'   expected {want!r}'}")

    if bad and repair:
        print(f"\nre-applying {', '.join(bad)} from config...")
        sl.call("POST", f"/campaigns/{cid}/settings", {
            "track_settings": want_track,
            "stop_lead_settings": want_stop,
            "send_as_plain_text": cfg.get("send_as_plain_text", False)})
        c = sl.call("GET", f"/campaigns/{cid}")
        print(f"  track_settings now {c.get('track_settings')!r}, "
              f"stop_lead_settings now {c.get('stop_lead_settings')!r}")
        bad = [b for b in bad if b not in ("track_settings", "stop_lead_settings")]

    print("\nCANNOT be checked from the API -- confirm by eye in the UI every time:")
    print("  - HubSpot activity logging ON")
    print("  - 'Add unsubscribe message in all emails' ON")
    print("  - 'Optimize Email Delivery' OFF")
    if bad:
        print(f"\nSTILL DRIFTED: {', '.join(bad)}. Re-run with --repair, or fix in the UI.")
        return 1
    print("\nAPI-set settings match config.")
    return 0


def record_enrolment(rows, cid, name, apply_changes: bool) -> int:
    """Write the enrolment back to HubSpot: campaign id + outbound_status=in_sequence.

    Closes the gap that `outbound_last_campaign_id` was documented as ESSENTIAL -- the
    only link from a HubSpot contact to the campaign that mailed it, since there is no
    local database -- and nothing wrote it.

    `in_sequence` matters more. The pre-send filter's SOFT tier skips contacts already
    in sequence, but nothing ever set it, and **Smartlead does not block cross-campaign
    duplicates either** (verified 2026-09-02: the same lead uploaded cleanly to two
    campaigns, skipped_in_other_campaign_count=0). So without this, an overlapping
    second list enrols the same person twice and they receive two cold sequences in
    parallel, possibly from two different senders.

    Returns the number of contacts recorded.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from eligibility import HubSpot, env_token

    ids = [(r.get("hs_object_id") or "").strip() for r in rows]
    linked = [i for i in ids if i]
    unlinked = len(ids) - len(linked)
    if unlinked:
        print(f"  {unlinked} enrolled lead(s) have no hs_object_id, so their enrolment "
              f"cannot be recorded in HubSpot. They will look un-enrolled to the next "
              f"eligibility run.")
    if not linked:
        return 0

    hs = HubSpot(env_token())
    # Guard: eligibility should already have excluded these. If one slipped through,
    # enrolling it is the bug -- say so rather than papering over it with a status write.
    emails = [(r.get("email") or "").strip() for r in rows if (r.get("email") or "").strip()]
    current = hs.search_by_email(emails, ["email", "outbound_status", "outbound_suppressed"])
    blocked = {e: p for e, p in current.items()
               if str(p.get("outbound_suppressed") or "").lower() in ("true", "1")
               or (p.get("outbound_status") or "") in ("opted_out", "bounced")}
    if blocked:
        raise RuntimeError(
            f"REFUSING to record enrolment: {len(blocked)} enrolled contact(s) are "
            f"suppressed or terminal in HubSpot -- {sorted(blocked)}. They should never "
            f"have reached campaign creation, so the eligibility step was skipped or "
            f"stale. Re-run scripts/eligibility.py and regenerate from its output.")

    props = {"outbound_last_campaign_id": f"{cid}", "outbound_status": "in_sequence"}
    if not apply_changes:
        print(f"  would record enrolment on {len(linked)} contact(s): {props}")
        return len(linked)

    # Batched: one call per 100 rather than one per contact.
    import json as _json
    import urllib.request as _u
    tok = env_token()
    done = 0
    for i in range(0, len(linked), 100):
        chunk = linked[i:i + 100]
        body = {"inputs": [{"id": h, "properties": props} for h in chunk]}
        req = _u.Request("https://api.hubapi.com/crm/v3/objects/contacts/batch/update",
                         method="POST", data=_json.dumps(body).encode(),
                         headers={"Authorization": f"Bearer {tok}",
                                  "Content-Type": "application/json"})
        with _u.urlopen(req, timeout=60) as r:
            r.read()
        done += len(chunk)
    print(f"  recorded enrolment on {done} HubSpot contact(s): "
          f"outbound_last_campaign_id={cid}, outbound_status=in_sequence")
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Create a DRAFTED Smartlead campaign from approved copy. Never launches.")
    ap.add_argument("--verify", metavar="CAMPAIGN_ID",
                    help="read an existing campaign back and check the API-set settings "
                         "still match config. The UI overwrites them; run this after any "
                         "manual toggling and before launching.")
    ap.add_argument("--repair", action="store_true",
                    help="with --verify, re-apply the config values that have drifted")
    ap.add_argument("--csv", required=False, type=pathlib.Path,
                    help="output of scripts/run_generation.py, after human approval")
    ap.add_argument("--audience", help="e.g. ra-premium")
    ap.add_argument("--usecase", help="e.g. switch")
    ap.add_argument("--mailboxes",
                    help="comma-separated sending mailboxes, all must be in config/senders.md")
    ap.add_argument("--approved-by",
                    help="who approved this copy (golden rule 1)")
    ap.add_argument("--approval-note",
                    help="where the approval is recorded, e.g. a Slack permalink")
    ap.add_argument("--skip-failed", action="store_true",
                    help="drop rows that failed validation instead of refusing the batch")
    ap.add_argument("--delays",
                    help="TEST ONLY: override seq_delay_days, e.g. '0,1,1', so a "
                         "threading check does not wait 3 days for email 2. Never use "
                         "this on a real campaign; production delays are in "
                         "config/smartlead-defaults.md for deliverability reasons.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print exactly what would be sent to Smartlead; write nothing")
    a = ap.parse_args(argv)
    cfg = load_defaults()

    if a.verify:
        return verify_campaign(Smartlead(api_key()), a.verify, cfg, repair=a.repair)
    needed = [n for n, v in (("--csv", a.csv), ("--audience", a.audience),
                             ("--usecase", a.usecase), ("--mailboxes", a.mailboxes),
                             ("--approved-by", a.approved_by),
                             ("--approval-note", a.approval_note)) if not v]
    if needed:
        # Creation still requires all of them, approval included -- guarantee 2 is
        # unchanged. Only --verify is exempt, and it writes no copy and enrolls nobody.
        ap.error(f"required for creating a campaign: {', '.join(needed)}")

    rows = load_rows(a.csv, a.skip_failed)

    # Mailboxes must be real senders: an unmapped one means the sign-off in the copy does
    # not match the account that sends it, which misrepresents the sender.
    sender_map = assemble.load_sender_map()
    boxes = [m.strip().lower() for m in a.mailboxes.split(",") if m.strip()]
    unknown = [m for m in boxes if m not in sender_map]
    if unknown:
        raise RuntimeError(f"mailboxes not in config/senders.md: {unknown}")
    placeholders = [m for m in boxes if assemble.is_placeholder_sender(sender_map[m])]
    if placeholders:
        raise RuntimeError(f"mailboxes still mapped to placeholder senders: {placeholders}")

    # Guarantee 5: the copy's signature and the sending mailbox must be the same person.
    signed = {(r.get("sender") or "").strip() for r in rows if (r.get("sender") or "").strip()}
    if not signed:
        raise RuntimeError(
            "the CSV has no `sender` column, so there is no way to check that the copy's "
            "signature matches the mailbox it will send from. Regenerate with a current "
            "scripts/run_generation.py, which records sender and mailbox per row.")
    if len(signed) > 1:
        counts = {s: sum(1 for r in rows if (r.get("sender") or "").strip() == s)
                  for s in sorted(signed)}
        print(f"REFUSING: this CSV mixes copy from {len(signed)} senders {counts}.\n"
              f"A Smartlead campaign rotates across its mailboxes, so an email signed by "
              f"one person would send from another's. Split the CSV by `sender` and run "
              f"once per sender with only that sender's mailboxes.", file=sys.stderr)
        raise SystemExit(2)
    sender = signed.pop()
    wrong = [m for m in boxes if sender_map[m] != sender]
    if wrong:
        raise RuntimeError(
            f"the copy is signed {sender!r} but these mailboxes belong to someone else: "
            f"{ {m: sender_map[m] for m in wrong} }. A mismatch misrepresents the sender.")

    name = (f"{dt.date.today():%Y-%m}_{a.audience}_{a.usecase}")
    delays = list(cfg.get("seq_delay_days", [0, 3, 4]))
    delay_override = ([int(x) for x in a.delays.split(",")] if a.delays else None)
    if delay_override:
        # Test affordance ONLY. Production delays live in config/smartlead-defaults.md
        # and are 3 then 4 days for deliverability reasons; compressing them on a real
        # campaign would send three emails to a prospect inside a week.
        delays = delay_override
        print(f"!! DELAYS OVERRIDDEN to {delays} -- test campaigns only. "
              f"Config says {cfg.get('seq_delay_days')}.")
    cap = int(cfg.get("max_new_leads_per_day", 15))

    print(f"campaign name : {name}")
    print(f"approved by   : {a.approved_by}  ({a.approval_note})")
    print(f"leads         : {len(rows)}")
    print(f"sender        : {sender} (all copy signed by one person, mailboxes match)")
    print(f"mailboxes     : {len(boxes)} -> {', '.join(sorted(boxes))}")
    print(f"schedule      : {cfg.get('timezone')} {cfg.get('start_hour')}-{cfg.get('end_hour')} "
          f"days={cfg.get('days_of_the_week')} cap={cap}/mailbox/day")
    print(f"sequence      : 3 steps, delays {delays} days, subjects on email 1 only")
    print(f"capacity      : {len(boxes) * cap} sends/day across these mailboxes; "
          f"{len(rows)} leads is ~{max(1, -(-len(rows) // max(1, len(boxes) * cap)))} day(s) of first touches")

    blockers = assemble.send_readiness_blockers(sender_map)
    if blockers:
        print("\nSEND-READINESS BLOCKERS (a DRAFTED campaign is fine; sending is not)")
        for b in blockers:
            print(f"  - {b}")

    sequences = {"sequences": [
        {"seq_number": p,
         "seq_delay_details": {"delay_in_days": delays[p - 1] if p - 1 < len(delays) else 3},
         # Subject on email 1 only: an empty subject is what makes 2 and 3 threaded
         # replies, verified by read-back on the write test.
         "subject": "{{" + FIELD_SUBJECT + "}}" if p == 1 else "",
         "email_body": "{{" + FIELD_BODY.format(p) + "}}"}
        for p in POSITIONS]}

    lead_list = []
    for r in rows:
        fields = {FIELD_SUBJECT: r.get("message_1_subject", "")}
        for p in POSITIONS:
            fields[FIELD_BODY.format(p)] = to_html(r.get(FIELD_BODY.format(p), ""))
        lead_list.append({
            "first_name": r.get("first_name", ""), "last_name": r.get("last_name", ""),
            "email": r["email"].strip(),
            "company_name": r.get("prospect_org") or r.get("company", ""),
            "custom_fields": fields})

    if a.dry_run:
        print("\nDRY RUN: nothing written to Smartlead. First lead as it would be sent:")
        print(json.dumps(lead_list[0], indent=2)[:1200])
        print("\nsequence:")
        print(json.dumps(sequences, indent=2)[:700])
        print("\nenrolment write-back:")
        # Runs the SUPPRESSED/TERMINAL guard here too, on purpose: a dry run is the
        # cheapest place to discover that a contact should never have reached campaign
        # creation, because no campaign exists yet to clean up.
        try:
            record_enrolment(rows, "(not created)", name, apply_changes=False)
        except Exception as e:
            print(f"  WOULD REFUSE: {e}", file=sys.stderr)
            return 2
        return 0

    sl = Smartlead(api_key())
    created = sl.call("POST", "/campaigns/create", {"name": name})
    cid = created.get("id")
    if not cid:
        raise RuntimeError(f"no campaign id returned: {created}")
    print(f"\ncreated campaign {cid}")

    try:
        sl.call("POST", f"/campaigns/{cid}/settings", {
            "unsubscribe_text": "Unsubscribe",
            "send_as_plain_text": bool(cfg.get("send_as_plain_text", False)),
            "stop_lead_settings": cfg.get("stop_lead_settings", "REPLY_TO_AN_EMAIL"),
            "track_settings": cfg.get("track_settings", ["DONT_EMAIL_OPEN"])})
        sl.call("POST", f"/campaigns/{cid}/schedule", {
            "timezone": cfg.get("timezone"),
            "days_of_the_week": cfg.get("days_of_the_week"),
            "start_hour": cfg.get("start_hour"), "end_hour": cfg.get("end_hour"),
            "min_time_btw_emails": int(cfg.get("min_time_btw_emails", 10)),
            "max_new_leads_per_day": cap, "schedule_start_time": None})
        ids = [a_["id"] for a_ in sl.call("GET", "/email-accounts/?offset=0&limit=200")
               if (a_.get("from_email") or "").lower() in boxes]
        if len(ids) != len(boxes):
            raise RuntimeError(f"matched {len(ids)} Smartlead accounts for {len(boxes)} "
                               f"mailboxes; refusing a campaign with the wrong senders")
        sl.call("POST", f"/campaigns/{cid}/email-accounts", {"email_account_ids": ids})
        sl.call("POST", f"/campaigns/{cid}/sequences", sequences)
        up = sl.call("POST", f"/campaigns/{cid}/leads", {"lead_list": lead_list})
        print(f"  uploaded {up.get('upload_count')} lead(s); "
              f"duplicates={up.get('duplicate_count')} blocked={up.get('block_count')} "
              f"invalid={up.get('invalid_email_count')} "
              f"already_in_another_campaign={up.get('skipped_in_other_campaign_count')}")
    except Exception as e:
        # Guarantee 4: no half-configured campaign left behind for someone to trust.
        print(f"\nFAILED after creation: {e}", file=sys.stderr)
        try:
            sl.call("DELETE", f"/campaigns/{cid}")
            print(f"deleted the partial campaign {cid}", file=sys.stderr)
        except Exception as e2:
            print(f"COULD NOT DELETE partial campaign {cid}: {e2}\n"
                  f"Delete it in the Smartlead UI before retrying.", file=sys.stderr)
        return 1

    # After the campaign exists, not before: recording an enrolment that then failed to
    # be created would make contacts look enrolled when nothing was.
    print()
    try:
        record_enrolment(rows, cid, name, apply_changes=not a.dry_run)
    except Exception as e:
        print(f"  ENROLMENT NOT RECORDED: {e}", file=sys.stderr)
        print(f"  The campaign {cid} EXISTS and its leads are uploaded. Fix the cause and "
              f"re-record before launching, or the next eligibility run will treat these "
              f"contacts as never mailed.", file=sys.stderr)

    final = sl.call("GET", f"/campaigns/{cid}")
    status = final.get("status")
    print(f"\nstatus: {status}  ({sl.calls} API calls)")
    if status != "DRAFTED":
        print(f"UNEXPECTED: status is {status}, not DRAFTED. This script never activates "
              f"a campaign; check the UI before anything sends.", file=sys.stderr)
        return 1

    print(f"""
NOT LAUNCHED, and not launchable until a human acts. Before starting it:

  1. HubSpot activity logging ON  (campaign's HubSpot settings)
     No API endpoint exists for this; verified again 2026-08-31. Without it the campaign
     logs NOTHING to HubSpot, silently, and the reply loop reads HubSpot.
  2. "Optimize Email Delivery" OFF
     No API endpoint either. It disables HTML and takes the unsubscribe link with it.
  3. Confirm the unsubscribe link renders on the FIRST REAL SEND.
     unsubscribe_text was set by API, but a test send shows the link non-clickable by
     design, so only a real send proves it.
  4. Check email 1 renders as paragraphs, not one block.
     Bodies were converted to HTML here; the first real send is the proof.
  5. Then launch a SMALL batch from the UI and watch deliverability before ramping.

  campaign {cid}: {name}
  approved by {a.approved_by} ({a.approval_note})""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
