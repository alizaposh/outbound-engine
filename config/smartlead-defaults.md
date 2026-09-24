# Config: Smartlead Campaign Defaults

Default settings applied when creating a campaign, unless a brief overrides them.
Lock these once the Smartlead account exists (Phase 1).

## Sending limits
- Per-mailbox daily ceiling: **30 messages/mailbox/day.** RAISED from 15 on 2026-09-17,
  applied to all 12 accounts by `scripts/set_send_limits.py --limit 30 --apply` and
  verified by read-back.
  - The evidence for raising it: **189 lifetime cold sends across the four domains with
    ZERO bounces**, all 12 mailboxes warmup ACTIVE at 99-100%, and the cap demonstrably
    binding — Carl's four mailboxes were sitting at 12/12/12/13 of 15 while his 94-lead
    campaign was rate-limited.
  - 30 is the ceiling named in `CLAUDE.md` golden rule 4, so this is the top of the
    documented range rather than a new frontier. `set_send_limits.py` warns above it.
  - **What this does NOT measure.** Bounces are the easy signal; the real risk of more
    volume is silent inbox-to-spam placement, and open and click tracking are both OFF by
    deliberate decision (`track_settings`), so a degradation shows up only as a reply rate
    drifting down — lagging and noisy at this volume. Read bounces AND replies before
    going further, and per golden rule 4 the way past 30 is more mailboxes, not a higher
    number here.
- Fleet capacity: **12 mailboxes × 30 = 360/day**, or 120/day per sender identity.
  - This line read "~30 messages/mailbox/day" while the account was actually set to 15
    until 2026-09-16, overstating capacity by 2×. The figures above are now the measured
    account state, not an aspiration; re-derive them from
    `GET /email-accounts` rather than trusting this file if a decision turns on them.
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
max_new_leads_per_day: 40           # CAMPAIGN-WIDE new leads per day, NOT per mailbox.
                                    # The comment here said "per mailbox, matching the
                                    # Smartlead account setting" until 2026-09-16 and was
                                    # wrong on both halves. Two different settings exist
                                    # and conflating them makes volume planning wrong by
                                    # the mailbox count:
                                    #   * campaign `max_leads_per_day` — how many NEW
                                    #     leads ENTER the campaign each day. A ramp
                                    #     control, campaign-wide.
                                    #   * email account `message_per_day` (30 on all 12
                                    #     as of 2026-09-17) — the per-mailbox daily SEND
                                    #     cap, and the deliverability throttle. 4
                                    #     mailboxes per sender x 30 = 120 sends/day.
                                    #     WRITTEN as `max_email_per_day`; the API reports
                                    #     it as message_per_day and rejects that name on
                                    #     write. Use scripts/set_send_limits.py.
                                    #
                                    # **VERIFIED 2026-09-17: the value DOES apply.** An
                                    # earlier note here said otherwise, because campaigns
                                    # 3955179 and 3921033 read back 50 and 30. Those two
                                    # predate the setting or were changed in the UI; all
                                    # three campaigns built on 2026-09-17 read back
                                    # exactly 15, the config value at the time.
                                    #
                                    # RAISED 15 -> 30 the same day. It was the ACTUAL
                                    # bottleneck, not the per-mailbox cap: the three live
                                    # campaigns each sent exactly 15/15/16 on their first
                                    # day, pinned by this number, and raising
                                    # message_per_day to 30 on its own would have changed
                                    # nothing. 30 matches the mailbox cap, so one
                                    # sender's 4 boxes can absorb 30 new leads a day plus
                                    # the follow-ups they generate: peak ~90 sends/day
                                    # against 120 of capacity.
                                    #
                                    # RAISED 30 -> 40 on 2026-09-24. 30 was chosen when
                                    # campaigns were 46-94 leads, where it emptied the
                                    # queue in three days. At 657 leads per campaign it
                                    # became the binding constraint and left a QUARTER
                                    # of the mailboxes idle: 30 new leads x 3 emails =
                                    # 90 sends/day against 120 of capacity.
                                    #
                                    # 40 is not a round number, it is the arithmetic:
                                    # 4 mailboxes x 30/day = 120 sends, divided by 3
                                    # emails per contact. It saturates the fleet exactly.
                                    # Saturating is not reckless here -- 30/mailbox/day
                                    # is itself the conservative cap, so this uses the
                                    # budget already decided rather than exceeding it.
                                    # Takes email 1 across 657 leads from 22 days to 16.
                                    #
                                    # An existing campaign does NOT pick this up. Run
                                    # `create_campaign.py --verify <id> --repair`, which
                                    # checks max_leads_per_day as of the same date --
                                    # it did not before, which is why three live
                                    # campaigns sat at the old value unnoticed.
log_sends_enabled: true             # scripts/sync_sends.py writes engine sends and
                                    # replies to the HubSpot contact timeline. TRUE
                                    # because both vendor paths are unavailable: Smartlead
                                    # cannot sync API-imported leads, and HubSpot's BCC
                                    # only logs mail from a HubSpot seat. SET TO FALSE the
                                    # day Smartlead supports it, or every activity is
                                    # logged twice.
max_leads_in_flight: 1700            # INTAKE ceiling for scripts/slack_intake.py. Counts
                                    # leads inside ACTIVE/DRAFTED/PAUSED campaigns, not
                                    # sends per day: a lead occupies capacity for about
                                    # the length of the sequence (~7 days at [0,3,4]), so
                                    # a per-day ceiling would let a week of campaigns all
                                    # start on one morning. Deliberately well under the
                                    # 180/day the mailboxes could carry at the time.
                                    # (Fleet capacity is 360/day since 2026-09-17; this
                                    # ceiling was not raised with it, because it paces
                                    # young domains rather than tracking throughput.)
                                    #
                                    # RAISED 60 -> 100 on 2026-09-10, which the previous
                                    # note anticipated ("raise it as they age"). A
                                    # 41-lead request was being QUEUED behind the 25
                                    # already in flight, 66 > 60, and would not have run.
                                    # The arithmetic at 66 in flight: 50 sends still due
                                    # on the existing 25 (emails 2 and 3) plus 123 for
                                    # the new 41, so ~173 sends over ~10 days, about
                                    # 17/day against the 180/day the fleet carries --
                                    # roughly 10% utilisation. The ceiling was never
                                    # about throughput; it paces young domains. 100
                                    # keeps that pacing intent with room for one real
                                    # campaign alongside one in flight.
                                    # Still well short of 180/day. Raise further only
                                    # with a reason, and never to clear a backlog.
                                    #
                                    # RAISED 100 -> 250 on 2026-09-16 for a 204-lead
                                    # round split across ALL THREE senders. 36 in
                                    # flight + 204 = 240, so 100 would have QUEUED it
                                    # and the morning would have produced nothing.
                                    #
                                    # The arithmetic, since "raise only with a reason":
                                    # 612 sends for the new 204 plus ~72 still owed on
                                    # the 36 in flight = ~684, spread over the ~11 days
                                    # a [0,3,4] sequence occupies once ramp is included
                                    # -- about 60-70/day against the 180/day the fleet
                                    # carries, so roughly 35-40% utilisation, or ~63%
                                    # in the compressed case where Smartlead front-loads
                                    # email 1. Previous rounds ran near 10%.
                                    #
                                    # THE SPLIT ACROSS THREE SENDERS IS WHAT MAKES THIS
                                    # SAFE, and it is a condition rather than a detail.
                                    # The same 204 on Brooke and Zach alone is 8
                                    # mailboxes, not 12, which pushes the same volume to
                                    # 70-95% of each mailbox's 15/day cap for about five
                                    # days. Use scripts/split_by_sender.py, which keeps
                                    # existing ownership and least-loads the rest.
                                    #
                                    # All 12 mailboxes were warmup ACTIVE at 99-100%
                                    # reputation when this was raised. Revisit if any
                                    # mailbox drops, and do NOT treat 250 as headroom
                                    # for a single-sender campaign of that size.
                                    #
                                    # RAISED 250 -> 1700 on 2026-09-24 for a 1,400-lead
                                    # round. 186 in flight + 1400 = 1586, so 1700 is the
                                    # number plus a little headroom rather than a round
                                    # figure chosen for looks.
                                    #
                                    # **1,400 was chosen over the 2,800 originally
                                    # asked for, and the reason is the domains rather
                                    # than the ceiling.** 4,200 sends is already 8x
                                    # everything these four domains have ever sent
                                    # (~511). 2,800 would have been 16x, in a month,
                                    # with open tracking off -- so a reputation problem
                                    # would surface as a reply rate quietly sagging
                                    # rather than as an alert. The second 1,400 goes
                                    # after this round's bounce data, not before.
                                    #
                                    # This is now well ABOVE a day's fleet capacity
                                    # (360), which earlier notes treated as the
                                    # comparison. That is fine and expected: a lead
                                    # occupies in-flight capacity for its whole ~11-day
                                    # sequence, so at steady state the ceiling should be
                                    # roughly the sequence length times the daily rate.
                                    # It is not a throughput number.
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

## How big should a campaign be

**Tell a rep: 100-200 contacts per request.** Decided 2026-09-16.

**Campaign size is almost unrelated to deliverability risk, and that is the thing most
people get backwards.** The risk lever is the per-mailbox DAILY RATE, which Smartlead
enforces at the email account's `message_per_day: 15` whatever the campaign size. A 500-lead campaign
sends no faster from any one mailbox than a 50-lead campaign; it just runs longer.
Smartlead imposes no meaningful per-campaign cap. So "keep campaigns small to protect the
domains" is not a real strategy — the pacing already does that, and shrinking campaigns
only shrinks the signal.

What size actually governs is **DURATION**, and that is arithmetic. One sender has 4
mailboxes at 30/day, so 120 sends/day, and each contact costs 3 sends. **Revised
2026-09-17 when the cap went 15 -> 30; the knee doubled with it:**

| Contacts, one sender | Sends | Days to push | Campaign length |
|---|---|---|---|
| 46 | 138 | 1.2 | ~7 days, delay-bound |
| 100 | 300 | 2.5 | ~7 days, delay-bound |
| 200 | 600 | 5 | ~8 days |
| **280** | 840 | 7 | **~7-9 days — the knee** |
| 400 | 1200 | 10 | ~13 days |
| 800 | 2400 | 20 | ~3 weeks |

`seq_delay_days: [0, 3, 4]` means a sequence takes 7 days on its own. **Below ~280 per
sender the delays bind, not throughput**, so the campaign finishes in about that 7-9 days
regardless. Above ~280 it stretches, and a three-week campaign means slow feedback and
copy approved a month earlier still landing in inboxes.

**The recommended request size stays 100-200, and the reason is no longer throughput.**
At 30/day the fleet could carry far more; what has not changed is that a reviewer has to
read every draft, and 200 contacts is already 600 bodies. The binding constraint moved
from the mailboxes to the human, which is worth saying out loud because raising the cap
makes it tempting to raise the request size with it. Revisit when auto-approval clears
the exit criterion in golden rule 1, not because there is spare sending capacity.

- **Under ~50 is fine but inefficient.** Approval and the manual Smartlead UI step cost
  the same per campaign whatever its size, so a 30-lead request pays full overhead for a
  fraction of the signal. Batch small asks together instead.
- **Over ~250 needs `max_leads_in_flight` raised** and runs 2+ weeks. Two rounds beat one.
- **Never size on how many leads exist. Size on how many a human will READ.** At 200
  contacts that is 600 bodies in one review tab, and the reviewer is the real bottleneck —
  not the mailboxes. This is what golden rule 1's auto-approval exit criterion in
  `CLAUDE.md` exists to relieve.

**Small campaigns do NOT cost you measurement.** `campaign_report.py` pools every
campaign into an "ACROSS ALL N CAMPAIGN(S)" total and applies the 200-delivered floor to
that total, so a series of 46-lead campaigns reaches a quotable rate just as a single
200-lead one does. Worth stating because the opposite is the intuitive assumption, and it
would otherwise argue for oversized campaigns for the wrong reason.

**One sender per campaign is fixed** (`create_campaign.py` guarantee 5), so a request
spanning senders becomes one campaign each. `scripts/split_by_sender.py` does that split,
keeping existing ownership and least-loading the remainder.

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

## ~~HubSpot activity logging (MANDATORY per campaign — MANUAL UI STEP)~~ SUPERSEDED

> **This whole section is obsolete, kept only so the reasoning is traceable. Read
> "BOTH vendor paths are dead" further down instead.** It describes activity logging as a
> mandatory manual toggle. It is not manual — it is **impossible** for our leads, because
> Smartlead cannot enable HubSpot sync for API-imported leads and every lead this engine
> sends is API-imported. `scripts/sync_sends.py` replaces it entirely.
>
> Left here because the two facts below — per campaign, UI only — are accurate about
> Smartlead's feature, and because deleting the section would hide why the engine ever
> expected a human to do this.

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
