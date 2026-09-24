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

excluded_owners:                        # name -> hubspot_owner_id, resolved 2026-08-24.
                                        # 6 names: Rob Dong removed 2026-09-11 and
                                        # Bastian Delalande 2026-09-16, see notes.
  - Dani Edelstein      # 82992386   danielle@posh.vip
  - Ty Scearce          # 91700241   ty@posh.vip
  - Pavlos Tiftikidis   # 87936293   pavlos@posh.vip
                                        # KEPT deliberately. On 2026-09-16 the one
                                        # contact of his on list 1902 turned out to be
                                        # mis-assigned and the owner was corrected by
                                        # hand -- but the GATE stays, because outreach to
                                        # contacts he genuinely owns is still barred.
                                        # Fixing one record is not a reason to open the
                                        # rule that protects the rest.
  - Avante Price        # 10486941   avante@posh.vip
  - Jenny Blake         # 90391601   jenny@posh.vip
  - Will Heyman         # 90391665   will@posh.vip
                                        # IDs are a convenience copy; resolve by name at
                                        # runtime so an owner change can't go unnoticed.

lead_status_exclude: [IN_PROGRESS, OPEN_DEAL]   # internals confirmed 2026-08-24.
                                    # CONNECTED REMOVED 2026-09-11: it is a
                                    # leftover value from the previous CRM, not a
                                    # statement about current engagement, so it
                                    # was excluding contacts nobody is working.
csm_property: customer_success_manager  # any non-empty value -> exclude
lifecycle_allow: [lead, opportunity, 1442770269]    # internals confirmed 2026-08-24 (labels differ)
sequence_property: hs_sequences_is_enrolled   # must be false
create_missing_contacts: false          # 2026-08-24: the filter never writes to HubSpot.
                                        # Leads are assumed to exist there already; one
                                        # that doesn't is surfaced, not created.
# Unused while create_missing_contacts is false. Kept for the day a creation step exists:
new_contact_source_value: "Outbound Email Engine"   # Source option for engine-created contacts
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
- **`lifecycle_allow`** now reads `[lead, opportunity, 1442770269]`. **1442770269 is
  "Dormant"** — added 2026-09-24, on the evidence of a real list: 1,013 of the 2,800
  "Priority Leads" sat at that stage and were being excluded, 36% of a list somebody had
  curated deliberately.

  A dormant lead is LAPSED, not disqualified, and re-engaging lapsed prospects is the
  thing this engine exists to do. Excluding them meant the engine refused the exact
  audience it was built for.

  Nothing is lost by including them: a contact who declined recently still carries
  `outbound_recycle_after` and is skipped until that date passes, whatever their
  lifecycle stage says. The recycle gate does the work people imagine this one doing.

  **Read the LABELS, not the values.** This portal's stages are non-standard — `customer`
  is labelled "Outreached", and the numeric ids are real stages with real names
  ("Dormant", "Deal Created", "Deal Won"). An unrecognised id in an exclusion report is
  a prompt to look it up, not a reason to assume it belongs there. Use
  `GET /crm/v3/properties/contacts/lifecyclestage`.
- **`create_missing_contacts: false` (2026-08-24).** The filter is strictly read-only —
  it decides, it does not write. Leads are assumed to already exist in HubSpot, so a
  lead with no record is a **list/CRM disagreement**, not a normal path. Such a lead
  still clears every gate by definition (no activity, no owner, no CSM, not a
  customer), so it stays ELIGIBLE, but the run flags it by email: nothing about it was
  actually verified, and there is nowhere to write its reply status back to later.
  Setting this to `true` aborts the filter, because no creation step exists to honor it.
- **`new_contact_source_value`** attributes engine-created contacts so they can be
  reported separately from other sources (e.g. "Internal Lead Scraper").
- **No separate referral source in v1** (decided 2026-08-24). A `wrong_contact`
  replacement is created without its own Source option; the constraint that actually
  matters — never enrolled, never sent to until it clears this check and human review —
  is enforced in `instructions/reply-handling.md`, not by the source tag. Revisit if
  referral-sourced pipeline ever needs separating from cold-sourced in reporting.

## Portal values — confirmed 2026-08-24

Read from the live portal (hub `50950747`) via the properties and owners APIs, not from
UI labels. HubSpot internal values differ from displayed labels, which is what made this
list necessary.

- **Rob Dong removed from `excluded_owners` 2026-09-11.** He owns a large share of the
  database and is not actively working most of it: on the first real rep submission
  (list 1914) his ownership excluded **31 of 41 contacts**, three quarters of a usable
  list. **Ownership turned out to be a weak proxy for "someone is working this."** The
  signals that actually mean active work are still enforced and were kept deliberately:
  `in HubSpot sequence`, the recency gates on `notes_last_contacted` /
  `hs_last_sales_activity_timestamp`, and `has CSM`. A contact Rob is genuinely working
  will trip one of those; a contact he merely owns will not. The other names remain
  — remove one only with the same evidence, a real list where that owner is blocking
  contacts nobody is touching.
- **Bastian Delalande removed 2026-09-16**, on exactly that evidence: on list 1902 his
  ownership was blocking **8 contacts** none of the active-work gates objected to. Same
  finding as Rob Dong, one list later, which is the second data point that ownership is a
  weak proxy for "someone is working this".
- **Pavlos Tiftikidis KEPT on the same list, deliberately.** His single contact on 1902
  was mis-assigned and the owner was corrected by hand in HubSpot, so that record now
  clears the gate on its own. **The gate itself stays**: outreach to contacts he
  genuinely owns is still barred, and correcting one mis-assigned record is not evidence
  about the rest. Worth keeping the distinction visible, because "this contact should not
  have been his" and "his contacts should be contactable" look similar in a list of
  exclusion reasons and mean opposite things.
- **`hs_lead_status`** — the excluded values are now `IN_PROGRESS` and `OPEN_DEAL`
  (uppercase, underscored). **`CONNECTED` was removed 2026-09-11**: it is residue from
  the previous CRM rather than a claim about current engagement, so it was excluding
  contacts nobody is working. The full enum is `NEW`, `OPEN`, `IN_PROGRESS`, `OPEN_DEAL`,
  `UNQUALIFIED`, `ATTEMPTED_TO_CONTACT`, `CONNECTED`, `BAD_TIMING`. **`lead_status_exclude`
  previously held display labels** ("In Progress"), which would have matched nothing and
  silently excluded no one.
- **`lifecyclestage`** — confirmed: `lead` is labeled *Created*, `customer` *Outreached*,
  and `opportunity` *Opportunity*. The allow-list uses internals, so it is correct.
  **Also present:** two custom numeric stages, `1403597677`
  (*Google_Paid Ads_Call Booked*) and `1421690440` (*Meta_Paid Ads_Call Booked*). Neither
  is in `lifecycle_allow`, so paid-ads contacts who booked a call are excluded — right by
  default (someone is working them), but now a deliberate exclusion rather than an
  accident of the allow-list.
- **Source property** — internal key is plain `source`; the `"Outbound Email Engine"`
  option exists, so `new_contact_source_value` writes cleanly.
- **Owners** — all eight names resolve; IDs recorded inline in `excluded_owners` above.
  Requires the `crm.objects.owners.read` scope, granted 2026-08-24.

**Re-confirm if the portal changes.** These are point-in-time reads: a renamed lifecycle
stage or a deactivated owner breaks a gate quietly, and the owner case is the dangerous
one — an unresolved name makes that rep's contacts eligible.

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
