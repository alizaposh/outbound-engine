# Instruction: Campaign Creation (Smartlead)

**Purpose:** Turn an *approved* review dataset into a live Smartlead campaign via the
API. **Never run this without a recorded approval.** Read
`config/smartlead-defaults.md` for the default settings.

## How to run it

`scripts/create_campaign.py` implements the steps below. It creates the campaign
**DRAFTED and never launches**: launching stays a human action in the Smartlead UI.

```
./.venv/bin/python scripts/create_campaign.py \
  --csv reviews/<approved-generation-output>.csv \
  --audience ra-premium --usecase switch \
  --mailboxes carl.newmark@vibeposhvip.com,carl.newmark@coreposhvip.com \
  --approved-by "<name>" --approval-note "<slack permalink>" \
  --dry-run          # drop this to actually create
```

**ONE SENDER PER CAMPAIGN, and the script enforces it.** A Smartlead campaign rotates
across its assigned mailboxes, so a campaign holding copy signed by three people would
send an email signed "Carl" from Brooke's mailbox. That is the misrepresented-sender
fault that once put the wrong name in 18 of 34 emails, one level up. Generation records
`sender` and `mailbox` on every row; this script refuses a CSV that mixes senders, and
refuses mailboxes that belong to anyone but the one who signed the copy. **Run it once
per sender.**

It also refuses a batch containing any row that failed validation (`--skip-failed` drops
those rows instead), requires `--approved-by` and `--approval-note` so the approval is
recorded, and deletes the campaign if any step after creation fails rather than leaving a
half-configured campaign for someone to trust later.

**What was confirmed possible by API on 2026-08-31** (write-access test, every value read
back rather than trusted): create, schedule, mailbox assignment, the 3-step sequence,
per-lead custom fields, `unsubscribe_text`, `stop_lead_settings`, `track_settings`, and
delete. Two things are **not** reachable and stay manual, both rejected with
`"is not allowed"`: HubSpot activity logging and "Optimize Email Delivery".

Three details worth keeping in mind:
- **Per-prospect copy rides as per-lead custom fields.** The sequence body is literally
  `{{message_1_body}}`; each lead carries its own text. Steps 2 and 3 have `subject: ""`,
  which is what makes them threaded replies.
- **Bodies are converted to HTML** before upload. Campaigns send as HTML, where plain
  newlines collapse, so a four-paragraph email would arrive as one block.
- **The schedule cannot be read back:** `GET /campaigns/{id}/schedule` returns 404. The
  write returns `ok: true` and the UI shows the result, but nothing can verify it
  programmatically, so check the schedule in the UI before launching.

## Preconditions (all required)
- Explicit approval recorded in Slack. The Slack thread **is** the record — there is no
  local approvals store.
- Mailboxes are warmed and healthy in Smartlead.
- Each prospect has message_1..3 in the approved dataset.
- Suppression list checked: no opted-out / hard-bounced / stop-requested contacts.
- Every prospect cleared the pre-send eligibility check
  (`instructions/pre-send-eligibility-check.md`) before generation, and the annotated
  list (ELIGIBLE plus EXCLUDED with reasons) is in the review Sheet. That check gates
  on `hs_email_optout`, but it is still **not redundant** with the suppression check
  above: Smartlead catches hard bounces, and catches unsubscribes that have not yet
  been written back to HubSpot. Run both.

## Steps
1. **Create the campaign.** Set a clear campaign name (convention in
   `config/smartlead-defaults.md`).
2. **Configure sending:** schedule/timezone, assigned **warmed** mailboxes, daily
   limit (~30/mailbox/day ceiling), and inter-email delays. All from defaults.
3. **HubSpot activity logging — STOP and hand off to a human. Manual UI step, no API.**
   Activity logging is per-campaign and can **only** be toggled in the Smartlead UI
   (campaign's HubSpot settings); there is no API endpoint for it. A campaign that
   sends without it logs nothing to HubSpot — silently, with no error. Claude Code
   cannot complete this step: ask a human to enable it and confirm they have, before
   any sends start. Full rule + verification gate in the "HubSpot activity logging"
   section of `config/smartlead-defaults.md`.
4. **Unsubscribe settings — MANUAL UI, and compliance-critical.** The body already
   carries Smartlead's real tag, `%unsubscribe-text%` (`UNSUBSCRIBE_TOKEN` in
   `scripts/assemble.py`), but two per-campaign toggles decide whether it renders, and
   neither is visible to code:
   - **"Add unsubscribe message in all emails" ON.** This also enables the one-click
     **Unsubscribe Header Tag**, which Google requires of bulk senders.
   - **"Optimize Email Delivery" OFF.** It disables HTML content and takes the
     unsubscribe link with it, silently.

   A working opt-out is a legal requirement, not a nicety (see the compliance rules in
   `CLAUDE.md`), so this is a hard gate: do not launch without it. **A test send cannot
   verify it** — Smartlead deliberately renders the link non-clickable in test emails, so
   it will look present and dead. Only the first real send proves it.
5. **Add prospects** and attach each prospect's message_1..3 as the campaign's
   per-lead custom fields / personalized content.
6. **Configure the 3-email sequence** using those personalized fields.
7. **Stop-on-reply:** ensure follow-ups halt automatically when a prospect replies.
8. **Verify settings** before activating. Re-read them back and confirm with the
   human if anything looks off.
9. **Record the campaign on each enrolled contact** — `outbound_last_campaign_id` in
   HubSpot, so a contact traces back to the campaign that mailed it. Smartlead holds the
   campaign itself; email is the join key. No local mapping store.

## Launch
- **After any manual UI toggling, and BEFORE launching, re-verify the API-set settings:**
  ```bash
  python scripts/create_campaign.py --verify <campaign_id> --repair
  ```
  **The UI overwrites what the API set, silently.** Observed on campaign 3887546: created
  with `track_settings: ["DONT_EMAIL_OPEN"]`, read back as `["DONT_LINK_CLICK"]` after the
  manual toggles were done in the UI. The enum round-trips correctly when set by API, so
  the call was never wrong — the UI simply wins last, and saving its settings panel
  rewrites the tracking flags. The consequence is not cosmetic: open tracking back ON
  means a tracking pixel on cold mail from a young domain, which is the deliverability
  cost `config/smartlead-defaults.md` deliberately avoids and a spam signal besides.
  Since the mandatory toggles in steps 3–4 REQUIRE going into the UI, this drift is the
  expected case, not an edge case.
- **Un-pause the three scheduled routines** (`outbound-morning`, `outbound-midday`,
  `outbound-afternoon`) in Claude Desktop → Code → Routines. They were created and
  verified on 2026-08-31 and then left **Paused** deliberately, to avoid three
  "nothing to do" heartbeats a day while there were no campaigns. **The moment a
  campaign sends, that reasoning inverts:** replies start arriving and nothing is
  watching for them. Paused routines fail silently by definition — there is no heartbeat
  to be missing, so the Slack channel looks the same as a healthy quiet day. See
  `instructions/scheduled-tasks.md`.
- Start with a **small batch** (per your plan, ~100 contacts) across multiple warmed
  mailboxes. Watch deliverability + reply quality, then ramp gradually.
- **Confirm the unsubscribe link rendered** on the very first real send, before any
  further sends. Open the delivered email and click it. If it is missing, check the two
  toggles in step 4: "Optimize Email Delivery" being on is the usual cause.
- **Gate the full lead set behind the activity-logging check** in
  `config/smartlead-defaults.md`: after the first send, confirm on a test contact that
  it lands as an EMAIL activity and moved native "Last Contacted", not just "Last
  Activity Date". Only then release the rest of the leads — this also catches a broken
  integration connection on that campaign.
- Never spike volume on one mailbox/domain; scale by adding mailboxes/domains.
- Pause any mailbox/domain showing deliverability problems.

## TODO / [FILL IN]
Both original items are **DONE** (verified 2026-09-01) and are kept only so the closure
is visible:
- ~~Confirm the exact Smartlead API endpoints/fields once the account exists.~~ Confirmed
  against the live API and implemented in `scripts/create_campaign.py`, which has created,
  read back and deleted real campaigns.
- ~~Lock the campaign-naming convention and default delays.~~ Locked in
  `config/smartlead-defaults.md`; that file has no `[FILL IN]` markers left.

---

## Slack intake: a rep submits a HubSpot list (built 2026-09-08)

`scripts/slack_intake.py`. Implements the request channel decided in `CLAUDE.md`.

```bash
python scripts/slack_intake.py --self-test     # parsing + capacity rules, no API
python scripts/slack_intake.py                 # DRY RUN: reads, decides, posts nothing
python scripts/slack_intake.py --apply         # posts replies and runs the pipeline
```

**The rep posts a HubSpot list plus a one-line brief.** A URL, `list 1764`, or the bare id
on its own line all parse. A number inside a sentence deliberately does NOT — "we did this
in 2026" must not queue a campaign against list 2026.

**Why a HubSpot list and not pasted emails.** Eligibility consumes list membership by
`hs_object_id`, HubSpot is the source of truth, and contact creation is off by standing
decision — so a pasted address with no HubSpot record could not be processed at all. That
would be a confusing dead end for a rep who just pasted 40 emails.

### What it does, and where it stops
1. Reads the request channel, parses the list and brief.
2. **Capacity check** against `max_leads_in_flight` in `config/smartlead-defaults.md`
   (60 today). Over the ceiling → replies `[engine:queued]` and picks it up on a later run.
3. Under the ceiling → eligibility → generation → export a review tab → replies
   `[engine:accepted]` with the tab name.
4. **It stops there.** A human approves, `create_campaign.py` builds a DRAFTED campaign,
   and a human does the two UI toggles and launches. Golden rule 1 and two API-less
   settings make this unavoidable, which is the right outcome rather than a limitation.

### The ceiling counts leads IN FLIGHT, not sends per day
A lead occupies capacity for about the length of the sequence (~7 days at `[0, 3, 4]`), so
a per-day ceiling would let a week of campaigns all start on one morning. And note what it
is FOR: **Smartlead already paces sends at 15/mailbox/day**, so this is not flood
protection — it decides whether to START a campaign, which matters while the domains are
weeks old. Raise it as they age; 60 against a 180/day mailbox capacity is deliberately
conservative.

### State lives in the Slack thread
There is no intake database. A request the engine has handled carries an `[engine:...]`
tag in its own thread, and that tag IS the dedup store — the same rule as everywhere else
in this engine: what it needs to remember lives somewhere a human can open and read. It
also means the audit trail is the conversation, and a queued request that has already been
acknowledged is not re-acknowledged every morning.

### Prerequisites, both outside the script
- **Slack scopes `channels:history` and `channels:read`.** The bot holds only `chat:write`,
  so intake fails with a one-line message naming the fix until they are added and the app
  re-installed. Note this grants the bot read access to that channel's content.
- **`SLACK_REQUEST_CHANNEL` in `.env`**, and the bot invited. Deliberately not defaulted to
  the review channel: requests and approval traffic should not share one.

### Not yet in the heartbeat, on purpose
Intake runs generation, which is slow and costs model calls. Run it by hand a few times
first, confirm the replies read well to a rep, then add it to the morning slot — the same
graduation pattern the write jobs used.
