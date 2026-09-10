# CLAUDE.md: Outbound Engine Operating Manual

This file is read automatically by Claude Code. It is the top-level operating manual
for the AI outbound email engine. Read it fully before doing anything in this repo.

---

## What this system is

An AI-run outbound email system. Claude handles lead selection, message generation,
campaign creation, reply handling, and iteration. **Smartlead** handles email
infrastructure and sending. **HubSpot** is the CRM. **Slack** is used for campaign
review and approval.

The goal of a finished campaign request is to be as simple as:

> "Reach out to these N people about this product / use case. For message one,
> focus on this problem and this offer."

Claude turns that into a complete, reviewed, approved, launched campaign.

---

## Golden rules (do not break these)

1. **Never launch or send anything without explicit human approval.** In v1, no
   campaign goes live without a recorded approval in Slack. No reply is auto-sent
   outside the categories explicitly allowed in `instructions/reply-handling.md`.
   **A scheduled job delivering a reply a human marked `Approve` is not auto-sending**
   — a person read that exact text and chose to send it; only the delivery is
   automated. The `auto_send_intents` allowlist, which *would* send with no human, is
   empty and stays empty.
2. **Smartlead and HubSpot are the sources of truth. Never treat a CSV as
   authoritative.** CSVs and Google Sheets are *review surfaces for humans*. The one
   exception is narrow and explicit: the Reply Review Queue Sheet is also the record of
   which replies have been queued, because there is no local store to keep it in.
3. **Respect stop / unsubscribe / opt-out immediately.** If a prospect asks to
   stop, they are suppressed everywhere and never contacted again. Follow-ups stop
   the moment a prospect replies.
4. **Stay within sending limits.** ~30 messages per mailbox per day ceiling. Scale
   by adding domains/mailboxes, never by spiking volume on existing ones.
5. **Only make claims allowed in `config/positioning.md`.** Never invent
   capabilities, customers, metrics, or guarantees. Prohibited claims are listed
   there. Treat that list as hard rules.
6. **Credentials live in environment variables (`.env`), never in code, prompts,
   or committed files.** See "Credentials" below. `.env` is git-ignored.
7. **When unsure, stop and ask the human.** Ambiguous, sensitive, or high-value
   situations always go to a person.

---

## v1 scope

**In scope for v1:**
- One personalized sequence of **3 emails** per prospect, generated before launch.
- Campaign creation in Smartlead via API.
- Reply retrieval via the Smartlead API on a schedule (**polling, no webhooks**).
- Reply classification + drafted responses, with autonomous follow-up that is
  **review-gated** (a quality check runs before anything goes out).
- HubSpot updates on a reply, to the engine's **own** fields only: the classified
  intent goes to `outbound_reply_intent`, and the reply also moves `outbound_status`
  (`replied`, `meeting_booked`, or `opted_out`). v1 writes **no native HubSpot sales
  fields** (Lead Status, Lifecycle Stage) — that mapping is deferred to v2. See
  `config/hubspot-properties.md`.
- Everything runs **locally**: Claude Code + Claude desktop scheduled tasks. No
  servers, queues, or webhook infrastructure. The schedule is three weekday slots
  running `scripts/heartbeat.py`, which posts to Slack on every run so a missed slot is
  visible rather than silent — see `instructions/scheduled-tasks.md`.

**v1 scope caveat — campaign creation is not fully hands-off.** Enabling Smartlead's
HubSpot activity logging is a per-campaign UI toggle with no API endpoint. Every
campaign therefore has one mandatory manual step (a human enabling activity logging
in the Smartlead UI before sends start), gated in instructions/campaign-creation.md.
This is the single point where v1 requires a human in the Smartlead UI; everything
else in campaign creation is API-driven.

**Deferred (not v1). Do not wire into the live flow:**
- **Lead qualification.** See `instructions/lead-qualification.DEFERRED.md`. The
  structure exists so we can revisit post-v1, but v1 does not qualify/score leads
  before generation. The review dataset therefore contains contact fields +
  message_1..3 only (no qualification columns).

**Decided: the campaign request channel is a Slack brief.**
- A stakeholder posts the campaign audience (a lead source reference) + a short brief
  as a Slack message. That message *is* the campaign brief. Claude reads it, retrieves
  the leads, generates, posts the review link back in Slack, collects feedback, and
  launches only after explicit Slack approval. Requires a Slack bot token (see `.env`).

---

## Architecture & sources of truth

| Layer | System | Role |
|---|---|---|
| Email sending, warmup, mailboxes, deliverability | **Smartlead** | Source of truth for email/campaign activity and replies |
| CRM: contacts, companies, sales status | **HubSpot** | Source of truth for CRM data |
| Engine bookkeeping | **HubSpot `outbound_*` properties** + **Google Sheets** | Where the engine records its own state — see below |
| Human review | **Google Sheet / CSV** in `reviews/` | Review surface, and the queue's own record of what has been queued |
| Bulk copy generation | **Claude Haiku via Amazon Bedrock** | Writes personalized messages at volume |

**There is no local database.** No SQLite, no local state file, no working DB. The engine
keeps no private store: everything it needs to remember lives in a system a human can
open and read — HubSpot, Smartlead, or a Sheet. This is a deliberate constraint, not a
gap waiting to be filled. It costs some convenience and buys two things: no state can
silently disagree with the systems of record, and nothing important is lost when a
laptop is.

**So where does each piece of state live?**

| What needs remembering | Where it lives |
|---|---|
| Contact ⇄ campaign | `outbound_last_campaign_id` on the HubSpot contact |
| Contact ⇄ sender | `outbound_sender` on the contact, **write once**. Keeps the same persona corresponding with a prospect across months |
| Contact ⇄ Smartlead lead | **Email is the join key.** Both systems key on it; no mapping table needed |
| Reply outcome / lifecycle | `outbound_status`, `outbound_reply_intent` on the contact |
| Suppression, recycle date | `outbound_suppressed`, `outbound_recycle_after` on the contact |
| A sequence paused by an out-of-office | `outbound_resume_after` on the contact — the day to restart. Cleared once restarted, so set = still waiting |
| Which replies are already handled | `smartlead_message_id` in the Reply Review Queue Sheet (`config/review-surfaces.md`) |
| Generated message versions | The review CSV in `reviews/`, plus what is live in the Smartlead campaign |
| Approval | The Slack thread where it was given, plus the Smartlead campaign it produced |

**Email is the join key throughout.** It is what the lead lists, HubSpot, and Smartlead
all carry, which is why the pre-send check matches on it too.

---

## Repository map

```
CLAUDE.md                  ← you are here: the operating manual
README.md                  ← human-facing overview + how to run
GETTING-STARTED.md         ← setup: install, create repo, first session
.env.example               ← credential template (copy to .env; never commit .env)
requirements.txt           ← Python dependencies (for scripts Claude Code writes)

instructions/              ← reusable "how to do each job" files
  pre-send-eligibility-check.md  ← HubSpot eligibility filter; RUN THIS BEFORE GENERATING
  research.md              ← how to research a prospect from available data
  message-generation.md    ← tone, structure, CTA, prohibited claims, 3-email logic
  campaign-creation.md     ← how to build & configure a Smartlead campaign via API
  reply-handling.md        ← classify replies, draft responses, auto-send rules
  campaign-analysis.md     ← what metrics to pull and how to turn them into rules
  scheduled-tasks.md       ← the v1 scheduler: Claude Desktop tasks + Slack heartbeat
  lead-qualification.DEFERRED.md  ← out of v1 scope; kept for later

config/                    ← company-specific facts Claude relies on
  pre-send-defaults.md     ← eligibility gates: hard/soft tiers, recency, excluded owners
  hubspot-properties.md    ← the outbound_* Contact properties: names, values, write rules
  positioning.md           ← what we sell, value props, proof, PROHIBITED claims
  personas.md              ← per-persona angles and messaging guidance
  meeting-routing.md       ← meeting owner + booking link; never hardcode a name
  review-surfaces.md       ← review Sheet IDs + columns (Reply Review Queue)
  senders.md               ← mailbox → sign-off name (PLACEHOLDER data today)
  banned-phrases.md        ← phrasing the generator must never produce
  generation-failure-fallback.md  ← what to do when generation fails a prospect
  smartlead-defaults.md    ← schedule, limits, delays, HubSpot activity-logging gate
  reply-defaults.md        ← recycle windows, the OOO resume wait, and the (empty,
                             enforced) auto-send allowlist. Parsed by reply_check.py;
                             the numbers live here only
  analysis-defaults.md     ← the 200-delivered floor below which no rate is quoted, and
                             which intents count positive/negative/deferred. Parsed by
                             campaign_report.py, which refuses to start if these buckets
                             and INTENTS disagree

scripts/                   ← Python (stdlib + anthropic only)
  eligibility.py           ← THE PRE-SEND FILTER. Run before generation. Read-only
  enrich_callbacks.py      ← optional: reads logged EMAIL history, adds callback_*
                             columns for §9 warm opens. Read-only. Runs between the
                             two below
  run_generation.py        ← draft-only generation: CSV in, reviewed CSV out.
                             HubSpot-free by design; callbacks arrive on the CSV
  reply_check.py           ← WORKFLOW B. Polls Smartlead for replies, classifies,
                             updates outbound_* in HubSpot, resumes auto-responders,
                             queues the rest. DRY RUN BY DEFAULT; never sends a reply
  heartbeat.py             ← THE SCHEDULED RUN. Shells the polling + sync jobs, and in
                             the morning slot send_replies, then posts to Slack EVERY
                             run, so silence means broken
  send_replies.py          ← THE ONLY THING THAT SENDS TO A PROSPECT. Sends replies a
                             human approved in the review Sheet. DRY RUN BY DEFAULT.
                             Runs in the morning heartbeat slot, capped at 25/run, so
                             marking `Approve` is enough — see scheduled-tasks.md
  sync_sends.py            ← logs engine sends AND prospect replies to the HubSpot
                             contact timeline as email engagements. The ONLY way reps
                             see our sends: both vendor paths are unavailable
  close_sequences.py       ← finished sequences -> outbound_status=no_response, so a
                             non-replier is contactable again instead of stuck
                             in_sequence forever. DRY RUN BY DEFAULT. Will NOT close a
                             contact with outbound_resume_after set: that sequence is
                             paused for an absence, not finished
  resume_sequences.py      ← restarts a sequence an out-of-office froze, on the date the
                             auto-reply named. Without it a prospect who was merely on
                             holiday gets email 1 and is never contacted again. Runs
                             AFTER close_sequences (see its docstring). DRY RUN BY DEFAULT
  sync_bounces.py          ← Smartlead bounces -> HubSpot outbound_status=bounced.
                             DRY RUN BY DEFAULT. Never sets outbound_suppressed: a
                             bounce is a deliverability fact, not a consent decision
  sync_unsubscribes.py     ← Smartlead unsubscribes -> HubSpot outbound_suppressed.
                             DRY RUN BY DEFAULT. Scoped suppression only, never the
                             native global opt-out
  campaign_report.py       ← THE WEEKLY REVIEW. Reads Smartlead + HubSpot, writes only
                             to a Sheet. Human reply rate (excludes auto-responders,
                             unlike Smartlead's own count), outcome split, Wilson
                             intervals. REFUSES to quote a rate below 200 delivered — a
                             "4%" from one reply in 25 invites a copy change built on a
                             single email. --write appends history to the Campaign
                             Report tab (the rate cell stays EMPTY below the floor, so
                             nobody charts it); --slack posts the headline. Monday slot
  review_queue.py          ← appends replies needing a human decision to the review
                             Sheet. Never writes the decision/notes columns
  export_review.py         ← pushes a generation run to the review Sheet, one tab per run
  create_campaign.py       ← builds a DRAFTED Smartlead campaign from approved copy.
                             NEVER launches; one sender per campaign
  assemble.py / repair.py / validate.py  ← sign-off assembly, repairs, copy checks
data/                      ← input lead lists / working CSVs (git-ignored)
reviews/                   ← exported review CSV/Sheet links (git-ignored)
```

---

## Core workflows

### A. Campaign creation
1. Take the lead source (HubSpot list / Google Sheet / CSV) and the brief.
2. **Before generating anything, run the pre-send eligibility check.** Filter the list
   against HubSpot per `instructions/pre-send-eligibility-check.md`. Only **ELIGIBLE**
   leads go on to generation; the full annotated list, including every EXCLUDED contact
   and its reason, goes into the review surface so targeting decisions are visible.
   This step absorbs the old dedupe-and-create pass: email is the match key, and a lead
   with no HubSpot record is eligible and gets created there (that file's Step 4).
3. Research each prospect using available company + contact data. See
   `instructions/research.md`. Run `scripts/enrich_callbacks.py` on the ELIGIBLE list
   first — **not optional as of 2026-09-10**, and it is a step in
   `slack_intake.run_pipeline`. It was described as optional here and the automated path
   duly skipped it, so every rep request produced cold opens even for contacts with a
   real prior conversation. It is the strongest defence against sounding
   machine-written and costs one read-only pass: it reads each contact's logged email history in HubSpot and adds
   `callback_tier` / `callback_detail` columns, so email 1 can open on a real prior
   interaction (`instructions/message-generation.md` §9). A prior *send* with no reply
   is not an interaction; uncertain always means no callback.
4. Generate the 3-email sequence per prospect with the cheap LLM. See
   `instructions/message-generation.md`. Later emails must read correctly even if
   earlier ones got no reply.
5. Export the review dataset to a Google Sheet / CSV in `reviews/`
   (fields: first_name, last_name, email, job_title, company, message_1, message_2,
   message_3). Post the link + campaign brief in Slack.
6. Collect feedback. Turn feedback into **reusable rules** in `config/` and
   `instructions/message-generation.md`. Do not just fix individual emails.
   Regenerate a sample. Repeat until the copy consistently meets the bar.
7. On explicit approval, create the Smartlead campaign. See
   `instructions/campaign-creation.md`. Record the campaign on each enrolled contact
   (`outbound_last_campaign_id`) so a HubSpot record traces back to its campaign.
8. Launch gradually, starting with a small batch across warmed mailboxes.

### B. Reply handling (scheduled, polling)
1. On a schedule, pull replies from Smartlead since the last successful check.
2. Dedupe by Smartlead message ID; ignore already-processed replies.
3. Read the **full conversation** before doing anything.
4. Classify the reply and decide the next action. See
   `instructions/reply-handling.md`.
5. Draft (and, only for allowed categories, send) the response through the
   review gate. Stop all sequence follow-ups once a live conversation starts.
6. Update HubSpot's `outbound_*` fields: write the classified intent to
   `outbound_reply_intent`, and move `outbound_status` to `replied`,
   `meeting_booked`, or `opted_out`. **Never write native sales fields in v1.**
   Exception: an `out_of_office` intent must not move `outbound_status`.
7. Record the reply as handled: its `smartlead_message_id` in the Reply Review Queue
   Sheet, which is what step 2 dedupes against. There is no local store — see
   "Architecture & sources of truth".

---

## Credentials

All secrets come from environment variables loaded from `.env` (git-ignored).
Never hardcode or commit a key. Copy `.env.example` → `.env` and fill it in.
Expected variables are documented in `.env.example`.

**Bulk generation runs on Amazon Bedrock, not the first-party Anthropic API.**
Auth is a Bedrock long-term API key in `AWS_BEARER_TOKEN_BEDROCK`, sent as
`Authorization: Bearer`, with the region in `AWS_REGION`. Two consequences worth
keeping straight:
- **Model IDs are Bedrock-shaped**, carrying the `anthropic.` provider prefix and a
  version suffix, optionally with a `us.` cross-region inference profile in front:
  `us.anthropic.claude-haiku-4-5-20251001-v1:0`, not the bare first-party ID.
  Requests go to `bedrock-runtime.$AWS_REGION.amazonaws.com` with
  `"anthropic_version": "bedrock-2023-05-31"` in the body and no `model` field,
  since the model sits in the URL path.
- **Billing is AWS at Bedrock's rates**, separate from both Anthropic's list pricing
  and the Claude subscription that runs Claude Code.

### Bedrock integration: the decided shape

Verified working end to end. Use this exactly rather than re-deriving it.

| Piece | Value |
|---|---|
| Client | `anthropic.AnthropicBedrock` (**not** `AnthropicBedrockMantle`) |
| Endpoint | `https://bedrock-runtime.$AWS_REGION.amazonaws.com` (resolved by the client) |
| Auth | Bearer token from `AWS_BEARER_TOKEN_BEDROCK` |
| Region | `AWS_REGION` (currently `us-east-1`) |
| Model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| SDK | `anthropic==0.122.0`, on Python 3.11+ |

```python
client = anthropic.AnthropicBedrock(aws_region=os.environ["AWS_REGION"])
```

- **Do not pass `api_key`.** The SDK reads `AWS_BEARER_TOKEN_BEDROCK` from the
  environment on its own and sets `Authorization: Bearer`, skipping SigV4.
- **Gotcha: never pass `api_key` together with AWS credentials.** Combining it with
  `aws_access_key`, `aws_secret_key`, `aws_session_token`, or `aws_profile` raises
  `ValueError`. The bearer token replaces AWS credentials, it does not supplement
  them.
- **Why not Mantle:** `AnthropicBedrockMantle` targets a different endpoint
  (`bedrock-mantle.$AWS_REGION.api.aws/anthropic`) and takes bare `anthropic.`
  prefixed model IDs. Our ID is the `bedrock-runtime` inference-profile form, so it
  belongs to `AnthropicBedrock`.
- **Why not boto3:** `invoke_model` would need hand-built JSON bodies and
  byte-decoded responses. The Anthropic SDK speaks the Messages API shape directly.

---

## Sending & deliverability guardrails

- **Never send from the primary company domain.** Only warmed secondary/
  brand-adjacent domains connected to Smartlead.
- Keep warmup running on new mailboxes before and after launch; pause any mailbox
  showing deliverability problems.
- Every message must comply with applicable outbound-email law for the recipient
  (e.g. CAN-SPAM in the US: accurate sender identity, a valid physical mailing
  address, and a working opt-out). Maintain a suppression list and honor it.
- Keep a persistent **suppression list** of anyone who opted out, bounced hard, or
  asked to stop. Check it before adding anyone to a campaign.

---

## How to work in this repo (for Claude Code)

- **Before generating any campaign, run the pre-send eligibility check per
  `instructions/pre-send-eligibility-check.md`.** Generate for ELIGIBLE leads only. A
  list that has not been through that filter is not ready to generate from, however
  the leads arrived.
- Before generating copy, read `config/positioning.md`, `config/personas.md`, and
  `instructions/message-generation.md`.
- Before creating a campaign, read `instructions/campaign-creation.md` and
  `config/smartlead-defaults.md`.
- When a human gives feedback, update the relevant instruction/config file and note
  what changed and why. This repo is the persistent memory of the system.
- Prefer small, reviewable steps. Show the human what you're about to do before
  doing anything that sends, launches, or writes to HubSpot/Smartlead.
