# Instruction: Message Generation

**Purpose:** Generate a personalized **3-email sequence** per prospect using the
cheap bulk LLM. This file is the rulebook. When stakeholders give feedback, update
*this file* (and `config/`) rather than hand-fixing individual emails.

Always read `config/positioning.md` and `config/personas.md` before generating.

## Using the research signals
The research note (see `instructions/research.md`) carries the persona call and the
signals behind it. Three inputs matter most.

- **`current_competitor`** is the sharpest personalization lever available. It sets the
  persona and it points at the switch angle. Use it to ask about their setup, not to
  diagnose it: "are you locked in on Eventbrite?" rather than a critique of Eventbrite.
  See **Voice anchor** above.
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
- **Tone:** a warm SDR who is genuinely excited to help, not a consultant diagnosing
  the prospect's problems. Peer-to-peer and direct, like someone who understands the
  events world. No jargon, specific over generic. See **Voice anchor** above, which is
  the authoritative register.
- **Length:** messages 1 and 2 are roughly **80 to 110 words**, calibrated to the
  voice anchor, which is itself about 100 words: the warmth and the package pitch need
  the room. Message 3 is a breakup and is shorter, roughly **40 to 70 words**. These
  are **targets, not caps**. The validator reports drift as a WARN and never fails an
  email on length, because a good email slightly outside is better than a gutted one
  exactly on target. Stay skimmable on a phone.
- **Subject lines:** conversational, and avoid spam-trigger words and punctuation
  (free, guarantee, !!!, $$$). Word count and casing are in **Hard constraints** below.
- **Sign-off:** appended by code, not written here. End the body at the CTA.
  `scripts/assemble.py` attaches the sender's first name and `Posh`, looked up from
  the sending mailbox in `config/senders.md`. See "Compliance in the copy" below.
- **Personalization:** at least one line that could only be written for this prospect.
- **No dashes.** See **Hard constraints** below.

## Voice anchor

The block between the markers is **extracted verbatim and injected into every
generation prompt**, next to the output contract, by `scripts/repair.py`
(`load_voice_anchor`). Edit the voice here and nowhere else.

<!-- VOICE-ANCHOR:BEGIN -->
### The register to match

This is a real SDR email. Match its **register**: warm, direct, genuinely excited to
help. Not a consultant diagnosing the prospect's problems.

> Hey [first name]'s team,
>
> Hope this finds you well! Reaching out to see if you're locked in on your current
> ticketing setup with [competitor]? Any opportunity to compare what Posh could put
> together in a custom proposal?
>
> We've been putting together very competitive offers this year, all focused on
> helping organizers drive better reach, earlier conversions, and generating extra
> revenue with dedicated account support, financial incentives, marketing push and
> more — with a huge and active community in New York.
>
> Let me know if you're open to connecting, would love to hear more about your plans
> this year and see what we can bring to the table!
>
> Thanks,

### This is a tone target, not a template

- **The bracketed specifics are illustrative.** Never hardcode a literal from the
  example: no "TicketWeb", no "Lucinda", no platform or person name carried over.
  Use the actual prospect's details from the research note.
- **Do not reference New York, or any city.** Prospecting is national. Match the
  warmth and the benefit-bundling of that closing clause, but never claim a local
  community anywhere. Where the anchor leans on a local community, use Posh's
  national reach and the marketplace instead: organic demand the organizer did not
  have to source.
- **Do not reuse the greeting.** "Hope this finds you well" and "...'s team" are
  illustrative, not required. Vary the opening line across prospects. Thirty emails
  opening identically reads more templated than any single phrase ever could.
- **The anchor contains an em dash. Do not reproduce it.** Hard constraint 1 still
  governs everything you write. The anchor is quoted as written for register only.

### Tone rules

- **Open warm, then ask about their current setup.** "Are you locked in on
  [competitor]?" Do **not** open with a diagnosis of what is wrong with their tool.
  Never open with "Managing events on [platform] works, but...".
- **The CTA is a concrete offer**, not a vague ask. "Compare what Posh could put
  together in a custom proposal." "A tailored comparison, want me to?" Never "worth a
  quick conversation."
- **Sell the bundled package with enthusiasm:** dedicated account support, financial
  incentives, marketing push. That bundle is the pitch.
- **At most one stat per 3-email sequence, not one per email.** Lead with the package
  and the offer, not a number. A stat in every opener reads corporate.
- **One idea per email, developed fully. This is the main lever on length.** Email 1
  carries the warm question plus **one** facet of the package, not the whole bundle.
  The other facets (financial incentives, marketing push, dedicated support) belong in
  emails 2 and 3. If an opener is running long, move a facet later in the sequence
  rather than compressing the voice. Concrete nouns over abstract benefit language.
  Short sentences. No rule-of-three cadence. Do not open message 2 with "One thing
  that stands out..."

### When the current platform is unknown

If the research note has no usable `current_competitor`, **never guess one.** Do not
infer a platform from the vertical, the company name, the email domain, or anything
else. A wrong platform named confidently is the single most expensive mistake in a
cold email: it proves the sender did not actually look. Ask the generic question
instead, and name no platform anywhere in the sequence.

Use this pattern. Same voice rules, same greeting-variation caveat: do not stamp
"Hope this finds you well" or "...'s team" on every email in the batch.

> Hey [first name]'s team,
>
> Hope this finds you well! Reaching out to see if you're locked in on your current
> ticketing setup? Any opportunity to compare what Posh could put together in a
> custom proposal?
>
> We've been putting together very competitive offers this year, all focused on
> helping organizers drive better reach, earlier conversions, and generating extra
> revenue with dedicated account support, financial incentives, marketing push and
> more.
>
> Let me know if you're open to connecting, would love to hear more about your plans
> this year and see what we can bring to the table!
>
> Thanks,

Note this is the same email as the main anchor with the platform reference and the
local-community clause removed. Everything else about the register is unchanged.

### This, not that

**NOT** (cold diagnosis, then a vague ask):
> Managing events on Resident Advisor works, but it's built for discovery, not for
> running the show... Worth a quick conversation about how it could simplify your
> next event?

**THIS:** the warm question plus custom-proposal pattern from the anchor above.
<!-- VOICE-ANCHOR:END -->

## Hard constraints

These three rules are checked mechanically, and two of them are also repaired
automatically before review. They live here as the single source of truth: the block
between the markers is **extracted verbatim and injected into every generation
prompt**, adjacent to the output contract, by `scripts/repair.py`
(`load_hard_constraints`). Do not restate them elsewhere, and do not edit them
anywhere but here. They sit next to the output contract because buried rules were
being dropped: on the first real run, rules stated only in the middle of this file
were violated in most emails.

<!-- HARD-CONSTRAINTS:BEGIN -->
1. **No dashes.** Never use em dashes or en dashes. Rephrase so the sentence does not
   need one: use a period, comma, or colon, split into two sentences, or use
   parentheses for an aside that already contains commas. Do not swap in a hyphen.
2. **The two approved stats appear only as these exact sentences:**
   - "The average event sells 13% of its tickets through the Posh marketplace."
   - "Posh events convert 40% better than other platforms."
   No hedging ("on average", "roughly", "about", "up to"), no rewording, no
   substituting a different noun for "the Posh marketplace".
3. **Subject lines are 2 to 7 words, lowercase.** Canonical acronyms and initialisms
   keep their standard casing: RA, NYC, DJ, RSVP, VIP, EDM, LA, SF, DM. Every other
   word is lowercase, including the first. (The authoritative list the validator
   checks is `CANONICAL_ACRONYMS` in `scripts/validate.py`.)
<!-- HARD-CONSTRAINTS:END -->

Rules 1 and 2 are additionally repaired in code by `scripts/repair.py` before
validation, because punctuation and exact-claim wording are mechanical. Rule 3 is not
auto-repaired: truncating a subject to fit a word count would mangle its meaning, so
it stays caught rather than prevented.

### Structure of the 3-email sequence
- **Email 1, the opener.**
  1. A warm opening line, varied across prospects, then a question about their
     current setup. Not a diagnosis of it.
  2. Persona context: **Premium** is manual work plus brand mismatch; **Pro** is
     scale, and they are probably already comparing platforms.
  3. **One** facet of the package, not the whole bundle. Pick the single facet that
     fits this persona and develop it properly.
  4. The concrete-offer CTA.
- **Email 2, the follow-up** (~3 to 4 days later). Its job is to **develop one specific
  angle that Email 1 did not cover**, with enough substance to stand on its own.
  1. **Pick the angle.** Exactly one of: a **proof point** (an approved case study from
     `config/positioning.md`, cited only where it genuinely fits this prospect), a
     **concrete capability** (something the platform actually does, described in
     specifics), or **the part of the package Email 1 left on the table**. If Email 1 led
     on marketplace reach, this one develops dedicated account support and financial
     incentives. The sequence-level rule of at most one stat across all three emails
     still governs, so a proof point here is usually the story, not a number.
  2. **Develop it properly.** What it is, and what it changes for an organizer in their
     vertical at their scale. Concrete nouns over benefit language. The substance is the
     whole point of this email: naming an angle and moving straight to the ask is not
     doing this email's job.
  3. **It must read correctly if Email 1 got no reply**, which is the normal case. No
     "just circling back", no "following up on my last note", no "as I mentioned". Do
     not reference the earlier email at all. Reference the topic and open on the angle
     itself, as if this were the first time you raised it.
  4. **Close on a concrete-offer CTA, in the anchor's register.** Offer to *do*
     something: "happy to put together a tailored comparison, want me to?", "any
     opportunity to compare what we could put together for your next one?". This email
     defaults to the vague hedge if left to itself, and the whole "worth a quick
     chat/look/conversation" family is a hard FAIL in `config/banned-phrases.md`. The
     fix is not to soften that ask, it is to make a real offer instead.
     **Vary the ask from Email 1's.** If Email 1 offered a custom proposal, offer the
     tailored comparison here, or offer to walk them through the specific angle this
     email developed. The same ask three times reads automated.

  **Its length should come from having something to say.** If this email is running
  short, the angle was too thin: choose a more specific one, or develop it further with
  real detail. Never pad it to fill space.
- **Email 3, the close** (~4 to 5 days later). Graceful, a closing-the-loop message
  carrying the **remaining facet** of the package plus one easy concrete offer. Must
  also stand on its own.

### Sequence rules
- **At most one stat across all three emails.** Not one per email.
- **Rotate the angles.** No value prop repeats across all three emails.
- **One CTA per email.**
- **Stay inside the approved claims** in `config/positioning.md`.

## CTA rules
- **Goal: booked meetings.** Every sequence drives toward a conversation.
- **Default CTA:** a concrete offer that invites a reply, e.g. "Any opportunity to
  compare what Posh could put together in a custom proposal?" or "Happy to put
  together a tailored comparison, want me to?" Never a vague "worth a quick
  conversation." Persona-specific wording lives in `config/personas.md`.
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
- **Promise a specific or quantified commercial term.** See "Commercial terms" in
  `config/positioning.md`, which is authoritative. **The existence of a tailored offer
  is sayable; its contents are not.** You may say Posh can put together a competitive
  or custom offer, mention **financial incentives** vaguely and bundled with the rest
  of the package the way the voice anchor does, and describe **dedicated account
  support**, which is a real capability. You may never name a term: no lower or reduced
  fees, rates, or commission, no credit of any kind, no free or discounted month, no
  percentage or dollar figure, and no time-boxed offer ("this quarter", "your first
  month"). Hedging does not rescue it. Nobody has priced this prospect, so a term in a
  cold email is one someone later has to honor or walk back.
  - **NOT this:** "Lower fees on a subset of your events, or a flat credit toward your
    first month on Posh, depending on your volume."
  - **THIS:** "...generating extra revenue with dedicated account support, financial
    incentives, marketing push and more." Same promise of value, nothing to honor.
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
