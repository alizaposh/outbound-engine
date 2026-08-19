# Config: Pre-Send Eligibility Defaults

Tunable values for the pre-send eligibility check. The procedure — how to look leads
up, which properties to read, and what to do with the result — lives in
`instructions/pre-send-eligibility-check.md`. **This file is the source of truth for
the values**; that file describes the logic they feed.

Every gate here excludes a contact. A contact is ELIGIBLE only if it clears all of
them. Change a value here rather than hand-waving an exception for one list.

## Canonical values

```
optout_property: hs_email_optout        # native HubSpot opt-out; true -> exclude

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
new_contact_lifecycle: lead
```

## Why each value is what it is

- **`optout_property: hs_email_optout`** — the **native** HubSpot opt-out field
  ("Unsubscribed from all email"), not a custom property, and the same field set by
  HubSpot's opt-out-list import and by the Communication Preferences API. It is gate 1,
  evaluated before everything else, so an opted-out contact is reported as "opted out"
  rather than as stale or owned. Do not repoint this at a custom property: a custom
  field would miss opt-outs recorded through any other channel.
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

## Needs confirming in the portal  [FILL IN]

These are the values most likely to be wrong, because HubSpot internal values can
differ from the labels shown in the UI. Confirm each before the first live run.

- `hs_lead_status` internals for **In Progress / Connected / Open Deal**: `[FILL IN]`
- `lifecyclestage` internals — in this portal the `lead` stage is **labeled** *created*
  and `customer` is **labeled** *outreached*. The filter uses the internal values
  (`lead`, `opportunity`, `customer`). Confirmed? `[FILL IN]`
- The **Source property's own internal field key** (not the option value) that a
  create writes to: `[FILL IN]`
- Owner-name → `hubspot_owner_id` resolution for all eight names above: `[FILL IN]`

## Opt-out: resolved, and still not the only check

`hs_email_optout` is gated on as of 2026-08-19. What was previously recorded here as a
known gap is closed: a HubSpot-side opt-out, including one recorded through a channel
this engine never touched, now excludes the contact before generation.

The Smartlead suppression check in `instructions/campaign-creation.md` remains
**separate and not redundant**. It catches hard bounces, and it catches anyone who
unsubscribed from a Smartlead send in the window before that opt-out reaches HubSpot.
Neither check should be removed on the assumption the other covers it. The backlog item
that syncs Smartlead unsubscribes into HubSpot narrows that window but does not remove
the need for both.
