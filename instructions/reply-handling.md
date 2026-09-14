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
- **`objection`** — a concern a reply could address. **Includes a named incumbent**
  ("we already use X", "we're happy with X"): a stated reason is a concern.
- **`not_interested`** — a **bare** decline that gives no reason. If they said why, it is
  an `objection`.
- **`not_now`** — positive or neutral, but explicitly later.
- **`not_qualified`** — structural non-fit (out of business, doesn't run ticketed events).
- **`wrong_contact`** — the sender has left, or isn't the right person.

**A `wrong_contact` who volunteered a NEW ROLE gets asked about it (added 2026-09-14).**
Real reply: *"I no longer work at Chopin. I'm now the Programs and Booking Manager at the
legendary Churchill's Pub. For the Chopin Foundation you can email info@chopin.org..."*

The draft thanked him and stopped, which is what the rule said — and the rule was written
for a different situation. *"Ask nothing further"* exists so the engine does not pester a
stranger for a colleague's contact details. **This person is not a stranger:** he
disqualified himself for the company we mailed and, unprompted, told us he now runs
booking somewhere that sells tickets. He is a better prospect than the one we wrote to.

So the draft now congratulates the move and **asks** whether ticketing is something he
handles there. Ask, never assert — we know nothing about the new company beyond its name,
so no claim about its events, its size, or what it needs.

The referral rule is unchanged: the replacement addresses he volunteered go in the queue
row for a human, and the engine still creates no contact.

**A `wrong_contact` who names no new role still stops after the thank-you.** The
distinction is whether *they* offered the opening.
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
| interested | replied | no | stop | Answer (send any materials asked for) **in the persona's voice**; share **the sender's own** booking link from `config/meeting-routing.md` |
| question | replied | no | stop | Answer the question, then share **the sender's own** booking link (`config/meeting-routing.md`) — the meeting lands on their calendar |
| objection | replied | no | stop | Acknowledge, leave the door open, **no call and no link** — see below |
| not_now | replied | no | stop | Acknowledge; **set `outbound_recycle_after`** (see recycle windows below); nurture later |
| not_interested | replied | no | stop | Polite close; **set `outbound_recycle_after`**; stays recyclable. Flag firm/definitive rejections for optional human review — a human may manually suppress, automation does not |
| not_qualified | disqualified | no | stop | Mark disqualified; excluded from future campaigns by the eligibility status filter (reversible) |
| wrong_contact | disqualified (old contact) | no | stop | Old contact excluded; named replacement created as a **referral lead only — never enrolled, never sent**. See below |
| asked_to_stop | opted_out | YES (+ opt_out_date) | stop | Confirm removal. The ONLY classifier-driven suppression |
| out_of_office | unchanged | no | **we resume it, on a date** | Do NOT advance the lead or write status=replied. Write `outbound_resume_after` from the return date in the auto-reply (else +14d); `resume_sequences.py` restarts it then. See "Who resumes an out-of-office" below |
| automated_reply | unchanged | no | RESUME | Ignore; do NOT advance the lead or write status=replied |

**Booking links route to the SENDER** (`config/meeting-routing.md`), looked up from
`outbound_sender` on the contact — written once at enrolment, so a reply months later
still resolves to whoever actually wrote to them.

**If the sender is unknowable, the link falls back to Zach's calendar.** That happens
when the lead has no HubSpot contact at all: a Smartlead-only lead, a hand-uploaded list,
or a contact deleted after enrolment. The draft would otherwise have no way for a warm
prospect to book, and **a lead who cannot book is worse than one booking with Zach**, who
took every meeting until 2026-09-14 regardless of sender.

The queue row's `review_reason` says the fallback was used, so a reviewer can substitute
the real sender's link if they know it. Without that note the draft looks identical to a
correctly-routed one.

**A NAMED sender with no row in `meeting-routing.md` is still a hard error**, not a
fallback. That means somebody added a sender to `senders.md` and forgot the routing file,
which affects every contact that sender mails, so it should be loud.

### Recycle windows — `outbound_recycle_after` (set on not_now / not_interested)

A decline is a *wait*, not a suppression. The handler writes a date to
`outbound_recycle_after`: the earliest day the contact may re-enter a campaign. The
SOFT eligibility tier skips anyone whose date is still in the future, so the field is
what actually enforces the wait.

The windows live in **`config/reply-defaults.md`**, which is the source of truth;
`scripts/reply_check.py` parses that file. They are floors, tunable there, and are
deliberately NOT restated here — this file used to carry its own copy and the handler
declared a second one, so tuning either left the other wrong.

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

### Auto-send allowlist — SETTLED 2026-09-01: empty, and enforced
**The allowlist is empty. Nothing is auto-sent.** The `[FILL IN]` markers here were
closed rather than answered: "start empty" was always the answer, and leaving them open
made a settled decision read as an unfinished one.

Three independent things hold this, so it cannot drift by accident:
1. **No send code exists.** `scripts/reply_check.py` never calls Smartlead's
   `reply-email-thread` endpoint; the only mention of it in the repo is the docstring
   saying so.
2. **`auto_send_intents: []` in `config/reply-defaults.md` is ASSERTED at startup**, not
   merely read. A non-empty list makes the script refuse to run and name this gate, so
   turning auto-send on is a deliberate act with review attached, never a config edit
   nobody noticed.
3. Golden rule 1 in `CLAUDE.md`.

**Gap CLOSED 2026-09-02: `scripts/send_replies.py`.** `Approve` and `Edit & send` now
do something. The job reads those rows, sends the `draft_response` **as edited in the
Sheet**, and stamps `sent_at` so a row cannot send twice.

```bash
python scripts/send_replies.py            # DRY RUN: shows what would send
python scripts/send_replies.py --apply    # SENDS
python scripts/send_replies.py --row 7 --apply
```

**Scheduled since 2026-09-09: you no longer have to run it.** `send_replies` is the first
job in the `morning` heartbeat slot, capped at 25 sends per run. Marking `Approve` is now
sufficient; the reply goes out at the next weekday morning run.

This was added after the failure it prevents actually happened. On the first live test the
reviewer marked `Approve`, correctly expected the reply to send, and nothing did — because
until then a human also had to remember to run this script. A queue whose approval control
does nothing on its own will strand replies, and the person marking the row is the last
one who would think to check.

**This does not weaken the auto-send allowlist above, and the distinction is the whole
point.** Sending here requires a human to have read that specific text and marked the
row. An entry in `auto_send_intents` would send with no human at all; that list stays
empty and asserted. A human approving one drafted reply is a different act from
authorising a category.

It re-checks suppression **at send time**, because a reply queued Monday and approved
Thursday may have opted out in between and the row cannot know that. And it claims the
row *before* sending, so a crash leaves `sending …` and blocks a retry rather than
risking a duplicate reply from a supposed person.

**A removal confirmation is exempt, added 2026-09-14.** An `asked_to_stop` reply
suppresses the contact, and the suppression check then refused to send the one line
telling them so — **the suppression that reply caused blocked the answer to that same
reply.** Observed live on a real prospect who replied "blocked": approved in the sheet,
refused at send, leaving him having said stop into silence with no idea it registered.
Sending "you're removed from our list" is both the humane answer and the one that stops
him asking again.

The exemption is narrow on purpose:
- **Only `asked_to_stop`.** No other intent may mail a suppressed contact.
- **Never when `hs_email_optout` is set.** That is HubSpot's global opt-out, written only
  by a human honouring an all-email request. The engine never writes it, so its presence
  is a person's explicit decision and outranks this courtesy.
- **Never when the status is `bounced`** — nothing is deliverable there anyway.
- **One confirmation only**, which dedup already guarantees: one queue row per Smartlead
  message id, so a second reply is the only way to get a second row.

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

## Response guidance by category (filled 2026-09-02; refine with real examples)

Enforced in the `draft_response` instructions inside `scripts/reply_check.py`.

**These were written here on 2026-09-02 and were NOT in the prompt until 2026-09-09.** The
doc and the prompt had diverged, and the result was that **5 of 7 intents produced an empty
draft** — a queued row with nothing to edit, which is most of what the queue exists to
save. Found by the deliberate reply test, not by reading the code. If this guidance changes,
change the prompt in the same commit.

- **Interested** → warm, one line, **plus the meeting owner's booking link as a plain
  URL** from `config/meeting-routing.md`. Do not offer to find a time by hand: give them
  the link. The persona stays the correspondent; the meeting lands on the owner's calendar.
- **Question** → answer only what can be answered without inventing anything, then the
  booking link. **Deferring to the call is a complete answer**, not a failure.
- **Objection** → acknowledge it, do not argue, offer the call. Never counter with a
  claim we cannot support.
- **Not interested** → short, gracious, no re-pitch, no link. `outbound_recycle_after`
  does the follow-up work, not the copy.
- **Not now** → acknowledge the timing, confirm you will come back, and capture the date
  they named. No link and no pitch.
- **Stop** → confirm removal, suppress, no further contact, no link.

### THE HARD RULE OF DRAFTS: never invent a fact about Posh

Discovered 2026-09-02 while wiring the booking link. Asked "what's the payout timing
like?", the drafter produced **"We process payouts within 2 business days of event
close."** Nothing approves that. It was invented, and it was fluent.

**Why this is more dangerous than the same error in cold copy.** Generated copy is
machine-checked against an approved claims list and would FAIL. **Drafts are not checked
at all** — they go straight to a human, and a confident specific is exactly what a
reviewer skims past and sends. The engine would be putting a fabricated product fact in
front of a prospect, with a person's name on it.

So the drafter is now told: no day counts, percentages, fees, rates, limits or named
integrations unless the **prospect's own message** said it first, and route anything
specific to the call. Verified: timing, fee and integration questions all now defer and
share the link instead of inventing an answer.

**If drafts ever start being sent without a human reading them, this rule needs machine
enforcement**, not prompt discipline.

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
- **The message-history shape, CONFIRMED against a real reply 2026-09-01.** The docs
  were wrong or incomplete on three of four points:
  | What the docs said | What the API actually sends |
  |---|---|
  | `direction`: `"inbound"` / `"outbound"` | **`type`: `SENT` / `REPLY`** |
  | body field undocumented | **`email_body`** |
  | `id` | **`message_id`** (an RFC id, `<...@mail.gmail.com>`) |
  | `sent_at` / `received_at` | **`time`** |

  Both direction spellings are handled and an unrecognised one is a HARD ERROR, because
  a wrong guess feeds OUR OWN email to the classifier as though the prospect wrote it.
- **Dedupe on `message_id`, never `stats_id`.** They look interchangeable and are not:
  in the verified thread **both messages carried the SAME `stats_id`** (it identifies the
  send, not the message), so keying on it would treat a reply as already-processed the
  moment the outbound email was recorded.
- **Inbound bodies are quote-stripped before they are classified or queued.** A reply
  carries the whole thread beneath it, including our own copy. Unstripped, that reaches
  the classifier as though the prospect wrote it and lands in the review Sheet as the
  "reply".

### Two classifier boundaries worth knowing

- **`interested` and `question` are operationally identical** in the action map: same
  `outbound_status`, no recycle date, sequence stopped, queued for a human. The
  classifier is not held to the distinction on money-adjacent product questions ("what's
  the payout timing like?"), because forcing it flipped an actual pricing ask to
  `not_now`, which parks a warm lead for 90 days. The cheap error is not worth the
  expensive one.
- **`objection` vs `not_now` on a contract lock — SETTLED 2026-09-01, and it reversed.**
  It now classifies as **`not_now` with the contract end date captured** in
  `outbound_recycle_after`. The SDR copy spec is explicit: email 1 asks "are you locked
  in?", so "we're locked in through June" is **the successful answer it was designed to
  get**, not a rejection. Treating it as an objection was reading a win as a loss.

  This supersedes the earlier reading, where the precedence table's "a constraint you
  could answer outranks timing" made it an `objection` with no recycle date at all. That
  left the one decline that tells us exactly when to return as the only decline with no
  scheduled return — which is why it had been logged as a v2 gap. **The v2 item is closed
  by this, not by building it.**

  The test between the two is now clean: **a contract or a season they must wait out is
  `not_now`; a doubt about us that an answer would resolve is `objection`.**
- **`objection` vs `not_interested` on satisfied incumbency — FIXED 2026-09-09, found in
  the first live accuracy test.** *"We're happy on tixr, but thanks for reaching out."*
  classified as **`not_interested`**, so the drafted reply was a polite goodbye. It should
  be **`objection`**.

  **Naming an incumbent is the most workable objection this engine will receive** — it is
  a comparison a reply can engage — and it was being routed to a sign-off. Two costs, not
  one: the draft closes a live conversation, and the two intents recycle on different
  clocks, so the come-back date was wrong too.

  The model was classifying on **tone**. "Happy on X, thanks anyway" is friendly and
  sounds final, while the content is a switching conversation; the word *but* carried the
  whole signal and was dropped. Note that this sits directly beneath the contract-lock
  rule above and is a different case: **a contract you must wait out is `not_now`; a
  preference you could change is `objection`.**

  Fixed with an exemplar and its contrast pair in the classifier prompt, not a longer
  definition — the repeated lesson in this repo. The pair is the whole test:
  *"We're happy on Tixr, but…"* → `objection` (gives a reason) vs *"Not interested,
  thanks."* → `not_interested` (gives none). **`not_interested` is the intent for a
  decline with nothing in it to answer.**

- **An `objection` draft proposes no meeting and carries no link — CHANGED 2026-09-09.**
  The guidance used to read *"acknowledge the concern, do NOT argue it, offer the call.
  No link, and never counter with a claim."* Three of those four clauses were right.

  **The CTA never made sense.** If the draft may not argue the objection and may not
  counter with a claim, the proposed call has no stated purpose: it asks someone who just
  said "we're happy with X" to book thirty minutes to discuss nothing we are allowed to
  raise. "Offer the call" and "no link" also contradicted each other outright, and the
  model resolved that by pasting the link.

  **The CTA was also generating fabrications, which is the real reason it had to go.** A
  meeting you are forbidden to justify forces you to invent a justification. Asked to
  handle *"your platform can't do reserved seating, can it?"*, the prompt drafted
  **"Reserved seating is actually something we handle well"** — a capability claim, for a
  real prospect, from a model with no product documentation in its context and no
  approved-claims check on its output. `positioning.md` says nothing about reserved
  seating. The instruction to sell is what produced the lie; removing it removes the
  pressure.

  **What an objection draft does now:** acknowledge it, leave the door open, stop. The
  come-back is `outbound_recycle_after`, not a CTA — the draft does not have to win
  anything back today, and trying is how it invents things.

  Note this does **not** cost us the legitimate call offers. A prospect who *asks* us
  something classifies as `question` or `interested`, both of which still carry the link.
  The line is clean: **a call is offered in answer to a question, never in answer to a
  no.**

### What this script deliberately does not do

- **It never sends.** No call to `reply-email-thread` exists in it. Drafts go in the
  queue. The auto-send allowlist is empty (above), and this cannot bypass it.
- **It never creates a contact.** On `wrong_contact` the named replacement is printed and
  left in the queue row for a human, per the standing decision not to create contacts.
- **It never writes `hs_email_optout`.** Only `outbound_suppressed` +
  `outbound_opt_out_date`, plus a Smartlead unsubscribe. Asserted in code.

## Who resumes an out-of-office (rewritten 2026-09-09 — **the engine does, on a date**)

**The engine schedules the restart itself and depends on Smartlead for none of it.**

    out_of_office -> read the return date out of the auto-reply
                  -> write outbound_resume_after on the contact
                  -> scripts/resume_sequences.py restarts the lead when the day arrives

`resume_ooo_default_days` (14) covers an auto-responder that names no date. A date it
*does* name always wins. Both live in `config/reply-defaults.md`.

### What this replaced, and why it was wrong

The previous rule was **"Smartlead resumes it, we do not"**, resting on a single premise:
that Smartlead has an OOO auto-pause which auto-restarts after N days. That premise does
not survive contact with the system:

- **No OOO auto-pause or auto-restart setting is exposed on the campaign object.** The
  only related field is `stop_lead_settings`, and ours is `REPLY_TO_AN_EMAIL`.
- **`REPLY_TO_AN_EMAIL` stops the lead on ANY reply** — and an auto-responder is a reply.
- Seven test replies **Smartlead itself labelled out-of-office** all finished as
  `COMPLETED`. **Not one was `PAUSED`.**
- Smartlead's OOO detection is separately unreliable: those seven were ordinary human
  replies, and it called every one of them out-of-office.

**If nothing restarts those leads, a prospect who was merely on holiday receives email 1
and is never contacted again.** That is the worst shape a bug here can take. It is silent
— the lead reads `COMPLETED`, exactly like a genuine non-replier — and it strikes the most
recoverable non-response there is. The old "residual risk" note called this a rare case
where Smartlead *misses* an OOO; the evidence says it is the ordinary path.

### Why a date rather than better detection

The auto-responder tells us itself: they nearly always say when they are back. Reading
that date needs no vendor feature and no second signal, and it **deletes the "never
resumes" failure mode** rather than narrowing it — which matters, because the classifier
is not perfect and `out_of_office` has already been observed slipping to
`automated_reply`. Behaviour that depends on getting a label exactly right will
eventually get it wrong.

`automated_reply` is unchanged and still resumes **immediately**: nobody is absent, so
there is nothing to wait for.

### The safety rules that matter

An absence is often weeks, and the date is written before it starts. `resume_sequences.py`
therefore re-reads everything at resume time and **only restarts a contact still sitting
at `in_sequence`** — the one status an out-of-office leaves behind. Anything else means
something happened while they were away. The important member of that set is `replied`:
resuming there would push sequence step 2 into a live conversation, as a persona who is
supposedly already corresponding with them.

**`close_sequences.py` will not close a contact while `outbound_resume_after` is set**,
and the morning slot runs it **before** `resume_sequences.py`. Both halves are required:
an out-of-office lead is `COMPLETED` in Smartlead and `in_sequence` in HubSpot, which is
indistinguishable from a finished non-responder, and that date is the only thing telling
them apart. Since this job clears the date, running it first would remove the very
protection the other job depends on.
