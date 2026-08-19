# Pre-Send Eligibility Check

**Repo location:** `instructions/pre-send-eligibility-check.md`
**Tunable values:** `config/pre-send-defaults.md` (see Config section)

## Purpose

Before any campaign is generated, filter a sales-provided lead list down to the
people we are actually allowed to enroll, using HubSpot as the source of truth.
HubSpot sees *all* activity — reps' calls, emails, meetings, and logged notes
(which is how reps record manual Instagram/text outreach) — not just what this
engine has done. So it's the right place to confirm no one is already working a
contact and that they aren't an existing customer.

This step replaces the previously scoped local dedup DB. It is a filter, not a
database: it reads HubSpot, decides ELIGIBLE vs EXCLUDED per contact, and passes
an annotated list forward. It does not store state.

## Where this runs in the flow

```
Sales-provided leads (Slack brief / CSV / HubSpot list)
        ↓
[THIS STEP] Pre-send eligibility check   ← runs here, before generation
        ↓
Message generation (eligible leads only)
        ↓
Review Sheet → Slack → approval → campaign creation
```

The full annotated list (including excluded contacts and the reason) should also
be written into the review Sheet, so reviewers can see who was filtered out and
why. Targeting decisions must be visible, not silent.

## Inputs

- A list of leads with, at minimum, an email address per lead.
- Email is the match key.

## Step 1 — Resolve each lead in HubSpot

Look each lead up by email via the contacts search endpoint
(`POST /crm/v3/objects/contacts/search`), filtering on `email`.

- Batch: search with an `IN` filter on up to ~100 emails per request and page
  through results, rather than one request per lead. Keeps you under HubSpot's
  search rate limits on larger lists.
- **found** → Step 2. **not found** → Step 4.

## Step 2 — Fetch these properties (found contacts)

| Property (internal name) | Gate | Role |
|---|---|---|
| Unsubscribed from all email (`hs_email_optout`) | Opt-out | Native HubSpot opt-out; `true` = never contact |
| Last activity date (`notes_last_updated`) | Recency | Includes logged notes = manual rep outreach |
| Last contacted (`notes_last_contacted`) | Recency | Chat/call/sales-email/meeting logged |
| Last engagement date (`hs_last_sales_activity_timestamp`) | Recency | Last sales activity |
| Has group (`has_group`) | Customer | `yes` = existing customer |
| Contact owner (`hubspot_owner_id`) | Ownership | Stores an owner **ID**, not a name — see caveats |
| Lead status (`hs_lead_status`) | Active status | Enum |
| Customer Success Manager (`customer_success_manager`) | Customer | Any value = managed customer |
| Lifecycle stage (`lifecyclestage`) | Stage | Allowed: lead, opportunity |
| Now in Sequence (`hs_sequences_is_enrolled`) | Sequence | Must be false |

## Step 3 — Decision rules

A contact is **ELIGIBLE** only if it passes **every** gate below. If any gate
fails, the contact is **EXCLUDED** with the corresponding reason. (Evaluate in
order; report the first failing reason.)

1. **Opt-out (hard gate, evaluated first)** — `hs_email_optout` must NOT be `true`.
   Exclude if `hs_email_optout = true` ("Unsubscribed from all email"). This is the
   **native** HubSpot opt-out property, not a custom one, and it is the same field set
   by HubSpot's opt-out-list import and by the Communication Preferences API. It is
   evaluated before every other gate so an opted-out contact reports "opted out" as its
   reason rather than whichever gate happens to fail next — an opt-out is a compliance
   fact, and it should never be recorded as merely stale or owned.
2. **Lifecycle stage** — `lifecyclestage` must be `lead` or `opportunity`.
   Exclude otherwise (notably `customer`).
3. **Has group** — `has_group` must NOT equal `yes`. Empty is allowed.
   Exclude if `has_group = yes` (existing customer).
4. **Customer Success Manager** — `customer_success_manager` must be empty.
   Exclude if it has any value (managed customer).
5. **Contact owner** — `hubspot_owner_id` must be empty OR not one of the
   excluded owners (see config). Exclude if owned by a listed rep.
6. **Lead status** — `hs_lead_status` must be empty OR not one of
   {In Progress, Connected, Open Deal}. Exclude if it is one of those.
7. **Now in Sequence** — `hs_sequences_is_enrolled` must be `false`.
   Exclude if already enrolled in a HubSpot sequence.
8. **Recency** — each of `notes_last_updated`, `notes_last_contacted`, and
   `hs_last_sales_activity_timestamp` must be empty OR older than 30 days ago.
   Exclude if ANY of the three falls within the last 30 days (someone is
   actively working them; a logged note counts).

Empty timestamp fields on the recency gate mean "never" and pass.

## Step 4 — Leads not in HubSpot

No record = no activity history, no owner, no CSM, not in a sequence, not a
customer, and no recorded opt-out — so it clears every gate.

- Decision: **ELIGIBLE**.
- Default action: create the contact so there's a record to write reply status
  back to later. On creation, set:
  - `lifecyclestage` = `lead` (also satisfies the lifecycle gate)
  - **Source** dropdown = option value `Outbound Email Engine` — this attributes
    every engine-created contact so it can be reported on separately from other
    sources (e.g. the "Internal Lead Scraper" source). The option's internal
    value equals its label, `Outbound Email Engine`. Confirm the internal name of
    the **Source property itself** (the field key, not the option) in HubSpot
    property settings, since that's what the API write targets.
- Configurable: `create_missing_contacts = false` to pass them through without
  creating a record.
- Annotate as "new to HubSpot" in the output.

## Output schema

One row per input lead:

| Field | Description |
|---|---|
| `email` | Match key |
| `hubspot_contact_id` | Resolved ID, or "to-create" / "created" |
| `decision` | `ELIGIBLE` / `EXCLUDED` |
| `reason` | e.g. "opted out", "active in last 30d", "has CSM", "owned by Rob Dong", "new to HubSpot" |
| `notes_last_updated` / `notes_last_contacted` / `hs_last_sales_activity_timestamp` | For transparency |
| `lifecyclestage`, `hs_lead_status`, `owner` | For transparency in review |

ELIGIBLE leads flow into generation. The full list goes into the review Sheet.

## Config values

**All tunable values live in `config/pre-send-defaults.md`, which is the source of
truth. Read them from there; do not restate them here.** That file carries the
canonical block (recency window and fields, `has_group` exclude value, the excluded-owner
names, the lead-status and lifecycle allow/exclude lists, the CSM and sequence property
names, and the create-if-missing behavior), the reasoning behind each value, and the
list of portal internals still to confirm.

Keeping a second copy in this file is how the two drift apart, so a value that needs
changing gets changed there.

## Caveats & implementation notes

- **Owner names need resolving to IDs.** `hubspot_owner_id` holds owner IDs, not
  names. Resolve the eight names to their owner IDs once via the Owners API (or
  the owner-search tool), cache the ID set, and compare against that. If a name
  doesn't resolve, surface it rather than silently skipping.
- **Confirm enum internals.** `hs_lead_status` and `lifecyclestage` store
  internal values that can differ from display labels. In your portal the
  lifecycle "lead" stage is labeled *created* and "customer" is labeled
  *outreached* — the internal values (`lead`, `opportunity`, `customer`) are what
  the filter uses. Verify the `hs_lead_status` internals for In Progress /
  Connected / Open Deal too.
- **Recency intentionally includes `notes_last_updated`.** A logged note counts
  as a contact touch here, because reps log manual outreach (Instagram, text) as
  notes. This is deliberate for this workflow.
- **Lifecycle allow-list is strict.** Only `lead` and `opportunity` pass, so
  other stages (subscriber, MQL, SQL, etc.) are currently excluded. Confirm
  that's intended; widen `lifecycle_allow` if not.
- **Opt-out is gated here (resolved 2026-08-19).** Gate 1 excludes any contact with
  `hs_email_optout = true`, so a HubSpot-side opt-out — including one made through a
  channel this engine never touched — is caught before generation. This closes what
  was previously recorded as an open gap.
  Smartlead's own suppression list still runs independently and is **not** redundant
  with this gate: it covers hard bounces and anyone who unsubscribed from a Smartlead
  send but has not yet been written back to HubSpot. Keep both. The Smartlead → HubSpot
  unsubscribe sync that narrows that window is a backlog item.

## Maps to

- Project description steps 1-3 (sales provides list → looked up → entered into
  the engine).
- Tracker: reframes the Phase 3 "design data layer" task; absorbs the old
  "dedup / create-if-missing" task into Step 1 + Step 4.
