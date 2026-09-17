#!/usr/bin/env python3
"""The scheduled run: do the polling jobs, then report to Slack every single time.

Invoked by the Claude Desktop scheduled task described in
`instructions/scheduled-tasks.md`. Business-hours cadence, weekdays.

    slot=morning   -> approved replies, approved campaigns, reply check + the syncs
    slot=midday    -> reply check
    slot=afternoon -> reply check
    slot=weekly    -> the campaign review (Mondays, its own routine)

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
  5. IT CAN SEND MAIL, AND THAT IS THE ONE POWER TO WATCH. Until 2026-09-09 this script
     could only read and write records, and this guarantee said so. Adding `send_replies`
     to the morning slot means an unattended scheduled run can now put a message in a
     prospect's inbox, so the old wording would have been a lie left in place.
     **What makes that safe is not the heartbeat.** It is `send_replies` guarantee 2: a
     row sends only if a human typed `Approve` into it. The heartbeat contributes no
     judgement of its own and must never be given any — it decides *when to look*, never
     *what to send*. Do not add a job here that originates a message.
     It still cannot LAUNCH a campaign. `build_approved` was added to the morning slot
     on 2026-09-14 and it CREATES campaigns, but only DRAFTED ones, only from rows a
     human marked `Approved` in the review Sheet, and launching remains a manual act in
     the Smartlead UI because the unsubscribe settings have no API.
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
#
# `send_replies` runs FIRST, and only in the morning. First because approvals left in the
# sheet overnight should go out at the top of the business day rather than after several
# minutes of syncing. Morning-only because one daily batch is legible -- a reviewer can
# see the whole day's sends in one Slack line -- where replies trickling out at three
# separate times of day is harder to audit and no faster in any way that matters.
# Adding it to another slot is a one-line change if same-day turnaround is wanted.
#
# `resume_sequences` runs AFTER `close_sequences`, and that order is load-bearing rather
# than tidy: both read the same out-of-office lead, `outbound_resume_after` is the only
# thing distinguishing it from a finished non-responder, close_sequences refuses to close
# while that date is set, and resume_sequences clears it. Reverse them and the date is
# gone before close_sequences looks, so it closes the lead that was just revived. See the
# docstring in resume_sequences.py.
#
# `sync_meetings` runs LAST, and only in the morning. Last because it promotes a status
# every job ahead of it may have just written -- reply_check sets `replied`,
# close_sequences sets `no_response`, and a booking supersedes either -- so reading after
# they have all settled means one pass sees the day's final state instead of racing it.
# Morning-only because it feeds the weekly report rather than anything time-sensitive:
# `meeting_booked` is a number a human reads on a dashboard, and recording it hours
# earlier changes nothing for the prospect, who has already got the meeting.
SLOTS = {
    "morning":   ["send_replies", "build_approved", "reply_check", "sync_unsubscribes",
                   "sync_bounces", "close_sequences", "resume_sequences", "sync_sends",
                   "sync_meetings"],
    # `build_approved` is MORNING ONLY, by decision on 2026-09-14. It was briefly in all
    # three slots so an approval reached a campaign within hours; that was reverted
    # because it produces one campaign PER BATCH, and a reviewer approving a list over a
    # morning would get two or three campaigns for one list -- each needing its own
    # unsubscribe toggles in the Smartlead UI, since those have no API.
    #
    # One slot a day means one review sitting maps to one campaign per list, which is
    # what a human actually wants to manage. The cost is that an afternoon approval waits
    # until the next morning, and that is the right trade: the prospect is not waiting on
    # hours, and the reviewer is spared duplicate UI work.
    "midday":    ["reply_check"],
    # `sync_sends` added to the AFTERNOON slot 2026-09-17, and the reason is a real
    # complaint rather than tidiness. It ran morning-only, so the three campaigns
    # launched after the 10:07 heartbeat sent 40 emails that appeared NOWHERE in HubSpot
    # for the rest of the day -- and this job is **the only way a rep sees our sends at
    # all**, both vendor paths being unavailable (see CLAUDE.md on the corrected activity
    # -logging caveat). A rep opening a contact we emailed that morning saw an untouched
    # record, which is worse than a missing feature: it reads as "we never contacted
    # them" and invites a duplicate touch.
    #
    # Afternoon rather than all three slots. Sends run 09:00-17:00 ET, so the ~16:35 run
    # catches nearly a full day before anyone looks in the evening, and the lag drops
    # from up to 24 hours to a few. Midday would trim it further and is a one-word
    # change; it is left off because the cost is not free -- the job fetches a thread per
    # lead (253 Smartlead calls at 247 leads, so roughly one per lead) and that scales
    # with every campaign still ACTIVE. Two runs a day is the compromise: revisit if reps
    # ask for same-hour visibility, and optimise the per-lead fetch first if so.
    "afternoon": ["reply_check", "sync_sends"],
    # Mondays only, via its own routine. Separate from the daily slots because it is a
    # REPORT, not a job that keeps state correct -- running it daily would append six
    # near-identical history rows a week and bury the weekly signal it exists to show.
    "weekly":    ["campaign_report"],
}
JOB_LABELS = {"reply_check": "Reply check", "sync_unsubscribes": "Unsubscribe sync",
              "sync_bounces": "Bounce sync",
              "close_sequences": "Sequence close-out",
              "sync_sends": "Activity logging",
              "send_replies": "Approved replies",
              "resume_sequences": "Out-of-office restarts",
              "campaign_report": "Weekly campaign review",
              "sync_meetings": "Meetings booked",
              "build_approved": "Approved campaigns"}

# Extra arguments per job. `send_replies` is capped because the heartbeat runs it
# unattended and nobody reads a dry run first: a reviewer who drag-fills `Approve` down
# the decision column would otherwise fan out every row of the sheet in one unsupervised
# burst, as real messages to real prospects. The cap turns that mistake into a slow and
# visible one instead of an irreversible one. Rows over the cap are left untouched and
# reported, never silently dropped.
JOB_ARGS = {"send_replies": ["--limit", "25"],
            # Writes the history row AND posts its own detailed summary. That means two
            # Slack messages on a Monday: the report itself, and the heartbeat's health
            # line saying the job ran green. Deliberate -- "did it run" and "what did it
            # find" are different questions, and if the report dies the heartbeat is
            # still what tells you.
            "campaign_report": ["--write", "--slack", "--include-completed"]}

# Pulled out of each job's stdout for the Slack summary. Best-effort by design: if a
# pattern stops matching, the message gets less pretty, never wrong -- the raw tail is
# posted instead. Parsing must not be able to turn a real result into a false one.
SUMMARY_PATTERNS = [
    re.compile(r"^\d+ reply\(s\) processed.*$", re.M),
    re.compile(r"^\d+ to suppress.*$", re.M),
    re.compile(r"^no campaigns in the account.*$", re.M),
    re.compile(r"^no unsubscribes found.*$", re.M),
    re.compile(r"^\d+ recorded, \d+ skipped.*$", re.M),      # sync_bounces
    re.compile(r"^no bounced rows found.*$", re.M),
    re.compile(r"^\d+ closed, \d+ already current.*$", re.M),   # close_sequences
    re.compile(r"^no finished sequences.*$", re.M),
    re.compile(r"^\d+ engagement\(s\) (?:written|would be written).*$", re.M),
    re.compile(r"^\d+ sent, \d+ already sent, \d+ failed.*$", re.M),   # send_replies
    re.compile(r"^\d+ resumed, \d+ blocked.*$", re.M),            # resume_sequences
    re.compile(r"^no contact has a resume date.*$", re.M),
    re.compile(r"^\d+ promoted, \d+ already current.*$", re.M),    # sync_meetings
    re.compile(r"^no engine-enrolled contact has booked.*$", re.M),
    re.compile(r"^history: .*$", re.M),                          # campaign_report
    re.compile(r"^\d+ campaign\(s\) built.*$", re.M),            # build_approved
]


def run_job(name: str, apply_changes: bool) -> dict:
    """Run one job in its own process. Never raises: a crash is a reported result."""
    cmd = ([PY, str(ROOT / "scripts" / f"{name}.py")]
           + (["--apply"] if apply_changes else []) + JOB_ARGS.get(name, []))
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
    # Matches both "queued for review" and the dry-run "WOULD be queued", so amber
    # still lights when a dry run finds work waiting.
    re.compile(r"(\d+) (?:queued for review|WOULD be queued)"),
    re.compile(r"(\d+) to suppress"),            # sync: suppressions to write
    re.compile(r"(\d+) unmatched"),              # sync: unsubscribes HubSpot cannot record
    re.compile(r"(\d+) recorded"),               # bounces newly written
    re.compile(r"(\d+) unmatched"),              # a finished lead with no contact
    # A reply a human approved that did NOT go out. Both of these mean a prospect is
    # waiting on an answer someone already signed off, which is the worst kind of silence
    # this system can produce, so they light the amber.
    re.compile(r"(\d+) failed"),                 # send_replies: refused by Smartlead
    re.compile(r"(\d+) approved row\(s\) NOT sent"),   # send_replies: over the cap
    # A campaign was built and is DRAFTED: it needs a human in the Smartlead UI before
    # it can send, so the amber light is the prompt to go and do that.
    re.compile(r"(\d+) campaign\(s\) built"),
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

    # Inspecting the channel first would be tidier, but conversations.info needs
    # channels:read and the heartbeat does not. Demanding a read scope purely to run a
    # setup check would be the diagnostic dictating the app's permissions, which is
    # backwards. With chat:write alone the only honest verification is to post, so this
    # posts one clearly-labelled test message. That also tests the real code path rather
    # than a proxy for it.
    print("posting a test message (this is the only way to verify the channel and the "
          "invite with chat:write alone)...")
    try:
        post_to_slack(":wrench: Outbound engine setup test — heartbeat can post here. "
                      "Scheduled runs will report to this channel.")
    except RuntimeError as e:
        msg = str(e)
        print(f"FAILED: {msg}")
        if "not_in_channel" in msg:
            print(f"  The bot is not in the channel. Type  /invite @{who.get('user')}  "
                  "in it. This is the step that is usually missing.")
        elif "channel_not_found" in msg:
            print("  Wrong channel id, or a private channel the bot cannot see. Copy the "
                  "id from the channel's About tab; it starts with C.")
        elif "missing_scope" in msg:
            print("  The token lacks chat:write. Add it under Bot Token Scopes, then "
                  "re-install the app to the workspace.")
        return 1
    print("\nposted. Slack is ready.")
    print("  ./.venv/bin/python scripts/heartbeat.py --slot morning   # a real heartbeat")
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
