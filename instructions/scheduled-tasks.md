# Instructions: Scheduled Tasks (v1)

The v1 scheduler is **Claude Desktop scheduled tasks** running `scripts/heartbeat.py`
on a business-hours weekday cadence, reporting to Slack on every run.

Polling, not webhooks — see "Why polling and not Smartlead webhooks" in `BACKLOG.md`.
Cloud-hosted scheduling is the v2 option, recorded in the same file.

---

## The cadence

| Slot | Time (America/New_York) | Days | Jobs |
|---|---|---|---|
| `morning` | 09:45 | Mon–Fri | reply check **+ unsubscribe sync + bounce sync + sequence close-out** |
| `midday` | 13:05 | Mon–Fri | reply check |
| `afternoon` | 16:25 | Mon–Fri | reply check |

**Why this shape:**

- **The times are set around the laptop being open, not around the working day.** A local
  Desktop task only fires while the app is running and the machine is awake. An earlier
  slot (the first draft said 08:05) would be asleep every morning and would survive only
  on the catch-up mechanism — which works, but makes the schedule fiction and fills the
  task history with a skip every single day, so a REAL failure would be invisible among
  the expected ones. 09:45 assumes the laptop is open by ~09:30; move all three if that
  changes. The three are spaced about 3h20 apart, and the last lands with enough of the
  day left to act on what it finds.
- **Three slots, not one.** Cadence should match when a human will look at the queue,
  not be optimised on its own — every reply goes to a person, so polling more often than
  you review buys nothing. But a morning-only check means a reply landing at 08:15 waits
  a full day. Three slots keep the worst case to about four working hours, and each poll
  is only a handful of API calls.
- **Weekdays only.** Nobody reviews the queue at the weekend. Monday morning catches it.
- **The unsubscribe and bounce syncs run once, in the morning.** The unsubscribe sync
  walks every lead on every campaign, so it is the expensive job; the bounce sync is
  cheap but there is no reason to run it three times a day. The reply check only pulls message history for
  leads already marked replied, so it stays cheap at every slot.
- **A late poll is safe, and this is the reason.** Smartlead's `stop_lead_settings` is
  `REPLY_TO_AN_EMAIL` (set in `config/smartlead-defaults.md` and sent by
  `create_campaign.py`), so follow-ups halt the moment someone replies, independent of
  our polling. A check that runs hours late can never send email 2 to someone who already
  answered. That is what makes a relaxed cadence defensible rather than risky.

---

## Setting up the tasks in Claude Desktop

Requires Claude Desktop **1.1.5368 or newer**. In the **Code** tab, click **Routines** in
the sidebar (or under **More**) → **New routine** → choose **Local**. A local routine runs
on this machine with access to this repo; a remote one runs in the cloud from a fresh
clone and would not have `.env` (see `BACKLOG.md`).

Create **three** routines, identical except for the slot and time:

| Name | Schedule | Instructions |
|---|---|---|
| `outbound-morning` | **Weekdays**, 9:45 AM | prompt below with `morning` |
| `outbound-midday` | **Weekdays**, 1:05 PM | prompt below with `midday` |
| `outbound-afternoon` | **Weekdays**, 4:25 PM | prompt below with `afternoon` |

**Weekdays** is a built-in preset (Daily, skipping Sat/Sun) with a time picker — no cron
needed. Set **working folder** to this repo; Desktop will ask you to trust it. Leave the
worktree toggle **off**: these jobs read live credentials and write to real systems, so
an isolated copy of the repo is not wanted.

### Current state: created, verified, PAUSED (2026-08-31)

All three routines exist and all three have been run once via **Run now**, green, with
their permissions approved. They are deliberately **Paused** until closer to the first
campaign launch, to avoid three "nothing to do" heartbeats a day while there is nothing
to poll.

**Un-pausing is a step in the launch procedure** (`instructions/campaign-creation.md`,
Launch section), not something to remember. A paused routine is the one failure mode the
heartbeat cannot report: there is no missing message, because there is no message —
the channel looks identical to a healthy quiet day.

### Do this immediately after creating each one, or it will silently stall

Click **Run now** and answer the permission prompt with **always allow**. A task in Manual
permission mode that hits an un-approved tool does not fail — it *stalls*, waiting for a
human, and the heartbeat never posts. That failure looks exactly like the one the
heartbeat exists to expose, so approve the Bash command once, up front, on each of the
three. You can review or revoke these later from the task's detail page.

### Two behaviours worth knowing

- **Runs fire a few minutes late by design.** Desktop adds a small deterministic offset to
  stagger API traffic, so 8:05 may fire at 8:07. Harmless here.
- **Missed runs get one catch-up.** On wake or app start, Desktop checks the last seven
  days and starts a single catch-up for the most recently missed time, discarding older
  ones. **For these jobs that is a feature, not a hazard**: both are idempotent, so a
  morning check that actually runs at 11pm simply catches up. It is the safety net for an
  unusual day, though, not the mechanism the schedule should lean on daily — which is why
  the slots are set for hours the machine is actually awake. It will post a heartbeat
  labelled `morning` with the real 11pm timestamp, which reads oddly but is accurate. No
  prompt guardrail is needed — unlike a task that, say, reviews "today's" commits.
- **Sleep still skips.** Settings → **Desktop app → General** → **Keep computer awake**
  prevents idle sleep, but closing the lid sleeps regardless.

### The three prompts, verbatim

**The `--slot` flag is the part that matters** — it decides which jobs run. The word in
the first line is only there so the session is readable at a glance. Copy each block
whole rather than editing one of them, so the flag and the label cannot drift apart: a
task labelled MIDDAY still running `--slot morning` would run the unsubscribe sync three
times a day and mislabel every heartbeat. Harmless, since the jobs are idempotent, but
it makes the report lie about what happened.

`outbound-morning` — Weekdays, 9:45 AM:

```
Run the outbound engine's scheduled MORNING check.

From /Users/alizamayer/Desktop/email-engine/outbound-engine, execute exactly:

    ./.venv/bin/python scripts/heartbeat.py --slot morning --apply

Then stop and report only the summary it printed.

Do not run any other command. Do not edit any file. Do not create, modify, or launch a
Smartlead campaign. Do not send any email or reply. If the command fails, report the
error verbatim and do NOT retry it — the heartbeat has already posted the failure to
Slack, and a retry would post a second time and muddy the signal.
```

`outbound-midday` — Weekdays, 1:05 PM:

```
Run the outbound engine's scheduled MIDDAY check.

From /Users/alizamayer/Desktop/email-engine/outbound-engine, execute exactly:

    ./.venv/bin/python scripts/heartbeat.py --slot midday --apply

Then stop and report only the summary it printed.

Do not run any other command. Do not edit any file. Do not create, modify, or launch a
Smartlead campaign. Do not send any email or reply. If the command fails, report the
error verbatim and do NOT retry it — the heartbeat has already posted the failure to
Slack, and a retry would post a second time and muddy the signal.
```

`outbound-afternoon` — Weekdays, 4:25 PM:

```
Run the outbound engine's scheduled AFTERNOON check.

From /Users/alizamayer/Desktop/email-engine/outbound-engine, execute exactly:

    ./.venv/bin/python scripts/heartbeat.py --slot afternoon --apply

Then stop and report only the summary it printed.

Do not run any other command. Do not edit any file. Do not create, modify, or launch a
Smartlead campaign. Do not send any email or reply. If the command fails, report the
error verbatim and do NOT retry it — the heartbeat has already posted the failure to
Slack, and a retry would post a second time and muddy the signal.
```

The prompt is deliberately narrow. A scheduled agent with repo access could do far more
than intended, and the task only needs it to run one command and read back the result.

---

## Prerequisites

1. **Slack.** Set `SLACK_BOT_TOKEN` and `SLACK_HEARTBEAT_CHANNEL` in `.env`, then run
   `./.venv/bin/python scripts/heartbeat.py --check-slack` — it tests the token, the
   channel and the invite separately and posts nothing.

   Creating the app, once:
   1. **api.slack.com/apps** → **Create New App** → **From scratch**. Name it
      `Outbound Engine`, choose the workspace.
   2. **OAuth & Permissions** → **Bot Token Scopes** → add **`chat:write`**. That is the
      only scope the heartbeat needs. The broader `chat:write.public` (post to any public
      channel without joining) is deliberately NOT used: `chat:write` plus a one-time
      invite means the bot can only post where it has been put.
   3. **Install to Workspace**. If the workspace requires admin approval for apps, this
      is where it is requested.
   4. Copy the **Bot User OAuth Token**, which starts **`xoxb-`** → `SLACK_BOT_TOKEN`.
      The app-level `xapp-` token on the same page is a different thing and will not work.
   5. **Invite the bot to the channel**: `/invite @Outbound Engine` in the channel itself.
      This is the step that gets missed — Slack answers a post from an uninvited bot with
      `not_in_channel`.
   6. Channel **About** tab → copy the **ID** (starts with `C`) → `SLACK_HEARTBEAT_CHANNEL`.
      Use the id, not `#name`: it survives a channel rename.

   **`--check-slack` posts one test message**, and that is deliberate. Inspecting the
   channel instead would need `channels:read`, which the heartbeat does not use — having
   a setup check dictate the app's permissions is backwards. With `chat:write` alone the
   only honest verification is to post, and it exercises the real code path rather than a
   proxy for it.

   **Current setup (2026-08-31): the heartbeat posts to the REVIEW channel**
   (`SLACK_REVIEW_CHANNEL`, `C0BU2F84KUL`), because that is the only channel that exists
   so far. `SLACK_HEARTBEAT_CHANNEL` is unset and the code falls back. That is fine while
   the approval flow does not exist — there is nothing yet for the heartbeat to bury.
   **Split them when the Slack brief/approval flow ships**: three heartbeats a day on top
   of approval requests is how an approval request gets missed.

   **Scopes stay minimal on purpose.** The Slack brief/approval flow will later need read
   scopes (`channels:history`, `channels:read`); add them when that is built, as a
   re-install. There is no reason to grant read access to channels today for a job that
   only posts.
2. **The machine must be awake and Claude Desktop running.** Neither this nor any local
   scheduler wakes a sleeping Mac. A missed slot is invisible from the inside — which is
   precisely what the heartbeat is for.
3. Test before scheduling:
   ```bash
   ./.venv/bin/python scripts/heartbeat.py --check-slack               # token/channel/invite
   ./.venv/bin/python scripts/heartbeat.py --slot morning --no-slack   # prints, no post
   ./.venv/bin/python scripts/heartbeat.py --slot morning              # posts for real
   ```
   `--no-slack` is for setup only. **Never put it in a scheduled task** — it disables the
   heartbeat, which is the one part that must not be optional.

---

## Reading the heartbeat

Every run posts, including runs where nothing happened. That is the whole design: a
report that appears only when there is news cannot be told apart from a job that never
ran.

| Signal | Means |
|---|---|
| 🟢 | Ran, nothing needs a human. |
| 🟡 | Ran, something is waiting: replies queued, suppressions to write, or unmatched unsubscribes. |
| 🔴 | A job failed. The message carries the last 15 lines of its output. |
| **nothing at all** | **BROKEN.** Machine asleep, Claude Desktop closed, task deleted, or the Slack token expired. Silence is never "quiet" — a quiet run is 🟢. |

The amber signal is driven by parsed **counts**, not by matching words in the output, so
"0 queued for review" stays green.

---

## Graduated to `--apply` on 2026-09-08

**Done.** The three task prompts above now carry `--apply`, so the jobs write. The
criteria below were met: a real campaign is live (3921033), all three HubSpot write paths
were proven live against a throwaway contact, and `BODY_FIELDS` was settled against a real
reply in rehearsal 1.

### What `--apply` switches on — more than the reply queue

| Job | With `--apply` |
|---|---|
| `reply_check` | HubSpot `outbound_*` writes, Smartlead resume for automated replies, **and the queue rows** |
| `sync_unsubscribes` | `outbound_suppressed` + `outbound_opt_out_date` |
| `sync_bounces` | `outbound_status=bounced` |

It is all-or-nothing at the heartbeat level, and **that is the right state once a campaign
is live**: leaving bounces and unsubscribes unsynced while mail is going out is worse than
leaving the queue empty. An unsynced unsubscribe means HubSpot does not know someone opted
out; an unsynced bounce means a dead address gets mailed again next campaign.

### What `--apply` does NOT switch on

**`send_replies.py` is not in any slot, so nothing is ever auto-sent.** Drafts are queued,
a human reads them, marks `Approve` or `Edit & send`, and runs `send_replies --apply`
themselves. Graduating the routines does not put the engine in charge of replying, and the
`auto_send_intents` allowlist stays empty and asserted.

### Reverting
Remove `--apply` from the three prompts. Everything already written stays written; the
jobs are idempotent, so re-enabling later picks up where it left off.

### Original criteria, for the record
The tasks started in **dry run** deliberately: an unattended task that writes to HubSpot
on its first run, before anyone has read what it decides, is exactly the thing to avoid.
Promotion required:

1. Real campaigns have been running long enough to produce real replies and unsubscribes.
2. Several heartbeats have been read, and the decisions match what a person would have
   made — particularly the classified intents and the suppression matches.
3. The `BODY_FIELDS` question in `instructions/reply-handling.md` is settled against a
   real reply. Until a real inbound message has been parsed once, the reply check may
   abort by design rather than guess at an unreadable body.

Both jobs are idempotent, so a promoted task that double-runs, or a slot that gets
missed, costs nothing but time. The next run catches up completely.
