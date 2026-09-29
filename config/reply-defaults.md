# Config: Reply Handling Defaults

Tunable values for the reply loop. **This file is the source of truth.**
`scripts/reply_check.py` parses the block below; it does not restate these numbers.
Change a value here and the script changes with it — no code edit needed.

Repo convention, same as `config/pre-send-defaults.md`: tunable values live in `config/`,
and `instructions/` describes the logic that consumes them. Created 2026-08-31, when
building the reply handler produced a second copy of the recycle windows and made the
drift risk real rather than theoretical.

The logic these feed is in `instructions/reply-handling.md`. Read it before tuning
anything here — particularly the four recycle rules, which the numbers alone do not
convey.

## Canonical values

```
# Recycle windows: the earliest day a declined contact may re-enter a campaign.
# Both are FLOORS, not fixed waits. A date the prospect actually names in a not_now
# reply wins, INCLUDING one earlier than the floor -- they asked for that timing.
# Computed from the REPLY date, never the processing date. An existing later date is
# never shortened. See recycle_date() and the four rules in reply-handling.md.
recycle_not_now_days: 90
recycle_not_interested_days: 180

# How far AHEAD of a named contract end the re-engagement task is due. A prospect who
# says "we're with DICE until next June" should be spoken to before the renewal is
# drafted, not on the day it completes. Applies ONLY to a date the prospect actually
# named -- see the tuning note below, this distinction is the whole design.
recycle_task_lead_days: 90

# Cooldown for an OBJECTION that names an incumbent but gives no date ("we have a
# contract with RA"). Without it such a contact is only held by the 30-day
# status=replied window and becomes re-mailable a month after telling us they are
# committed elsewhere. Applies only when a platform was actually named -- see the
# tuning note. A date they DO name always wins over this.
recycle_objection_days: 180

# How long to wait before restarting a sequence halted by an out-of-office
# auto-responder that named NO return date. A date the auto-responder DOES name always
# wins over this. Applies to out_of_office only: automated_reply resumes immediately,
# because nobody is absent. See resume_date() and scripts/resume_sequences.py.
resume_ooo_default_days: 14

# Which classified intents may be auto-sent WITHOUT a human reading the reply first.
# DELIBERATELY EMPTY, and the script asserts it is empty at startup rather than merely
# reading it. Emptying is not the same as unimplemented: reply_check.py contains no
# send path at all, so adding an intent here does NOT enable auto-send -- it makes the
# script refuse to run, on purpose, so that building the send path is a deliberate
# decision with review attached and never a config edit nobody noticed.
auto_send_intents: []
```

## Tuning notes

- **`recycle_not_now_days = 90`** exists because a vague "later" needs some floor. It is
  overridden by any date the prospect names, so in practice it only applies to a
  `not_now` with no timing in it.
- **`recycle_task_lead_days = 90`** moves the TASK earlier than the recycle date, and
  **only when the prospect named a date.** The distinction matters more than the number:

  - They named one ("under contract until June 2027") -> that is a real contract end, and
    the renewal conversation happens before it. Task due June 2027 minus 90 days.
  - They named nothing ("not right now") -> the date is our own +90 day floor, a guess,
    not a contract end. Subtracting 90 from a guess would make every vague "later" a
    task due TODAY, which empties the meaning out of the queue. Task due on the date.

  Floored at tomorrow, so a contract ending inside the lead window ("we're locked in
  through next month") produces a task now rather than one dated in the past.

  **It does NOT move `outbound_recycle_after`.** The task tells a rep to reach out
  personally ahead of renewal; the recycle date still governs when the ENGINE may cold-
  email them, and mid-contract is still mid-contract. A rep who wants to re-enrol them
  in a campaign early can, by submitting them like any other list.
- **`recycle_objection_days = 180`** closes a real gap found 2026-09-28. A reply of
  "we have a contract with RA" classifies as `objection`, not `not_now` -- there is no
  timing in it -- and objections set no recycle date at all. The contact was therefore
  held only by the 30-day `status=replied` window and became eligible for a fresh cold
  email about a month after telling us they were under contract. Being re-mailed in
  that situation is worse than never following up at all.

  180 days is a compromise, and an honest guess rather than a known deadline: long
  enough to be respectful, short enough to plausibly land near a renewal. **Only when a
  platform was named** -- a bare objection ("too expensive") is a copy problem, not a
  contract, and does not earn a six-month silence.

  The task created alongside it says the date is OUR estimate, not something the
  prospect said. Same rule as the unnamed `not_now`: never present a guess as a fact
  about the account.
- **`recycle_not_interested_days = 180`** always applies. No date is read from a
  `not_interested` reply: a decline is not an invitation to negotiate timing.
- **Lengthening either is safe. Shortening is not**, and not because of the code — the
  code handles it fine. Shortening means contacting people sooner after they declined,
  which is a deliverability and reputation decision, not a config tweak.
- **`resume_ooo_default_days = 14`** is a fallback, not the normal path: most
  auto-responders state a return date and that date wins. It only covers the ones that
  say "I am away" with no "until". Two weeks is chosen to be longer than a typical
  holiday, because **the two errors are not symmetric**: resuming too early mails someone
  who is still away and looks careless, while resuming too late costs a few days on a
  lead that would otherwise have been lost entirely. Lengthen freely; shorten with care.
- **`objection` has no recycle window on purpose in v1**, so a contract expiry does not
  schedule its own return. That is a known gap, deferred by decision on 2026-08-31 — see
  "V2: give `objection` a recycle date of its own" in `BACKLOG.md`. Do not add a value
  for it here without reading that note; the wait behaviour needs deciding first.
