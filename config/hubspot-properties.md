# HubSpot Properties — Outbound Engine

Authoritative list of the HubSpot **Contact** properties the outbound engine reads
and writes. Claude Code should treat the internal names here as stable and write to
these exact keys. All properties live in a dedicated property group named
**"Outbound Engine"** on the **Contact** object.

Design rule: HubSpot holds the CRM-visible state the sales team needs, not a mirror of
Smartlead. There is **no local database** to hold the rest, so where each piece of state
lives is set out in `CLAUDE.md` ("Architecture & sources of truth"): email is the join
key between HubSpot and Smartlead, `outbound_last_campaign_id` ties a contact to its
campaign, and the Reply Review Queue Sheet records which replies have been handled.
Do not add properties that duplicate what Smartlead already holds.

---

## Essential for v1 — create these

| Label | Internal name | Type | Options / values | Who sets it |
|---|---|---|---|---|
| Outbound Status | `outbound_status` | Dropdown select | `in_sequence`, `no_response`, `replied`, `meeting_booked`, `bounced`, `disqualified`, `opted_out` | Engine. Master lifecycle field. Covers the project step-7 "no response" write-back and the reply/meeting outcomes in one reportable field. `disqualified` is the not-a-fit landing state (see reply-intent action map); excluded from future campaigns by the eligibility status filter, not by suppression. |
| Outbound Reply Intent | `outbound_reply_intent` | Dropdown select | `interested`, `question`, `objection`, `not_interested`, `not_now`, `not_qualified`, `wrong_contact`, `asked_to_stop`, `out_of_office`, `automated_reply` | Reply classifier (tracker row 52). Only `asked_to_stop` auto-suppresses. `out_of_office` and `automated_reply` must NOT advance the lead. Full action map + precedence live in `instructions/reply-handling.md`. |
| Outbound Suppressed | `outbound_suppressed` | Single checkbox | true = suppress (do not send) | Written by the unsubscribe-sync job (row 59), the reply handler on opt-out, and manually. The do-not-send gate — opt-out is one reason among manual/other holds. **NOT the only suppression key:** the eligibility gate must suppress on this OR native `hs_email_optout` — reading only one under-suppresses. See "Suppression key" below. |
| Opt-Out Date | `outbound_opt_out_date` | Date picker | — | Unsubscribe-sync job. Compliance record. |
| Recycle After | `outbound_recycle_after` | Date picker | — | Reply handler, on `not_now` / `not_interested`. Earliest date the contact may re-enter a campaign. `not_now`: the date named in the reply if any, else reply date + 90d. `not_interested`: reply date + 180d. The SOFT eligibility tier skips a contact whose `outbound_recycle_after` is in the future. |
| Last Campaign (Smartlead) | `outbound_last_campaign_id` | Single-line text | Smartlead campaign ID/name | Engine, at enrollment (`instructions/campaign-creation.md` step 8). **Essential as of 2026-08-25:** with no local database, this is the ONLY link from a HubSpot contact to the campaign that mailed it. Nothing native captures it. Was "recommended" while a local mapping store was assumed. |

Meetings booked are tracked in v1 via the `meeting_booked` value on `outbound_status`
(no dedicated date property — see "Deferred to v2" below).

### Rules that ride on these

- **OOO must not change status.** When `outbound_reply_intent = out_of_office`, do
  **not** touch `outbound_status`. This encodes the project step-8 rule: log a reply's
  intent, but an out-of-office is not a real reply and must not advance the lead.
- **`outbound_suppressed` is our engine's do-not-send flag — but not the only key the
  gate reads.** The "true = suppress" behavior is not a property setting; it is enforced
  in the pre-send eligibility check (tracker row 32) and mirrored by a HubSpot active
  list + the Smartlead block list. The checkbox only stores the flag. See the
  suppression-key section below for how it relates to HubSpot's native opt-out.
- **`outbound_status` vs `outbound_suppressed`.** Status is the human-readable
  lifecycle state; the checkbox is the machine-enforced gate. On opt-out both are set
  (status `opted_out` + checkbox true) but they serve different jobs — keep both.
- **Suppression is opt-out only.** `outbound_suppressed` is set by exactly two things:
  the `asked_to_stop` intent (explicit removal/unsubscribe) and a deliberate manual
  human decision. Nothing else auto-suppresses — not a firm `not_interested`, not
  `not_qualified`. Not-a-fit contacts land in `outbound_status = disqualified` and are
  excluded from future campaigns by the eligibility check's **status filter** (a
  reversible, campaign-level exclusion), keeping "suppressed" to mean "opted out" for
  compliance clarity. Eligibility is therefore two-tier: HARD (never contact) =
  `outbound_suppressed = true` OR `hs_email_optout = true` OR status in `opted_out` /
  `bounced`; SOFT (skip this campaign, reversible) = status in `disqualified` /
  `in_sequence`, replied within the recent-reply window, OR `outbound_recycle_after`
  is a future date.

### Suppression key: `outbound_suppressed` vs native HubSpot opt-out

These are NOT the same field and do not conflict — they govern different sending
systems, and the reconciliation happens in the eligibility check, not by picking one.

- **Native "Unsubscribed from all email" (`hs_email_optout`)** is HubSpot's global
  email-subscription opt-out. It is set when a contact unsubscribes from a HubSpot
  marketing email (or is opted out manually/by import), it is out-of-the-box and its
  behavior is not editable, and it governs HubSpot's OWN sending tools (marketing and
  one-to-one CRM email). It does **not** stop a Smartlead send, because Smartlead sends
  outside HubSpot. HubSpot will not suppress our outbound for us.
- **`outbound_suppressed`** is our engine's scoped do-not-send flag for Smartlead
  outbound. HubSpot's own tools ignore it.

Because neither field automatically controls the other, the pre-send eligibility check
is the single reconciliation point and MUST suppress if EITHER is true:

> Suppress the contact if `outbound_suppressed = true` **OR** the contact is
> unsubscribed in HubSpot (`hs_email_optout = true`, and — if the team uses
> subscription types — the relevant `Opted out of email: <type>`). Never cold-email
> someone HubSpot already shows as opted out, even if they never hit our unsubscribe.

Write direction (v1 policy):

- On a Smartlead unsubscribe, set `outbound_suppressed = true` + `outbound_opt_out_date`
  + `outbound_opt_out_source`. This, plus Smartlead's own block list, satisfies the
  CAN-SPAM duty to stop the outbound that prompted the opt-out.
- **Cascade policy (settled): scope-match the opt-out.** A standard cold-outbound
  unsubscribe sets `outbound_suppressed` + Smartlead block + opt-out metadata only; it
  does NOT touch native `hs_email_optout`. The scoped suppression already satisfies
  CAN-SPAM, and setting the global native flag has a wide blast radius (kills the team's
  marketing and one-to-one HubSpot email too) that conflates two different consent
  contexts. EXCEPTION: if the prospect explicitly asks to be removed from ALL email /
  all communication (not just this outreach), honor that scope — but a HUMAN sets native
  `hs_email_optout`; the classifier never automates the global opt-out. (Default is
  RevOps/legal-informed, not legal advice.)
- Native opt-out is READ as a suppression input; it is never written by the engine.

Naming decision (resolved): the flag is `outbound_suppressed`, not `outbound_opted_out`.
Rationale: it is the general do-not-send gate — opt-out is one reason, but manual and
other holds also set it, so an opt-out-specific name would mislabel a manual suppression
as an opt-out (a compliance-record integrity problem). It also avoids collision with
HubSpot's overloaded native "opt out" vocabulary. The opt-out-specific siblings
(`outbound_opt_out_date`, `outbound_opt_out_source`) keep their names and populate ONLY
when the suppression reason is an opt-out; a manual hold sets `outbound_suppressed = true`
and leaves them blank, so "suppressed with opt-out metadata" reads as a true opt-out and
"suppressed without" reads as a manual/other hold.

---

## Recommended — create if you want tracing/attribution

| Label | Internal name | Type | Options / values | Who sets it |
|---|---|---|---|---|
| Opt-Out Source | `outbound_opt_out_source` | Dropdown select | `smartlead`, `manual`, `backfill_artisan` | **Dropped 2026-08-24, not built.** The opt-out date plus `outbound_status` is the compliance record; nothing writes a source. Revisit only if the Artisan backfill needs separating from live Smartlead unsubs. |

`outbound_last_campaign_id` moved to **Essential** on 2026-08-25 — see that table. It
stopped being an optional nicety when the local mapping store went away.

---

## Deliberately NOT created — native fields cover these

Do not create custom "last contacted" or "last reply" date properties. The Smartlead
HubSpot integration logs sent and replied emails as **email activities**, and
HubSpot's native calculated fields update off those automatically:

- **Last Contacted** (`notes_last_contacted`) — updates on a logged one-to-one email.
- **Last Activity Date** (`notes_last_updated`) — updates on a logged/tracked email.

These native fields are HubSpot-calculated and cannot be overwritten or redefined, so
the correct integration is "let the activity log bump them," not "write a date." This
is also the field set the sales team already filters on — reusing it avoids a parallel
property nobody adopts.

**Consequence to stay aware of:** enabling activity tracking means every cold send
bumps Last Contacted / Last Activity, so outbound-touched contacts drop out of the
"not contacted in N days" lists AEs source from. The fix is not to disable tracking —
it is to give AEs a sourcing filter that excludes contacts where `outbound_status`
is set (or `= in_sequence`), so they key off deliberate outbound state instead of
leaning on Last Contacted for a signal it wasn't built for.

---

## Deferred to v2 — do NOT build in v1

While testing and building v1, the engine writes ONLY its own `outbound_*` fields.
It does not write to, map onto, or otherwise tamper with native HubSpot sales fields.
The following are explicitly out of scope until v2:

1. **Mapping outbound engagement to native sales status.** e.g. having `interested`
   also flip native Lead Status / Lifecycle Stage (tracker row 53). Deferred so the
   team's native status stays untouched while we test. In v1, reply outcomes are
   written ONLY to the engine's own fields — `outbound_reply_intent` (the
   classification) and `outbound_status` (lifecycle changes: `replied`,
   `meeting_booked`, `opted_out`) — plus `outbound_suppressed` on an opt-out. Native
   Lead Status / Lifecycle Stage are not written in v1. Revisit in v2 once the
   classifier is trusted.
2. **Dedicated meeting-booked date property + attribution decision.** Native vs custom
   (`outbound_meeting_booked_date`) is a v2 call. In v1, track meetings with no new
   field and no native-field writes: report on contacts whose `outbound_status`
   reached `meeting_booked`, and read HubSpot's native "Date of last meeting booked in
   meetings tool" for the date. That satisfies the meetings/week metric (tracker row
   75) with zero custom plumbing.

---

## Value conventions

- Dropdown **internal values** are lowercase-underscored (`no_response`,
  `not_interested`, `asked_to_stop`). Claude Code writes to these stable internal
  values, never to the display labels.
- Confirm none of the `outbound_` internal names collide with existing properties
  before creating them.
