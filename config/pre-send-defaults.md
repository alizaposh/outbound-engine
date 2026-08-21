# Config: Pre-Send Eligibility Defaults

Tunable values for the pre-send eligibility check. The procedure — how to look leads
up, which properties to read, and what to do with the result — lives in
`instructions/pre-send-eligibility-check.md`. **This file is the source of truth for
the values**; that file describes the logic they feed.

Every gate here excludes a contact. A contact is ELIGIBLE only if it clears all of
them. Change a value here rather than hand-waving an exception for one list.

## Canonical values

```
# HARD gate — never contact. OR-ed; exclude if ANY is true
optout_properties:
  - outbound_suppressed                 # engine do-not-send flag (row 59 sync + asked_to_stop)
  - hs_email_optout                     # native HubSpot global opt-out (read-only input)
  # optional third floor if outbound maps to a subscription type:
  # - "Opted out of email: <type>" == true
status_hard_values:                     # outbound_status values that are ALSO never-contact
  - opted_out                           # compliance fact, not a campaign-level skip
  - bounced                             # undeliverable; re-sending damages the domain

# SOFT gate — skip THIS campaign, reversible. Exclude if outbound_status is any of:
status_skip_values:
  - disqualified                        # not_qualified / wrong_contact (reversible)
  - in_sequence                         # already enrolled in a live campaign
status_recent_reply_skip_days: 30       # skip status=replied within this window.
                                        # This is the MID-CONVERSATION floor, NOT the
                                        # recycle window for not_now / not_interested
                                        # (that lives on outbound_recycle_after below).
recycle_property: outbound_recycle_after  # skip while this date is in the FUTURE.
                                        # Written by the reply handler on not_now
                                        # (named date, else +90d) and not_interested
                                        # (+180d) — see instructions/reply-handling.md.

recency_window_days: 30
recency_fields:
  - notes_last_updated
  - notes_last_contacted
  - hs_last_sales_activity_timestamp

has_group_exclude_value: "yes"          # has_group = yes -> existing customer

excluded_owners:                        # resolve NAMES -> hubspot_owner_id via Owners API
  - Dani Edelstein
  - Bastian Delalande
  - Ty Scearce
  - Pavlos Tiftikidis
  - Rob Dong
  - Avante Price
  - Jenny Blake
  - Will Heyman

lead_status_exclude: [In Progress, Connected, Open Deal]   # confirm internal enum values
csm_property: customer_success_manager  # any non-empty value -> exclude
lifecycle_allow: [lead, opportunity]    # confirm internal values (custom labels in portal)
sequence_property: hs_sequences_is_enrolled   # must be false
create_missing_contacts: true
new_contact_source_value: "Outbound Email Engine"   # Source dropdown option for engine-created contacts
referral_source_value: "Outbound Referral"          # Source option for wrong_contact replacements
                                        # (created, never enrolled — see reply-handling.md)
new_contact_lifecycle: lead
```

## Why each value is what it is

- **`optout_properties` — two fields, OR-ed, and neither one wins.** Gate 1 excludes a
  contact if **any** listed property is `true`. The two cover different origins and
  neither is a superset of the other, so both are required:
  - **`hs_email_optout`** is the **native** HubSpot field ("Unsubscribed from all
    email"), also set by HubSpot's opt-out-list import and the Communication
    Preferences API. It catches opt-outs recorded through channels this engine never
    touches. Treat it as a **read-only input** — the engine reads it, never writes it.
  - **`outbound_suppressed`** is the custom field the unsubscribe-sync job (row 59)
    writes when someone unsubscribes from a Smartlead send. Those opt-outs may never
    reach the native field, so gating on native alone would let them through.
  Gate 1 stays evaluated before everything else, so an opted-out contact is reported as
  "opted out" rather than as stale or owned. **Never narrow this to one property** —
  dropping either one silently reopens sending to a class of opted-out contacts.
  Property definitions live in `config/hubspot-properties.md`.
- **`status_hard_values` — status values that belong in the HARD tier.** Two
  `outbound_status` values are never-contact, not skip-this-campaign:
  - **`opted_out`** is a compliance fact. It normally rides along with
    `outbound_suppressed = true`, but if the two ever disagree — a manual status edit,
    a partial write, a backfill — status alone must still block the send. Treating it as
    soft would let a reversible campaign filter be the only thing standing between an
    opted-out contact and another cold email.
  - **`bounced`** is a deliverability fact. The address is undeliverable, so re-sending
    burns sender reputation on a guaranteed failure. Nothing about waiting a campaign
    makes a hard-bounced address deliverable.
- **`status_skip_values` / `status_recent_reply_skip_days` — the SOFT gate.** Eligibility
  is two-tier: hard means *never contact*; soft means *skip this campaign, reversibly*.
  The soft tier exists because the reply handler parks not-a-fit contacts in
  `outbound_status = disqualified` (from `not_qualified` and `wrong_contact`) **without**
  suppressing them — suppression stays reserved for opt-outs, per
  `config/hubspot-properties.md`. Without this filter, `disqualified` writes nothing any
  gate reads, so those contacts flow straight back into the next campaign and
  `not_qualified` becomes a no-op. `in_sequence` and a recent `replied` are skipped for
  the same reason a rep's recent touch is: someone is already mid-conversation.
  **Keep the tiers distinct in both directions** — a soft value promoted to hard turns a
  reversible exclusion into an apparent compliance opt-out, and a hard value demoted to
  soft reopens sending to someone who must never be contacted.
- **`status_recent_reply_skip_days: 30` is the mid-conversation floor, not a recycle
  window.** It answers "is someone still mid-thread with this contact?" Do not conflate
  it with the recycle delay: reusing 30 days there would re-approach a contact who
  declined last month.
- **`recycle_property: outbound_recycle_after` — the recycle gate, also SOFT.** A
  decline is a *wait*, not a suppression, so the reply handler stamps the earliest date
  a contact may re-enter a campaign (`not_now`: the date named in the reply, else +90d;
  `not_interested`: +180d — constants in `instructions/reply-handling.md`). This gate is
  what enforces it: **skip while the date is in the future**, and let the contact back in
  once it passes. A past or empty date passes, so no backfill is needed for contacts
  predating the property. Without this gate the dates are decoration and every declined
  contact returns in the next campaign.
- **`recency_window_days: 30`** — inside 30 days, assume a human is actively working
  the contact and stay out of their way.
- **`recency_fields`** includes `notes_last_updated` **on purpose**. Reps log manual
  outreach (Instagram DMs, texts) as notes, so a note counts as a contact touch here.
  Dropping it would make the engine blind to most manual outreach. An empty timestamp
  means "never" and passes.
- **`excluded_owners`** is a list of *names*, but HubSpot stores `hubspot_owner_id`.
  Resolve the names to IDs once per run via the Owners API and compare against that ID
  set. **A name that does not resolve must be surfaced, never silently skipped** — a
  dropped name means that rep's contacts quietly become eligible.
- **`lifecycle_allow: [lead, opportunity]`** is deliberately strict: subscriber, MQL,
  SQL, and everything else are excluded today. Widen this list if that turns out to be
  too tight.
- **`create_missing_contacts: true`** — a lead with no HubSpot record clears every gate
  by definition (no activity, no owner, no CSM, not a customer), and gets created so
  there is somewhere to write reply status back to later. Set `false` to pass those
  leads through without creating records.
- **`new_contact_source_value`** attributes engine-created contacts so they can be
  reported separately from other sources (e.g. "Internal Lead Scraper").
- **`referral_source_value` — a separate source, deliberately not the engine one.**
  A `wrong_contact` reply names a replacement, and the reply handler creates that person
  as a **referral lead that is never enrolled and never sent to**
  (`instructions/reply-handling.md`). Tagging them `new_contact_source_value` would file
  them as an outbound lead the engine had already vetted and mailed, which is exactly
  backwards: they have passed no gate. A distinct source keeps them findable as a
  hand-off queue for a human, and keeps referral-sourced pipeline separable from
  cold-sourced pipeline in reporting. **Both values write to the same Source property**
  — one field, two option values — so the internal field key below covers both.

## Needs confirming in the portal  [FILL IN]

These are the values most likely to be wrong, because HubSpot internal values can
differ from the labels shown in the UI. Confirm each before the first live run.

- `hs_lead_status` internals for **In Progress / Connected / Open Deal**: `[FILL IN]`
- `lifecyclestage` internals — in this portal the `lead` stage is **labeled** *created*
  and `customer` is **labeled** *outreached*. The filter uses the internal values
  (`lead`, `opportunity`, `customer`). Confirmed? `[FILL IN]`
- The **Source property's own internal field key** (not the option value) that a
  create writes to: `[FILL IN]`
- **Does the Source dropdown have an "Outbound Referral" option?** `referral_source_value`
  assumes that label exists. A dropdown write to a non-existent option fails (or silently
  drops, depending on the endpoint), so either create the option or change the value here
  to an existing one: `[FILL IN]`
- Owner-name → `hubspot_owner_id` resolution for all eight names above: `[FILL IN]`

## Opt-out: resolved, and still not the only check

`hs_email_optout` is gated on as of 2026-08-19, joined by `outbound_suppressed` on
2026-08-21 (OR-ed — see `optout_properties` above). What was previously recorded here as
a known gap is closed: a HubSpot-side opt-out, including one recorded through a channel
this engine never touched, now excludes the contact before generation — as does a
Smartlead-side unsubscribe once the row 59 sync writes it to `outbound_suppressed`.

The Smartlead suppression check in `instructions/campaign-creation.md` remains
**separate and not redundant**. It catches hard bounces, and it catches anyone who
unsubscribed from a Smartlead send in the window before that opt-out reaches HubSpot.
Neither check should be removed on the assumption the other covers it. The backlog item
that syncs Smartlead unsubscribes into HubSpot narrows that window but does not remove
the need for both.
