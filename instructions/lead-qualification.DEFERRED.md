# Instruction: Lead Qualification  — ⚠️ DEFERRED, NOT IN v1

**Status:** Intentionally **out of scope for v1** (per the project plan). This file
is a placeholder so the structure exists when we revisit. **Do not wire qualification
into the live campaign flow in v1.** The v1 review dataset has contact fields +
message_1..3 only — no qualification columns.

## When revisited (post-v1), this should cover:
- Qualification criteria for the ICP (a reusable, explicit rulebook).
- Bulk research/scoring of candidates using the cheap LLM where judgment is needed.
- Store `qualified = yes/no` plus the **reason** for the decision.
- Exclude unqualified prospects **before** generation.
- If qualification can't happen before outreach, mark the lead so reply-handling
  knows qualification is still pending.

## [FILL IN when revisiting]
- The concrete qualification criteria for your ICP.
- Where qualified/reason get stored (SQLite + HubSpot property).
