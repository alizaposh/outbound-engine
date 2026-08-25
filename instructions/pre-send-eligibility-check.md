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

This step replaces the previously scoped local dedup store. It is a filter and nothing
more: it reads HubSpot, decides ELIGIBLE vs EXCLUDED per contact, and passes an
annotated list forward. **It stores no state** — every gate is answered from HubSpot at
run time, so there is nothing to keep in sync.

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
| Unsubscribed from all email (`hs_email_optout`) | Opt-out | Native HubSpot opt-out; `true` = never contact. Read-only input |
| Outbound Suppressed (`outbound_suppressed`) | Opt-out (hard) | Custom; engine do-not-send flag (row 59 sync + `asked_to_stop`). `true` = never contact |
| Outbound Status (`outbound_status`) | Status (hard **and** soft) | Custom; **hard** if `opted_out` / `bounced`, **soft** if `disqualified` / `in_sequence`, or `replied` within 30d |
| Recycle After (`outbound_recycle_after`) | Recycle (soft) | Custom; set on `not_now` / `not_interested`. A **future** date = skip until it passes. Empty/past = passes |
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

1. **Opt-out (hard gate, evaluated first)** — exclude the contact if **ANY** of these
   is `true`:

   ```
   Exclude from sending (NEVER contact) if ANY of:
     - outbound_suppressed == true       # engine do-not-send flag (row 59 sync + asked_to_stop)
     - hs_email_optout == true           # native HubSpot global opt-out (read-only input)
     - outbound_status in (opted_out, bounced)   # compliance / deliverability facts
     # optional third floor if outbound maps to a subscription type:
     # - "Opted out of email: <type>" == true
   ```

   **Neither field wins — it is an OR, and both are mandatory.** `hs_email_optout` is
   the native property ("Unsubscribed from all email"), the same field set by HubSpot's
   opt-out-list import and the Communication Preferences API, so it catches opt-outs
   recorded through channels this engine never touches; the engine only ever reads it.
   `outbound_suppressed` is the custom field the unsubscribe-sync job (row 59) writes for
   Smartlead-side unsubscribes, which may never reach the native field. Checking only
   one silently reopens sending to the other's opt-outs.

   **Two `outbound_status` values are hard, not soft.** `opted_out` is a compliance fact
   and `bounced` a deliverability one; neither becomes contactable by waiting a campaign.
   `opted_out` normally rides with `outbound_suppressed = true`, but if the two ever
   disagree — manual edit, partial write, backfill — status alone must still block.

   This gate is evaluated before every other one so an opted-out contact reports "opted
   out" as its reason rather than whichever gate happens to fail next — an opt-out is a
   compliance fact, and it should never be recorded as merely stale or owned.
2. **Outbound status (soft gate, evaluated second)** — skip the contact for **this
   campaign** if `outbound_status` is any of:

   ```
   Skip for this campaign (reversible) if outbound_status in:
     - disqualified          # not_qualified / wrong_contact — reversible, not suppressed
     - in_sequence           # already live in another campaign
   ...or status == replied within the last 30 days (status_recent_reply_skip_days)
   ...or outbound_recycle_after is a FUTURE date   # declined; waiting out the window

   NOTE: opted_out and bounced are NOT here — they are hard, in gate 1.
   ```

   **This is a soft, reversible exclusion, not suppression.** It is the gate that makes
   `not_qualified` and `wrong_contact` mean something: the reply handler writes those to
   `outbound_status = disqualified` **without** setting `outbound_suppressed`, because
   suppression is reserved for opt-outs. If nothing reads status, a disqualified contact
   flows straight back into the next campaign and the classification is a no-op. Report
   the reason as "disqualified" / "in sequence" / "replied recently" — never as "opted
   out", which would misrepresent a reversible skip as a compliance opt-out.

   **`status_recent_reply_skip_days: 30` is the mid-conversation floor, not a recycle
   window.** It asks "is someone still mid-thread with this contact?" — a different
   question from when a declined contact may be approached again.

   **The recycle gate: `outbound_recycle_after` in the future = skip.** The reply handler
   stamps that date on `not_now` (the date named in the reply, else +90d) and
   `not_interested` (+180d), so this gate is what turns a decline into an actual wait
   rather than a note nobody reads. It is **self-clearing** — once the date passes the
   contact is eligible again with no cleanup job — and an **empty or past date passes**,
   so contacts predating the property need no backfill. Report the reason as "recycling
   until <date>" so a reviewer can see it is a timed wait, not a rejection.
3. **Lifecycle stage** — `lifecyclestage` must be `lead` or `opportunity`.
   Exclude otherwise (notably `customer`).
4. **Has group** — `has_group` must NOT equal `yes`. Empty is allowed.
   Exclude if `has_group = yes` (existing customer).
5. **Customer Success Manager** — `customer_success_manager` must be empty.
   Exclude if it has any value (managed customer).
6. **Contact owner** — `hubspot_owner_id` must be empty OR not one of the
   excluded owners (see config). Exclude if owned by a listed rep.
7. **Lead status** — `hs_lead_status` must be empty OR not one of
   {`IN_PROGRESS`, `CONNECTED`, `OPEN_DEAL`}. Exclude if it is one of those.
   **Match the internal values, not the display labels** ("In Progress" matches
   nothing and would exclude no one).
8. **Now in Sequence** — `hs_sequences_is_enrolled` must be `false`.
   Exclude if already enrolled in a HubSpot sequence.
9. **Recency** — each of `notes_last_updated`, `notes_last_contacted`, and
   `hs_last_sales_activity_timestamp` must be empty OR older than 30 days ago.
   Exclude if ANY of the three falls within the last 30 days (someone is
   actively working them; a logged note counts).

Empty timestamp fields on the recency gate mean "never" and pass.

## Step 4 — Leads not in HubSpot

**Leads are assumed to already exist in HubSpot** (`create_missing_contacts: false`,
set 2026-08-24). This filter never writes to the CRM, so a lead with no record is a
**disagreement between the list and the CRM**, not a routine case.

No record = no activity history, no owner, no CSM, not in a sequence, not a customer,
and no recorded opt-out — so it clears every gate:

- Decision: **ELIGIBLE**, reason `NOT IN HUBSPOT - verify before sending`.
- **Surfaced, not created.** The run lists these by email, because two things are true
  of them that are not true of any other ELIGIBLE lead: nothing was actually verified
  against the CRM, and there is nowhere to write reply status back to later.
- **No contact creation anywhere in this step.** If a creation step is wanted later it
  is a separate, explicitly-invoked script — setting `create_missing_contacts: true`
  aborts this filter rather than silently doing nothing.

## Output schema

One row per input lead:

| Field | Description |
|---|---|
| `email` | Match key |
| `hubspot_contact_id` | Resolved ID, or "to-create" / "created" |
| `decision` | `ELIGIBLE` / `EXCLUDED` |
| `reason` | e.g. "opted out", "bounced", "disqualified", "in sequence", "replied recently", "recycling until 2026-11-19", "active in last 30d", "has CSM", "owned by Rob Dong", "new to HubSpot" |
| `exclusion_tier` | `hard` (never contact) or `soft` (skipped this campaign, reversible). **`hard`** for opt-out, `hs_email_optout`, `opted_out`, `bounced`. **`soft`** for `disqualified`, `in sequence`, `replied recently`, `recycling until …`, and the recency/owner/customer gates |
| `notes_last_updated` / `notes_last_contacted` / `hs_last_sales_activity_timestamp` | For transparency |
| `lifecyclestage`, `hs_lead_status`, `owner` | For transparency in review |

ELIGIBLE leads flow into generation. The full list goes into the review Sheet.

## How to run it

Implemented in `scripts/eligibility.py` (stdlib only — no pip install needed).

```
./.venv/bin/python scripts/eligibility.py --leads path/to/leads.csv
```

Outputs two CSVs in `reviews/` (git-ignored): the **annotated list** (every input lead
with decision, reason, tier) for the review Sheet, and an **ELIGIBLE-only list** in the
exact shape `run_generation.py --contacts` expects. Generation is then:

```
./.venv/bin/python scripts/run_generation.py --contacts reviews/eligible-<date>.csv --mailbox <mailbox>
```

**Strictly read-only.** It never writes to HubSpot — no contact creation, no property
writes. It reads, decides, and writes two CSVs.

**It aborts rather than run a weakened filter** (exit code 2) if a gated property is
missing from the portal, if an `excluded_owners` name doesn't resolve to an owner ID, or
if `create_missing_contacts` is `true`. Each would otherwise let contacts through, or
silently not do what the config says, while looking like a clean run.

### How `replied` gets dated
`outbound_status = replied` records **that** a prospect replied, not **when** — it is a
status, not a date. Gate 2 needs the timing ("within
`status_recent_reply_skip_days`"), so the two work together:

- **`outbound_status` supplies the fact.** Only a contact whose status is `replied` is
  considered for this gate at all.
- **HubSpot's native activity timestamps supply the date.** A logged reply *is* an email
  activity, so it bumps `notes_last_contacted` / `notes_last_updated`. The freshest of
  the three recency fields dates the reply.

This is sound precisely because per-campaign HubSpot activity logging is **mandatory**
(see `config/smartlead-defaults.md`) — a reply on a properly configured campaign always
leaves a timestamp. So no `outbound_replied_at` property is needed.

**The failure case is diagnostic:** a contact with `status = replied` and *no* activity
timestamp means the reply never got logged, which points straight at activity logging
being off for that campaign. Such a contact is skipped as `replied (date unknown)` —
reversible, unlike mailing into a live conversation — and the run flags the count as a
signal to check that campaign's logging toggle.

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
- **Enum internals, confirmed 2026-08-24.** `hs_lead_status` and `lifecyclestage`
  store internal values that differ from display labels, and the filter matches
  the internals. `hs_lead_status` excludes `IN_PROGRESS`, `CONNECTED`,
  `OPEN_DEAL`. Lifecycle `lead` is labeled *Created* and `customer` *Outreached*;
  the allow-list uses `lead` / `opportunity`. Values live in
  `config/pre-send-defaults.md`. Re-confirm if the portal's enums are edited.
- **Recency intentionally includes `notes_last_updated`.** A logged note counts
  as a contact touch here, because reps log manual outreach (Instagram, text) as
  notes. This is deliberate for this workflow.
- **Lifecycle allow-list is strict.** Only `lead` and `opportunity` pass, so
  other stages (subscriber, MQL, SQL, etc.) are currently excluded. Confirm
  that's intended; widen `lifecycle_allow` if not.
- **Opt-out is gated here (resolved 2026-08-19; widened to two fields 2026-08-21).**
  Gate 1 excludes any contact with `hs_email_optout = true` **or**
  `outbound_suppressed = true`, so both a HubSpot-side opt-out — including one made
  through a channel this engine never touched — and a Smartlead-side unsubscribe synced
  by row 59 are caught before generation. This closes what was previously recorded as an
  open gap.
  Smartlead's own suppression list still runs independently and is **not** redundant
  with this gate: it covers hard bounces and anyone who unsubscribed from a Smartlead
  send but has not yet been written back to HubSpot. Keep both. The Smartlead → HubSpot
  unsubscribe sync that narrows that window is a backlog item.

## Maps to

- Project description steps 1-3 (sales provides list → looked up → entered into
  the engine).
- Tracker: reframes the Phase 3 "design data layer" task; absorbs the old
  "dedup / create-if-missing" task into Step 1 + Step 4.
