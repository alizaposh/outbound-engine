# Config: Smartlead Campaign Defaults

Default settings applied when creating a campaign, unless a brief overrides them.
Lock these once the Smartlead account exists (Phase 1).

## Sending limits
- Per-mailbox daily ceiling: **~30 messages/mailbox/day** (initial operating ceiling).
- Ramp: start low, increase gradually as mailboxes build sending history.
- Scaling rule: add domains/mailboxes to grow volume. Never spike an existing mailbox.

## Canonical values

Read by `scripts/create_campaign.py`. Confirmed settable via the Smartlead API on
2026-08-31 (write-access test); every value below was written and read back.

```
campaign_name_format: {date}_{audience}_{usecase}   # e.g. 2026-09_ra-premium_switch
timezone: America/New_York          # DECIDED 2026-08-31. Smartlead schedules per
                                    # campaign, not per recipient, so every lead gets the
                                    # Eastern window: 09:00-17:00 ET means a Los Angeles
                                    # prospect is mailed from 06:00 local. Accepted
                                    # knowingly. If West Coast reply rates lag, the fix is
                                    # a separate campaign per region rather than a
                                    # different timezone here.
days_of_the_week: [1, 2, 3, 4, 5]   # weekdays only, Monday = 1
start_hour: "09:00"
end_hour: "17:00"
min_time_btw_emails: 10             # minutes, spreads sends inside the window
max_new_leads_per_day: 15           # per mailbox, matching the Smartlead account setting
max_leads_in_flight: 60             # INTAKE ceiling for scripts/slack_intake.py. Counts
                                    # leads inside ACTIVE/DRAFTED/PAUSED campaigns, not
                                    # sends per day: a lead occupies capacity for about
                                    # the length of the sequence (~7 days at [0,3,4]), so
                                    # a per-day ceiling would let a week of campaigns all
                                    # start on one morning. Deliberately well under the
                                    # 180/day the mailboxes could carry, because the
                                    # domains are weeks old. Raise it as they age.
seq_delay_days: [0, 3, 4]           # email 1 immediately, 2 after 3 days, 3 after 4 more
stop_lead_settings: REPLY_TO_AN_EMAIL   # stop-on-reply; already the Smartlead default
track_settings: [DONT_EMAIL_OPEN, DONT_LINK_CLICK]   # BOTH off. Open tracking off
                                    # because a tracking pixel is a
                                    # deliverability cost on cold mail. Click tracking
                                    # off added 2026-09-01 per the SDR spec: the cold
                                    # sequence carries at most one link, so click
                                    # tracking buys nothing and costs a rewrite of every
                                    # URL through a tracking domain we would then have
                                    # to maintain and warm.
send_as_plain_text: false
```

## Sequence
- 3 emails per prospect.
- **Inter-email delays: 3 days to email 2, then 4 more to email 3** (`seq_delay_days`).
- Stop-on-reply: **ON** (follow-ups halt when a prospect replies). This is Smartlead's own
  default (`REPLY_TO_AN_EMAIL`), confirmed on a created campaign, so it needs verifying
  rather than setting.
- **Per-prospect copy rides as per-lead custom fields.** The sequence step body is
  literally `{{message_1_body}}` and each lead carries its own text. Verified end to end
  on 2026-08-31: newlines survive the round trip. Steps 2 and 3 carry `subject: ""`,
  which is what makes them threaded replies.

## Mailboxes
- Only warmed, healthy secondary/brand-adjacent mailboxes. Never the primary domain.
- Distribute each campaign across multiple mailboxes.

## Naming convention
- Format: `{date}_{audience}_{usecase}`, e.g. `2026-09_ra-premium_switch`. Set in the
  canonical block above; `scripts/create_campaign.py` builds it from `--audience` and
  `--usecase` so two campaigns cannot collide on name.

## Warmup
- Keep warmup running on new mailboxes before launch and continue some after launch.
- Pause any mailbox that develops deliverability problems.

## Unsubscribe (MANDATORY per campaign — MANUAL UI, compliance-critical)

The merge tag is **`%unsubscribe-text%`** (percent-delimited, not curly braces),
confirmed against Smartlead's help centre 2026-08-26. It lives once in code, as
`UNSUBSCRIBE_TOKEN` in `scripts/assemble.py`, and is appended to every assembled body.

The tag alone does not give you a working opt-out. Two per-campaign UI settings decide
whether it renders, and neither is reachable by API:

- **"Add unsubscribe message in all emails" ON.** Also enables the one-click
  **Unsubscribe Header Tag**, which Google requires of bulk senders.
- **"Optimize Email Delivery" OFF.** It disables HTML content, and the unsubscribe link
  goes with it. This is the usual cause of a missing link.

**A test send cannot verify this.** Smartlead deliberately renders the link
non-clickable in test emails, so it looks present and dead. Only the first real send
proves it, so confirm on that send before releasing the rest of the leads.

Why this is a hard gate and not a nicety: a working opt-out is a legal requirement for
outbound email (CAN-SPAM), and the suppression rules in `config/hubspot-properties.md`
assume prospects have a way to opt out in the first place.

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

---

## HubSpot activity logging: BOTH vendor paths are dead. We log it ourselves. (2026-09-09)

**Two mechanisms were tried and both are structurally unavailable. Do not retry either
without new information from a vendor.**

### 1. Smartlead's per-campaign HubSpot sync — impossible
Smartlead support, 2026-09-09: *"HubSpot syncing cannot be enabled for leads that are
added through an API import. There are no API parameters available to enable this setting
during the import process."* Every lead this engine sends to is API-imported, so the
mandatory gate in `campaign-creation.md` **was unsatisfiable from the day it was
written**. Confirmed in practice: campaign 3921033 sent 25 emails and all 25 contacts had
every activity field `None`.

### 2. HubSpot's BCC-to-CRM — requires the sender to be a HubSpot SEAT
Smartlead does expose an account-level "BCC to CRM" setting, so this looked like the clean
answer. It is not. **Proven by a controlled pair of sends on 2026-09-09**, identical
recipient and identical BCC address, differing only in sender:

| From | A HubSpot user? | Logged? |
|---|---|---|
| `aliza.mayer@gmail.com` | no | **NO** — nothing after 15+ minutes |
| `aliza@posh.vip` | yes (one of 57 owners) | **YES** — engagement created, `notes_last_contacted` moved |

The successful engagement carried `hubspot_owner_id: 91475403`. **HubSpot attributes every
BCC-logged email to a user and drops what it cannot attribute.** None of the 12 sending
mailboxes are HubSpot seats, and making them seats means buying 12 licences for robot
mailboxes.

Also learned from the successful log: BCC moves `notes_last_contacted` and
`num_contacted_notes` but **not** `hs_last_sales_activity_timestamp`.

### The remaining path: log the activity ourselves
`/crm/v3/objects/emails` with an association to the contact. Proven on 2026-09-08: the
engagement is created and `notes_last_contacted` moves within ~20 seconds. This is now the
only option, not a preference.

## Original BCC plan, superseded by the finding above


**Smartlead support, 2026-09-09: "HubSpot syncing cannot be enabled for leads that are
added through an API import. There are no API parameters available to enable this setting
during the import process."**

Every lead this engine sends to is added by API, so **the per-campaign HubSpot activity
logging gate can never be satisfied.** Confirmed in practice first: campaign 3921033 sent
25 emails and all 25 contacts had `notes_last_contacted`,
`hs_last_sales_activity_timestamp`, `notes_last_updated`, `num_contacted_notes` and
`hs_email_last_send_date` all `None`. A rep opening any of them saw no evidence of contact.

### The replacement: BCC to CRM, set per sender account
Smartlead exposes **"BCC to CRM Settings — add a BCC email address to forward all emails
sent by this sender account to your CRM"** at the account level. Set it on all 12
mailboxes to HubSpot's portal BCC address.

**Use the BCC address, NOT the forwarding address.** HubSpot exposes two and they are not
interchangeable:

| HubSpot address | Purpose | Use it? |
|---|---|---|
| `<portal>@bcc.hubspot.com` | logs emails **you send** (outgoing) | **YES** |
| `<portal>@forward.hubspot.com` | logs emails **you receive** (incoming) | **NO** |

**Why the forwarding address is worse than logging nothing** (checked 2026-09-09, it was
the one found first):
- It logs the activity as **INCOMING**, so our outbound sends appear on the timeline as
  though the prospect emailed us. A rep reading that draws the opposite conclusion about
  who initiated contact.
- HubSpot's own description: *"If no contact is found, a new one will be created."* That
  breaks the standing no-new-contacts decision. Prospects would match existing records,
  but the message also carries our sender address, so HubSpot may create contacts for the
  12 sending mailboxes and pollute the CRM with our own infrastructure.

**Copy it from HubSpot, do not construct it.** A wrong address fails silently, which is
the worst failure mode available here.

**Why this is better than logging the activity ourselves.** It uses each vendor's intended
mechanism, adds no code, and creates nothing to maintain. Writing engagements from our
side was proven feasible (a `/crm/v3/objects/emails` engagement moves
`notes_last_contacted` within ~20 seconds) and was the fallback — but it would make this
repo the system of record for send activity, duplicating a vendor integration, and would
double-log if Smartlead ever changes its position.

### Roll out to ONE mailbox first, never twelve
Set it on a single sender, send one test to a contact that already exists in HubSpot, and
check three things before touching the other eleven:
1. the activity appears on the contact;
2. its direction reads **outgoing**, not incoming;
3. **no new contact was created** for the sender address.

Twelve mailboxes configured with a wrong address is twelve times the cleanup, and one of
the failure modes creates CRM records.

### Two things the verification must settle
1. **Our senders are not HubSpot users.** `carl.newmark@vibeposhvip.com` is not a seat in
   the portal, and HubSpot derives the "logged by" user from the sending address. Whether
   it logs an email from an unrecognised sender, logs it unowned, or drops it is unknown.
   **If it drops them, this approach is dead** and the fallback is
   `/crm/v3/objects/emails` from our side.
2. **It does not backfill.** The 25 emails already sent will never be logged. Either
   accept that for round one, or backfill from Smartlead message history using the
   engagement API.

### The verification gate, unchanged from the version written for the old toggle
> After enabling, confirm on a test contact that a Smartlead send appears as an EMAIL
> activity AND moved native "Last Contacted" (not only "Last Activity Date"). Only then
> release the full lead set.

A natural test arrives on its own: **email 2 of campaign 3921033 sends ~2026-09-11** to
all 25 contacts. Re-run the activity check then. A single test send settles it sooner.

### If it works, a side effect to expect and probably want
`notes_last_contacted` is one of gate 9's `recency_fields` with a 30-day window, so a
contact we mail becomes **gate 9 excluded for 30 days after their last send**. Today there
is NO cooldown after `close_sequences` moves a non-replier to `no_response` — they become
re-contactable immediately, which is worse. The cost is semantic: gate 9's reason will
read "recently touched" when it was our own engine, which misleads whoever reads the
exclusion report. Worth correcting the reason string once this is confirmed working.
