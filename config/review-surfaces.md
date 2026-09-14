# Config: Review Surfaces

Google Sheets the engine writes to for human review. **Review surfaces only** —
Smartlead and HubSpot remain the sources of truth. Nothing here is authoritative; a
row in a sheet is a request for a human decision, not a record of one.

## Reply Review Queue

One row per reply that needs a human decision, appended by the reply-check workflow.

```
REPLY_REVIEW_SHEET_ID: 1VznhnN3cKr7mzJySPLcPqcbLAow2ivRJI1Abwsknyt0
REPLY_REVIEW_TAB: Replies
```

**Columns (15, in this order — the header row is authoritative and must not be
rewritten by code):**

| # | Column | Filled by |
|---|---|---|
| 1 | `received_at` | engine |
| 2 | `contact_name` | engine |
| 3 | `email` | engine |
| 4 | `company` | engine |
| 5 | `campaign` | engine |
| 6 | `sent_by` | engine (the sending persona/mailbox) |
| 7 | `reply_text` | engine |
| 8 | `intent` | engine (`outbound_reply_intent` value) |
| 9 | `proposed_action` | engine (from the action map) |
| 10 | `draft_response` | engine |
| 11 | `review_reason` | engine (why this needs a human) |
| 12 | `decision` | **human** — dropdown |
| 13 | `notes` | **human** |
| 14 | `smartlead_message_id` | engine (dedup key) |
| 15 | `processed_at` | engine |

The engine fills every column **except `decision` and `notes`**, which are the human's.
Code never writes those two, so a queued row cannot arrive pre-decided.

### `decision` dropdown

Data validation on column L, rows 2+ (never the header). Invalid entries are rejected,
so a decision is always one of:

`Approve` · `Edit & send` · `Suppress` · `Do not send` · `Reclassify`

### What never reaches this queue

Per `instructions/reply-handling.md`, `out_of_office` and `automated_reply` are not real
replies — they must not advance the lead, and they must not consume human attention
either. The append function drops them.

## Generation Review (draft copy for the sales team)

The 3-email drafts a run produced, one row per contact, for the sales team to score.

```
GENERATION_REVIEW_SHEET_ID: 1M15_NNFf8hqJcaGs5Bddiwt8aqs-U-oXydC5GWVApLc
GENERATION_REVIEW_TAB: Test2
```

**One tab per run.** `Test1` holds the 2026-08-19 run scored by the AEs, whose feedback
became the "Sales-team messaging rules" block in `instructions/message-generation.md`.
Keeping each run on its own tab is what makes a before/after comparison possible, so
point `GENERATION_REVIEW_TAB` at a new tab per run rather than appending to an old one.

**26 columns, and the layout is the sheet's, not the CSV's.** It is close to
`run_generation.COLUMNS` but not identical, so the export maps explicitly:
- **`Seller`** (column B) is in the sheet but not the CSV. It is the sender first name
  for the run's mailbox, from `config/senders.md`.
- **`company`** is in the CSV but not the sheet.
- **`Ranking (X/5)`** and **`Feedback`** (Y, Z) are the **human's**. Code never writes
  them, exactly as with `decision`/`notes` on the reply queue: a row must not arrive
  pre-scored.

Writes append below the existing header row and never rewrite it.

## Auth

Service-account JSON key, path in **`GOOGLE_SERVICE_ACCOUNT_JSON`** (`.env`,
git-ignored). The sheet must be shared with the key's `client_email` as **Editor**.

Note the trap: Google's client libraries auto-read **`GOOGLE_APPLICATION_CREDENTIALS`**,
a different variable this project does not set. Credentials are therefore loaded from
`GOOGLE_SERVICE_ACCOUNT_JSON` explicitly and passed in — never left to the default
lookup, which would silently pick up an unrelated ambient credential or fail with a
misleading message.

**The key lives outside the repo** — `~/.config/outbound-engine/sheets-key.json`, mode
`600` in a `700` directory (moved there 2026-08-25; it had been sitting in the repo root
where `.gitignore` was the only thing standing between it and a push). Keep it there.
A credential that is not in the working tree cannot be committed by `git add -f`, by an
edited ignore rule, or by zipping the folder to share it.

`.gitignore` still carries `/*.json` and the GCP `<project>-<hash>.json` shape as a
backstop for the next key someone downloads into the wrong place.

## Columns added 2026-09-02 for `scripts/send_replies.py`

Appended, never inserted: `decision` and `smartlead_message_id` are addressed by
POSITION in `review_queue.py`, so inserting a column would write a human's decision into
the wrong cell.

| Column | Written by | Purpose |
|---|---|---|
| `smartlead_stats_id` | the reply check | Addresses the THREAD. `reply-email-thread` requires it as `email_stats_id`. |
| `sent_at` | the reply sender | Send-once stamp. `sending …` while in flight, then `sent …` or `FAILED …`. |

**The two ids are not interchangeable, and each breaks something different.**
`smartlead_stats_id` is **shared across a whole thread**, so it addresses the thread but
is useless for dedup — keying dedup on it would mark a reply processed the moment the
outbound email was recorded. `smartlead_message_id` is unique per message, so it is the
dedup key but cannot address a thread. Verified against a real thread on 2026-09-01,
where both messages carried one `stats_id`.

**`sent_at` reading `sending …`** means a run died between claiming the row and getting a
response. **Do not simply clear it**: check the thread in Smartlead first, because the
reply may or may not have gone out.

## Tab renamed 2026-09-08: `Untitled` -> `Replies`

The tab was literally called `Untitled`, which worked only because every script reads the
name from `REPLY_REVIEW_TAB` here rather than hardcoding it. It was renamed for legibility:
with one tab called `Untitled`, adding a second leaves no way to tell which is the queue.

**Nothing else needed changing**, which is the point of the config indirection — grep
confirmed no script contained the old name. Verified after the rename that the 17-column
header and, importantly, **the data validation on the `decision` column both survived**.
That dropdown is the human's only control in this sheet, and losing it silently would turn
free-text typos into decisions the engine cannot read.

## When does a row actually appear? (three gates, 2026-09-08)

**Sends never appear in this sheet.** It is a queue of replies needing a human decision,
not a send log. Sends live in Smartlead, on the HubSpot contact timeline if the
per-campaign activity-logging toggle is on, and as `outbound_last_campaign_id` +
`outbound_status=in_sequence` on the contact.

A reply row appears only when **all three** are true:

1. **A campaign is live and someone replies.**
2. **`reply_check.py` runs.** The three Claude Desktop routines are currently **PAUSED**
   (`instructions/scheduled-tasks.md`).
3. **It runs with `--apply`.** The task prompts deliberately omit it, so the routines are
   dry-run. **Un-pausing alone will NOT populate this sheet** — graduating to `--apply` is
   a separate, deliberate step with its own criteria in the scheduled-tasks file.

**Only 8 of the 10 intents queue.** `out_of_office` and `automated_reply` never do
(`NEVER_QUEUE`): they are not real replies and must not consume human attention.

**The dry-run wording was fixed on 2026-09-08 because of exactly this confusion.** The
summary said "1 queued for review" in dry run, which the heartbeat printed into Slack
every weekday while the sheet stayed empty — a reliable way to conclude the queue is
broken. It now reads "1 WOULD be queued (dry run, sheet unchanged)".

---

## Campaign Report (weekly)

One row **per campaign per run**, appended by `scripts/campaign_report.py --write`. Lives
in the same spreadsheet as the reply queue, on its own tab.

```
CAMPAIGN_REPORT_TAB: Campaign Report
```

**Append-only, and that is the point.** A single run is a snapshot and cannot show a
trend; the interesting question is almost never "what is the rate today" but "is it
moving". History accumulating in rows is what makes that answerable, and what lets you
chart it without any of this code being involved.

| # | Column | Notes |
|---|---|---|
| 1 | `run_date` | the day the report ran, not the campaign's date |
| 2 | `campaign_id` | |
| 3 | `campaign_name` | |
| 4 | `status` | Smartlead campaign status at run time |
| 5 | `leads` | enrolled |
| 6 | `sent` | emails sent, not people |
| 7 | `bounced` | |
| 8 | `delivered` | `sent - bounced`, the denominator for every rate |
| 9 | `human_replies` | **excludes auto-responders**, unlike Smartlead's own count |
| 10 | `positive` | |
| 11 | `negative` | |
| 12 | `deferred` | |
| 13 | `machine` | auto-responders, counted but never in a rate |
| 14 | `unaccounted` | replies Smartlead saw that we could not classify — **investigate any non-zero** |
| 15 | `reply_rate` | **BLANK below the threshold** |
| 16 | `rate_low` | low end of the confidence interval |
| 17 | `rate_high` | high end |

**`reply_rate` is deliberately left EMPTY until `min_delivered_for_rate` is met**, rather
than written and flagged. A number in a spreadsheet cell gets charted, averaged and
quoted in a meeting by someone who never saw the caveat attached to it — and "4%" from a
single reply in 25 is exactly the figure that starts an argument about copy. An empty
cell cannot be plotted. The counts beside it are real and always written.

**Idempotent on `(run_date, campaign_id)`.** Running twice in a day updates nothing and
adds nothing, so a re-run after a failure is safe.

**A finished campaign is recorded once and then left alone.** Its numbers cannot change
again, so re-recording them every week would write an identical row forever — history
that grows without carrying any information. The final row is kept, because that *is*
the useful artefact; after that the campaign is skipped. An `ACTIVE` campaign is always
re-recorded, since its movement is the entire point of the history.

### Generated tab: name and columns (changed 2026-09-11)

**Name: `<Requester first name>-<YYYY-MM-DD>`**, e.g. `Aliza-2026-09-11`. A rep should
recognise their own request without decoding `Intake-1914-20260911-1359`. The list id
lives on in the CSV filenames under `reviews/`, which is where a debugger looks anyway.
A same-day second request from the same person gets `-2`, because `export_review` refuses
a tab that already has rows and a silent collision would fail the run at its last step.

The requester comes from a **"Your name"** field on the Slack form. Workflow Builder
submissions are `bot_message` with `user: None` and carry no submitter, so this is the
only way to know who asked; without the field the tab falls back to `List<id>-<date>`.
The parser accepts "Your name", "Requested by", "Name", "Rep", "Requester" or
"Submitted by", in either Workflow Builder layout.

**Columns: 10, not 24.**

| Column | Filled by |
|---|---|
| `Seller` | engine (the sending persona) |
| `first_name`, `last_name`, `email` | engine |
| `message_1_subject` | engine — the subject for the WHOLE sequence |
| `message_1_body`, `message_2_body`, `message_3_body` | engine |
| `Approved` | **human** — a strict `Y`/`N` dropdown. `Y` builds the campaign |
| `Ranking (X/5)` | **human** |
| `Feedback` | **human** |
| `Built into` | engine — the campaign this row was built into. Empty means approved but not yet built |

Emails 2 and 3 have no subject column because they send with `subject: ""` and thread as
"Re: ...".

**What was removed and where it went.** `persona`, `persona_basis`, `platform_known`,
`current_competitor`, `estimated_gmv_usd`, `vertical`, `validation`, `generation_error`,
`attempts`, `repairs_applied`, `sequence_findings`, `bedrock_message_id` and
`hs_object_id` are engine diagnostics — how a failure gets debugged, and noise to a rep
scoring copy. **All of them remain in the run's CSV under `reviews/`.** The Sheet is the
review surface; the CSV is the archive.

`Ranking (X/5)` and `Feedback` were kept although not in the requested list: they are the
reviewer's own columns and the reason the sheet exists, since feedback becomes rules in
`config/`. A rep with no cell to write in cannot review.

**Existing tabs are untouched.** Rows map to each tab's own header BY NAME, so Test1-Test12
keep their 24 columns and still populate correctly. This changes only tabs the engine
creates.


### The `Approved` column is the trigger (added 2026-09-14)

Selecting **`Y`** on a row marks that contact's copy approved. The column is a
**strict `Y`/`N` dropdown**, matching how `decision` works on the reply queue.

**The strictness is the point, not the dropdown.** A free-text approval column accepts
"Yes " with a trailing space, "yep", "APPROVE" — none of which the builder recognises. A
reviewer would mark a row approved, watch nothing happen, and have no way to see why.
Rejecting the value at entry makes that impossible rather than merely unlikely. `scripts/build_approved.py`
reads the tab in the morning heartbeat and creates a DRAFTED campaign from the approved
rows.

**This mirrors the reply queue deliberately.** There, `decision = Approve` *is* the
instruction `send_replies` acts on. Here the approval previously lived in a Slack message
or in somebody's head, and the campaign got built because a person remembered to run a
command. A step that can be forgotten is not a gate.

**THE SHEET IS THE COPY THAT SHIPS.** `build_approved.py` reads the message bodies from
the tab, not from the generated CSV on disk. Before this, `create_campaign.py --csv` read
the CSV only, so a rep who fixed a line in the sheet would have watched the original go
to Smartlead — the same failure `send_replies` guarantee 3 exists to prevent, one stage
earlier. Edit the sheet and the edit is what sends.

**Approval reaches a campaign at the NEXT heartbeat, not the next morning.**
`build_approved` runs in all three slots: approve in the morning and midday builds it,
approve at midday and the afternoon does, approve in the evening and the morning does.

**That cadence is only safe because the dedup is per ROW.** Each built row is stamped with
its campaign name in `Built into` and never offered again. A per-tab check would have
broken here: approve 10 rows, let midday build them, approve 20 more, and a tab-level
"already has a campaign" test skips the tab — orphaning those 20 silently. Per-row means
the second batch becomes its own campaign (`Tab-b2`), which is also how a reviewer working
through a long list across sittings would expect it to behave.

**Rows are stamped only AFTER the campaign exists.** Stamping first would mark rows built
into a campaign that then failed to create, and nothing would ever retry them — the same
ordering reason `send_replies` writes `sending` before its POST but `sent` after.

**Partial approval is allowed and is the point.** Approve 30 of 36 and the campaign
carries 30; the other 6 stay eligible for a later one. A single bad draft no longer
blocks a curated list, which is the same reasoning as the validation retries.

**Launch is still manual.** This produces a DRAFTED campaign. The unsubscribe settings
have no API, so a human still opens Smartlead — see `instructions/campaign-creation.md`.
