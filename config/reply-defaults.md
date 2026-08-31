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
- **`recycle_not_interested_days = 180`** always applies. No date is read from a
  `not_interested` reply: a decline is not an invitation to negotiate timing.
- **Lengthening either is safe. Shortening is not**, and not because of the code — the
  code handles it fine. Shortening means contacting people sooner after they declined,
  which is a deliverability and reputation decision, not a config tweak.
- **`objection` has no recycle window on purpose in v1**, so a contract expiry does not
  schedule its own return. That is a known gap, deferred by decision on 2026-08-31 — see
  "V2: give `objection` a recycle date of its own" in `BACKLOG.md`. Do not add a value
  for it here without reading that note; the wait behaviour needs deciding first.
