# Backlog

Deferred work, with the trigger that unblocks each item. Nothing here is in v1 scope
until its trigger is met.

---

## Current state

*Replace this whole section on each checkpoint — do not append a second one.*

**Last updated:** 2026-08-18 · **HEAD = `3201849`**

### Done and committed

The generation pipeline is runnable from committed code:

- **`scripts/run_generation.py`** — the orchestrator. Three-position validation is
  structural (the loop over m1/m2/m3 lives inside `process_contact` with asserts, so a
  caller cannot lose coverage). Retry-once on generation/JSON-parse failure. Contacts
  that fail after retry get a CSV row with `validation=ERROR` and `generation_error`
  populated — never silently dropped.
- **Three-branch persona default** — anchored generation / no-platform fallback /
  flag-for-review — with the **platform-fabrication guard**: when `current_competitor`
  is missing or unusable, the opener asks the generic setup question and no platform
  may be named anywhere (enforced in the prompt and by `check_no_invented_platform`).
- **Positional length targets:** m1/m2 80–110 words, m3 40–70. WARN only, never a gate.
- **Subjects 2–7 words**, lowercase, with the canonical-acronym exception (RA, NYC, DJ…).
- **CTA-family banned regex** — `worth a quick conversation/comparison/chat/call/look` —
  replacing the old literal, which missed siblings that shipped in real runs. Hard FAIL,
  deliberately not auto-repaired: rewriting a CTA is editorial.
- **Sign-off strip in `repair.py`** — removes a model-written trailing sign-off before
  assembly appends the real one.
- **Sequence-level stat-budget WARN** — flags more than one stat, or a repeated stat,
  across the three-message sequence.
- **The SDR voice anchor is installed** and injected verbatim from
  `instructions/message-generation.md` via the `VOICE-ANCHOR` markers, so the spec and
  the prompt cannot drift.

### Next task: the first full 34-contact run

Run all 34 through the **committed** `scripts/run_generation.py`, not a scratchpad
caller. **This is a diagnostic run: read it for pattern, not to ship.**

What to read, in order:

1. **The error column.** Did anyone land `status=ERROR`? Did `micromusic.denver`
   survive on retry (it has failed first-attempt JSON parsing in two separate batches)?
2. **Branch distribution across all 34.** How many anchored vs no-platform-fallback vs
   flagged, and whether `persona_basis` reads honestly on real missing-data contacts.
3. **Is Ashley's "stacks 3 ideas, runs long" a class or a one-off?** She has been the
   length outlier for four rounds. **Do not tune generation rules to bind her** until
   the 34 shows whether other contacts share the shape.
4. **Do the stat-budget check and retry fire on real data?** Both are currently proven
   only against synthetic stubs.
5. **The volume PASS/WARN/FAIL split**, and whether the gate holds on blank-GMV
   contacts and non-Party verticals it was never tuned on.

**Expect FAILs to rise versus the last 34-run.** The CTA-family regex and the
stat-budget check are new and stricter. Sort genuine problems from the gate correctly
catching what it previously missed.

### Still parked (known, not blockers for the 34)

- **Placeholder sender names** in `config/senders.md` and the **unconfirmed Smartlead
  unsubscribe token** remain deliberate send-blockers. Both clear during Smartlead
  setup, still pending finance approval.
- **Mailbox-assignment timing.** Assembly needs the sender name during generation, but
  mailbox assignment currently happens at campaign creation. Documented in
  `config/senders.md`; not implemented.

---

## Google Sheets review surface
**Trigger:** after copy testing is validated.

Set up a GCP service account and enable the Sheets API, put the key path in
`GOOGLE_SERVICE_ACCOUNT_JSON`, share the target sheet with the service-account email,
then build an "export review dataset to Google Sheet" step. The sheet is the artifact:
share its link in Slack for review, which fits the planned Slack review/approval flow.

**Until then:** generation writes to a local CSV.
