# Instruction: Message Generation

**Purpose:** Generate a personalized **3-email sequence** per prospect using the
cheap bulk LLM. This file is the rulebook. When stakeholders give feedback, update
*this file* (and `config/`) rather than hand-fixing individual emails.

Always read `config/positioning.md` and `config/personas.md` before generating.

## The sequence: 3 emails
- **Email 1 — the opener.** Lead with the prospect's likely problem (per the brief
  and their persona), then the offer. Specific to the prospect via the research note.
- **Email 2 — follow-up.** Adds a new angle or proof point. **Must read correctly
  even if Email 1 got no reply** — no "just circling back on my last note" that
  assumes they read it. Reference the topic, not the prior email.
- **Email 3 — final touch.** Short, low-friction, easy yes or a graceful close.
  Again, must stand on its own.

## Tone & structure  [FILL IN — refine with stakeholder feedback]
- Tone: `[FILL IN: e.g. direct, peer-to-peer, no hype]`
- Length: short. `[FILL IN target, e.g. under ~90 words each]`
- Structure: `[FILL IN: e.g. one-line hook → one-line relevance → one-line offer → CTA]`
- Personalization: at least one line that could only be written for this prospect.

## CTA rules  [FILL IN]
- Preferred CTA: `[FILL IN: e.g. a soft interest-check question vs. a meeting ask]`
- One clear CTA per email. No stacked asks.

## Prohibited claims — HARD RULES
Pull the authoritative list from `config/positioning.md`. Never:
- Invent customers, logos, metrics, or results.
- Promise outcomes or guarantees not sanctioned in positioning.
- Misrepresent who the sender is or why they're reaching out.
- `[FILL IN any category-specific claims you must avoid]`

## Compliance in the copy
- Each email must be compatible with a compliant footer (accurate sender identity,
  physical address, working opt-out — handled at the campaign/mailbox level, but the
  copy must not contradict it).
- Never obscure that this is outbound from your company.

## Output format
Return, per prospect: `first_name, last_name, email, job_title, company,
message_1, message_2, message_3`. (No qualification fields — qualification is
deferred in v1.) Each message should include a subject line and body.

## Efficiency
Generate with **Claude Haiku** (`BULK_LLM_MODEL` in `.env`), once per prospect or in
efficient batches. Keep the prompt lean; feed in the research note + persona guidance
rather than everything. Note this uses the Anthropic **API key**, billed separately
from the Claude subscription that runs Claude Code.

## Persona-specific angles
See `config/personas.md`. Example of the kind of rule that lives there:
> "For [persona X], lead with the operational problem, not the revenue opportunity."
