# Instruction: Message Generation

**Purpose:** Generate a personalized **3-email sequence** per prospect using the
cheap bulk LLM. This file is the rulebook. When stakeholders give feedback, update
*this file* (and `config/`) rather than hand-fixing individual emails.

Always read `config/positioning.md` and `config/personas.md` before generating.

## The sequence: 3 emails
- **Email 1, the opener.** Lead with the prospect's likely problem (per the brief
  and their persona), then the offer. Specific to the prospect via the research note.
- **Email 2, the follow-up.** Adds a new angle or proof point. **Must read
  correctly even if Email 1 got no reply.** No "just circling back on my last
  note" that assumes they read it. Reference the topic, not the prior email.
- **Email 3, the final touch.** Short, low-friction, easy yes or a graceful close.
  Again, must stand on its own.

## Tone & structure  [FILL IN: refine with stakeholder feedback]
- Tone: `[FILL IN: e.g. direct, peer-to-peer, no hype]`
- Length: short. `[FILL IN target, e.g. under ~90 words each]`
- Structure: `[FILL IN: e.g. one-line hook → one-line relevance → one-line offer → CTA]`
- Personalization: at least one line that could only be written for this prospect.
- **No dashes.** Never use em dashes (`—`) or en dashes (`–`) in generated copy.
  Rephrase so the sentence doesn't need one: use a period, comma, or colon, or split
  into two sentences. Do not just swap in a hyphen.

## CTA rules
- **Goal: booked meetings.** Every sequence drives toward a conversation.
- **Default CTA:** a soft, low-friction interest-check that invites a reply, e.g.
  "Open to exploring how Posh can help sell out your next event? Let me know if you'd
  like to connect." Persona-specific wording lives in `config/personas.md`.
- **One clear CTA per email. No stacked asks.**
- **Keep the opener link-light.** A booking link in a cold first email can hurt
  deliverability and reads as presumptuous. Introduce a scheduling link or a specific
  time only after interest is shown, or in a later step.
- **Frame outcomes as exploration, not guarantees** (see positioning prohibited
  claims): "help sell out your next event?" as a question is fine; "we'll sell out
  your event" is not.

## Prohibited claims: HARD RULES
Pull the authoritative list from `config/positioning.md`. Never:
- Invent customers, logos, metrics, or results.
- Promise outcomes or guarantees not sanctioned in positioning.
- Misrepresent who the sender is or why they're reaching out.
- `[FILL IN any category-specific claims you must avoid]`

## Compliance in the copy
- **Every email ships with a footer.** Not just the first in a sequence. Each of
  the three steps. The footer carries accurate sender identity, the physical mailing
  address, and a working opt-out. Sender name and address come from
  `config/positioning.md` (Sender identity & compliance basics); use those values
  verbatim, don't retype them from memory.
- **Never hand-write an unsubscribe link.** Do not invent a URL, a `mailto:`, or
  "reply STOP to unsubscribe" as a substitute. A fabricated link is worse than
  none. It looks compliant while doing nothing, and it can't feed the suppression
  list.
- **Leave the opt-out to Smartlead's unsubscribe token.** Emit the token itself and
  let Smartlead render the real per-recipient link at send time. This is what keeps
  one-click opt-outs wired into Smartlead's own unsubscribe tracking, which is what
  the suppression list and `instructions/reply-handling.md` depend on.
  - Token to emit: `[FILL IN: confirm the exact merge tag in the Smartlead account;
    do not guess the string]`. Until it's confirmed, emit a clearly-marked
    `{{UNSUBSCRIBE_TOKEN}}` placeholder and flag the campaign as not send-ready
    rather than substituting anything that looks like a live link.
  - If a generated draft reaches review with a literal URL in the opt-out slot, treat
    it as a defect and regenerate. Do not patch it by hand.
- The body copy must not contradict the footer, and must never suggest the opt-out is
  unavailable, conditional, or slower than one click.
- Never obscure that this is outbound from Posh.

## Output format
Return, per prospect: `first_name, last_name, email, job_title, company,
message_1, message_2, message_3`. (No qualification fields, since qualification
is deferred in v1.) Each message should include a subject line and body.

## Efficiency
Generate with **Claude Haiku** (`BULK_LLM_MODEL` in `.env`), once per prospect or in
efficient batches. Keep the prompt lean; feed in the research note + persona guidance
rather than everything. Note this uses the Anthropic **API key**, billed separately
from the Claude subscription that runs Claude Code.

## Persona-specific angles
See `config/personas.md`. Example of the kind of rule that lives there:
> "For [persona X], lead with the operational problem, not the revenue opportunity."
