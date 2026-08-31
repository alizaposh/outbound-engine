# Instruction: Reply Handling

**Purpose:** Detect, classify, and respond to prospect replies. v1 uses **polling,
no webhooks**, and follow-ups are **autonomous but review-gated**.

## Retrieval (scheduled)
1. Pull replies from Smartlead since the last successful check. Smartlead is the source
   of truth for replies; there is no local store of them.
2. Dedupe by **Smartlead message ID**; skip anything already processed.
3. For each new reply, retrieve the **full conversation** before acting.
4. After processing, record the message ID as handled — for a queued reply that is the
   `smartlead_message_id` written to the Reply Review Queue Sheet
   (`scripts/review_queue.py`). See the dedup note below.

## Classification
Read the whole thread, then classify the reply as exactly one `outbound_reply_intent`
value (enum in `config/hubspot-properties.md`):

- **`interested`** — wants to engage / learn more / meet. **Also covers a request for
  materials, pricing, a deck, or a demo** — those are buying signals, not questions.
- **`question`** — asking something before deciding, with no buying lean.
- **`objection`** — has a concern to address.
- **`not_interested`** — a decline, with nothing stronger present.
- **`not_now`** — positive or neutral, but explicitly later.
- **`not_qualified`** — structural non-fit (out of business, doesn't run ticketed events).
- **`wrong_contact`** — the sender has left, or isn't the right person.
- **`asked_to_stop`** — explicit removal / unsubscribe request.
- **`out_of_office`** — an away/on-leave auto-responder.
- **`automated_reply`** — any other machine-generated reply.

A single reply can carry several signals; resolve it with the **precedence** rules
below, then take the action from the **action map**.

**Retired values (resolved 2026-08-21).** `requested_info` and `needs_qualification`
are no longer in the enum, and **nothing routes to either**:

- **`requested_info` → route by signal.** A request for materials, pricing, a deck, or
  a demo is a **forward/buying signal** → classify as **`interested`** (send the
  materials *and* drive to the meeting). A bare informational question with no buying
  lean → **`question`**. So "send me the deck" and "send pricing" are `interested`,
  not `question`.
- **`needs_qualification` → removed as a destination; nothing routes here.** A reply
  showing structural non-fit is **`not_qualified`**. A genuinely ambiguous reply is
  handled by the **human-review flag** (see Responding), not by an enum value — v1 has
  no "park it in a status" option for ambiguity.

## Reply-intent action map (outbound_reply_intent → what the handler does)

| Intent | outbound_status write | outbound_suppressed | Smartlead sequence | Action |
|---|---|---|---|---|
| interested | replied | no | stop | Answer (send any materials asked for) **in the persona's voice**; share the **meeting owner's** booking link from `config/meeting-routing.md` |
| question | replied | no | stop | Answer the question, then share the **meeting owner's** booking link (`config/meeting-routing.md`) — persona stays the correspondent |
| objection | replied | no | stop | Handle the objection, keep engaging |
| not_now | replied | no | stop | Acknowledge; **set `outbound_recycle_after`** (see recycle windows below); nurture later |
| not_interested | replied | no | stop | Polite close; **set `outbound_recycle_after`**; stays recyclable. Flag firm/definitive rejections for optional human review — a human may manually suppress, automation does not |
| not_qualified | disqualified | no | stop | Mark disqualified; excluded from future campaigns by the eligibility status filter (reversible) |
| wrong_contact | disqualified (old contact) | no | stop | Old contact excluded; named replacement created as a **referral lead only — never enrolled, never sent**. See below |
| asked_to_stop | opted_out | YES (+ opt_out_date) | stop | Confirm removal. The ONLY classifier-driven suppression |
| out_of_office | unchanged | no | RESUME | Ignore; do NOT advance the lead or write status=replied |
| automated_reply | unchanged | no | RESUME | Ignore; do NOT advance the lead or write status=replied |

### Recycle windows — `outbound_recycle_after` (set on not_now / not_interested)

A decline is a *wait*, not a suppression. The handler writes a date to
`outbound_recycle_after`: the earliest day the contact may re-enter a campaign. The
SOFT eligibility tier skips anyone whose date is still in the future, so the field is
what actually enforces the wait.

Named constants — **defaults/floors, tunable**:

```
RECYCLE_NOT_NOW_DAYS        = 90    # not_now, when the reply names no date
RECYCLE_NOT_INTERESTED_DAYS = 180   # not_interested, always
```

- **`not_now`** → the **date named in the reply** if there is one ("circle back after
  the summer", "ask me in Q1") — use it. Otherwise `reply_date + RECYCLE_NOT_NOW_DAYS`.
  A named date **earlier** than the floor is still honored: the prospect asked for that
  timing, and honoring it is the point of the intent.
- **`not_interested`** → always `reply_date + RECYCLE_NOT_INTERESTED_DAYS`. No date is
  read from the reply here; a decline is not an invitation to negotiate timing.
- Compute from the **reply date**, not the processing date, so a delayed poll doesn't
  quietly extend the wait.
- **Never shorten an existing future date.** If a contact already carries a later
  `outbound_recycle_after`, keep the later one — declines accumulate patience, they
  don't reset it.

### Precedence (a reply can carry several signals — highest wins)

1. **asked_to_stop** — an explicit removal/unsubscribe beats everything (a "not interested + please remove me" is asked_to_stop, not not_interested).
2. **out_of_office / automated_reply** — classify by FORM. If it's an auto-responder, stop there; do not mine the auto-text for intent.
3. **wrong_contact** — sender has left / isn't the right person.
4. **not_qualified** — structural non-fit (out of business, doesn't run ticketed events).
5. **interested** — a buying-signal question or pricing ask beats a stated objection ("happy with our tool, but is yours free?" → interested).
6. **question / objection** — engaged, needs a response.
7. **not_now** — positive-or-neutral but explicitly later.
8. **not_interested** — the default decline when nothing stronger is present.

### `wrong_contact` — two contacts, and the replacement is NOT a lead to send to

A `wrong_contact` reply ("I've left", "that's not me, talk to Dana") touches two
records. Handle them separately.

**1. The old contact (the one who replied)**
- `outbound_status` = `disqualified`. **Not suppressed** — this is a reversible,
  campaign-level exclusion, not an opt-out.
- Excluded from sends by the SOFT eligibility tier.

**2. The named replacement — a referral lead, not an enrollment**
- **Create or update** the HubSpot contact, **deduping by email** — the person may
  already exist, and a second record would fragment their history and risk a
  double-send. No email in the reply? Record the referral on the old contact and hand
  it to a human; do not guess an address from a naming pattern.
- **No special source tag in v1** (decided 2026-08-24). Note the referral's origin — who
  named them — where it is visible to whoever reviews the record, but do not create or
  write a dedicated Source option for it. What keeps this safe is the no-send rule below,
  not the tag.
- **DO NOT enroll in a campaign. DO NOT send anything.** Not even a "your colleague
  suggested I reach out" note.
- The candidate must clear the **normal pre-send eligibility check**
  (`instructions/pre-send-eligibility-check.md`) **and human/AE review** before any
  outreach. A referral is not pre-qualified: they may be an existing customer, a rep's
  active contact, or already opted out — exactly what that check is for.

Why this is strict: a referral arrives mid-conversation and feels warm, which is how a
never-vetted contact ends up receiving cold email without passing a single gate. The
handler's job here ends at *creating a well-attributed record*.

### Stop-on-reply resume rule (critical)

Smartlead halts follow-ups on ANY reply and cannot tell an auto-reply from a human.
So out_of_office and automated_reply will trip stop-on-reply and silently freeze the
sequence for a lead who never engaged. For those two intents ONLY, the handler must
RESUME the paused sequence, must not set outbound_status = replied, and must not log
engagement. Every other intent correctly leaves the sequence stopped.

## Responding
- **Draft first, gate always.** A quality check runs before anything goes out.
- **Auto-send is allowed ONLY for the categories explicitly listed below.**
  Everything else is drafted for human review.
- **Stop all sequence follow-ups the moment a live conversation starts.** Hand off
  from sequence automation to conversation mode.
- Unusual, sensitive, high-value, or ambiguous conversations → **always human**. This
  flag — not an enum value — is where genuinely ambiguous replies go, now that
  `needs_qualification` is retired.
- **The review surface is the Reply Review Queue Sheet.** Anything needing a human goes
  there via `append_reply()` in `scripts/review_queue.py` (sheet + columns in
  `config/review-surfaces.md`). The engine fills every column except `decision` and
  `notes`, which are the human's, so a queued row never arrives pre-decided.
  `out_of_office` and `automated_reply` are never queued — they are not real replies and
  must not consume human attention any more than they may advance a lead.
- **Meetings — persona-fronted, owner-booked.** Never hardcode the meeting owner or
  booking link; both come from `config/meeting-routing.md`. The **sending persona stays
  the correspondent** and shares the meeting owner's booking link, so the meeting lands
  on the owner's calendar without any mid-thread identity swap. **Escalate substantive
  live conversations to the meeting owner** (human review) — he decides per thread
  whether to introduce himself. Never make that introduction automatically.

### Auto-send allowlist  [FILL IN: start empty / conservative]
Begin with an empty allowlist (everything reviewed), then add safe categories over
time as trust builds. Candidate first additions:
- `[FILL IN: e.g. simple opt-out acknowledgements]`
- `[FILL IN: e.g. "sending the one-pager you asked for"]`

## HubSpot updates

Write **only** the engine's own `outbound_*` properties. **No native HubSpot sales
fields (Lead Status, Lifecycle Stage) in v1** — that mapping is deferred to v2. Field
definitions and allowed values: `config/hubspot-properties.md`.

- **Always: `outbound_reply_intent`** — the classified intent, every time, including
  for `out_of_office` and `automated_reply`.
- **`outbound_status`** — per the action map above, which is the authority on the write
  for each intent. `meeting_booked` is set separately when the conversation produces a
  booked meeting.
- **`outbound_suppressed`** — only for `asked_to_stop`, with `outbound_opt_out_date`. No
  other intent auto-suppresses; a human may suppress manually. (No opt-out *source*
  field in v1 — dropped 2026-08-24; the date plus the status is the compliance record.)
- **Scope-match the opt-out, and never automate the global one.** A standard
  "stop emailing me" sets `outbound_suppressed` + the Smartlead block + opt-out metadata
  and **does not touch native `hs_email_optout`**. If the prospect asks to be removed
  from **all** email or all communication, that wider scope must be honored — but
  **flag it for a human**, who sets the native flag. The classifier never writes the
  global opt-out: it is irreversible and kills the team's marketing and one-to-one email
  too. Policy in `config/hubspot-properties.md`.
- **`outbound_recycle_after`** — on `not_now` and `not_interested` only, per the recycle
  windows above. Never shorten an existing future date.
- **Exception — `out_of_office` and `automated_reply` do NOT move status.** Log the
  intent, leave `outbound_status` untouched, and RESUME the sequence. Neither is a real
  reply, so neither may advance the lead.

## Response guidance by category  [FILL IN with real examples over time]
- Interested → `[FILL IN]`
- Question → `[FILL IN]`
- Objection → `[FILL IN]`
- Not interested → `[FILL IN]`
- Stop → confirm removal, suppress, no further contact.

Corrections from humans become new rules here. Keep this file current.

---

## The implementation: `scripts/reply_check.py`

Workflow B in `CLAUDE.md`. Polling, no webhooks. Dry run by default.

```bash
python scripts/reply_check.py --self-test        # 9 recycle cases, 5 parse cases, 15 live
python scripts/reply_check.py                    # DRY RUN: reads and prints, writes nothing
python scripts/reply_check.py --apply            # writes HubSpot + Smartlead + the Sheet
python scripts/reply_check.py --campaign 123 --limit 5
```

### What the API actually allows, verified live 2026-08-31

- **There is no "replies since timestamp" endpoint.** The path is
  `GET /campaigns/{id}/statistics?email_status=replied` (paginated) to find who replied,
  then `GET /campaigns/{id}/leads/{lead_id}/message-history` per lead for the thread. So
  a poll costs 1 + N calls per campaign, not 1.
- **`POST /campaigns/{id}/leads/{lead_id}/resume` returns 409 "This is the last sequence.
  You cannot resume this lead."** when no step remains. This is EXPECTED and not an
  error: an out-of-office arriving after email 3 has nothing to resume. The handler
  reports it and carries on. Any other non-200 is a real failure and raises.
- `pause` and both `unsubscribe` endpoints exist and respond. Unsubscribe was NOT
  probed live, because it would blocklist a real address.
- **The message body field is UNDOCUMENTED** and could not be observed without a live
  reply. `BODY_FIELDS` in the script lists the candidate names, and an inbound message
  matching none of them is a HARD ERROR rather than an empty reply. **First real reply:
  check this immediately.** If the run aborts naming the fields it saw, add the right
  one to `BODY_FIELDS`. That failure is the design working, not a bug.

### Two classifier boundaries worth knowing

- **`interested` and `question` are operationally identical** in the action map: same
  `outbound_status`, no recycle date, sequence stopped, queued for a human. The
  classifier is not held to the distinction on money-adjacent product questions ("what's
  the payout timing like?"), because forcing it flipped an actual pricing ask to
  `not_now`, which parks a warm lead for 90 days. The cheap error is not worth the
  expensive one.
- **`objection` vs `not_now` on a contract lock** ("we're signed with Tixr through next
  summer") is a genuine judgement call and the precedence table settles it as
  `objection`, since a constraint you could answer outranks timing. Note the consequence:
  `objection` sets NO recycle date, so a contract expiry does not schedule its own
  return, and the human in the queue has to set one manually. **Accepted for v1 and
  deferred to v2 by decision on 2026-08-31** — see "V2: give `objection` a recycle date
  of its own" in `BACKLOG.md`. Do not quietly add one here; the wait behaviour needs
  deciding first.

### What this script deliberately does not do

- **It never sends.** No call to `reply-email-thread` exists in it. Drafts go in the
  queue. The auto-send allowlist is empty (above), and this cannot bypass it.
- **It never creates a contact.** On `wrong_contact` the named replacement is printed and
  left in the queue row for a human, per the standing decision not to create contacts.
- **It never writes `hs_email_optout`.** Only `outbound_suppressed` +
  `outbound_opt_out_date`, plus a Smartlead unsubscribe. Asserted in code.
