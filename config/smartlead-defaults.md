# Config: Smartlead Campaign Defaults

Default settings applied when creating a campaign, unless a brief overrides them.
Lock these once the Smartlead account exists (Phase 1).

## Sending limits
- Per-mailbox daily ceiling: **~30 messages/mailbox/day** (initial operating ceiling).
- Ramp: start low, increase gradually as mailboxes build sending history.
- Scaling rule: add domains/mailboxes to grow volume. Never spike an existing mailbox.

## Schedule  [FILL IN]
- Sending window / timezone: `[FILL IN]`
- Sending days: `[FILL IN, e.g. weekdays only]`

## Sequence
- 3 emails per prospect.
- Inter-email delays: `[FILL IN, e.g. 3 to 4 business days between steps]`
- Stop-on-reply: **ON** (follow-ups halt when a prospect replies).

## Mailboxes
- Only warmed, healthy secondary/brand-adjacent mailboxes. Never the primary domain.
- Distribute each campaign across multiple mailboxes.

## Naming convention  [FILL IN]
- Campaign name format: `[FILL IN, e.g. YYYY-MM_audience_usecase]`

## Warmup
- Keep warmup running on new mailboxes before launch and continue some after launch.
- Pause any mailbox that develops deliverability problems.

## HubSpot activity logging (MANDATORY per campaign — MANUAL UI STEP, no API)

Smartlead's HubSpot activity logging is what makes native "Last Contacted" /
"Last Activity Date" update and what logs replies onto the contact record. Two
confirmed facts govern how we handle it:

- It is PER CAMPAIGN, and
- It is a UI toggle ONLY — there is NO API endpoint to enable it.

Consequences (design around these, don't try to automate them away):

- Activity logging cannot be enabled programmatically. Every campaign has an
  unavoidable manual step: a human enables activity logging in the Smartlead UI
  (campaign's HubSpot settings) BEFORE sends start. Miss it and that campaign
  logs nothing to HubSpot — silently, with no error.
- Campaign creation is therefore NOT fully hands-off in v1. Every campaign-creation
  path must gate sends behind this manual enable step (tracker rows 44, 71).
- This gate lives in ONE place: instructions/campaign-creation.md. Every campaign-
  creation path routes through that file and inherits the gate. The self-serve
  request workflow (tracker row 71, not yet built) must call campaign-creation.md
  at its launch step — it must NOT re-implement or bypass the gate.
- Verification gate: after enabling, confirm on a test contact that a Smartlead
  send appears as an EMAIL activity AND moved native "Last Contacted" (not only
  "Last Activity Date"). Only then release the full lead set. Activity only logs
  when the send actually flows through a healthy integration connection, so this
  check also catches a broken connection per campaign.

One-time optimization to investigate: whether Smartlead offers an account/
workspace-level default that turns activity logging on for all new campaigns. If
it exists, set it once and keep the per-campaign verification as the safety net.
That's the only lever that reduces the manual burden — worth 10 minutes to check.
