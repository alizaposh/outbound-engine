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

`scripts/run_generation.py` parses the `## Shape 1A:` headings; keep them exactly.

## The fixed skeleton of email 1

Every 1x shape is this, with only the OPENER differing. Do not reorder it.

```
Hey {first_name},

{sender.intro_line}

{OPENER — the only part the shapes below vary}

Are you locked in on your ticketing platform right now?

If there's room, I'd like to put a custom offer together — marketing support and
financial incentives.

Worth 15 minutes to see what we could bring to the table?
```

- **The question is present-tense and flat.** No year, no season, no "looking ahead to".
- **Name both levers out loud** — marketing support AND financial incentives. Never
  compress them into "value" or "what we could do for you".
- **Ask for a reply, not a booking.** No calendar link anywhere in the cold sequence.
- **≤ 75 words**, intro line included.
- **The sender's self-introduction stays**, near the top. The SDR draft omitted it; the
  person running outbound kept it by explicit decision on 2026-09-01, as they had in
  August. Without it email 1 never says what Posh is.

## Shape 1A: the competitor, named
For a contact whose `current_competitor` is known and usable.

**Opening variants (code picks one; use it as the opening move):**
- Saw {prospect_org} is running ticketing through {competitor}.
- Noticed {prospect_org} is on {competitor} for ticketing at the moment.
- Came across {prospect_org} and saw you're running ticketing on {competitor}.

> Saw {prospect_org} is running ticketing through {competitor}.

Nothing evaluative about the platform. The observation earns the email; it does not argue
yet.

## Shape 1B: the competitor plus the operational consequence
Known competitor, and the contact is large enough that operations are the live problem.

**Opening variants (code picks one; use it as the opening move):**
- Saw {prospect_org} is running ticketing through {competitor}. Most {vertical} organizers we work with in {city} end up with guest lists, payouts and promotion in three different places.
- Noticed {prospect_org} is on {competitor}. The {vertical} organizers we work with in {city} usually have guest lists, payouts and promotion sitting in three separate tools.
- Saw you're running {prospect_org} ticketing on {competitor}. Most {city} {vertical} organizers we talk to are stitching guest lists, payouts and promotion together by hand.

> Saw {prospect_org} is running ticketing through {competitor}. Most {vertical}
> organizers we work with in {city} end up with guest lists, payouts and promotion in
> three different places.

Two sentences maximum. This is the longest opener permitted and the 75-word cap has to
absorb it.

## Shape 1C: no platform named
**Used whenever the competitor is unknown or unusable. A correctness gate, not a style
choice** — 1A, 1B and 1D all state which platform they are on, and stating that wrongly is
worse than any amount of sameness.

**Opening variants (code picks one; use it as the opening move):**
- We work with a lot of {vertical} organizers in {city}.
- Most of who we work with in {city} are {vertical} organizers, so {prospect_org} caught my eye.
- We do a lot of work with {vertical} organizers around {city}.

Says only what the lead data supports: their vertical and their city. **No platform is
named in any variant** — that is the gate.

## Shape 1D: the endorsed shape
The opener the person running outbound wrote themselves, kept as the tone reference.

**Opening variants (code picks one; use it as the opening move):**
- Saw {prospect_org} is running ticketing through {competitor}. We work with a lot of {vertical} organizers in {city}, and I often notice that organizers on {competitor} face operational challenges, such as having your guest lists, payouts and promotion all living in three different places.
- Saw {prospect_org} is on {competitor}. We work with a lot of {vertical} organizers in {city}, and I often notice that guest lists, payouts and promotion end up living in three different places.
- Noticed {prospect_org} runs ticketing on {competitor}. Working with {vertical} organizers around {city}, I often see guest lists, payouts and promotion all sitting apart.

> Saw {prospect_org} is running ticketing through {competitor}. We work with a lot of
> {vertical} organizers in {city}, and I often notice that organizers on {competitor}
> face operational challenges, such as having your guest lists, payouts and promotion all
> living in three different places.

**Trim to fit 75 words with the intro line.** If it will not fit, use 1B.

## Email 2 shapes (threaded reply, no greeting, no re-introduction)

Beats: light human re-open → company proof → both levers restated with more weight → the
season reason → the same 15-minute ask. **≤ 90 words** — the only cap that went up,
because this email carries the proof email 1 withholds.

The **$37M Series B** is approved here and only here. The Fortune article may appear as a
**visible plain URL**, never as anchor text, and the default is no link at all.

**One cleared customer name, matched to their world** (`config/positioning.md`):
nightlife → VibeApple or Caché Life; festival → Palm Tree Festival or We Belong Here;
dating and networking → We Met IRL; run clubs → NARC Run Club. **Never a figure beside
any of them** except NARC's cleared numbers.

### Shape 2A: proof first
> Hope you had a good weekend — circling back on this.
>
> Bit more context on us: we just closed a $37M Series B, and we run ticketing for
> {cleared_customer}. Happy to get into the marketing side, and there's real room on the
> financial incentives for a {vertical} organizer like {prospect_org}.
>
> With the holiday season coming up, this is usually the best time of year for us to get
> a strong offer across.
>
> Free for 15 minutes this week?

### Shape 2B: the comparable first
Leads on the named customer rather than the funding, for a prospect whose world maps
cleanly onto a cleared name.

> Circling back on this.
>
> We run ticketing for {cleared_customer}, and just closed a $37M Series B. For a
> {vertical} organizer like {prospect_org} there's real room on the incentives, and the
> marketing side is usually where we add the most.
>
> The holiday run-up is when we can get the strongest offers across.
>
> Free for 15 minutes this week?

### Shape 2C: short
When email 1 ran long, or the contact's register is terse.

> Circling back. We just closed a $37M Series B and run ticketing for
> {cleared_customer}. There's real room on the incentives for {prospect_org}, and the
> holiday run-up is when we can get the strongest offer across.
>
> Free for 15 minutes this week?

## Email 3 shapes (the close)

**One line. ≤ 30 words.** No new information, no new value props, no breakup theatrics,
no urgency. Close the loop and stop.

### Shape 3A: the endorsed close
> Closing the loop here — if you've got time this week to look at the offer, let's get on
> the phone.

### Shape 3B: the plain question
> Closing the loop — worth 15 minutes this week to look at the offer?

### Shape 3C: shortest
> Closing the loop here. Still worth a look at the offer?

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
- **CONCRETE, NOT VAGUE.** This replaced a phrase blacklist that was cutting the wrong
  things, and it still governs every sentence that survives the new caps.
  - **Write this:** "I often notice that organizers on {competitor} face operational
    challenges, such as having your guest lists, payouts, and promotion all living in
    three different places." It works because it is **first person** ("I often notice"),
    it **names their world**, and it **lists the actual items** rather than gesturing at
    them.
  - **Not this:** "which is the part most ticketing tools are worst at", "that is the part
    organizers tell us eats the week". Opinions with no content: they explain the problem
    back to the person who has it.
  - A closing "so ..." consequence is **good** when specific — "so you're not juggling
    tools on event night" — and filler when it restates the sentence before it.
- **Cut the last sentence.** The final line of a draft is almost always throat-clearing: a
  summary of what was already said, or a soft apology for emailing. Delete it and check
  whether the email still works. It usually reads better.
- **Never inflate their title.** If they manage partnerships, they manage partnerships —
  not "run", "lead", "head up" or "own".
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
