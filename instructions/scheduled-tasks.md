# Instructions: Scheduled Tasks (v1)

The v1 scheduler is **Claude Desktop scheduled tasks** running `scripts/heartbeat.py`
on a business-hours weekday cadence, reporting to Slack on every run.

Polling, not webhooks — see "Why polling and not Smartlead webhooks" in `BACKLOG.md`.
Cloud-hosted scheduling is the v2 option, recorded in the same file.

---

## The cadence

| Slot | Time (America/New_York) | Days | Jobs |
|---|---|---|---|
| `morning` | 08:05 | Mon–Fri | reply check **+ unsubscribe sync** |
| `midday` | 12:05 | Mon–Fri | reply check |
| `afternoon` | 16:05 | Mon–Fri | reply check |

**Why this shape:**

- **Three slots, not one.** Cadence should match when a human will look at the queue,
  not be optimised on its own — every reply goes to a person, so polling more often than
  you review buys nothing. But a morning-only check means a reply landing at 08:15 waits
  a full day. Three slots keep the worst case to about four working hours, and each poll
  is only a handful of API calls.
- **Weekdays only.** Nobody reviews the queue at the weekend. Monday morning catches it.
- **The unsubscribe sync runs once, in the morning.** It walks every lead on every
  campaign, so it is the expensive job. The reply check only pulls message history for
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
| `outbound-morning` | **Weekdays**, 8:05 AM | prompt below with `morning` |
| `outbound-midday` | **Weekdays**, 12:05 PM | prompt below with `midday` |
| `outbound-afternoon` | **Weekdays**, 4:05 PM | prompt below with `afternoon` |

**Weekdays** is a built-in preset (Daily, skipping Sat/Sun) with a time picker — no cron
needed. Set **working folder** to this repo; Desktop will ask you to trust it. Leave the
worktree toggle **off**: these jobs read live credentials and write to real systems, so
an isolated copy of the repo is not wanted.

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
  morning check that actually runs at 11pm simply catches up. It will post a heartbeat
  labelled `morning` with the real 11pm timestamp, which reads oddly but is accurate. No
  prompt guardrail is needed — unlike a task that, say, reviews "today's" commits.
- **Sleep still skips.** Settings → **Desktop app → General** → **Keep computer awake**
  prevents idle sleep, but closing the lid sleeps regardless.

The prompt for each task:

```
Run the outbound engine's scheduled MORNING check.

From /Users/alizamayer/Desktop/email-engine/outbound-engine, execute exactly:

    ./.venv/bin/python scripts/heartbeat.py --slot morning

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

## Graduating to `--apply`

The tasks start in **dry run**: the jobs read, decide, and report, and write nothing.
This is deliberate. An unattended task that writes to HubSpot on its first run, before
anyone has read what it decides, is exactly the thing to avoid.

Promote by adding `--apply` to the command in each task prompt, but only once:

1. Real campaigns have been running long enough to produce real replies and unsubscribes.
2. Several heartbeats have been read, and the decisions match what a person would have
   made — particularly the classified intents and the suppression matches.
3. The `BODY_FIELDS` question in `instructions/reply-handling.md` is settled against a
   real reply. Until a real inbound message has been parsed once, the reply check may
   abort by design rather than guess at an unreadable body.

Both jobs are idempotent, so a promoted task that double-runs, or a slot that gets
missed, costs nothing but time. The next run catches up completely.
