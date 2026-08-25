# Backlog

Deferred work, with the trigger that unblocks each item. Nothing here is in v1 scope
until its trigger is met.

---

## Current state

*Replace this whole section on each checkpoint — do not append a second one.*

**Last updated:** 2026-08-21. Copy-testing state is still the third 34-run; the
reply-to-CRM state model landed since (`712a437`).

*No commit hash here on purpose.* It went stale three times; `git log --oneline -5` is
always right and this line never was. Date the section, describe the state, and let git
answer "which commit".

Three full 34-contact runs have now happened, all draft-only. Review CSVs live in
`reviews/`, which is git-ignored, so the artifacts are local to whoever ran them.

### Done and committed

Everything from the previous checkpoint still holds: structural three-position
validation, retry-once, the three-branch persona default with the
platform-fabrication guard, positional length targets, subjects 2–7 words, the
CTA-family banned regex, the `repair.py` sign-off strip, the sequence-level
stat-budget WARN, and the `VOICE-ANCHOR` injection. Added since:

- **Message 2 has a defined job** (`e446c7f`). It develops one angle m1 did not cover,
  must stand alone if m1 got no reply, and its length must come from content rather
  than padding. No word floor was added. m2 median went 80.5 → 89.5 words and
  under-target dropped from 16/34 to 8/32.
- **Message 2 has its own concrete-offer CTA rule** (`46a0a06`), varied from m1's ask.
  m2 was defaulting to the banned hedge (13 of 32 bodies) because m1 and m3 carried a
  CTA rule and m2 did not.
- **Quantified commercial terms are a hard FAIL** (`a5e5cf5`, `check_commercial_terms`).
  The *existence* of a tailored offer is sayable; its *terms* are not. The vague
  bundled "financial incentives" the anchor uses still passes. 14/14 boundary tests,
  3 genuine fires and 0 false positives across 207 emails. Not auto-repaired, for the
  same reason the CTA family isn't.
- **Generation-failure fallback** (`875ff09`). On retry exhaustion the row is filled
  with the committed copy in `config/generation-failure-fallback.md`, marked
  `GENERATION_FAILED_FALLBACK`, keeps its original `generation_error`, and is counted
  and named separately in the run summary. Fallback rows are excluded from the
  validation report so they cannot inflate the pass rate. That file is deliberately
  **not** in `RULEBOOK_FILES`: a ready-made sequence in the prompt is something the
  model would echo.
- **Batch-level verbatim-opener check** (`8221aef`, WARN, called from the orchestrator).
  Flags byte-identical opening sentences reused across contacts. Caught 3 real reuses
  on replay, two of them in **m1**, not m2.

### Reply-to-CRM state model, documented not built (2026-08-21, `712a437`)

A design pass on paper only — no code, and the HubSpot properties do not exist in the
portal yet. What is now decided and written down:

- **Ten reply intents** with an action map, precedence rules, and per-intent status
  writes (`instructions/reply-handling.md`). `requested_info` and `needs_qualification`
  are retired: materials/pricing/deck/demo requests are buying signals → `interested`,
  and ambiguity goes to the human-review flag rather than a status.
- **The stop-on-reply trap is handled.** Smartlead halts follow-ups on *any* reply and
  cannot tell an auto-reply from a human, so `out_of_office` and `automated_reply` must
  RESUME the sequence and must not advance the lead. Without this, an OOO silently
  freezes a lead who never engaged.
- **Two-tier eligibility.** HARD/never-contact = `outbound_suppressed` OR
  `hs_email_optout` OR status in (`opted_out`, `bounced`). SOFT/skip-this-campaign =
  status in (`disqualified`, `in_sequence`), a reply within 30d, or a future
  `outbound_recycle_after`. The soft tier is the point: `not_qualified` and declines
  previously wrote to fields no gate read, so those contacts returned next campaign.
- **Declines are timed waits, not suppressions.** `not_now` → the date named in the
  reply, else +90d; `not_interested` → +180d. Suppression stays reserved for opt-outs,
  which is also why the flag is named `outbound_suppressed` rather than
  `outbound_opted_out`.
- **`wrong_contact` creates a referral, never an enrollment.** The named replacement is
  created (deduped by email) and must clear the eligibility check plus human review
  before any send. No dedicated referral Source option in v1.
- **Campaign creation is not fully hands-off.** Smartlead's HubSpot activity logging is
  a per-campaign UI toggle with no API endpoint, so every campaign needs a human to
  enable it before sends start — gated once, in `instructions/campaign-creation.md`.
- **Meeting owner is config, not a hardcoded name** (`config/meeting-routing.md`).

**Empty responses were never a retry gap.** They surface as `JSONDecodeError` from
`json.loads("")` and are caught by the same clause as malformed JSON, so they always
got the retry. Verified with a stub client. The `char 0` error signature cannot
distinguish a truly empty response from a bare opening code fence, but it does rule
out truncation.

### Latest 34-run (`8221aef` minus the CTA and opener commits)

8 PASS / 7 WARN / 17 FAIL / 2 generation-failure fallback. 75 of 96 generated emails
passed. Branch distribution unchanged across every run: 25 `gmv`, 9 `competitor`,
12 Pro, 22 Premium, one `platform_known=False`.

### Next task: a 34-run on the three newest changes

**The CTA rule, the verbatim-reuse rule, and the batch check have only been seen on a
5-contact sample.** None is validated at 34. Run it and read, in order:

1. **m2 CTAs.** The sample went 0/5 on the banned family, but 2 of 5 landed on
   `"Worth exploring whether…"`, an unbanned sibling hedge, and one of those stacked a
   second ask. Does that sibling spread at 34? If it does, it belongs in
   `banned-phrases.md`, not in more guidance.
2. **Batch-level findings.** Expect fewer than the 3 found on replay. Anything left is
   a real verbatim collision.
3. **Shared-prefix openers.** The batch check matches whole sentences only, so the case
   that motivated it is *not* covered: `"One thing that tends to surprise organizers…"`
   went to three contacts with divergent tails. Only the generation-side rule addresses
   that today. If prefixes still collide at 34, decide whether to match on a leading
   n-gram — that is a design call with real false-positive risk.
4. **Sign-off drift.** `model_wrote_footer` WARNs went 4 → 22 after m2 got its job
   definition, with `SIGNOFF` repairs 4 → 20. Repair catches all of it so nothing ships
   broken, but that check exists to detect prompt drift and it is firing loudly.
5. **Empty-response rate.** 4 of 34, then 2 of 34. Every failure ever seen has been a
   nameless `info@`/`contact@` contact, but most nameless contacts succeed, so treat
   that as a weak risk factor and not a cause. Two runs is thin evidence.

### Still parked

- **Placeholder sender names** in `config/senders.md` and the **unconfirmed Smartlead
  unsubscribe token** remain deliberate send-blockers. Both clear during Smartlead
  setup, still pending finance approval. (The booking-link placeholder is resolved:
  `https://meetings.hubspot.com/zach-hickman`, verified reachable 2026-08-21.)
- All six `outbound_*` properties now exist in the portal (five on 2026-08-24,
  `outbound_last_campaign_id` on 2026-08-25). Nothing on the property side is blocking.
- **Mailbox-assignment timing.** Assembly needs the sender name during generation, but
  mailbox assignment currently happens at campaign creation. Documented in
  `config/senders.md`; not implemented.
- **Branches 2 and 3 have never been exercised on real data.** Every contact in the
  list routes on `gmv` or `competitor`. The `fallback: vertical/jobtitle/company-type`
  paths and the branch-3 flag remain proven only against synthetic stubs. Testing them
  needs a list with genuinely missing signals, not this one.

---

## Google Sheets review surface
**Trigger:** after copy testing is validated.

**Auth is DONE (2026-08-25).** Service account `outbound-sheets-bot@
email-outbound-engine.iam.gserviceaccount.com`, key path in
`GOOGLE_SERVICE_ACCOUNT_JSON`, Sheets access proven end to end. Credentials are loaded
from that variable explicitly — the Google libraries default to
`GOOGLE_APPLICATION_CREDENTIALS`, which this project does not set. Reusable for any
sheet: share it with that address as Editor and add its ID to
`config/review-surfaces.md`.

**Reply Review Queue: BUILT (2026-08-25).** `scripts/review_queue.py`, see below.

**Still to build:** the *generation* review surface — "export review dataset to Google
Sheet" for campaign copy, whose link goes in Slack for approval. Until then generation
writes to a local CSV in `reviews/`.

---

## Reply Review Queue — BUILT 2026-08-25
`scripts/review_queue.py`. Sheet ID and the 15-column contract live in
`config/review-surfaces.md`, not in code.

`append_reply(reply)` is the one function the reply loop calls. It fills 13 columns and
leaves `decision` and `notes` empty — code never writes the human's columns, so a queued
row cannot arrive pre-decided. `decision` carries a strict dropdown (Approve / Edit &
send / Suppress / Do not send / Reclassify) on rows 2+, never the header.

Skips `out_of_office` and `automated_reply` (not real replies), and any reply with no
`smartlead_message_id`, since that is the dedup key. `review_reason` is `"suppress?"`
for `not_interested`, otherwise a short per-intent reason.

**Verified:** auth, header contract, all four failure messages (they distinguish
key-missing from sheet-not-shared), offline logic for skip/dedup/row-shape, then a live
append → read-back → dropdown check → dedup refusal → delete. Sheet left header-only.

**Gotcha worth remembering:** appending with `insertDataOption=INSERT_ROWS` creates a
brand-new row that does **not** inherit the decision column's data validation, so the
row lands without its dropdown. The append uses OVERWRITE (the default), which writes
into the next existing empty row and keeps the validation. Safe because the queue is
append-only.

### Where processed IDs live — decided 2026-08-25
**No local database**, so the queue Sheet's own `smartlead_message_id` column is the
record, read behind one seam: `get_processed_id_store()` in `review_queue.py`.

**The known hole:** it answers "is this reply already **in the queue**", not "was it
handled at all". A reply the engine handled *without* queuing it is invisible, and there
are two such cases:
- one auto-sent under the auto-send allowlist, and
- `out_of_office` / `automated_reply`, which are deliberately never queued — so every
  poll reclassifies them and re-resumes the sequence.

Neither is harmful today: the allowlist starts empty, and resuming an already-resumed
sequence is a no-op. It becomes real the moment anything is auto-sent. The fix when that
day comes, in preference order: a second **Handled** tab on the same sheet (one row per
reply seen, queued or not), or a HubSpot property. Both keep the no-local-DB rule and
need only that one function changed.

---

## Sync Smartlead unsubscribes to HubSpot
**Trigger:** Stage 1 once reply retrieval via the Smartlead API is running (Phase 6);
Stage 2 only after Stage 1 has run several cycles and the email matching is trusted.

**Priority: Medium, and the reason matters.** This is *not* send-safety. When a lead
clicks Smartlead's unsubscribe, Smartlead suppresses them on its own side immediately
and across all future campaigns, with no action from us. Nobody is at risk of a re-send
while this sits in the backlog. What is missing is the opt-out reaching HubSpot as the
authoritative record that reps, marketing, and the pre-send eligibility check read.

### Stage 1 — log to a Google Sheet, write nothing
On each scheduled reply-check run, pull the leads that unsubscribed in Smartlead since
the last run and append them to a Sheet. No HubSpot write yet. The point is to verify
the sync pulls the right emails with no bad matches *before* anything irreversible
happens, and to keep a human-controlled suppression checkpoint.

Sheet schema, import-ready so suppression is export → HubSpot opt-out import:
`email` (match key), `unsubscribed_at`, `campaign`, `smartlead_lead_id`, and
`pushed_to_hubspot` (blank until suppressed, date-stamped once imported).

Suppression itself stays manual: export the not-yet-pushed rows, import them through
HubSpot's **opt-out list** import ("List of contacts to opt-out of emails"), which sets
the native `hs_email_optout`, then stamp `pushed_to_hubspot`.

### Stage 2 — write the native opt-out programmatically
Flip the task from "append to sheet" to calling HubSpot's Communication Preferences API
(`POST /communication-preferences/v4/statuses/{email}/unsubscribe-all?channel=EMAIL`;
confirm the current API version and required scopes against HubSpot's docs). It sets the
same native `hs_email_optout` the manual import does, so nothing downstream changes and
the export/import step simply disappears. Optionally stamp `optout_source = Smartlead`
and `optout_date` as an audit trail.

**Carry this caution into Stage 2:** native opt-out is global and sticky. It opts the
contact out of *all* HubSpot email, not just cold outbound, and is hard to reverse. Good
for compliance, but a wrong email match globally suppresses the wrong person with no
easy undo. That is the whole reason Stage 1 verifies matching first.

**No webhooks in v1.** Both stages fold into the existing polling reply-check task. A
Smartlead `LEAD_UNSUBSCRIBED` webhook is the natural real-time upgrade if the system
ever moves to hosted infrastructure.

**Depends on:** reply retrieval via the Smartlead API; HubSpot write-back plumbing; a
reliable Smartlead-lead → HubSpot-contact match by email (shared with the pre-send check
and every other write-back).

**Related:** the one-time Artisan opt-out backfill has the same destination (HubSpot
opt-out list via manual CSV import), once the CSM provides the list.

**Resolved 2026-08-19, widened 2026-08-21: the pre-send check gates on `hs_email_optout`
OR `outbound_suppressed`.** Gate 1 of nine in `instructions/pre-send-eligibility-check.md`,
with `optout_properties` (plural) in `config/pre-send-defaults.md`. This item's premise
therefore holds — both stages feed a field the engine actually reads.

**⚠️ Stage 2 as written is superseded by the cascade policy (settled 2026-08-21).**
`config/hubspot-properties.md` now settles the scope question: **scope-match the
opt-out.** A standard cold-outbound unsubscribe sets `outbound_suppressed` + the
Smartlead block + opt-out metadata and does **not** touch native `hs_email_optout` —
the scoped suppression already satisfies CAN-SPAM, and the global flag conflates two
different consent contexts. Only an explicit "remove me from all email" earns the
native flag, and **a human sets it**; nothing automates the global opt-out.

Rewrite the stages accordingly:

- **Stage 1 is unaffected** and still worth shipping — it writes nothing. But its
  suppression path (export → HubSpot opt-out-list import → native `hs_email_optout`) is
  now the **wrong routine path**: it globally opts out every cold-outbound unsub. Retarget
  it, or keep the import strictly for the human-escalated all-email cases.
- **Stage 2 should retarget `outbound_suppressed`** (+ `outbound_opt_out_date`), not the
  Communication Preferences API. That field is what the engine's own gate reads, it is
  scoped to outbound, and it is reversible. There is no opt-out *source* field in v1
  (dropped 2026-08-24), so origin — live Smartlead unsub vs Artisan backfill — is not
  distinguishable on the contact; if the backfill needs separating later, that is the
  reason to add it back. **The Communication Preferences `unsubscribe-all` endpoint is not approved
  for automated use** — it is the global flag the policy reserves for a human.
- The **Artisan opt-out backfill** needs the same review: it was scoped to the HubSpot
  opt-out list, which is the global flag. Whether historical cold-outbound opt-outs
  should land global or scoped is now answerable by the same rule — scoped, unless the
  original request was all-email.

---

## Prior-interaction callbacks — BUILT 2026-08-25, NOT YET RUN AGAINST HUBSPOT
`scripts/enrich_callbacks.py`. Reads a contact's HubSpot timeline and emits a callback
for email 1 (`instructions/message-generation.md` §9, which holds the wording rules).
Sits between eligibility and generation:

    eligibility.py -> eligible.csv -> enrich_callbacks.py -> eligible-enriched.csv
                   -> run_generation.py --contacts eligible-enriched.csv

Kept separate from `eligibility.py` on purpose: that filter is a tight read-only
decision step with no LLM calls, and this needs the cheap LLM. `run_generation.py`
stays HubSpot-free; the callback rides the CSV seam and is recomputed each run, so no
store and nothing to go stale. Reuses eligibility's read-only client, so auth, retry,
and pacing are not duplicated.

**Classification guardrails (19 offline cases, all passing).** The whole value is in
what it refuses to call an interaction:
- **A prior send is not a prior conversation.** `hs_email_direction == INCOMING_EMAIL`
  is the crux; `EMAIL` and `FORWARDED_EMAIL` are outbound and count for nothing.
- **A voicemail is not a chat.** Only the Connected call disposition qualifies. A
  `COMPLETED` call with no disposition logged is treated as uncertain, so `none`.
- **A meeting that did not happen** (`no show`, `canceled`) is not an interaction.
- **A note is context, never itself an interaction**, though a note is searched for the
  detail once a real interaction exists, since reps log substance there.
- **Uncertain returns `none`** at every branch, and the LLM returning no detail
  downgrades `specific` to `soft` rather than inventing one.

Property names and enums were confirmed against HubSpot's live docs rather than assumed
(`hs_email_direction`, `hs_call_disposition` GUIDs, `hs_meeting_outcome`, `hs_call_status`).

### Blocked on two things before it can run for real
1. **HubSpot daily API limit was already exhausted on 2026-08-25** (every call, even a
   property read, returned 429 `DAILY`). Nothing in this project consumed that: the
   whole session used well under a hundred calls, so another integration in the portal
   is eating the quota. Worth finding out which, since it will block the eligibility
   filter on live-run day too.
2. ~~Engagement reads need scopes the token does not have.~~ **RESOLVED 2026-08-25:
   `sales-email-read` added, 10 scopes now.** It mattered more than it sounds: inbound
   email is *the* signal for "the contact replied", so without it the highest-value tier
   was unreachable and every email-only history would have read as cold.
   `enrich_callbacks.py` raises a scope-naming error rather than treating a 403 as "no
   history", which would have turned every contact cold invisibly.

### NEXT SESSION: run the dry-run (2026-08-26 or later)
The only thing standing between this and a real campaign. The daily quota was still
exhausted at the end of 2026-08-25, so **nothing here has touched a real HubSpot
timeline yet.** Do not wire the enriched CSV into a campaign until it has.

- The **10-contact `--dry-run`** on contacts with known history: some with meetings plus
  good notes, some with a meeting or call but no notes, some with only ignored outbound.
  Confirm the tiers land `specific` / `soft` / `none` and that **every `specific` detail
  is faithful to its source note**. Only then wire the enriched CSV into a real campaign.
- Cost check at campaign scale: association reads plus one cheap-LLM call per contact
  that has a real interaction. It runs on the ELIGIBLE set only.

**Verified without HubSpot:** 19 classification cases; extraction faithfulness against
the live model (voicemail text and vague admin notes both correctly yield no detail);
the CSV seam (`OUT_COLUMNS` = `ELIGIBLE_COLUMNS` + 4) parsed by
`run_generation.load_contacts`; an un-enriched `eligible.csv` still runs and produces
cold opens; and a 3-contact draft run where the `specific` contact opened "When we last
connected, you were running about one event a month on Eventbrite...", the `soft`
contact opened "Good to reconnect.", the `none` contact opened cold, and no email 2 or 3
carried a callback.

---

## Pre-send eligibility filter — BUILT 2026-08-24
`scripts/eligibility.py`. Stdlib only, so it runs on the existing venv with no
`pip install`. Separate step before generation, as designed — `run_generation.py`
stays HubSpot-free and takes `--contacts eligible-<date>.csv`.

Nine gates in two tiers, first failure wins so the reported reason is the most
important one. Emits the annotated list (every input lead, with reason and
`exclusion_tier`) plus the ELIGIBLE-only list in the shape generation expects.

**Verified:** 31 offline gate cases covering every gate, both tiers, precedence, epoch
and ISO timestamps, and the label-vs-internal lead-status trap. Then a live read-only
run over 18 real contacts + 3 synthetic rows: 21 in, 21 out, gates firing, and the
ELIGIBLE output parsed by `run_generation.load_contacts` and routed.

**Safety properties, all exercised:**
- **Strictly read-only.** No contact creation, no property writes
  (`create_missing_contacts: false`, 2026-08-24 — leads are assumed to exist in HubSpot
  already). A lead with no record is ELIGIBLE but flagged by email as a list/CRM
  disagreement: nothing about it was verified, and it has nowhere to write reply status.
- **Aborts (exit 2) if a gated property is missing** from the portal, naming the gate it
  would have disabled. A renamed property reads as empty and its gate would pass
  everybody — indistinguishable from a clean run.
- **Aborts (exit 2) if `create_missing_contacts` is `true`**, rather than silently not
  honoring it.
- **Aborts (exit 2) if an `excluded_owners` name doesn't resolve** to an owner ID, since
  an unresolved name quietly makes that rep's contacts eligible.
- **No lead silently dropped:** one output row per input row, malformed rows included
  (`decision = ERROR`).
- Config is **parsed** from `config/pre-send-defaults.md`, not restated, so the two
  cannot drift.

**Dating a reply — resolved, no new property needed.** `outbound_status = replied` gives
the fact; HubSpot's native activity timestamps give the date, because a logged reply is
an email activity and bumps `notes_last_contacted`. That holds because per-campaign
activity logging is mandatory. `replied` with no timestamp therefore means the reply was
never logged — a signal that a campaign's logging toggle is off — so the contact is
skipped as `replied (date unknown)` and the run flags the count.

### Still open on this
- **Optional belt-and-braces:** a guard in `load_contacts` that hard-skips any row whose
  `decision` is not `ELIGIBLE`. Catches "ran generation on the raw list by mistake", not
  "never ran the filter at all". Cheap, still not done.
- **Not yet run on a real sales-provided list** — only on a sample drawn from HubSpot.

---

## `outbound_*` HubSpot properties — DONE 2026-08-24

All five v1 properties exist in the **"Outbound Engine"** group on **Contact**, verified
against the spec value-by-value:

| Property | Type | State |
|---|---|---|
| `outbound_status` | Dropdown, 7 options | Rebuilt via API — the UI-created version had Title-Case internal values |
| `outbound_reply_intent` | Dropdown, exactly 10 | Rebuilt via API — Title-Case values, plus a stray `Disqualified` (belongs on status) |
| `outbound_suppressed` | Single checkbox | Correct as created |
| `outbound_opt_out_date` | Date | Correct as created |
| `outbound_recycle_after` | Date | Correct as created |
| `outbound_last_campaign_id` | Single-line text | Created 2026-08-25 (see below) |

Both dropdowns had zero data, confirmed by `HAS_PROPERTY` search, so delete + recreate
was safe; archived internal names proved reusable (probed on a disposable property
first). Old definitions were backed up before deletion.

**Not built, deliberately:** `outbound_opt_out_source` — dropped 2026-08-24, the opt-out
date plus status is the compliance record.

**`outbound_last_campaign_id` — created 2026-08-25** (single-line text, "Outbound
Engine" group). It had been skipped as "recommended tier, nothing depends on it", which
assumed a local mapping store. With no local database, this property **is** the
contact-to-campaign link, so it moved from optional to required. The engine writes it at
enrollment (`instructions/campaign-creation.md` step 8).

**Still true and worth keeping in the filter's design:** *absent ≠ false*. A property
that goes missing reads as empty, so any gate depending on it silently passes everybody
— which looks identical to a clean run. The filter should fail loudly rather than treat
an absent gated property as a pass.

### Portal values — confirmed 2026-08-24
Recorded in `config/pre-send-defaults.md`; none of these block a run any more.
- **`hs_lead_status`:** `IN_PROGRESS`, `CONNECTED`, `OPEN_DEAL`. The config previously
  held display labels, which would have matched nothing and excluded no one.
- **`lifecyclestage`:** `lead` (*Created*), `customer` (*Outreached*), `opportunity`.
  Two custom numeric paid-ads stages also exist and fall outside the allow-list.
- **Source:** internal key `source`; the `"Outbound Email Engine"` option exists.
- **Owners:** all eight names resolve (IDs recorded inline in the config), via the
  `crm.objects.owners.read` scope granted 2026-08-24.

---

## Meeting handoff model — RESOLVED 2026-08-21
**Model: persona-fronted, Zach-owned.** The sending persona stays the thread
correspondent and shares Zach's booking link on `interested` / `question` replies; the
meeting lands on Zach's calendar. No automatic mid-thread identity swap. Substantive
live conversations escalate to Zach via human review, and he decides per thread whether
to introduce himself. Written up in `config/meeting-routing.md`; consumed by
`instructions/reply-handling.md`, which references the config meeting-owner value rather
than a name.

**Booking link filled in 2026-08-21:** `https://meetings.hubspot.com/zach-hickman`
(HubSpot meetings link, so bookings land natively and the native meetings-tool date
carries the meeting per the v1 tracking decision). No longer a send-blocker. This item
is closed.

---

## Check for a Smartlead account-level activity-logging default
**Trigger:** ~10 minutes, any time. Worth doing early — it is the only lever that
reduces a recurring manual step.

HubSpot activity logging is per-campaign and UI-only (no API), so today every campaign
needs a human to toggle it before sends start. If Smartlead exposes an
account/workspace-level default that turns it on for all new campaigns, set it once and
keep the per-campaign verification as the safety net. If it does not exist, the manual
gate in `instructions/campaign-creation.md` is permanent for v1 and the self-serve
request workflow (tracker row 71) has to route through it rather than around it.

---

## Copy-rule pass from the 2026-08-19 34-run
**Trigger:** before the next generation run. One pass, all four items together — three
rule changes plus the checkpoint that records them.

Findings measured on `reviews/draft-run-34-20260819-cta-opener.csv` (7 PASS / 13 WARN /
13 FAIL / 1 fallback; 83 of 99 emails passed). Deferred deliberately, not forgotten:

1. **The `worth …` hedge family belongs in `banned-phrases.md`.** The m2 CTA rule cut the
   banned form from 13/32 bodies to 5/33, but the hedge migrated to unbanned siblings
   rather than disappearing: "Worth exploring…" ×4, "Worth comparing…" ×4, "Worth digging
   into…" ×1, and one form nothing would catch, "Worth 15 minutes?". 21 of 33 contacts
   carry at least one. A candidate pattern was tested against all 99 emails with zero
   false positives; a bare-gerund pattern has one ("One thing worth mentioning", a
   transition, not a CTA).
2. **No check exists for m2 back-references.** 7 of 33 m2 bodies open with "Following up
   on…" or "Quick follow-up.", against the explicit rule that m2 must stand alone because
   no reply is the normal case. 2 of the 7 are PASS rows, so the pass rate currently
   over-reports readiness.
3. **m1 length and opener variety.** m1 median is 113 words with 18 of 33 over the 80-110
   target and none under, so all length findings are now overshoot rather than the old
   undershoot. Separately, 26 of 33 m1 openers share the prefix "Quick question: are …"
   and 19 of 33 m2 openers share "One thing that …" — a generation-side problem the
   whole-sentence batch check sees only 4 of.
4. **Refresh the Current state section** for this run once the three land. It still
   describes the three-run state and names a next task that has since been done. (The
   2026-08-21 checkpoint added the reply-to-CRM state model but deliberately did not
   reconstruct this run's copy numbers — that is still this item's job.)

---

## Move the recycle constants into config
**Trigger:** low priority; do it if the windows get tuned more than once, or when the
reply handler is implemented.

`RECYCLE_NOT_NOW_DAYS = 90` and `RECYCLE_NOT_INTERESTED_DAYS = 180` currently live in
`instructions/reply-handling.md`. Repo convention puts tunable values in `config/`
(`config/pre-send-defaults.md` is the precedent) and instructions describe the logic
that consumes them. A `config/reply-defaults.md` would be the consistent home, and would
also give the auto-send allowlist and response-guidance placeholders somewhere to live.
Not worth a new file for two constants alone.
