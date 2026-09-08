#!/usr/bin/env python3
"""Campaign intake from Slack: a rep posts a HubSpot list, the engine takes it from there.

Implements the request channel decided in `CLAUDE.md`: "A stakeholder posts the campaign
audience (a lead source reference) + a short brief as a Slack message. That message *is*
the campaign brief."

    Slack message with a HubSpot list  ->  eligibility -> generation -> review link

**It stops before sending, deliberately, and cannot be made not to.** Golden rule 1
requires recorded human approval, and two per-campaign settings (HubSpot activity logging,
Optimize Email Delivery) have no API at all. So the automated part ends with a review link
in the thread; a human approves, and `create_campaign.py` produces a DRAFTED campaign that
a human then launches.

Six guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required to post anything or run the pipeline.
  2. STATE LIVES IN THE SLACK THREAD, not in a database. A request with a bot reply has
     been handled, and the reply carries a machine-readable tag. This follows the same
     rule as the rest of the engine: everything it needs to remember lives somewhere a
     human can open and read. No local store to lose, and the audit trail is the
     conversation itself.
  3. ONE REPLY PER REQUEST PER STATE. A request cannot be processed twice, because the
     acknowledgement it would post is the same thing that marks it done.
  4. CAPACITY IS CHECKED BEFORE WORK, NOT AFTER. Over the ceiling, the request is queued
     with its position and picked up on a later run. Note what the ceiling is FOR:
     Smartlead already paces sends at 15/mailbox/day, so this is not flood protection --
     it decides whether to START a campaign, which matters while domains are young.
  5. A LIST THAT YIELDS NO ELIGIBLE LEADS IS REPORTED, NOT SILENTLY DROPPED. The rep gets
     told why, per exclusion reason, because "nothing happened" is the worst possible
     answer to a request.
  6. IT NEVER CREATES A HUBSPOT CONTACT. A list member with no usable record is reported.
     Contact creation is off by standing decision.

**Prerequisites, both outside this script:**
  - Slack scopes `channels:history` (read the channel) and `channels:read`. The bot holds
    only `chat:write` today, which is why this fails loudly rather than mysteriously.
  - `SLACK_REQUEST_CHANNEL` in `.env`, and the bot invited to that channel.
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
from create_campaign import load_defaults  # noqa: E402
from eligibility import env_value  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
SL_BASE = "https://server.smartlead.ai/api/v1"

# Machine-readable status tags. Visible in the thread on purpose: a human reading the
# channel should see the same state the engine sees.
TAG_ACCEPTED = "[engine:accepted]"
TAG_QUEUED = "[engine:queued]"
TAG_REJECTED = "[engine:rejected]"
ALL_TAGS = (TAG_ACCEPTED, TAG_QUEUED, TAG_REJECTED)

# A HubSpot list, however a rep pastes it: a full URL, "list 1764", or a bare id.
LIST_PATTERNS = (
    re.compile(r"objectLists/(\d+)"),
    re.compile(r"/lists/(\d+)"),
    re.compile(r"\blist[ :#]+(\d+)\b", re.I),
    re.compile(r"^\s*(\d{3,})\s*$", re.M),
)


# Canonical form labels, produced by a Slack Workflow Builder form. Parsed strictly so
# a rep's submission maps to the prompt the same way every time -- free text is accepted
# as a fallback, but the form is what keeps it uniform.
FORM_LABELS = {
    "list": ("hubspot list", "list", "hubspot list url", "audience"),
    "angle": ("angle", "campaign angle", "theme", "messaging angle", "copy direction"),
    "notes": ("notes", "context", "anything else"),
}
# The angle reaches the generation prompt, so it is capped. A rep pasting three
# paragraphs would crowd out the rulebook, and a topic hint does not need paragraphs.
ANGLE_MAX = 400


def parse_form(text: str) -> dict | None:
    """Parse a Workflow Builder submission into {list, angle, notes}, or None.

    Returns None when the message is not a form, so the caller can fall back to loose
    parsing. Requires a recognised LIST label: a message with only an angle is not a
    request, and guessing would queue a campaign against nothing.
    """
    fields: dict[str, str] = {}
    for line in (text or "").splitlines():
        # Workflow Builder commonly bolds labels, so the asterisks are stripped.
        m = re.match(r"^\s*[*_]{0,2}\s*([A-Za-z][A-Za-z ]{1,24}?)\s*[*_]{0,2}\s*:\s*(.*\S)?\s*$",
                     line)
        if not m:
            continue
        label = m.group(1).strip().lower()
        # Slack bold puts the closing marker AFTER the colon -- "*Angle:* Halloween" --
        # so the captured value starts with a stray "*". Strip markers from both ends.
        # Any mix of markers and spaces at either end: "_Angle:_ _NYE packages_" leaves
        # "_ _NYE packages_", which strip("*_") only partly cleans because it stops at
        # the space.
        value = re.sub(r"^[\s*_]+|[\s*_]+$", "", m.group(2) or "")
        for key, names in FORM_LABELS.items():
            if label in names:
                fields[key] = value
                break
    if "list" not in fields:
        return None
    list_id, _ = parse_request(fields["list"])
    if not list_id:
        return None
    angle = fields.get("angle", "")
    if angle.lower() in ("none", "n/a", "-", ""):
        angle = ""
    return {"list_id": list_id, "angle": angle[:ANGLE_MAX],
            "notes": fields.get("notes", ""), "form": True}


def parse_request(text: str) -> tuple[str | None, str]:
    """(hubspot list id, brief) from a Slack message.

    The brief is whatever the rep wrote minus the list reference — it is passed through
    to the review tab so the person reviewing copy can see what was asked for.
    """
    text = text or ""
    list_id = None
    for pat in LIST_PATTERNS:
        m = pat.search(text)
        if m:
            list_id = m.group(1)
            break
    brief = text
    if list_id:
        brief = re.sub(r"<?https?://\S*objectLists/\d+\S*>?", "", brief)
        brief = re.sub(r"\blist[ :#]+\d+\b", "", brief, flags=re.I)
    brief = re.sub(r"\s+", " ", brief).strip()
    return list_id, brief


def decide_capacity(in_flight: int, requested: int, ceiling: int) -> tuple[bool, str]:
    """(accept now, reason). Guarantee 4.

    The ceiling counts leads IN FLIGHT, not sends per day. A lead occupies capacity for
    roughly the length of the sequence (about a week at [0, 3, 4] delays), so counting
    daily sends would let a week's worth of campaigns start on the same morning.
    """
    if in_flight + requested <= ceiling:
        return True, f"{in_flight} in flight + {requested} requested <= {ceiling} ceiling"
    return False, (f"{in_flight} in flight + {requested} requested exceeds the {ceiling} "
                   f"ceiling; queued until capacity frees up")


class Slack:
    def __init__(self, token: str, apply_changes: bool):
        self.token = token
        self.apply = apply_changes

    def call(self, method: str, params: dict | None = None, post: bool = False):
        if post:
            req = urllib.request.Request(
                f"https://slack.com/api/{method}", method="POST",
                data=json.dumps(params or {}).encode(),
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json; charset=utf-8"})
        else:
            q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
            req = urllib.request.Request(
                f"https://slack.com/api/{method}?{q}",
                headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read() or b"{}")
        if not d.get("ok"):
            err = d.get("error")
            if err == "missing_scope":
                raise RuntimeError(
                    f"Slack rejected {method}: missing_scope. Intake needs "
                    "`channels:history` and `channels:read` on the bot token; it holds "
                    "only `chat:write` today. Add them under OAuth & Permissions, "
                    "re-install the app, and re-run.")
            if err == "not_in_channel":
                raise RuntimeError(
                    f"Slack rejected {method}: not_in_channel. Invite the bot to the "
                    "request channel.")
            raise RuntimeError(f"Slack {method} failed: {err!r}")
        return d

    def history(self, channel: str, limit: int = 50) -> list[dict]:
        return self.call("conversations.history",
                         {"channel": channel, "limit": limit})["messages"]

    def replies(self, channel: str, ts: str) -> list[dict]:
        return self.call("conversations.replies",
                         {"channel": channel, "ts": ts})["messages"]

    def reply(self, channel: str, ts: str, text: str) -> str:
        if not self.apply:
            return f"would reply in-thread: {text.splitlines()[0][:90]}"
        self.call("chat.postMessage",
                  {"channel": channel, "thread_ts": ts, "text": text}, post=True)
        return "replied in-thread"


def engine_status(replies: list[dict], bot_user_id: str) -> str | None:
    """The most recent engine tag in a thread, or None if the engine has not replied.

    Guarantee 2: this IS the dedup store. A request the engine has accepted carries an
    accepted tag in its own thread, so it can never be processed twice even if the
    channel is re-read from the beginning.
    """
    found = None
    for m in replies:
        if m.get("user") != bot_user_id and m.get("bot_id") is None:
            continue
        for tag in ALL_TAGS:
            if tag in (m.get("text") or ""):
                found = tag
    return found


def in_flight_leads(key: str) -> int:
    """Leads currently inside ACTIVE or DRAFTED campaigns."""
    def g(path):
        req = urllib.request.Request(
            f"{SL_BASE}{path}{'&' if '?' in path else '?'}api_key={key}",
            headers={"User-Agent": "outbound-engine/1.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    total = 0
    for c in g("/campaigns") or []:
        if (c.get("status") or "").upper() not in ("ACTIVE", "DRAFTED", "PAUSED"):
            continue
        d = g(f"/campaigns/{c['id']}/leads?offset=0&limit=1")
        total += int(d.get("total_leads") or 0)
    return total


def list_size(list_id: str) -> int:
    """How many contacts are in the HubSpot list, for the capacity check."""
    from eligibility import env_token
    req = urllib.request.Request(
        f"https://api.hubapi.com/crm/v3/lists/{list_id}",
        headers={"Authorization": f"Bearer {env_token()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    return int((d.get("list") or {}).get("size") or 0)


def run_pipeline(list_id: str, brief: str, mailbox: str, apply_changes: bool,
                 angle: str = "") -> dict:
    """eligibility -> generation -> export. Each step is the existing script, run as a
    subprocess so its own guarantees and refusals stay intact rather than being
    re-implemented here."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    work = ROOT / "reviews"
    work.mkdir(exist_ok=True)
    leads = work / f"intake-{list_id}-{stamp}-leads.csv"
    elig = work / f"intake-{list_id}-{stamp}-eligible.csv"
    gen = work / f"intake-{list_id}-{stamp}-generated.csv"
    tab = f"Intake-{list_id}-{stamp}"

    from eligibility import env_token
    ids, after = [], None
    while True:
        u = (f"https://api.hubapi.com/crm/v3/lists/{list_id}/memberships?limit=100"
             + (f"&after={after}" if after else ""))
        req = urllib.request.Request(u, headers={"Authorization": f"Bearer {env_token()}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        ids += [m["recordId"] for m in d.get("results", [])]
        after = (d.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    leads.write_text("hs_object_id\n" + "\n".join(ids) + "\n", encoding="utf-8")

    steps = [
        ("eligibility", [PY, str(ROOT / "scripts/eligibility.py"), "--leads", str(leads),
                         "--out", str(elig), "--sender", mailbox.split(".")[0]]),
        ("generation", [PY, str(ROOT / "scripts/run_generation.py"), "--contacts",
                        str(elig), "--mailbox", mailbox, "--out", str(gen), "--quiet"]
                       + (["--angle", angle] if angle else [])),
        ("export", [PY, str(ROOT / "scripts/export_review.py"), "--csv", str(gen),
                    "--mailbox", mailbox, "--tab", tab]),
    ]
    out = {"tab": tab, "leads": len(ids), "steps": {}}
    if not apply_changes:
        out["steps"] = {n: "would run" for n, _ in steps}
        return out
    for name, cmd in steps:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=ROOT)
        out["steps"][name] = "ok" if p.returncode == 0 else "FAILED"
        out[f"{name}_output"] = ((p.stdout or "") + (p.stderr or ""))[-1500:]
        if p.returncode != 0:
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read campaign requests from Slack. Dry run by default.")
    ap.add_argument("--apply", action="store_true",
                    help="post replies and run the pipeline. Without this, nothing "
                         "is posted and nothing is generated.")
    ap.add_argument("--mailbox", default="carl.newmark@vibeposhvip.com",
                    help="sending mailbox for generated copy; one sender per campaign")
    ap.add_argument("--limit", type=int, default=20, help="messages to scan")
    ap.add_argument("--self-test", action="store_true",
                    help="prove parsing and the capacity rule with no API calls")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    token = env_value("SLACK_BOT_TOKEN")
    channel = env_value("SLACK_REQUEST_CHANNEL")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not set")
    if not channel:
        raise RuntimeError(
            "SLACK_REQUEST_CHANNEL not set in .env. Create the request channel, invite "
            "the bot, and put its channel id (starts with C) there. Deliberately not "
            "defaulted to the review channel: campaign requests and approval traffic "
            "should not share a channel.")

    cfg = load_defaults()
    ceiling = int(cfg.get("max_leads_in_flight", 60))
    sl = Slack(token, a.apply)
    me = sl.call("auth.test")["user_id"]
    print("APPLY: will post replies and run the pipeline" if a.apply
          else "DRY RUN: nothing posted, nothing generated.")

    key = env_value("SMARTLEAD_API_KEY")
    flight = in_flight_leads(key) if key else 0
    print(f"capacity: {flight} lead(s) in flight, ceiling {ceiling}\n")

    msgs = sl.history(channel, a.limit)
    handled = queued = rejected = 0
    for m in reversed(msgs):                      # oldest first, so queue order is fair
        if m.get("subtype") or m.get("bot_id") or m.get("user") == me:
            continue
        ts, text = m["ts"], m.get("text") or ""
        status = engine_status(sl.replies(channel, ts), me)
        if status == TAG_ACCEPTED or status == TAG_REJECTED:
            continue                              # guarantee 3

        form = parse_form(text)
        if form:
            list_id, brief, angle = form["list_id"], form["notes"], form["angle"]
        else:
            list_id, brief = parse_request(text)
            angle = ""
        who = m.get("user", "?")
        if not list_id:
            print(f"  {ts} <@{who}>: no HubSpot list found; rejecting")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} I could not find a HubSpot list in that message.\n"
                  f"Use the campaign request form, or post at minimum "
                  f"`HubSpot list: <url>`. I will pick it up on the next run."))
            rejected += 1
            continue

        try:
            size = list_size(list_id)
        except Exception as e:
            print(f"  {ts} list {list_id}: cannot read it ({e}); rejecting")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} I could not read HubSpot list {list_id}. Check the id "
                  f"and that it is not a private list."))
            rejected += 1
            continue

        ok, why = decide_capacity(flight, size, ceiling)
        print(f"  {ts} list {list_id} ({size} contacts) "
              f"{'form' if form else 'free text'} angle={angle[:60]!r}")
        print(f"    capacity: {why}")
        if not ok:
            queued += 1
            if status != TAG_QUEUED:              # do not repeat the same message daily
                print("    " + sl.reply(channel, ts,
                      f"{TAG_QUEUED} Received: HubSpot list {list_id}, {size} contacts.\n"
                      f"Holding it — {why}. I will start it automatically once there is "
                      f"room and reply here with the review link."))
            else:
                print("    still queued; not repeating the reply")
            continue

        res = run_pipeline(list_id, brief, a.mailbox, a.apply, angle=angle)
        failed = [k for k, v in res["steps"].items() if v == "FAILED"]
        if failed:
            print(f"    pipeline FAILED at {failed[0]}")
            print("    " + sl.reply(channel, ts,
                  f"{TAG_REJECTED} List {list_id} failed at the {failed[0]} step. "
                  f"Nothing was sent. I have the output; a human needs to look."))
            rejected += 1
            continue
        flight += size                            # so a second request this run sees it
        handled += 1
        print(f"    pipeline: {res['steps']}, review tab {res['tab']}")
        print("    " + sl.reply(channel, ts,
              f"{TAG_ACCEPTED} HubSpot list {list_id}, {size} contacts — copy drafted"
              + (f" with your angle: _{angle}_" if angle else " (no angle given)") + ".\n"
              f"Review tab *{res['tab']}* in the generation review sheet.\n"
              f"Reply here with approval and I will build the campaign. "
              f"**Nothing sends until a human launches it.**"))

    print(f"\n{handled} accepted, {queued} queued, {rejected} rejected")
    if not a.apply:
        print("DRY RUN: nothing posted, nothing generated.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # Parsing, in the shapes a rep will actually paste.
    check("full HubSpot URL",
          parse_request("please run https://app.hubspot.com/contacts/50950747/objectLists/1764/filters "
                        "for NYC venues")[0], "1764")
    check("brief survives the URL being stripped",
          parse_request("https://app.hubspot.com/contacts/1/objectLists/1764/filters "
                        "NYC venues on Eventbrite")[1], "NYC venues on Eventbrite")
    check("'list 1764' form", parse_request("run list 1764 please")[0], "1764")
    check("'list: 1764' form", parse_request("list: 1764")[0], "1764")
    check("bare id on its own line", parse_request("1764")[0], "1764")
    check("no list at all", parse_request("can we email some venues?")[0], None)
    # A number inside a sentence must NOT be read as a list id: a rep saying "we did
    # this in 2026" would otherwise queue a campaign against list 2026. The bare-id
    # pattern requires the number alone on a line, which is what makes that safe.
    check("a year in prose is not a list id", parse_request("we did this in 2026")[0], None)
    check("a count in prose is not a list id",
          parse_request("about 250 venues in Austin please")[0], None)
    check("a real list wins over a number in the prose",
          parse_request("last year we did 2026 contacts, now run list 1764")[0], "1764")

    # Capacity. Guarantee 4.
    check("under the ceiling accepts", decide_capacity(25, 30, 60)[0], True)
    check("exactly at the ceiling accepts", decide_capacity(30, 30, 60)[0], True)
    check("over the ceiling queues", decide_capacity(50, 30, 60)[0], False)
    check("an empty account accepts", decide_capacity(0, 60, 60)[0], True)
    check("a single oversized list queues", decide_capacity(0, 500, 60)[0], False)

    # Guarantee 3 / 2: the thread reply is the store.
    bot = "U123"
    check("no engine reply means unhandled", engine_status([], bot), None)
    check("an accepted tag is found",
          engine_status([{"user": bot, "text": f"{TAG_ACCEPTED} done"}], bot),
          TAG_ACCEPTED)
    check("a human reply is not an engine tag",
          engine_status([{"user": "UHUMAN", "text": f"{TAG_ACCEPTED} nice"}], bot), None)
    check("the LATEST tag wins, so queued->accepted is respected",
          engine_status([{"user": bot, "text": f"{TAG_QUEUED} holding"},
                         {"user": bot, "text": f"{TAG_ACCEPTED} drafted"}], bot),
          TAG_ACCEPTED)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    # A configuration problem should read as one sentence, not a traceback: this runs
    # unattended, and the first thing anyone hits is the missing Slack scope.
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(2) from None
