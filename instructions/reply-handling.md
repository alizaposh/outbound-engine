# Instruction: Reply Handling

**Purpose:** Detect, classify, and respond to prospect replies. v1 uses **polling,
no webhooks**, and follow-ups are **autonomous but review-gated**.

## Retrieval (scheduled)
1. Pull replies from Smartlead since the last successful check timestamp (in SQLite).
2. Dedupe by **Smartlead message ID**; skip anything already processed.
3. For each new reply, retrieve the **full conversation** before acting.
4. After processing, store the message ID and update the last-check timestamp.

## Classification
Read the whole thread, then classify the prospect's reply as one of:
- **Interested** — wants to engage / learn more / meet.
- **Question** — asking something before deciding.
- **Requesting info** — wants materials/details.
- **Objection** — has a concern to address.
- **Not interested** — a soft or hard no.
- **Stop / opt-out** — asked to stop. → Suppress everywhere, halt all contact.
- **Needs qualification** — unclear fit (relevant because qualification is deferred
  in v1; flag these for a human).

Then decide the next action for that category.

## Responding
- **Draft first, gate always.** A quality check runs before anything goes out.
- **Auto-send is allowed ONLY for the categories explicitly listed below.**
  Everything else is drafted for human review.
- **Stop all sequence follow-ups the moment a live conversation starts** — hand off
  from sequence automation to conversation mode.
- Unusual, sensitive, high-value, or ambiguous conversations → **always human**.

### Auto-send allowlist  [FILL IN — start empty / conservative]
Begin with an empty allowlist (everything reviewed), then add safe categories over
time as trust builds. Candidate first additions:
- `[FILL IN: e.g. simple opt-out acknowledgements]`
- `[FILL IN: e.g. "sending the one-pager you asked for"]`

## HubSpot updates
- When a reply changes sales status (interested, meeting, not interested, opt-out),
  update the HubSpot contact accordingly.

## Response guidance by category  [FILL IN with real examples over time]
- Interested → `[FILL IN]`
- Question → `[FILL IN]`
- Objection → `[FILL IN]`
- Not interested → `[FILL IN]`
- Stop → confirm removal, suppress, no further contact.

Corrections from humans become new rules here — keep this file current.
