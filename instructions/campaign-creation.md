# Instruction: Campaign Creation (Smartlead)

**Purpose:** Turn an *approved* review dataset into a live Smartlead campaign via the
API. **Never run this without a recorded approval.** Read
`config/smartlead-defaults.md` for the default settings.

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
4. **Add prospects** and attach each prospect's message_1..3 as the campaign's
   per-lead custom fields / personalized content.
5. **Configure the 3-email sequence** using those personalized fields.
6. **Stop-on-reply:** ensure follow-ups halt automatically when a prospect replies.
7. **Verify settings** before activating. Re-read them back and confirm with the
   human if anything looks off.
8. **Record the campaign on each enrolled contact** — `outbound_last_campaign_id` in
   HubSpot, so a contact traces back to the campaign that mailed it. Smartlead holds the
   campaign itself; email is the join key. No local mapping store.

## Launch
- Start with a **small batch** (per your plan, ~100 contacts) across multiple warmed
  mailboxes. Watch deliverability + reply quality, then ramp gradually.
- **Gate the full lead set behind the activity-logging check** in
  `config/smartlead-defaults.md`: after the first send, confirm on a test contact that
  it lands as an EMAIL activity and moved native "Last Contacted", not just "Last
  Activity Date". Only then release the rest of the leads — this also catches a broken
  integration connection on that campaign.
- Never spike volume on one mailbox/domain; scale by adding mailboxes/domains.
- Pause any mailbox/domain showing deliverability problems.

## TODO / [FILL IN]
- Confirm the exact Smartlead API endpoints/fields once the account exists (Phase 1
  tracker task: "Confirm Claude can CREATE/manage campaigns via API").
- Lock the campaign-naming convention and default delays in `config/smartlead-defaults.md`.
