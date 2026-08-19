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
2. **Smartlead and HubSpot are the sources of truth. Never treat a CSV as the
   database.** CSVs and Google Sheets are *review surfaces for humans only*.
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
- HubSpot updates when a reply changes a prospect's sales status.
- Everything runs **locally**: Claude Code + Claude desktop scheduled tasks. No
  servers, queues, or webhook infrastructure.

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
| Local working state | **SQLite** (`data/outbound.db`, optional) | Claude's own bookkeeping: ID mappings, message versions, approvals, processed reply IDs, last-check timestamps |
| Human review | **Google Sheet / CSV** in `reviews/` | Review surface only, never authoritative |
| Bulk copy generation | **Claude Haiku via Amazon Bedrock** | Writes personalized messages at volume |

**ID mapping (store in SQLite):** HubSpot contact ⇄ Smartlead lead ⇄ campaign ⇄
generated-message version ⇄ approval ⇄ processed reply.

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
  lead-qualification.DEFERRED.md  ← out of v1 scope; kept for later

config/                    ← company-specific facts Claude relies on
  pre-send-defaults.md     ← eligibility gates: recency window, excluded owners, etc.
  positioning.md           ← what we sell, value props, proof, PROHIBITED claims
  personas.md              ← per-persona angles and messaging guidance
  smartlead-defaults.md    ← default schedule, limits, delays, sequence config

scripts/                   ← Python scripts Claude Code writes (empty to start)
data/                      ← local SQLite + working state (git-ignored)
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
   `instructions/research.md`.
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
   `instructions/campaign-creation.md`. Save the campaign ID in SQLite.
8. Launch gradually, starting with a small batch across warmed mailboxes.

### B. Reply handling (scheduled, polling)
1. On a schedule, pull replies from Smartlead since the last successful check.
2. Dedupe by Smartlead message ID; ignore already-processed replies.
3. Read the **full conversation** before doing anything.
4. Classify the reply and decide the next action. See
   `instructions/reply-handling.md`.
5. Draft (and, only for allowed categories, send) the response through the
   review gate. Stop all sequence follow-ups once a live conversation starts.
6. Update HubSpot if the reply changes sales status.
7. Record the processed reply ID + the successful-run timestamp in SQLite.

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
