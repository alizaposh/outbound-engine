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
| Outbound Suppressed | `outbound_suppressed` | Single checkbox | true = suppress (do not send) | Written by the unsubscribe-sync job (`scripts/sync_unsubscribes.py`), the reply handler on opt-out, and manually. The do-not-send gate — opt-out is one reason among manual/other holds. **NOT the only suppression key:** the eligibility gate must suppress on this OR native `hs_email_optout` — reading only one under-suppresses. See "Suppression key" below. |
| Opt-Out Date | `outbound_opt_out_date` | Date picker | — | Unsubscribe-sync job. Compliance record. |
| Recycle After | `outbound_recycle_after` | Date picker | — | Reply handler, on `not_now` / `not_interested`. Earliest date the contact may re-enter a campaign. `not_now`: the date named in the reply if any, else reply date + 90d. `not_interested`: reply date + 180d. The SOFT eligibility tier skips a contact whose `outbound_recycle_after` is in the future. |
| Resume After | `outbound_resume_after` | Date picker | — | Reply handler, on `out_of_office` only. The day a sequence frozen by an auto-responder should RESTART — the date the auto-reply itself names, else reply date + `resume_ooo_default_days` (14). **Not a recycle window and not interchangeable with one:** `outbound_recycle_after` is the earliest a *declined* contact may be approached again, this is a *paused* sequence waiting to continue. Acted on and then **CLEARED** by `scripts/resume_sequences.py`, so a value present means "still waiting" and empty means "nothing pending". While it is set, `close_sequences.py` refuses to close the contact — without that guard an out-of-office lead is indistinguishable from a finished non-responder. Created 2026-09-09. |
| Outbound Sender | `outbound_sender` | Dropdown select | `carl`, `brooke`, `zach` | Engine, at first enrolment (`scripts/create_campaign.py`). **WRITE ONCE and never changed.** A prospect who heard from Carl in March must hear from Carl in September; switching persona between campaigns reads as a boiler room and discards the only continuity a cold thread has. Read by `scripts/eligibility.py --sender` as gate 10, which soft-excludes contacts belonging to a different sender. Created 2026-09-02. **Adding a sender means adding an option here**; re-deriving assignments from a hash instead would re-shuffle everyone already mailed, which is exactly why this is stored rather than computed. |
| Last Campaign (Smartlead) | `outbound_last_campaign_id` | Single-line text | Smartlead campaign ID/name | Engine, at enrollment (`instructions/campaign-creation.md` step 8). **Essential as of 2026-08-25:** with no local database, this is the ONLY link from a HubSpot contact to the campaign that mailed it. Nothing native captures it. Was "recommended" while a local mapping store was assumed. |

Meetings booked are tracked in v1 via the `meeting_booked` value on `outbound_status`
(no dedicated date property — see "Deferred to v2" below).

**Written by `scripts/sync_meetings.py`, in the morning heartbeat, as of 2026-09-15.**
Until that date this paragraph described an intention rather than a behaviour: the value
was listed above, protected from being overwritten by `sync_unsubscribes.py` and
`close_sequences.py`, and **never written by anything.** A contact who replied, received
a booking link and booked stayed `replied` for good, so the engine's headline outcome
metric was structurally always zero. Two lessons worth keeping:

- **A value being *documented* and *defended* is not evidence anything produces it.**
  Four code sites referenced `meeting_booked`; every one was a read or a guard. The guards
  made the gap harder to see, because the code looked as though it handled the state.
- **It surfaced only when the metric was asked for.** Nothing failed, no check went red —
  a dashboard tile would simply have read zero and been believed.

The source is native: the booking links in `config/meeting-routing.md` are HubSpot
meetings links, so a booking populates `engagements_last_meeting_booked` on its own, and
`sync_meetings.py` promotes the status from it. It will **not** credit a booking that
predates enrolment — 358 contacts in this portal have booked a meeting at some point, and
crediting those would inflate the one number the engine is judged on. See its guarantee 2.

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


## Re-engagement tasks (added 2026-09-25)

`outbound_recycle_after` is a **guard, not a trigger**: `eligibility.py` refuses to mail
a contact while the date is in the future, and when it passes the contact simply stops
being excluded. Nothing fired on the date, so a prospect who said "come back in June"
was re-approached only if someone happened to pull a list containing them -- and that
silence was indistinguishable from a correct skip.

`reply_check.py` now also creates a **HubSpot task** on `not_now`:

| | |
|---|---|
| **When** | `not_now`, and an `objection` that NAMES an incumbent. Not `not_interested` (+180d) -- a much colder signal that would swamp the queue -- and not a bare objection with no platform named, which is a copy problem rather than a contract. |
| **Due** | **`recycle_task_lead_days` (90) BEFORE a contract end the prospect NAMED**, so the renewal conversation happens before the paperwork. On the recycle date itself when they named nothing -- that date is our own +90 day default, and subtracting a lead time from a guess would make every vague "later" a task due today. Floored at tomorrow. 13:00 UTC so it lands on the intended day in every US timezone. |
| **Assignee** | The existing contact owner if there is one; otherwise the contact's deterministic meeting-routing owner, so recycle work spreads across the team instead of piling onto the two people who own the warmed mailboxes. |
| **Body** | What the prospect actually said, their incumbent, and the date. The wording differs on whether the date was NAMED: a named date is called a contract end, an unnamed one is labelled as our own default. Calling our guess a contract end would put a fact in the CRM the prospect never stated. |
| **Dedup** | `[outbound-engine:recycle]` in the BODY. The queue is re-read three times a day; without this a single `not_now` would grow a new task every heartbeat. The subject is unusable for matching because it carries the org name and a human may rename it. |

**An objection naming an incumbent now sets a recycle date too** (`recycle_objection_days`,
180). Found 2026-09-28: "we have a contract with RA" classifies as `objection`, objections
set no recycle date, and the contact was therefore held only by the 30-day `status=replied`
window -- eligible for a fresh cold email about a month after telling us they were under
contract. That task carries no lead time and its wording says the date is OUR estimate,
because pulling a guess 90 days forward does not make it more accurate.

**`outbound_recycle_after` is NOT moved earlier.** The task asks a human to reach out
ahead of renewal; the recycle date still governs when the ENGINE may cold-email, and
three months before a contract ends is still mid-contract. A rep who wants them in a
campaign early submits them like any other list.

**A failed dedup check does NOT create the task.** If the associations lookup errors we
cannot prove absence, and a pile of duplicates a rep must clean up by hand is worse than
a reminder that is late. Same reasoning as the `sync_meetings` cutoff fallback.


## Lifecycle stage: what the engine writes, and one portal setting to fix

**The labels are not the internal values.** `customer` displays as *Outreached* and
`opportunity` as *Qualified*. `scripts/lifecycle.py` holds the mapping; never write a
literal. Anything outside HubSpot reading `lifecyclestage == customer` as "is a paying
customer" will miscount ~17,900 contacts.

| Stage written | Internal | When | By |
|---|---|---|---|
| Outreached | `customer` | A send is CONFIRMED delivered (not at enrolment — a stage saying we reached someone we never reached is worse than none) | `sync_sends.py` |
| Qualified | `opportunity` | An `interested` reply, or a booked meeting that postdates enrolment | `reply_check.py`, `sync_meetings.py` |
| Disqualified | `1439306394` | `not_qualified` with no competitor named | `reply_check.py` |

### HubSpot silently refuses backward moves in this portal

Verified 2026-09-25, and diagnosed properly 2026-09-29. A PATCH to a LOWER displayOrder
**returns HTTP 200 and the response body itself carries the OLD value**; the property
history records nothing at all. So it is rejected at WRITE time -- not reverted
afterwards by a workflow, which was the competing explanation. There is no error to
catch, which is why `lifecycle.apply_stage` reads back every write.

**This is not the "Restrict contacts from moving backwards" portal setting.** That
governs pipeline stages and UI actions, and it was OFF throughout. This is platform
behaviour specific to `lifecyclestage` and cannot be switched off. The documented way
round it is to CLEAR the property and then set it.

**This was a live bug, not a hypothetical.** `reply_check` had written Disqualified on
`not_qualified` replies since it was built, and for every contact then at DORMANT that
write was a no-op reporting success.

### RESOLVED 2026-09-29: Dormant moved to displayOrder 1

Dormant used to sit at 6, above Deal Won, which made it terminal -- a dormant contact
could not be marked Qualified, Disqualified or anything else, and roughly a third of
every list sits there. It is now at **1**, between New and Outreached. Verified with
real writes (each reverted): New -> Dormant, Dormant -> Outreached, -> Qualified and ->
Disqualified are all accepted.

**Position 1 and not 0.** It sat briefly at 0, which fixed everything the engine writes
and broke the other direction: `New -> Dormant` became backward, silently disabling
anything that marks inactive contacts Dormant. Moving a stage to an extreme fixes one
side and breaks the other; 1 satisfies both.

### The order is READ LIVE, and that is the real lesson

The fix above exposed a worse failure than the one it fixed. `lifecycle.py` held the
stage order as a hardcoded snapshot. When the portal was re-ordered, the code did not
notice: it went on refusing exactly the promotions the settings change had enabled, and
nothing reported a problem, because "refused" is indistinguishable from "nothing to do".

`lifecycle.refresh()` now reads the live property once per process and prints a warning
when the portal disagrees with the built-in fallback. **A configuration fix that cannot
reach the code is not a fix.**

**The manual remedy for a stage stuck too far forward:** clear the property, then set
it -- an empty stage has no order to move backward from. The engine deliberately does
NOT do this; it would bypass a control set on purpose in the portal.


## `handed_off` (added 2026-09-30)

An `outbound_status` value meaning **a named human owns this conversation now.** Set by
a reviewer choosing "Hand off" on a queue row, which sends the reply and writes the
status in one action -- deliberately one decision and not two, because a handoff that
sends the introduction and forgets to stand the engine down produces the worst outcome
available: the prospect is told a colleague is taking over, and then the engine replies
again as the original sender.

| Component | Behaviour |
|---|---|
| `reply_check` | **Never drafts.** Checked before classifying, so no model call and no queue row. The reply is still marked processed so it does not re-surface every heartbeat. Counted separately in the run summary -- a conversation deliberately left alone is not the same fact as a duplicate. |
| `eligibility` | In `status_skip_values`. Never re-enrolled. SOFT and reversible: clearing the status makes them mailable again if the handoff goes nowhere. |
| `sync_meetings` | **Still promotes to `meeting_booked`.** A rep closing a meeting is the SUCCESS case for a handoff; not promoting would make every handed-off win invisible and understate exactly the outcome the engine exists to produce. Guarantee 2 still applies, so it cannot claim a booking that predates enrolment. |
| `sync_sends` | Unchanged. Logging activity to the timeline stays useful. |
| `send_replies` | Writes the status **only after a confirmed send.** A failed send means the prospect was never told anybody is taking over, so standing down would abandon a live conversation on the strength of an email that does not exist. Pinned by a self-test. |

**Why a status and not just a note.** The engine has no other way to know. The sending
mailboxes are unwatched, so a colleague CC'd on a reply is invisible to it -- the next
prospect reply arrives exactly like any other and gets drafted for. The CC tells the
prospect who is coming; this tells the engine to stop.
