#!/usr/bin/env python3
"""Notice when the heartbeat has stopped, and say so in Slack.

    no heartbeat post for N business hours  ->  one warning in the channel

**Why this exists.** `heartbeat.py` guarantee 4 says a heartbeat that quietly stops
heartbeating is worse than having none, because it reads as healthy. That is exactly
what happened over the weekend of 2026-09-18: the last post was Friday 22:49 and nothing
followed on Monday, because the laptop was asleep or off all day. The engine did not
fail -- it never ran -- and the channel looked like a quiet weekend either way. The owner
found out by coming back and scrolling.

**The heartbeat cannot report its own silence. Something else has to.** The launchd
intake job is the right something: it survived the same outage and resumed at 08:57 on
the Tuesday, because launchd restarts a StartInterval job on wake without anyone
re-enabling it. So the watchdog rides along with the job that is already proven to come
back.

Three guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required to post.
  2. **IT WARNS ONCE PER OUTAGE, NOT ONCE PER CHECK.** Running every 5 minutes, a naive
     version would post 12 warnings an hour and be muted within a day -- which would
     leave the channel worse off than silence. A marker file records the last warning;
     the next one waits for `--repeat-after` hours.
  3. IT ONLY COUNTS BUSINESS HOURS. The heartbeat is a weekday 09:45/13:05/16:25
     schedule, so a quiet Saturday is correct and must not warn. The threshold is in
     WORKING hours elapsed, not wall clock.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import env_value  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Not in logs/ -- that is git-ignored and gets cleared; this must survive a tidy-up.
MARKER = ROOT / ".heartbeat-watchdog-state.json"
BUSINESS_DAYS, BUSINESS_START, BUSINESS_END = range(0, 5), 9, 18


def business_hours_between(a: dt.datetime, b: dt.datetime) -> float:
    """Working hours between two local datetimes. Weekends and nights count as zero.

    Hour by hour rather than analytically: the arithmetic version needs to handle
    partial days, weekends and the two boundaries at once, and this runs every five
    minutes over a span of days, so clarity is worth more than the microseconds.
    """
    if b <= a:
        return 0.0
    total, cur = 0.0, a.replace(minute=0, second=0, microsecond=0)
    while cur < b:
        if cur.weekday() in BUSINESS_DAYS and BUSINESS_START <= cur.hour < BUSINESS_END:
            total += 1
        cur += dt.timedelta(hours=1)
    return total


def last_heartbeat(token: str, channel: str) -> tuple[dt.datetime | None, str]:
    """(when the engine last posted a heartbeat, its first line)."""
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.history?channel={channel}&limit=60",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    if not d.get("ok"):
        raise RuntimeError(f"slack: {d.get('error')}")
    for m in d.get("messages") or []:
        text = m.get("text") or ""
        # The heartbeat's own header, in every slot and every state.
        if "Outbound engine —" in text and "check" in text:
            return (dt.datetime.fromtimestamp(float(m["ts"])),
                    text.splitlines()[0][:120])
    return None, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Warn in Slack when the heartbeat has stopped. Dry run by default.")
    ap.add_argument("--apply", action="store_true", help="actually post the warning")
    ap.add_argument("--after-hours", type=float, default=5.0,
                    help="warn after this many BUSINESS hours with no heartbeat. "
                         "Default 5: the slots are ~3.5 working hours apart, so one "
                         "missed slot alone is not evidence of a stop.")
    ap.add_argument("--repeat-after", type=float, default=24.0,
                    help="hours before the same outage is reported again")
    a = ap.parse_args(argv)

    token, channel = env_value("SLACK_BOT_TOKEN"), env_value("SLACK_REQUEST_CHANNEL")
    alert_channel = env_value("SLACK_REVIEW_CHANNEL") or channel
    if not token or not alert_channel:
        print("SLACK_BOT_TOKEN or channel missing; cannot check.")
        return 1

    when, first_line = last_heartbeat(token, alert_channel)
    now = dt.datetime.now()
    if when is None:
        print("no heartbeat post found in the last 60 messages; not warning — "
              "this looks like the wrong channel rather than an outage.")
        return 0

    idle = business_hours_between(when, now)
    print(f"last heartbeat: {when:%a %d %b %H:%M}  ({idle:.1f} business hours ago)")
    print(f"  {first_line}")
    if idle < a.after_hours:
        print(f"within the {a.after_hours}h threshold; nothing to do.")
        return 0

    # Guarantee 2.
    state = {}
    if MARKER.exists():
        try:
            state = json.loads(MARKER.read_text())
        except Exception:
            state = {}
    last_warn = state.get("warned_at")
    if last_warn:
        since = (now - dt.datetime.fromisoformat(last_warn)).total_seconds() / 3600
        if since < a.repeat_after and state.get("for_heartbeat") == when.isoformat():
            print(f"already warned {since:.1f}h ago for this same outage; not repeating.")
            return 0

    msg = (f":rotating_light: *The outbound heartbeat has not run for "
           f"{idle:.0f} business hours.*\n"
           f"Last post: {when:%a %d %b, %H:%M}.\n"
           f"The engine is not broken — it is not running. Nothing is being sent, no "
           f"replies are being classified, and no HubSpot activity is being logged "
           f"while this is true.\n"
           f"Usual cause is the laptop asleep or the Claude Desktop routines paused. "
           f"Check that `outbound-morning` / `-midday` / `-afternoon` are enabled and "
           f"the machine is awake at 09:45, 13:05 and 16:25.")
    print("\n" + msg)
    if not a.apply:
        print("\nDRY RUN: not posted.")
        return 0
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", method="POST",
        data=json.dumps({"channel": alert_channel, "text": msg}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    if not d.get("ok"):
        print(f"slack refused: {d.get('error')}")
        return 1
    MARKER.write_text(json.dumps({"warned_at": now.isoformat(),
                                  "for_heartbeat": when.isoformat()}))
    print("posted, and recorded so it is not repeated for "
          f"{a.repeat_after:.0f}h.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
