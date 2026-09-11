# Config: Message shapes

Rewritten 2026-09-01 to the SDR copy spec. Read the "SDR copy spec" section of
`instructions/message-generation.md` first: that is the rulebook, this file is the
structures that implement it.

**Why this file got narrower.** The old shapes varied the whole email, because a fixed
formula made every email 1 read identically with only the competitor name swapped. The
SDR spec deliberately **fixes three of email 1's four beats** — the question, the offer
and the ask are meant to be the same every time, because they are the three things the
sequence exists to say. So variation now lives in **beat 1 only**, the opener, which is
the one beat with real per-lead input. Varying the question or the offer is now a bug,
not variety.

`scripts/run_generation.py` parses the shape headings; keep their exact form.

## The fixed skeleton of email 1

Every 1x shape is this, with only the OPENER differing. Do not reorder it.

```
Hey {first_name},

{sender.intro_line}

{OPENER — the only part the shapes below vary}

Are you locked in on your ticketing platform right now?

%OFFER%

%CTA%
```

- **The question is present-tense and flat.** No year, no season, no "looking ahead to".
- **Name the offer as a bundle**, from the Offer variants at the end of this file. Never
  compress it into "value" or "what we could do for you".
- **Ask for a reply, not a booking.** No calendar link anywhere in the cold sequence.
- **≤ 75 words**, intro line included. The opener's budget is about **21 words**: the
  fixed beats cost roughly 54, so anything longer than one or two short sentences cannot
  fit. Arithmetic, not taste — shapes with three-sentence openers ran a median of 97 and
  went over in 8 of 8 emails.
- **Write NOTHING beyond these paragraphs.** No extra middle paragraph explaining the
  problem, no "Posh pulls that into one spot" line. A run produced a 113-word email 1 by
  inserting exactly that.
- **The sender's self-introduction stays**, near the top. The SDR draft omitted it; the
  person running outbound kept it by explicit decision on 2026-09-01.

## Shape 1A: the platform, named
For a contact whose `current_competitor` is known and usable.

**Opening variants (code picks one; use it as the opening move):**
- Saw {prospect_org} is running ticketing through {competitor}.
- Noticed {prospect_org} is on {competitor} for ticketing at the moment.
- Came across {prospect_org} and saw you're running ticketing on {competitor}.
- Saw you're running {prospect_org} ticketing on {competitor}.
- Noticed {prospect_org} runs ticketing on {competitor} right now.

> Hey {first_name},
>
> {sender.intro_line}
>
> Saw {prospect_org} is running ticketing through {competitor}.
>
> Are you locked in on your ticketing platform right now?
>
> %OFFER%
>
> %CTA%

**One sentence. State the platform and stop.** No characterisation of the platform, and
no observation about what organizers like them supposedly struggle with — see "NO
OBSERVATION SENTENCES" below.

## Shape 1C: no platform named
**Used whenever the competitor is unknown or unusable. A correctness gate, not a style
choice** — 1A states which platform they are on, and stating that wrongly is worse than
any amount of sameness.

**Opening variants (code picks one; use it as the opening move):**
- We work with a lot of organizers in {city}.
- Most of who we work with are organizers around {city}.
- We do a lot of work with organizers in {city}.

> Hey {first_name},
>
> {sender.intro_line}
>
> We work with a lot of organizers in {city}.
>
> Are you locked in on your ticketing platform right now?
>
> %OFFER%
>
> %CTA%

Says only what the lead data supports, and **names no platform and no category**.

**Every 1C opening names a `{city}`, so 1C requires one.** A contact with no city gets no
opening line at all: `pick_opening` drops variants it cannot fill and `strip_unfillable`
removes the line from the exemplar before the model sees it. That is deliberate. Handed
this shape with no city, the model wrote *"We do a lot of work with organizers in Kansas
City."* for `bookings@lanternroomkc.com` — mining `kc` out of the domain, inventing a
location AND asserting traction there that `config/positioning.md` does not support.

**A prose rule did not prevent that and could not.** The prompt already said to invent
nothing; the exemplar demanded a value, and the exemplar is what the model follows. The
fix is structural: remove the demand rather than argue with it. Any shape line whose
placeholder has no data behind it is deleted, for every shape and every contact.


## Email 2 shapes (threaded reply, no greeting, no re-introduction)

Beats: light human re-open → company proof → both levers restated with more weight → the
season reason → the same 15-minute ask. **≤ 90 words** — the only cap that went up,
because this email carries the proof email 1 withholds.

The **$37M Series B** is approved here and only here. The Fortune article may appear as a
**visible plain URL**, never as anchor text, and the default is no link at all.

**Phrase it as "organizers like {comparable}"**, not a bare "we run ticketing for
{comparable}". It reads as a comparable — here is the kind of organizer we work
with — rather than as a claim that the prospect and the customer are the same thing.

**Use `{comparable}` exactly as supplied.** The research note carries ONE cleared
customer name, already matched to this contact by `pick_comparable()` in
`run_generation.py`. **Do not choose your own** and do not name a second: the mapping
lives in code precisely so the internal vertical that drives it never reaches the prompt.
**Never a figure beside the name** except NARC's cleared numbers.

### Shape 2A: proof first
> Hope you had a good weekend — circling back on this.
>
> Bit more context on us: we just closed a $37M Series B, and we run ticketing for organizers
> like {comparable}. Happy to get into the marketing side, and there's real room on the
> financial incentives for {prospect_org}.
>
> With the holiday season coming up, this is usually the best time of year for us to get
> a strong offer across.
>
> %ASK2%

### Shape 2B: the comparable first
Leads on the named customer rather than the funding, for a prospect whose world maps
cleanly onto a cleared name.

> Following up on this one.
>
> We run ticketing for organizers like {comparable}, and just closed a $37M Series B. For {prospect_org}
> there's real room on the incentives, and the
> marketing side is usually where we add the most.
>
> The holiday run-up is when we can get the strongest offers across.
>
> %ASK2%

### Shape 2C: short
When email 1 ran long, or the contact's register is terse.

> Wanted to put this back in front of you. We just closed a $37M Series B and run ticketing for organizers
> like {comparable}. There's real room on the incentives for {prospect_org}, and the
> holiday run-up is when we can get the strongest offer across.
>
> %ASK2%

## Email 3 shapes (the close)

**≤ 30 words.** No new information, no new value props, no breakup theatrics, no urgency.

**A warm closer is required** (`%CLOSER%`, picked per contact from the list at the end of
this file). Without it the close reads harsh — a bare "closing the loop" is the last thing
a prospect hears from us and should not sound like a door shutting.

**This is NOT the "cut the last sentence" rule being broken.** That rule targets
throat-clearing: a summary of what was just said, or an apology for emailing. A warm
sign-off is neither. It adds no information and asks for nothing, which is exactly why it
is allowed to stay. Do not "tidy" it away.

### Shape 3A: the endorsed close
> Closing the loop here. If you've got time this week to look at the offer, let's get on
> the phone.
>
> %CLOSER%

### Shape 3B: the plain question
> Last note from me on this. Worth 15 minutes this week to look at the offer?
>
> %CLOSER%

### Shape 3C: shortest
> I'll leave it here — still worth a look at the offer?
>
> %CLOSER%


**Each shape at positions 2 and 3 opens DIFFERENTLY, on purpose.** Until 2026-09-11 every
email-2 exemplar opened "Circling back" and every email-3 one "Closing the loop", so
shape variety produced no visible variety at all — the shapes differ in the order of the
middle beats, which a reader never notices. Measured on the first real rep list, email 3
came out as **7 distinct bodies across 36 contacts, 29 of them byte-identical**. Changing
a shape's opener is the only edit that actually changes what the prospect sees, so keep
these three first lines distinct from each other when editing.

## Rules that apply to every shape

- **The three things the sequence must say**: are you locked in, I want to put a custom
  offer in front of you, will you give me 15 minutes. Email 1 says all three; emails 2 and
  3 re-ask the third with escalating context. A sentence serving none of them is cut.
- **OPEN WITH A REASON FOR REACHING OUT, not a bare assertion about them.** A cold email
  has to answer "why am I getting this?" in the first line.
  - **"Saw {prospect_org} is running ticketing through {competitor}"** is approved — it is
    the endorsed opener, and it is framed as *our observation*, which is a reason.
  - **"You're running {org} on {competitor} right now."** is not. Same fact, stated back
    at them as a flat assertion, which reads as surveillance rather than an introduction.
  - **"Quick one about {org}:"** is not. It opens on a demand.
  The difference is whose perspective the sentence is from. Keep it ours.
- **CONCRETE, NOT VAGUE — but there is now nothing between the opener and the
  question.** This rule used to carry a worked example of an observation sentence, and
  that example was reproduced in generated copy long after the sentence itself was cut.
  The example is gone; what it was really teaching survives as: when you do write a
  sentence, name the actual thing rather than gesturing at it. Opinions with no content
  ("which is the part most ticketing tools are worst at") were always banned and remain
  so.
- **Cut the last sentence.** The final line of a draft is almost always throat-clearing: a
  summary of what was already said, or a soft apology for emailing. Delete it and check
  whether the email still works. It usually reads better.
- **Never inflate their title.** If they manage partnerships, they manage partnerships —
  not "run", "lead", "head up" or "own".
- **NEVER PRINT OUR INTERNAL CATEGORY.** The lead's `vertical` — "Party", "Live
  Performance", "Other Social Communities", "Festival" — is an internal classification
  used to route the persona and pick the comparable. It is **not passed to the model at
  all** as of 2026-09-02, and it must never appear in copy. "live performance organizers
  in Los Angeles" and "party organizers" both shipped in a real batch, and "Other Social
  Communities organizers" was one draw away. Say "organizers", or say nothing.
  `validate.py` FAILs a category used as a descriptor.
- **NO OBSERVATION SENTENCES.** Cut 2026-09-02 as fluff. Sentences of the form "I often
  see organizers in {city} keeping guest lists, payouts and promotion apart" explain the
  prospect's own job back to them and earn nothing. The opener states a fact — what
  platform they are on, or where we work — and then the email asks its question. If a
  sentence describes what organizers "tend to" or "usually" or "often" do, delete it.
- **A compliment must name a specific thing, or be cut.** There is no data source for a
  booked act, so the opener makes a specific *observation* instead of paying a compliment.
  A generic compliment is the exact fluff the spec exists to remove.
- **No urgency in emails 1 or 3.** The sequence's only urgency is email 2's holiday
  window, and it is about our offer window, never their calendar.
- **No future-season, renewal or next-year talk anywhere in the cold sequence.** Timing is
  reply-triggered: a prospect saying they are locked in is a successful answer, and the
  timing thread starts in the reply handler.
- **Incentives stay qualitative.** Signal there is real room to go beyond standard terms;
  never a rate, rev-share, guarantee, minimum or dollar figure. Specifics happen on the
  call.
- **A warm open replaces the opener beat, never adds to it.** When `callback_tier` is not
  `none`, the callback *is* the opener (`message-generation.md` §9) and the rest of the
  skeleton is unchanged. Running both would double the opening and break the cap.

## Subject variants (code picks one)

**Email 1's subject only, and it is the subject for the WHOLE sequence.** Emails 2 and 3
send with `subject: ""` so Smartlead threads them and they arrive as "Re: ...". There is
never a second subject to write.

Picked per contact in code, preferring the most specific line the contact's data can
fill. Until 2026-09-11 there was no list at all and the model improvised from the shape,
which produced 14 distinct subjects across 36 contacts with two of them covering 23.

**Lowercase is the house style and Title Case is a FAIL** — it is the marketing-headline
register, and `check_subject_shape` enforces it. A proper noun keeps its capitals, so
"Neon Vault x Posh" passes and "Neon Vault Partnership With Posh" does not. Cap is
**2-8 words**, where the prospect's own name counts as one word however long it is.

Naming the competitor, when we know it:
- filling seats beyond {competitor}
- {competitor} working out for {prospect_org}?
- beyond {competitor} for ticketing?

Naming the organization, when we have a real one:
- {prospect_org} x Posh
- ticketing for {prospect_org}
- {prospect_org} partnership with Posh
- ticketing setup at {prospect_org}
- {prospect_org} and Posh?

Generic, when we have neither. **These carry most of a cold list** — on the first real
rep list only 9 of 36 contacts had a usable organization name and 1 had a known
competitor, so a thin generic set is what actually reaches most prospects:
- locked in on your ticketing setup?
- ticketing setup for your events?
- locked in on ticketing right now?
- who handles your ticketing?
- quick ticketing question
- your current ticketing setup?
- ticketing for your next run of events?
- open to a ticketing conversation?

## Offer variants (code picks one)

Declarative: they NAME the offer. The ask is the CTA's job, so these do not end in a
question. **Do not use a colon before the list** — the bundle is what the proposal
contains, not a definition of it, and a colon reads as the latter.

**Naming the bundle is OPTIONAL.** `config/positioning.md` approves two things
separately: that Posh "can put together a competitive or custom offer/proposal for them"
— on its own, with no contents named — and, if the contents *are* named, the exact
bundled wording "dedicated account support, financial incentives, marketing push and
more". It also says plainly: *the existence of a tailored offer is approved, its contents
are not.* So a short variant that names nothing is both **shorter and lower-risk** than
one that lists the bundle.

**Why that matters (2026-09-11).** The three original variants all listed the full bundle
at 19-21 words. On a 36-contact list that single block was both the main reason email 1
ran over its 75-word cap **and** the largest remaining source of sameness in email 1 —
near-verbatim in all 36. Short variants fix both at once.

**When the bundle IS named, keep the phrase intact.** Do not reorder or reword it:
"financial incentives" is approved only in that vague bundled form. **Bundled and
unquantified** — naming a rate, a share or a figure is a FAIL.

Short, no contents named (all approved by the "existence of a tailored offer" clause):
- I'd like to put a custom offer together for you.
- Happy to put a competitive proposal together for you.
- If there's room, I'd like to build you a custom proposal.
- There's a custom offer I'd like to put together for you.

Dedicated account support only — a real capability, and `positioning.md` allows this one
to be described concretely:
- I'd like to put a custom offer together for you, with a dedicated account team behind it.
- Happy to build you a custom proposal, with real account support behind it.

Full bundle, exact approved wording:
- I'd like to put a custom offer together for you with dedicated account support, financial incentives, marketing push and more.
- If there's room, I'd like to put a custom proposal together for you with dedicated account support, financial incentives and a marketing push.
- Happy to put something custom together for you, with dedicated account support, financial incentives and marketing behind it.

## CTA variants (code picks one)

One ask, reply-based. **Never a booking link** — the calendar goes out in the reply, after
they say yes.

- Worth 15 minutes to see what we could bring to the table?
- Let me know if you're open to connecting to see what we can bring to the table.
- Any opportunity to compare what Posh could put together in a custom proposal?
- Open to 15 minutes to see what this could look like for you?
- Worth a quick conversation?
- Free for a short call this week?
- Interested in seeing what that would look like?
- Any interest in talking it through?

**The four added on 2026-09-11 deliberately avoid "15 minutes" and "bring to the
table"**, which between them appeared in three of the original four and so turned up in
most emails on a 36-contact list. They are also shorter, which matters because the CTA
and the offer share email 1's 75-word budget.

A quiet side benefit: "15 minutes" beside a cleared customer name is what tripped
`case_study_rules` with "numeral near 'We Met IRL'" — a false positive, but a less
frequent one now that fewer CTAs carry a numeral.

The third was banned in August on AE feedback and **un-banned by explicit decision**,
because it appears in the sales team's own live email. Kept for the record so the
reversal is visible.

## Attempt callback variants (code picks one)

The opening line of email 1 when `callback_tier` is **`attempt`** — we emailed this
contact within the last year and they never replied. It **replaces** the shape's opening
beat rather than adding to it, and email 1 keeps its 75-word cap.

**Shorten the SETUP, never the question.** Three of the original eight were trimmed to
reach the 12-word budget by cutting the question itself, which produced "Better now?",
"Try again?" and "trying you again at a better time" — one nonsense fragment, one that
reads as us talking to ourselves, and one that asserts the very thing it is asking. The
question is the whole point of the line; the clause before it is what gives. A variant
that does not fit the budget needs a shorter preamble, not a clipped ask.

**The greeting stays.** These replace the shape's opening BEAT, not the salutation:
email 1 still opens "Hey {first_name}," and the line follows it. Phrasing the prompt as
"open email 1 with this line" cost 11 of 36 contacts their greeting on a real list.

**One sentence or one short pair, 12 words maximum.** An em-dash counts as a word here, because the length validator splits on whitespace and so does this budget. These are the only thing separating
an `attempt` email from a cold one, so they carry real weight for their length.

**They may claim only that we WROTE, never that we spoke.** "Good to reconnect", "great
speaking", "following up on our chat" are all false here — the prospect never answered.
They must also not reference what the earlier email SAID: our own logged sends are
bulk-associated and unreliable per contact, so *that* we wrote is known and *what* we
wrote is not. And no apology or guilt — not "sorry to bother you again".

- I know we tried to connect a while back. Better timing now?
- I know we tried to connect previously. Is now a better time?
- We reached out a while back. Is it better timing now?
- Tried you earlier in the year — worth revisiting?
- I think you've heard from us before. Timing may be better now.
- We got in touch a while ago. Worth trying again?
- Reached out before — trying again in case timing is better.
- I know we've emailed before — hoping this lands better.

**Why this is a config list and not a line in the prompt (2026-09-11).** It started as a
single worked example inside the classifier guidance, and all 30 `attempt` contacts on
the first real list wrote it verbatim: "I know we tried to connect a while back. Better
timing now?" thirty times. **A prompt example is a template, not a suggestion** — the
same lesson as the invented "Kansas City", the objection call-to-action, and the callback
that added a beat instead of replacing one. Variation has to be picked per contact in
code, exactly as the offer, CTA and closer are.

## Email 2 ask variants (code picks one)

Email 2's closing ask. **Separate from the email 1 CTA list on purpose:** this ask lands
after the proof beat — Series B, the comparable, the incentives — so it can be slightly
more direct than email 1's, and the two lists should be tunable independently.

Until 2026-09-11 the ask was hardcoded as "Free for 15 minutes this week?" inside all
three email-2 exemplars, so **all 36 contacts on the first real rep list closed email 2
with the identical sentence** while email 1's CTA varied eight ways. A beat written into
an exemplar cannot vary; only a slot can.

Reply-based, one ask, **never a booking link** — the calendar goes out in the reply.

- Free for 15 minutes this week?
- Worth 15 minutes this week?
- Any time this week for a quick call?
- Open to a short call this week?
- Want me to put something together for you?
- Worth a conversation this week?
- Free for a quick call in the next few days?
- Happy to walk you through it — this week work?

## Closer variants (code picks one)

The last line of email 3, and the last thing a prospect hears from the sequence. Warm,
short, no ask, no new information.

- Looking forward to chatting!
- Either way, hope the season goes well.
- Would be great to connect.
- Either way, good luck with the run.
- Hope the rest of the season treats you well.
- Happy to connect whenever the timing suits.
- Either way, wishing you a strong run of shows.
- Glad to talk whenever it makes sense.

**Count matters as much as wording, and this is the reason.** Email 3 is the shortest
email in the sequence and has only two moving parts: its shape's opener and this closer.
So the number of DISTINCT email 3s the engine can produce is exactly
`email-3 shapes x closers`. At 3 x 4 that was 12, and on a 36-contact list it produced
exactly 12 distinct bodies with 24 exact duplicates — the space was fully exhausted, and
no prompt change could have improved it. 3 x 8 doubles the ceiling to 24. **If email 3
looks repetitive on a future list, add closers here; do not add instructions.**

**Budget: 9 words maximum.** The longest close (3A) is 21 words and the cap is 30, so a
10-word closer pushed a real email to 32. Keep every variant at or under 9.

**No presumption.** "Looking forward to chatting!" is warm; "Speak Tuesday" would assume a
yes nobody gave.

## Removed shapes (history, not guidance)

Kept outside every shape section on purpose: the parser hands a shape's whole section to
the model, so a note living inside one becomes part of the prompt. This one was inside 1C
and was being read as copy guidance, describing the very observation sentences the shape
must not write.

**Shapes 1B and 1D, removed 2026-09-02.** Both existed to carry an observation sentence
about what organizers in the prospect's category tend to struggle with. That was cut as
fluff, which left them identical to 1A. There are only two real situations — we know their
platform or we do not — so there are two shapes. `assign_shapes` still asks for B and D
for some volume bands and `pick()` falls back to A, which is correct.
