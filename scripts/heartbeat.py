#!/usr/bin/env python3
"""The scheduled run: do the polling jobs, then report to Slack every single time.

Invoked by the Claude Desktop scheduled task described in
`instructions/scheduled-tasks.md`. Business-hours cadence, weekdays.

    slot=morning   -> reply check + unsubscribe sync
    slot=midday    -> reply check
    slot=afternoon -> reply check

**The heartbeat is the point, and "every time" is what makes it one.** A report that
only appears when something happened cannot be told apart from a job that never ran, and
the failure this exists to catch is exactly that: a laptop asleep at 8am, a cron that
silently stopped, an expired token. So this posts on quiet runs too. A quiet run says
"checked, nothing to do". Silence in the channel means BROKEN, and that is the only
reading it should ever have.

Five guarantees:

  1. IT ALWAYS POSTS. Success, nothing-to-do, or crash. A job that throws is caught,
     reported to Slack with its output, and turned into a non-zero exit — never a silent
     death.
  2. ONE JOB FAILING DOES NOT CANCEL THE OTHER. Each runs in its own subprocess and is
     reported independently, so a Smartlead outage during the reply check does not also
     skip the unsubscribe sync.
  3. DRY RUN BY DEFAULT, inherited by the jobs it runs. `--apply` is required and is
     passed down explicitly. A scheduled task that writes on its first run, unattended,
     before anyone has read what it decided, is the thing to avoid.
  4. IT NEVER SILENTLY SKIPS SLACK. An unconfigured or rejected Slack post is a loud
     failure with a non-zero exit, not a shrug. A heartbeat that quietly stops
     heartbeating is worse than having none, because it reads as healthy.
  5. IT ADDS NO NEW POWERS. It only shells the two existing scripts. It cannot send mail,
     launch a campaign, or write anything they would not write.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from reply_check import env_value  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

# Which jobs run in which slot. The unsubscribe sync walks every lead on every campaign,
# so it is the expensive one and runs once a day; the reply check is cheap (it only pulls
# message history for leads already marked replied) and runs every slot.
SLOTS = {
    "morning":   ["reply_check", "sync_unsubscribes"],
    "midday":    ["reply_check"],
    "afternoon": ["reply_check"],
}
JOB_LABELS = {"reply_check": "Reply check", "sync_unsubscribes": "Unsubscribe sync"}

# Pulled out of each job's stdout for the Slack summary. Best-effort by design: if a
# pattern stops matching, the message gets less pretty, never wrong -- the raw tail is
# posted instead. Parsing must not be able to turn a real result into a false one.
SUMMARY_PATTERNS = [
    re.compile(r"^\d+ reply\(s\) processed.*$", re.M),
    re.compile(r"^\d+ to suppress.*$", re.M),
    re.compile(r"^no campaigns in the account.*$", re.M),
    re.compile(r"^no unsubscribes found.*$", re.M),
]


def run_job(name: str, apply_changes: bool) -> dict:
    """Run one job in its own process. Never raises: a crash is a reported result."""
    cmd = [PY, str(ROOT / "scripts" / f"{name}.py")] + (["--apply"] if apply_changes else [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=ROOT)
        out = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0
    except subprocess.TimeoutExpired:
        return {"job": name, "ok": False, "summary": "timed out after 15 minutes",
                "tail": "", "attention": True}
    except Exception as e:                                    # guarantee 1
        return {"job": name, "ok": False, "summary": f"could not start: {e}",
                "tail": "", "attention": True}

    lines = [m.group(0).strip() for pat in SUMMARY_PATTERNS for m in pat.finditer(out)]
    summary = "; ".join(lines) if lines else (out.strip().splitlines() or ["(no output)"])[-1]
    return {"job": name, "ok": ok, "summary": summary,
            "tail": "\n".join(out.strip().splitlines()[-15:]),
            "attention": needs_attention(out)}


# Counts that mean a human has something to do. Read as NUMBERS, not as substrings: an
# earlier version searched for "queued for review" and lit the amber light on a run that
# said "0 queued for review". The colour is the whole signal, so it has to be exact.
ATTENTION_COUNTS = [
    re.compile(r"(\d+) queued for review"),      # reply_check: replies awaiting a human
    re.compile(r"(\d+) to suppress"),            # sync: suppressions to write
    re.compile(r"(\d+) unmatched"),              # sync: unsubscribes HubSpot cannot record
]


def needs_attention(out: str) -> bool:
    """True when this run found something a person should look at today."""
    return any(int(m.group(1)) > 0
               for pat in ATTENTION_COUNTS for m in pat.finditer(out))


def post_to_slack(text: str, blocks: list | None = None) -> None:
    """Post the heartbeat. Raises on any failure -- guarantee 4.

    Slack answers 200 with {"ok": false, "error": ...} on a rejected post, so the BODY
    is what decides success. Checking only the HTTP status is the classic way to build a
    heartbeat that reports healthy while posting nothing.
    """
    token = env_value("SLACK_BOT_TOKEN")
    channel = env_value("SLACK_HEARTBEAT_CHANNEL") or env_value("SLACK_REVIEW_CHANNEL")
    if not token or not channel:
        raise RuntimeError(
            "Slack is not configured: set SLACK_BOT_TOKEN and SLACK_HEARTBEAT_CHANNEL "
            "(or SLACK_REVIEW_CHANNEL) in .env. Refusing to run silently -- a heartbeat "
            "nobody receives reads as healthy, which is the failure it exists to catch.")
    body = {"channel": channel, "text": text}
    if blocks:
        body["blocks"] = blocks
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Slack post failed: HTTP {e.code} "
                           f"{(e.read() or b'').decode()[:200]}") from None
    if not payload.get("ok"):
        raise RuntimeError(
            f"Slack rejected the post: {payload.get('error')!r}. "
            "Common causes: the bot is not in the channel (invite it), the channel id is "
            "wrong, or the token lacks chat:write.")


def check_slack() -> int:
    """Diagnose the Slack setup without posting into the channel.

    Separates the three things that fail independently -- the token, the channel id, and
    whether the bot was invited -- because Slack reports all three as a post that simply
    did not appear, and guessing which one is wrong wastes the most setup time.
    """
    token = env_value("SLACK_BOT_TOKEN")
    channel = env_value("SLACK_HEARTBEAT_CHANNEL") or env_value("SLACK_REVIEW_CHANNEL")
    print(f"token   : {'set, ' + token[:5] + '...' if token else 'MISSING'}")
    print(f"channel : {channel or 'MISSING (set SLACK_HEARTBEAT_CHANNEL)'}")
    if not token:
        print("\nSet SLACK_BOT_TOKEN in .env. It is the Bot User OAuth Token and starts "
              "with xoxb-, not the app-level xapp- token.")
        return 1
    if not token.startswith("xoxb-"):
        print(f"\nWARNING: the token starts {token[:5]!r}, not 'xoxb-'. A bot token is "
              "what chat.postMessage needs; xapp- and xoxp- tokens will not work here.")

    def api(method: str, params: str = ""):
        req = urllib.request.Request(
            f"https://slack.com/api/{method}{params}",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")

    who = api("auth.test")
    if not who.get("ok"):
        print(f"\nTOKEN REJECTED: {who.get('error')!r}")
        print("  invalid_auth / token_revoked -> the token is wrong or the app was "
              "uninstalled. Re-copy it from OAuth & Permissions.")
        return 1
    print(f"\nauthenticated as {who.get('user')!r} in workspace {who.get('team')!r}")

    if not channel:
        return 1
    info = api("conversations.info", f"?channel={channel}")
    if not info.get("ok"):
        err = info.get("error")
        print(f"CHANNEL PROBLEM: {err!r}")
        if err == "channel_not_found":
            print("  Either the id is wrong, or it is a private channel the bot cannot "
                  "see. Use the id from the channel's About tab (starts with C).")
        return 1
    ch = info.get("channel") or {}
    member = ch.get("is_member")
    print(f"channel #{ch.get('name')} found; bot is "
          f"{'a member' if member else 'NOT a member'}")
    if not member:
        print(f"  Invite it: type  /invite @{who.get('user')}  in #{ch.get('name')}.")
        print("  Without this every post fails with not_in_channel and the heartbeat "
              "cannot report anything, including its own failure.")
        return 1
    print("\nSlack is ready. Post a real heartbeat with:")
    print("  ./.venv/bin/python scripts/heartbeat.py --slot morning")
    return 0


def render(slot: str, results: list[dict], apply_changes: bool) -> tuple[str, list]:
    failed = [r for r in results if not r["ok"]]
    attention = [r for r in results if r["ok"] and r["attention"]]
    icon = "🔴" if failed else ("🟡" if attention else "🟢")
    mode = "" if apply_changes else "  _dry run_"
    when = dt.datetime.now().strftime("%a %d %b, %H:%M")
    head = (f"{icon} *Outbound engine — {slot} check*  ·  {when}{mode}")
    lines = [head]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"{mark} *{JOB_LABELS.get(r['job'], r['job'])}* — {r['summary']}")
    if failed:
        lines.append("")
        for r in failed:
            lines.append(f"```{r['tail'][:1200]}```")
    text = "\n".join(lines)
    return text, [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scheduled outbound check with a Slack heartbeat.")
    ap.add_argument("--slot", choices=sorted(SLOTS), default="morning",
                    help="which scheduled run this is; decides which jobs run")
    ap.add_argument("--apply", action="store_true",
                    help="pass --apply to the jobs so they WRITE. Off by default.")
    ap.add_argument("--check-slack", action="store_true",
                    help="diagnose the Slack token, channel and bot invite without "
                         "posting anything. Run this first after setting up the app.")
    ap.add_argument("--no-slack", action="store_true",
                    help="print the report instead of posting it. For setup testing only "
                         "-- never use this in the scheduled task, it disables the heartbeat.")
    a = ap.parse_args(argv)

    if a.check_slack:
        return check_slack()

    results = [run_job(name, a.apply) for name in SLOTS[a.slot]]   # guarantee 2
    text, blocks = render(a.slot, results, a.apply)
    print(text)

    if a.no_slack:
        print("\n--no-slack: not posted. The scheduled task must NOT use this flag.")
    else:
        try:
            post_to_slack(text, blocks)
            print("\nposted to Slack")
        except RuntimeError as e:
            print(f"\nHEARTBEAT FAILED TO POST: {e}", file=sys.stderr)
            return 2                                              # guarantee 4
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
