# Instruction: Campaign Creation (Smartlead)

**Purpose:** Turn an *approved* review dataset into a live Smartlead campaign via the
API. **Never run this without a recorded approval.** Read
`config/smartlead-defaults.md` for the default settings.

## Preconditions (all required)
- Explicit approval recorded (Slack + noted in SQLite).
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
3. **Add prospects** and attach each prospect's message_1..3 as the campaign's
   per-lead custom fields / personalized content.
4. **Configure the 3-email sequence** using those personalized fields.
5. **Stop-on-reply:** ensure follow-ups halt automatically when a prospect replies.
6. **Verify settings** before activating. Re-read them back and confirm with the
   human if anything looks off.
7. **Save the Smartlead campaign ID** to SQLite, mapped to the campaign/approval.

## Launch
- Start with a **small batch** (per your plan, ~100 contacts) across multiple warmed
  mailboxes. Watch deliverability + reply quality, then ramp gradually.
- Never spike volume on one mailbox/domain; scale by adding mailboxes/domains.
- Pause any mailbox/domain showing deliverability problems.

## TODO / [FILL IN]
- Confirm the exact Smartlead API endpoints/fields once the account exists (Phase 1
  tracker task: "Confirm Claude can CREATE/manage campaigns via API").
- Lock the campaign-naming convention and default delays in `config/smartlead-defaults.md`.
