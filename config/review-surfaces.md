# Config: Review Surfaces

Google Sheets the engine writes to for human review. **Review surfaces only** —
Smartlead and HubSpot remain the sources of truth. Nothing here is authoritative; a
row in a sheet is a request for a human decision, not a record of one.

## Reply Review Queue

One row per reply that needs a human decision, appended by the reply-check workflow.

```
REPLY_REVIEW_SHEET_ID: 1VznhnN3cKr7mzJySPLcPqcbLAow2ivRJI1Abwsknyt0
REPLY_REVIEW_TAB: Untitled
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
