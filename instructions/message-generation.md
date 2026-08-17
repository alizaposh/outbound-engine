# Instruction: Message Generation

**Purpose:** Generate a personalized **3-email sequence** per prospect using the
cheap bulk LLM. This file is the rulebook. When stakeholders give feedback, update
*this file* (and `config/`) rather than hand-fixing individual emails.

Always read `config/positioning.md` and `config/personas.md` before generating.

## Using the research signals
The research note (see `instructions/research.md`) carries the persona call and the
signals behind it. Three inputs matter most.

- **`current_competitor`** is the sharpest personalization lever available. It sets the
  persona and it points at the switch angle: what their current tool makes hard, and
  what changes on Posh. Lead Email 1 with that problem where the signal is credible.
- **`vertical`** sets the vocabulary. `Party` and `Live Performance` can use nightlife
  and show-night language (door, guest list, promo push). `Festival` speaks to multi-day
  scale and production. `Other Social Communities` is community, civic, and recurring
  gatherings, where nightlife framing lands badly and should be dropped. It also narrows
  which case study fits, per `config/positioning.md`. It never changes the persona.
- **`jobtitle`** decides whose problem the email speaks to. Write to what that person
  actually owns (an owner/founder hears growth and revenue, an ops lead hears manual
  work, a marketing lead hears conversion and reach). Never open by reciting their
  title back at them.
- **`estimated_gmv_usd`** decides the persona track upstream and nothing else. It should
  not even appear in the research note. See the hard rule below.

**Never assert a scraped signal as fact.** `current_competitor` is an estimate, so
being wrong in writing is expensive: it reads as a mass-mailed guess and forfeits the
credibility the personalization was meant to buy. Write so a wrong guess still lands.
Prefer framings the prospect can correct ("if you're still running ticketing through
Eventbrite...") or that name the problem instead of the tool ("when RSVPs and payouts
live in different places..."). If the research note marks the signal low-confidence,
drop the competitor reference and personalize on something you do know.

## Tone & structure
- **Tone:** peer-to-peer and direct, like someone who understands the events world,
  not a marketer. Low hype, no jargon, confident rather than salesy. Specific over
  generic.
- **Length:** Email 1 is ~50 to 90 words. Follow-ups are shorter, ~40 to 70. All three
  should be skimmable on a phone in seconds.
- **Subject lines:** 2 to 5 words, lowercase and conversational. Avoid spam-trigger
  words and punctuation (free, guarantee, !!!, $$$).
- **Sign-off:** appended by code, not written here. End the body at the CTA.
  `scripts/assemble.py` attaches the sender's first name and `Posh`, looked up from
  the sending mailbox in `config/senders.md`. See "Compliance in the copy" below.
- **Personalization:** at least one line that could only be written for this prospect.
- **No dashes.** Never use em dashes (`—`) or en dashes (`–`) in generated copy.
  Rephrase so the sentence doesn't need one: use a period, comma, or colon, or split
  into two sentences. Do not just swap in a hyphen.

### Structure of the 3-email sequence
- **Email 1, the opener.**
  1. A hook line specific to this prospect, drawn from the research note.
  2. Connect it to their persona's pain: **Premium** is manual work plus brand
     mismatch; **Pro** is scale, and they are probably already comparing platforms.
  3. Exactly one value prop, chosen to fit the persona.
  4. The soft interest-check CTA.
- **Email 2, the follow-up** (~3 to 4 days later). Lead with a **different angle**
  than Email 1, add one new value point, and close with a soft CTA. **Must read
  correctly even if Email 1 got no reply:** no "just circling back on my last note"
  that assumes they read it. Reference the topic, not the prior email.
- **Email 3, the close** (~4 to 5 days later). Short and graceful, a closing-the-loop
  breakup, with one easy CTA. Must also stand on its own.

### Sequence rules
- **Rotate the angles.** No value prop repeats across all three emails.
- **One CTA per email.**
- **Stay inside the approved claims** in `config/positioning.md`.

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
- **Write `estimated_gmv_usd`, or any figure derived from it, into an email.** Never
  state, paraphrase, imply, or bracket a prospect's ticketing volume, revenue, or GMV.
  It is a scraped estimate used only to route Premium vs Pro. Telling an organizer what
  you think they gross is presumptuous when right and damaging when wrong, and it is
  never approved copy. The same applies to any other internal scale estimate.
- **State a scraped signal as established fact.** See "Using the research signals."
- `[FILL IN any category-specific claims you must avoid]`

## Compliance in the copy

**Do not write a sign-off or a footer. Code appends both.** `scripts/assemble.py`
attaches the sender sign-off and the compliance footer to every email after
generation, reading the sender name from `config/senders.md` and the legal name and
address from `config/positioning.md`. Generate the message body only, ending at the
CTA.

This is deliberate. On the first real generation run, six of nine emails silently
shipped with no footer at all, and the sign-off named the recipient rather than the
sender. Compliance-critical elements are the ones a missed instruction drops without
any visible symptom, so they are no longer the model's job. `scripts/validate.py`
flags any generated body that contains footer or sign-off content, because that means
this instruction has drifted.

What the copy itself must still do:
- **Never hand-write an unsubscribe link.** Do not invent a URL, a `mailto:`, or
  "reply STOP to unsubscribe" anywhere in the body. A fabricated link is worse than
  none. It looks compliant while doing nothing, and it can't feed the suppression
  list. The real opt-out is Smartlead's unsubscribe token, emitted by the assembly
  step, which is what keeps one-click opt-outs wired into Smartlead's own tracking,
  which the suppression list and `instructions/reply-handling.md` depend on.
  - The token lives in one place, `UNSUBSCRIBE_TOKEN` in `scripts/assemble.py`. It is
    currently the placeholder `{{UNSUBSCRIBE_TOKEN}}`, pending
    `[FILL IN: confirm the exact merge tag in the Smartlead account; do not guess the
    string]`. While it is a placeholder, campaigns are **not send-ready**.
- The body must not contradict the footer, and must never suggest the opt-out is
  unavailable, conditional, or slower than one click.
- Never obscure that this is outbound from Posh.

## Output format
Return, per prospect: `first_name, last_name, email, job_title, company,
message_1, message_2, message_3`. (No qualification fields, since qualification
is deferred in v1.) Each message should include a subject line and body.

## Efficiency
Generate with **Claude Haiku on Amazon Bedrock** (`BULK_LLM_MODEL` in `.env`), once
per prospect or in efficient batches. Keep the prompt lean: feed in the research note
plus persona guidance rather than everything.

This runs on Bedrock, not the first-party Anthropic API. Auth is
`AWS_BEARER_TOKEN_BEDROCK` sent as `Authorization: Bearer`, and **billing is AWS at
Bedrock's rates**, separate from the Claude subscription that runs Claude Code. See
`CLAUDE.md` (Credentials) for the endpoint and model-ID shape.

**Cache the rulebook prefix.** Every prospect in a batch sees the same large fixed
prompt (`config/positioning.md`, `config/personas.md`, and this file) followed by a
small per-prospect note. Ordering the prompt that way, stable content first, lets the
fixed portion be cached once and read on every subsequent prospect instead of being
re-sent at full price. Any per-prospect value placed above the cached portion defeats
this, so keep the note last.

## Persona-specific angles
See `config/personas.md`. Example of the kind of rule that lives there:
> "For [persona X], lead with the operational problem, not the revenue opportunity."
