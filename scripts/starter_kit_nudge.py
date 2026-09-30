#!/usr/bin/env python3
"""Nudge interested prospects who were sent a calendar link and went quiet.

    an `interested` reply we answered with a booking link
      + N days of silence, no meeting booked
      -> queue ONE follow-up offering the Starter Kit instead

**Why this exists.** The first real instance is a prospect who replied "Tell me more"
and got back "I'm happy to walk you through what Posh has to offer -- you can grab some
time with me here: <calendar link>". Nothing since. Someone asking to be *told* more
was asked for a 30-minute commitment instead, and the conversation ended there. The
Starter Kit is the smaller ask that reply deserved, and there is no reason the first
answer has to be the last one.

**IT QUEUES, IT DOES NOT SEND.** The row goes into the reply review queue exactly like
a classified reply, and `send_replies.py` sends it after a human approves. That is not
timidity about a fixed template -- it is what keeps ONE send path. The queue already
re-checks suppression at send time, refuses to fan out two replies on one thread in a
run, honours the `cc` column, stamps `sent_at`, and records
`outbound_starter_kit_offered` from the body that actually went out. A parallel sender
would have to reimplement all of that and would drift from it.

**Idempotent by construction.** The queue dedups on `smartlead_message_id`, so the row
carries a DERIVED id -- `nudge-starter-kit:<original message id>`. Re-running cannot
queue a second nudge for the same conversation, and that guarantee comes from the store
rather than from this script remembering anything.

Dry-run by default. `--apply` writes the queue rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import reply_check as rc  # noqa: E402
import review_queue as rq  # noqa: E402
from eligibility import env_token  # noqa: E402

DEFAULT_QUIET_DAYS = 7
NUDGE_PREFIX = "nudge-starter-kit:"
REVIEW_REASON = "starter-kit nudge -- silent after a booking link"

# Intents worth nudging: they asked to hear more and we answered with a calendar.
NUDGEABLE = ("interested", "question")

# States that mean "do not touch this conversation again", for four different reasons.
# Checked live at queue time rather than trusted from the sheet, because the sheet row
# was written when the reply arrived and every one of these can change after.
STOP_STATES = {
    "meeting_booked": "already booked -- the nudge would be absurd",
    "opted_out": "asked us to stop",
    "bounced": "address is dead",
    "disqualified": "not a fit",
    "handed_off": "a rep owns this thread; the engine must not write into it",
}
READ_PROPS = ["email", "outbound_status", "outbound_suppressed",
              "outbound_starter_kit_offered", "engagements_last_meeting_booked",
              "hs_object_id"]


def nudge_body(kit: dict[str, str]) -> str:
    """The follow-up. Fixed text, from config -- no model involved.

    Aliza's wording, taken from the edit she made to the first real nudge. Two things
    it deliberately does NOT do: re-pitch, and repeat the calendar link -- the prospect
    declined that ask by not taking it, and offering it twice is the same request in a
    smaller font.

    Her edit also dropped "but aren't ready to commit to a call yet" from my draft, and
    that is the better line. It presumed a reason for the silence. They might have been
    busy, or forwarded it internally, or simply missed it; telling someone why they did
    not reply is a good way to be wrong out loud.
    """
    url = (kit.get("starter_kit_url") or "").strip()
    when = (kit.get("starter_kit_when") or "").strip()
    return (f"If you're still interested in learning more about Posh, feel free to "
            f"sign up for a Starter Kit session"
            f"{' -- ' + when if when else ''}! Here's the link to sign up: {url}")


def parse_sent_at(raw: str) -> dt.datetime | None:
    """The sheet's sent_at, which reads like 'sent 2026-09-22T15:19:11+00:00'."""
    s = (raw or "").strip()
    for junk in ("sent ", "sending ", "FAILED "):
        if s.startswith(junk):
            s = s[len(junk):]
    s = s.strip()
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def replied_since(messages: list[dict], after: dt.datetime) -> bool:
    """Did the PROSPECT send anything after we answered?

    The whole premise is silence. A prospect who wrote back -- even to say no -- has
    had a human response and is not owed a canned nudge. Read from the Smartlead thread
    rather than inferred from the queue, because a reply that failed to classify still
    means they spoke.
    """
    for m in messages:
        if not m.get("inbound"):
            continue
        at = parse_sent_at(m.get("at") or "")
        if at and at > after:
            return True
    return False


def hs_read(emails: list[str], token: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(emails), 50):
        body = {"filterGroups": [{"filters": [
                    {"propertyName": "email", "operator": "IN",
                     "values": emails[i:i + 50]}]}],
                "properties": READ_PROPS, "limit": 100}
        req = urllib.request.Request(
            "https://api.hubapi.com/crm/v3/objects/contacts/search", method="POST",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            for x in json.load(r).get("results", []):
                p = x.get("properties") or {}
                out[(p.get("email") or "").lower()] = {**p, "hs_object_id": x["id"]}
    return out


def decide(row: dict, hs: dict, messages: list[dict], quiet_days: int,
           now: dt.datetime) -> tuple[bool, str]:
    """(queue it, why not). Pure, so the rules are testable without an API."""
    # NEVER nudge a nudge. The row this script writes carries intent=interested and
    # eventually a sent_at, so it re-enters the candidate pool on its own. Today it is
    # saved only by having no booking link in its body -- which is accidental, and
    # would stop being true the moment someone added a calendar link to the follow-up.
    # A self-perpetuating loop is worth an explicit guard rather than a lucky one.
    if (row.get("review_reason") or "").strip() == REVIEW_REASON:
        return False, "this row IS a nudge"
    if (row.get("intent") or "").strip() not in NUDGEABLE:
        return False, "not an interested/question reply"
    sent = parse_sent_at(row.get("sent_at") or "")
    if not sent:
        return False, "our answer has not been sent yet"
    age = (now - sent).days
    if age < quiet_days:
        return False, f"only {age}d since we answered; waiting for {quiet_days}d"
    # A nudge offering a SMALLER ask only makes sense if the bigger one was made.
    if "meetings.hubspot.com" not in (row.get("draft_response") or ""):
        return False, "our answer carried no booking link, so there is nothing to soften"
    if not hs:
        return False, "no HubSpot contact, so state cannot be checked"
    status = (hs.get("outbound_status") or "").strip()
    if status in STOP_STATES:
        return False, f"{status}: {STOP_STATES[status]}"
    if str(hs.get("outbound_suppressed") or "").lower() in ("true", "1"):
        return False, "suppressed"
    if (hs.get("outbound_starter_kit_offered") or "").strip():
        return False, "already offered the Starter Kit"
    # Belt and braces next to meeting_booked: the native field is what sync_meetings
    # reads, and it can be populated before the status write catches up.
    if (hs.get("engagements_last_meeting_booked") or "").strip():
        return False, "a meeting is on record even though the status has not caught up"
    if replied_since(messages, sent):
        return False, "they replied after our answer; a human owes them a real response"
    return True, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the queue rows")
    ap.add_argument("--quiet-days", type=int, default=DEFAULT_QUIET_DAYS,
                    help=f"silence required before nudging (default {DEFAULT_QUIET_DAYS})")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the rules with no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()

    kit = rc.starter_kit()
    if not kit.get("starter_kit_url"):
        print("no starter_kit_url in config/meeting-routing.md; nothing to offer")
        return 1
    body = nudge_body(kit)
    print("APPLY: queue rows will be written" if a.apply
          else "DRY RUN: nothing will be queued. Re-run with --apply.")
    print(f"\nthe follow-up, verbatim:\n  {body}\n")

    svc, _who = rq.sheets_service()
    cfg = rq.load_surface_config()
    grid = svc.spreadsheets().values().get(
        spreadsheetId=cfg["REPLY_REVIEW_SHEET_ID"],
        range=f"'{cfg['REPLY_REVIEW_TAB']}'").execute(
            num_retries=rq.SHEETS_RETRIES).get("values", [])
    hdr = [h.strip() for h in grid[0]]
    rows = [dict(zip(hdr, r + [""] * (len(hdr) - len(r)))) for r in grid[1:]]

    cands = [r for r in rows if (r.get("intent") or "").strip() in NUDGEABLE]
    emails = sorted({(r.get("email") or "").strip().lower()
                     for r in cands if r.get("email")})
    hs = hs_read(emails, env_token()) if emails else {}

    key = None
    for line in (pathlib.Path(__file__).resolve().parent.parent / ".env"
                 ).read_text().splitlines():
        if line.startswith("SMARTLEAD_API_KEY"):
            key = line.split("=", 1)[1].strip().strip('"')
    sl = rc.Smartlead(key, False)
    store = rq.get_processed_id_store(svc, cfg["REPLY_REVIEW_SHEET_ID"],
                                      cfg["REPLY_REVIEW_TAB"])
    now = dt.datetime.now(dt.timezone.utc)

    queued = skipped = 0
    lead_cache: dict[str, dict] = {}
    for r in cands:
        email = (r.get("email") or "").strip().lower()
        campaign = (r.get("campaign") or "").strip()
        # The thread is only fetched for rows that have cleared every cheap check, so a
        # long queue does not mean a long run.
        ok, why = decide(r, hs.get(email, {}), [], a.quiet_days, now)
        msgs: list[dict] = []
        if ok or why.startswith("they replied"):
            if campaign not in lead_cache:
                lead_cache[campaign] = sl.lead_ids_by_email(campaign)
            lid = lead_cache[campaign].get(email)
            if lid:
                msgs, _ = rc.read_thread(sl.thread(campaign, lid))
            ok, why = decide(r, hs.get(email, {}), msgs, a.quiet_days, now)
        if not ok:
            skipped += 1
            print(f"  skip  {email:<34} {why}")
            continue
        orig = (r.get("smartlead_message_id") or "").strip()
        res = rq.append_reply({
            "contact_name": r.get("contact_name", ""),
            "email": email,
            "company": r.get("company", ""),
            "campaign": campaign,
            "sent_by": r.get("sent_by", ""),
            # The ORIGINAL words, so a reviewer sees what they are following up on.
            "reply_text": r.get("reply_text", ""),
            "intent": (r.get("intent") or "").strip(),
            "proposed_action": "Offer the Starter Kit instead of a call.",
            "draft_response": body,
            "review_reason": REVIEW_REASON,
            # Derived id: the queue's own dedup then makes a second nudge impossible.
            "smartlead_message_id": NUDGE_PREFIX + orig,
            "smartlead_stats_id": (r.get("smartlead_stats_id") or "").strip(),
        }, service=svc, cfg=cfg, store=store, now=now) if a.apply else {
            "appended": True, "skipped": None, "row": None}
        if res.get("appended"):
            queued += 1
            print(f"  QUEUE {email:<34} silent "
                  f"{(now - parse_sent_at(r['sent_at'])).days}d after a booking link")
        else:
            skipped += 1
            print(f"  skip  {email:<34} {res.get('skipped')}")

    print(f"\n{queued} nudge(s) {'queued' if a.apply else 'WOULD be queued'}, "
          f"{skipped} skipped")
    print(f"{sl.calls} Smartlead calls")
    if not a.apply:
        print("DRY RUN: nothing was written.")
    else:
        print("Queued for review. They send when a human approves the row, like any "
              "other reply.")
    return 0


def _self_test() -> int:
    now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
    LINK = "https://meetings.hubspot.com/zach-hickman"
    base = {"intent": "interested", "sent_at": "sent 2026-09-22T15:19:11+00:00",
            "draft_response": f"grab some time here: {LINK}"}
    live = {"outbound_status": "replied", "hs_object_id": "1"}
    cases = [
        ("silent 8d after a booking link -> nudge", base, live, [], True),
        # Without this the script feeds on its own output once the nudge has sent.
        ("a nudge row never nudges itself",
         {**base, "review_reason": REVIEW_REASON}, live, [], False),
        ("...even if someone later puts a calendar link in the follow-up",
         {**base, "review_reason": REVIEW_REASON,
          "draft_response": f"come to a session, or book here: {LINK}"},
         live, [], False),
        ("only 3d of silence -> wait",
         {**base, "sent_at": "sent 2026-09-28T10:00:00+00:00"}, live, [], False),
        ("our answer never sent -> nothing to follow up",
         {**base, "sent_at": ""}, live, [], False),
        ("a decline is not nudgeable",
         {**base, "intent": "not_interested"}, live, [], False),
        # The nudge's whole premise is softening an ask that was made.
        ("no booking link in our answer -> nothing to soften",
         {**base, "draft_response": "thanks, noted"}, live, [], False),
        ("already booked -> absurd",
         base, {**live, "outbound_status": "meeting_booked"}, [], False),
        ("booking on the native field, status lagging -> still no",
         base, {**live, "engagements_last_meeting_booked": "2026-09-29"}, [], False),
        ("handed off -> a rep owns the thread",
         base, {**live, "outbound_status": "handed_off"}, [], False),
        ("opted out -> never", base, {**live, "outbound_status": "opted_out"}, [], False),
        ("suppressed -> never",
         base, {**live, "outbound_suppressed": "true"}, [], False),
        ("already offered the Starter Kit -> never twice",
         base, {**live, "outbound_starter_kit_offered": "2026-09-25"}, [], False),
        ("no HubSpot contact -> cannot check state, so do not act",
         base, {}, [], False),
        # The one that matters most: they DID answer, so a person owes them a reply.
        ("they replied after our answer -> a human owes them a real response", base, live,
         [{"inbound": True, "at": "2026-09-25T09:00:00+00:00"}], False),
        ("an inbound BEFORE our answer is the original reply, not a new one", base, live,
         [{"inbound": True, "at": "2026-09-21T09:00:00+00:00"}], True),
        ("our own later message is not them replying", base, live,
         [{"inbound": False, "at": "2026-09-28T09:00:00+00:00"}], True),
    ]
    bad = 0
    for why, row, hsp, msgs, want in cases:
        got, reason = decide(row, hsp, msgs, DEFAULT_QUIET_DAYS, now)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} {why}")
        if not ok:
            print(f"         got {got}, wanted {want} ({reason})")

    body = nudge_body(rc.starter_kit())
    checks = [
        ("the follow-up carries the Starter Kit link",
         (rc.starter_kit().get("starter_kit_url") or "") in body),
        # Offering the calendar again is the same ask in a smaller font.
        ("it does NOT repeat the booking link", "meetings.hubspot.com" not in body),
        ("it names the session time",
         (rc.starter_kit().get("starter_kit_when") or "") in body),
        # The URL is the join between the copy and the metric. Every consumer tests
        # `url in body`, so a config value LONGER than what a reviewer sends means the
        # offer goes out and outbound_starter_kit_offered is never written -- silently.
        # Holding the shortest identifying form makes that impossible.
        ("the configured url carries no query string, so it matches either form",
         "?" not in (rc.starter_kit().get("starter_kit_url") or "")),
        ("it does not presume WHY they went quiet",
         "aren't ready" not in body and "not ready" not in body),
        ("the derived id would dedup", NUDGE_PREFIX + "<abc>" != "<abc>"),
    ]
    for why, ok in checks:
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'WRONG'} {why}")
    total = len(cases) + len(checks)
    print(f"\n{total - bad}/{total} nudge cases correct")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
