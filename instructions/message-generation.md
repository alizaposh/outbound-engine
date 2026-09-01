# Instruction: Message Generation

**Purpose:** Generate a personalized **3-email sequence** per prospect using the
cheap bulk LLM. This file is the rulebook. When stakeholders give feedback, update
*this file* (and `config/`) rather than hand-fixing individual emails.

Always read `config/positioning.md` and `config/personas.md` before generating.

**Generate only for leads marked ELIGIBLE** by the pre-send eligibility check
(`instructions/pre-send-eligibility-check.md`). That filter runs before this step and
decides who we are allowed to enroll at all; never generate from a list that has not
been through it.

> ## ⚠️ PRECEDENCE: the sales-team rules below win
>
> **"Sales-team messaging rules (2026-08-25)" is authoritative.** It came from the AE
> team's own scoring of real drafts, and each rule cites the reviewer it came from.
> Where it conflicts with anything later in this file, in `config/personas.md`, or in
> `config/positioning.md`, **it wins** — the older text was written before that
> feedback existed.
>
> **One conflict is still live** (re-audited 2026-09-01), and it is between two sections
> of THIS file rather than with the code: see "Conflicts" at the end of that section.
> The other three are resolved and the code now matches the rules.

---

# Sales-team messaging rules (2026-08-25)

*Source: the sales team's scoring of real drafts. Every rule traces back to named AE
feedback or a confirmed decision, noted in italics. Read the reason before changing a
rule.*

## 1. Sequence structure

- **Three emails, threaded.** Emails 2 and 3 are replies on the same thread as email 1.
- **Only email 1 has a subject line.** Emails 2 and 3 inherit the thread subject (they send as "Re: ...") and must **not** invent a new subject. _Decision: sends are threaded in Smartlead, so a fresh subject would break the thread._
- **Open follow-ups as continuations, not fresh intros.** Email 2 starts like a bump ("Quick follow-up,"), not "Hi [name], I'm ...".
- **No re-greeting on email 2.** The earlier message sits right below it. (Email 3 may use a short "Hey [name]," because it's brief enough to read as a friendly nudge.)

## 2. One idea per email

- **Each email carries exactly one feature, outcome, or angle. Never a feature dump.** _Feedback: Vince (4/5) liked that each email focused on one thing; Dogwood, Olivia, Lawrence, 90stildawn all penalized feature-dump emails, and email 2 was the repeat offender._
- If you're tempted to list three benefits, pick the strongest one and cut the rest.

## 3. Length

- **Short throughout: roughly half the length of a bloated draft.** _Feedback: "too long" appears in the majority of scored rows._
- **Email 3 is the shortest.** A few lines at most. _Feedback: reviewers explicitly want the closer kept "super short."_

## 4. Email-by-email spec

### Email 1
**Write this one fresh for each lead. Do not follow a fixed template.** _Decision: a fixed opener formula made every email 1 read identically with only the competitor name swapped, which is the clearest "machine-generated" tell at volume._

- **Before writing, check for a warm open (§9).** If the contact has a genuine prior interaction on the HubSpot timeline, open with a callback per §9. Otherwise, write a cold open as below.
- **Vary the opening across leads.** Do not default every email to "Are you still running [competitor], or open to seeing what else is out there?" Open differently depending on what's actually notable about the lead: their vertical, the kind of events they run, their role, their competitor. Two leads in a row should not start the same way.
- Must still include: the sender's self-introduction **near the top** (the exact `sender.intro_line` from the research note, never a name you picked; see §7), one problem or angle tied to the lead, and a soft reply-based CTA (a plain question). It used to sit at the bottom of email 1, which read like a signature block rather than an introduction.
- **The hard guardrails still apply. Freedom is in the wording, not the rules.** Short (§3), one idea only (§2), human voice with no AI tells (§5), and only real claims (§6). "Write freely" does not mean longer, does not mean feature-dump, and does not mean fluff. Those are exactly what got down-scored.

### Email 2
**Vary the shape lead to lead. Don't run the same structure every time.** _Decision: a fixed single-feature "Quick follow-up," template makes every email 2 read alike, the same problem email 1 had._

- **Don't default every email to "Quick follow-up."** Open differently depending on the lead and the angle.
- **Pick one of a few approved shapes** (rotate; none should become the default):
  - **Single feature/outcome:** one real capability told as a short narrative (e.g. text blasts to your own crowd, guest-list + payouts in one place).
  - **"Here's the simple version" outcome list:** best for colder/unsure leads. A one-line framing, then a short scannable list of *outcomes* (not features), then a soft CTA. Outcomes to draw from: sell more tickets, reach more of the right people, own their attendee community, make check-in/payouts/promo/setup easier, build a more repeatable event business. Tailor the framing line to the lead and trim the list to fit them. Intentional exception to "one idea per email" (§2) because it's a summary, not a feature dump, so keep it short and don't pile on.
  - **One approved proof point:** see §6. At most one, only when it fits the angle.
- Continuation opener, no greeting-then-restart; one core message; soft CTA.

### Email 3
- A plain reply-based close: name that it's the last touch, ask one low-pressure question, exit graciously. No feature, no recap. _Decision: reworded from an earlier "one line only" rule. The ban is on bloat, not on line count._
- **NO booking link and no scheduler URL anywhere in the cold sequence.** _Decision (deliverability): the scheduling link belongs to the reply stage, after interest is shown. When a reply classifies as `interested` or `question`, the handler shares the meeting owner's link and the meeting books onto Zach's calendar whichever persona sent (`instructions/reply-handling.md`, `config/meeting-routing.md`). The link lives there, not here._
- Carry the meeting intent as a question instead. Example close: "Should I close this out for now, or would it help to grab 15 minutes?"
- Graceful close, e.g. "Otherwise, all the best this year!"

## 5. Voice

- Casual and human. Write like a real person typing a quick note.
- **No CTA phrasing is banned any more** (both CTA entries removed 2026-08-26 by explicit call). "Any opportunity to compare what Posh could put together?" and the "worth a quick chat / look" family are both allowed; the first appears in the sales team's own live email. They were originally banned on _Ashley's_ feedback ("CTAs are way too AI ... too fluffed up ... like the spam I get"), so the reversal is recorded rather than quietly dropped. **A concrete offer still reads better than a vague ask, but that is now guidance for the writer and for review, not a check.**
- **Watch for AI tells:** vivid-but-hollow phrases like "firefighting through it." _Feedback: West Coast Makers flagged that exact phrase._
- CTAs are plain questions that offer to do one thing: "want me to show you?", "happy to put together a quick comparison, want me to?". Never a mini-pitch. A concrete offer ("happy to put a comparison together") lands better than a vague ask ("worth a look?"), though neither is machine-checked now.

## 6. Claims & proof points (accuracy guardrails)

- **Do NOT claim native email follow-ups.** Posh does not do this natively; it requires a third-party tool. _Feedback: Dogwood Arts._
- **SMS / text blasting IS native and approved.** Safe to feature.
- **Do NOT use the "13% of tickets via the marketplace" stat.** Flagged internally as overstating reality. _Feedback: Lawrence and 90stildawn both rejected it._
- **Approved proof points** (use sparingly): $37M Series B; 60K organizers; 10M users in 5 years; newer features like waitlist, free SMS blasting, enhanced dispute protection. _Source: the sales team's own live email 2._
- **At most one stat per 3-email sequence**, and never two different stats across the sequence. _This is already enforced by validation (it flags e.g. m1:13% + m3:40%)._

## 7. Senders

Sequences send from **3 identities across 4 domains** (12 mailboxes total). Every
meeting books with Zach regardless of sender.

**The sender is supplied, never chosen.** The run's sending mailbox decides who sends,
and the research note carries that person's `sender.first_name` and `sender.intro_line`.
Use the intro line verbatim, near the top of email 1. The lines themselves live in
`config/senders.md`.

They are deliberately **not listed here any more.** A three-row table in this file read
as a menu: a 34-contact run put the wrong name in 18 of 34 emails, signing "Carl" while
the body said "I'm Brooke". A misrepresented sender breaks golden rule 2 and applicable
outbound-email law, so the fix was to remove the choice rather than add an instruction
telling the model not to make it.

- **No booking link in this rulebook.** The cold sequence carries none, so there is no
  handoff wording to specify here. Zach's link belongs to the reply stage and lives in
  `config/meeting-routing.md`; duplicating it here is how it leaks back into cold copy.
- **Sending domains:** vibeposhvip.com, coreposhvip.com, poshvippulse.com, poshviphub.com
- One intro line per sender, used across all campaigns for now.

## 8. Personalization & fallbacks

- Tailor email 1 to the lead's **current competitor** (Resident Advisor, Eventbrite, Eventeny, DICE, Eventnoire) and **vertical** (Party, Live Performance, Other Social Communities).
- **Missing first name:** many leads are role addresses (e.g. `info@`, `tickets@`) with no first name. Never output a broken "Hey ,". Use a name-less opener instead ("Hey there," / "Hey team,").

## 9. Prior-interaction callbacks (warm opens)

Before generating email 1, check the contact's **HubSpot timeline** for prior
engagements. A faithful callback to a real past interaction is the strongest
signal this isn't a cold blast, but a *fabricated* one is worse than none, so
this runs on strict tiers.

**The tier is computed upstream, not here.** `scripts/enrich_callbacks.py` reads the
timeline and writes `callback_tier` (`specific` / `soft` / `none`) plus
`callback_detail` and `callback_last_date` onto the contact CSV; generation receives
them in the research note under `callback` and words them per the tiers below.
Generation never reads HubSpot itself. If the columns are absent the tier defaults to
`none` and email 1 opens cold, so an un-enriched run is safe.

**First, decide whether a real interaction even happened:**
- **Counts as a prior interaction: a previous EMAIL conversation only** (narrowed 2026-08-26). An email that got a genuine reply *from the contact* is two-way and qualifies. Calls and meetings are deliberately not read: we are unlikely to be cold-emailing anyone we have already taken a call with, and supporting that path cost real complexity for a case that barely occurs.
- **Only the prospect's own new words are used.** A reply carries the whole quoted thread beneath it, which is *our* text. One real example ran 7.7k characters of which the prospect wrote 105; the rest was our own message, including per-ticket pricing and an advance. Everything from the first quote marker onward is discarded, so a callback can never be built out of our own words and attributed to them.
- **Does NOT count:** outbound emails we sent with no reply. A prior *send* is not a prior *conversation*. Several of these leads are old HubSpot contacts with ignored past outreach (per the project brief), and opening "great to reconnect" on a one-way send reads as false. Treat these as cold.

**Then pick the callback tier:**
- **Specific callback:** only when a concrete detail is actually written in the engagement (call/meeting notes, replied-email content). Paraphrase it faithfully; never inflate a vague note into a specific memory.
  - e.g. "Last time we spoke you mentioned you were on Eventbrite and happy with it. Still the case, or want me to show you what's changed?"
  - e.g. "When we connected you were running about one event a month. Have you scaled that, or is that where you'd want support?"
  - e.g. "Loved having you at Posh Blueprint earlier this year. How have you been feeling about your events since?"
- **Soft callback:** a real prior interaction exists but no reusable detail was logged. Acknowledge the reconnection only; assert nothing specific.
  - e.g. "Good to reconnect," / "It's been a while since we last connected,"
- **No callback:** no genuine prior interaction (or only ignored outbound). Use the normal cold open (§4, Email 1).

**Rules for the callback:**
- Callback goes in **email 1 only.** Don't repeat it in emails 2 and 3.
- **When in doubt, drop it and send the cold open.** A missing callback costs nothing; a wrong one costs the lead.
- Faithful paraphrase only. No embellishment, no upgrading "left a voicemail" into "we chatted."
- If the interaction was long ago, acknowledge the gap ("it's been a while") rather than implying it was recent.

_Limitation: the specific tier is only as good as the reps' logged notes. A call with no notes yields a soft callback at most. Sparse specific callbacks = a CRM note-taking gap, not a rules gap._

## 10. Reference: gold-standard sequence

Rewritten from the Dogwood Arts row after applying every rule above. Use as a
style anchor.

**Email 1**, _Subject: eventeny working out for Dogwood Arts?_
> Hi there,
>
> Are you still running events on Eventeny, or open to a look at something else?
>
> We work with a lot of community organizers, and the thing we hear most is how much lives *outside* the ticketing tool: guest approvals in one place, payouts in another, RSVPs scattered across email. Posh pulls that into one spot so the admin stops eating your week.
>
> Happy to put together a quick comparison for your next run of events, want me to?
>
> I'm Brooke, I run partnerships at Posh.

**Email 2** _(reply on same thread)_
> Quick follow-up. For recurring community events, most of your turnout is people who've already come once, but reaching them usually means exporting lists and hopping between tools.
>
> On Posh, your guest list and text blasts live in the same place as ticketing, so a reminder to past attendees goes out in a couple minutes instead of an afternoon.
>
> Want me to walk you through how that'd look for your calendar?

**Email 3** _(reply on same thread)_
> Last note from me on this, then I'll stop reaching out.
>
> Should I close this out for now, or would it help to grab 15 minutes and talk through how Posh could fit what you're running?
>
> Otherwise, all the best this year!

## Open items (fill in before go-live)

1. **Per-persona email-2 angle.** Should email 2 always anchor on a set feature per persona (e.g. Party/RA → text blasts; Community/Eventeny → repeat-attendee reach)? Currently the generator picks; a rule here would make it consistent.
2. **Series B link.** Decide whether the generator inserts the Series B announcement link (and whether that long tracking URL is templatized) or leaves it out.
3. **Intro variation.** Confirm one intro line per sender is fine across all verticals, or whether it should shift by persona.

## Conflicts: one still live

**Re-audited 2026-09-01.** This section listed four blockers and warned against trusting
a generated batch until they were fixed. Three had in fact been fixed and the warning had
gone stale, which is worse than no warning: it invites someone to "fix" code that is
already correct, and the obvious repair for item 1 would have REINTRODUCED the stat
machinery that was deliberately deleted. Verify before trusting an entry here.

1. ~~**The 13% stat is banned here, but the code forces it.**~~ **RESOLVED 2026-08-25/26.**
   Verified 2026-09-01: `snap_stats()` and `verify_canon()` are gone from `repair.py`
   (only a comment recording their removal remains), `CANON_13` no longer exists anywhere,
   and `validate.py.APPROVED_STAT_PATTERNS` is now `[]`, so no stat is accepted rather
   than one being forced. `STAT_MENTION` flags any `N%` for the stat budget instead.
2. ~~**Subject lines for emails 2 and 3.**~~ **RESOLVED 2026-08-25.** `check_subject_shape`
   now skips an empty subject at positions 2 and 3, still FAILs an empty one at
   position 1, and still shape-checks a stray non-empty subject on 2 or 3. The
   generation contract asks for a subject on `message_1` only. Casing was relaxed in the
   same pass to allow proper nouns, while ALL CAPS and Title Case still FAIL.
3. ~~**The banned CTA is still the documented default.**~~ **RESOLVED 2026-08-26 by
   reversal**, not by rewriting. Both CTA entries were un-banned by explicit decision, so
   "any opportunity to compare what Posh could put together" is allowed — it appears in
   the sales team's own live email. §5 above now records this, and `banned-phrases.md`
   keeps it only as a record of the removal. Nothing to reconcile: the rule moved, not
   the code.
4. **STILL LIVE — and it is a doc-vs-doc contradiction, not a code one.**
   Email 2 continuation vs. stand-alone. §1 says email 2 opens as a bump on a
   thread. "Structure of the 3-email sequence" below says the opposite: email 2 must
   read as if email 1 never happened, with "no 'just circling back'". Threading makes
   §1 correct; that older rule needs replacing, and `banned-phrases.md` should be
   checked for a follow-up-phrase ban that would now fire on correct copy.

Also worth reconciling: §6 bans claiming native email follow-ups, but
`config/personas.md` currently tells the generator to lead with "Posh automates the
manual marketing (text blasts, follow-ups)" for Premium. Text blasts are native and
fine; email follow-ups are not.

---

# Older rules (pre-2026-08-25)

Everything below predates the sales-team feedback above. Where the two disagree, the
section above wins. Kept because most of it — the voice anchor, the dash rule, the
compliance and output-format sections — is still the operative detail.

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
- **Length (recalibrated 2026-08-25):** messages 1 and 2 are roughly **45 to 90
  words**; message 3 is a breakup and shorter, roughly **20 to 50 words**. Previously
  80 to 110 and 40 to 70, which pushed copy toward exactly the length the AEs
  down-scored ("too long" in most scored rows) and which the team's own gold-standard
  sequence failed. See §3 of the sales-team rules: short throughout, email 3 shortest.
  These are **targets, not caps**. The validator reports drift as a WARN and never
  fails an email on length, because a good email slightly outside is better than a
  gutted one exactly on target. Stay skimmable on a phone.
  (Authoritative values: `LENGTH_TARGETS` in `scripts/validate.py`.)
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

Warm, direct, genuinely excited to help. A real SDR typing a quick note: not a
consultant diagnosing the prospect's problems, and not a stiff corporate pitch.

**The email's shape is assigned per contact** and arrives in the research note as
`shape.spec` (from `config/message-shapes.md`). Write that shape. This section governs
the *voice*; the shape governs the structure.

**No full example email lives here on purpose.** One used to, and the model treated it
as a form to fill in: a 34-contact run reproduced its paragraph structure 34 out of 34
times, its opening clause 34/34 and its closing question 34/34. A concrete example
outweighs any instruction telling you not to copy it, so the examples moved to the
shapes file where exactly one reaches you at a time.

### Tone rules

- **Open with a REASON FOR REACHING OUT, then ask about their current setup.** The first
  line has to answer "why am I getting this?". "Reaching out to see if you're locked in
  on your current ticketing setup" or "While looking at the event scene in [city], [org]
  stood out, so I wanted to reach out" both do. An assertion about them does not:
  "You're running [org] on [competitor] right now" reads as surveillance, and "Quick one
  about [org]:" opens on a demand.
- Do **not** open with a diagnosis of what is wrong with their tool. Never open with
  "Managing events on [platform] works, but...".
- **The CTA is a plain, concrete question.** Offer to *do* one specific thing and ask if
  they want it: "happy to put together a quick comparison, want me to?", "want me to
  show you how that'd look?", "open to seeing what we'd put together for your next one?".
  - **Prefer a concrete offer to a vague ask.** "Happy to put a comparison together,
    want me to?" beats "worth a quick look?". Neither is banned any more, so this is
    judgement rather than a rule: name the thing you will do rather than softening the
    ask.
- **One idea per email, developed fully.** Email 1 carries the warm question plus **one**
  facet of the package, not the whole bundle. Concrete nouns over abstract benefit
  language. Short sentences.
- **Sell with warmth, not fluff.** The bundle (dedicated account support, financial
  incentives, marketing push) is real, but naming all of it in one breath is the feature
  dump the AEs down-scored. Pick the single facet that fits this persona and band.
- **CONCRETE, NOT VAGUE.** The middle of the email is where it earns its tone, so it
  needs real content rather than less content. Speak in the first person, name their
  world, and list the actual items: "We work with a lot of [vertical] organizers in
  [city], and I often notice that organizers on [competitor] face operational challenges,
  such as having your guest lists, payouts, and promotion all living in three different
  places." The "I often notice" is doing work: a person is speaking, not a brand. Name a
  platform only when the research note actually carries one. What to avoid is the opinion with no content: "which is the
  part most ticketing tools are worst at", "that is the part organizers tell us eats the
  week". A closing "so ..." consequence is good when specific ("so you're not juggling
  tools on event night") and filler only when it restates the sentence before it.
- **Length: email 1 is 50 to 95 words of body.** The email the sales lead endorsed is
  about 85. When over, cut a vague sentence, never a specific one, and never the
  question. Vagueness is the problem, not length: a longer concrete email beats a short
  choppy one, and an earlier 65-word ceiling squeezed out the middle and read "cobbled
  together".
- **Write to THIS organizer.** `organization`, `city`, `vertical`, `volume_angle` and the
  competitor are all in the research note. A shape filled with generic nouns is the
  failure the shapes exist to prevent.
- **Never reuse an opening sentence across prospects.** Recurring structures are fine
  because the shape is assigned; the identical sentence landing in two inboxes is not.
- **Never claim a local footprint.** Referencing the prospect's own city is fine and
  reads as someone who looked. Claiming Posh has a community, presence, or scene
  anywhere is an unsupported claim. That distinction is the whole rule.
- **No dashes anywhere.** Hard constraint 1 forbids em and en dashes. Use a period,
  comma, colon, or parentheses.
- **At most one stat per sequence, and no numeric performance stats at all** (hard
  constraint 2). Lead with the package and the offer.

### When the current platform is unknown

If the research note has no usable `current_competitor`, **never guess one.** Do not
infer a platform from the vertical, the organization name, or the email domain. A wrong
platform named confidently is the most expensive mistake in a cold email: it proves the
sender did not look. Ask the generic version of the assigned shape's question and name
no platform anywhere.

### This, not that

**NOT** (cold diagnosis, then a vague ask, so both halves fail):
> Managing events on Resident Advisor works, but it's built for discovery, not for
> running the show. Worth a quick conversation about how it could simplify your next
> event?

**NOT** (a claim we cannot support):
> We have a huge and active community in New York.

**THIS**: the shape you were assigned, filled with this organizer's own details, in the
register above.
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
2. **No numeric performance stats.** Do not cite a percentage or figure for
   marketplace share, conversion, or any performance claim. Describe advantages
   qualitatively.
3. **Subject lines are 2 to 7 words, lowercase**, with two exceptions. Canonical
   acronyms and initialisms keep their standard casing: RA, NYC, DJ, RSVP, VIP, EDM,
   LA, SF, DM. A proper noun (a company, venue, or person name) keeps its single
   leading capital: "still using RA for Philadeep events?" is correct. Every other word
   is lowercase, including the first. Never ALL CAPS, and never Title Case every word:
   "Compare Your Ticketing Setup Today" reads like a marketing headline, not like a
   person typing. (The authoritative acronym list is `CANONICAL_ACRONYMS` in
   `scripts/validate.py`.)
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
  3. **It must read correctly if Email 1 got no reply**, which is the normal case, and
     it is a **threaded reply**, so a light continuation opener is correct ("quick
     follow-up," then straight into the angle). See §1 of the sales-team rules. What is
     still forbidden is *depending* on Email 1 having been read: no "as I mentioned", no
     recap, and nothing that only makes sense to someone who replied. Open on the angle
     itself and let it stand alone. **No re-greeting** either, since the earlier message
     sits directly below it.
  4. **Close on a concrete-offer CTA, in the anchor's register.** Offer to *do*
     something: "happy to put together a tailored comparison, want me to?", "any
     opportunity to compare what we could put together for your next one?". This email
     defaults to the vague hedge if left to itself. The "worth a quick chat/look/
     conversation" family is no longer banned, but it is still the weaker choice: make a
     real offer rather than softening the ask.
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
- **Default CTA:** a concrete offer phrased as a plain question, e.g. "happy to put
  together a quick comparison for your next one, want me to?", "want me to show you how
  that'd look?", or "open to seeing what we'd put together for your next one?" Name the
  one thing you will do, then ask.
  - **No CTA phrasing is banned** as of 2026-08-26: both the "worth a ..." family and
    "any opportunity to compare what Posh could put together" were un-banned by explicit
    decision. `config/banned-phrases.md` still catches invented features, disparagement,
    retired stats, local-community claims, and outcome promises, but the CTA is a human
    judgement now. The fix for a weak ask is still to name the thing you will do.
  - Persona-specific wording lives in `config/personas.md`.
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
  - The token lives in one place, `UNSUBSCRIBE_TOKEN` in `scripts/assemble.py`, and is
    **`%unsubscribe-text%`** as of 2026-08-26 (percent-delimited, not curly braces;
    confirmed against Smartlead's help centre). Never retype it into copy: assembly
    appends it, and the generator must not write it.
  - **The tag being right does not make a campaign send-ready.** Two per-campaign UI
    toggles decide whether it renders at all: "Add unsubscribe message in all emails"
    ON and "Optimize Email Delivery" OFF. See `config/smartlead-defaults.md` and step 4
    of `instructions/campaign-creation.md`.
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
