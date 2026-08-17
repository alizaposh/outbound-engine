# Instruction: Prospect Research

**Purpose:** Assemble a short, factual picture of each prospect and their company
*before* writing any copy, so messages are specific rather than generic.

## Inputs available
- HubSpot contact + associated company record.
- Any lead-source fields (Google Sheet / CSV columns provided with the request).
- The campaign brief (what problem/offer this campaign is about).

**Inputs are limited to the above.** Do not fetch external URLs, scrape sites, or call
outside services during research. If a prospect's record is thin, work with what's
there and say so in the note.

## Key HubSpot properties
These four drive persona routing and personalization. Read them first. The
authoritative routing rule lives in `config/personas.md`; this section says where each
property comes from and what it is allowed to affect.

- **`estimated_gmv_usd`** (rough annual ticketing volume). **Routing only, and it is a
  hard override.** When it has a value it decides the track by itself: `>= $50,000` is
  **Pro**, `< $50,000` is **Premium**, regardless of what `current_competitor` suggests.
  When it is blank, routing falls through to the competitor signal. **Never carry this
  number into the research note or any email.** Use it, then drop it. See the rule below.
- **`current_competitor`** (the platform they appear to be on now). Routes the persona
  **only when GMV is blank**: Eventbrite / Instagram / Plots / RA / Eventeny /
  Eventnoire point to **Premium**; Dice / Tixr / Shotgun / large-scale Eventbrite point
  to **Pro**. Its bigger job is the opener: the switch angle (what their current tool
  makes hard) is the strongest hook available, and it applies no matter which track the
  prospect landed on, so carry it into the note as the relevance angle where it fits.
- **`vertical`** (the kind of events they run). **Framing only, never routing.** It
  tailors how the opener sounds and narrows which case study fits.
  - Values seen on real lists: `Party`, `Live Performance`, `Festival`, `Other Social
    Communities`. Treat any unseen value as valid and work from the label's plain
    meaning rather than forcing it into this list.
  - **Opener framing:** `Party` and `Live Performance` lean nightlife and show-night
    operations (door, guest list, promo push). `Festival` leans multi-day scale and
    production. `Other Social Communities` is the community, civic, market, and
    recurring-gathering segment, so drop nightlife framing there entirely.
  - **Case-study matching:** it sharpens, but never replaces, the rules in
    `config/positioning.md`. `Party` and `Live Performance` point toward Caché Life,
    `Festival` toward We Belong Here, `Other Social Communities` toward NARC Run Club.
    The relevance gate still governs: a weak match means citing no case study at all.
- **`jobtitle`**. Who this person is and what they likely own, which sets whose problem
  the email should speak to (founder/owner, marketing, operations, talent/programming).
  Titles at these organizers are often informal, so read it for role, not seniority
  ranking.

**Reliability: `current_competitor`, `estimated_gmv_usd`, and `vertical` are scraped
estimates, not ground truth.** They are good enough to route a persona and shape an
angle, and not good enough to assert as fact to a prospect. Treat them as informed
guesses. `vertical` in particular is a hint about their world, so let it choose the
vocabulary without ever being said back to them ("as a festival organizer, you..."),
because it may simply be wrong. When signals disagree with the lead source, prefer the
more direct evidence and flag the prospect for human review rather than guessing.
`jobtitle` is CRM data and can be treated as reliable, though it may be stale.

## What to pull for each prospect
- **Person:** first name, last name, `jobtitle`, likely responsibilities.
- **Company:** name, industry, rough size, anything in HubSpot notes/properties that
  signals fit or a relevant trigger.
- **Current platform:** `current_competitor`, plus whether it looks reliable.
- **Vertical:** `vertical`, carried through as a framing hint.
- **Persona call:** Premium or Pro, per the routing rule in `config/personas.md`. Take
  `estimated_gmv_usd` first: if it has a value it decides the track outright. Only when
  it is blank does `current_competitor` route the prospect, and if that is also missing
  or unrecognized, default to Premium framing and flag for human review. Record which
  signal decided it so the basis is auditable.
- **Relevance angle:** one sentence connecting *this person's likely priority* to the
  campaign's problem/offer. This is what makes the email specific. Where
  `current_competitor` is present and credible, the switch angle usually belongs here,
  worded in the vocabulary their `vertical` suggests.

## Rules
- Use only information you actually have. **Do not invent** facts, metrics, mutual
  connections, or events. If a field is missing, work with what's present.
- Do not compile personal data beyond what's needed to write a relevant B2B message.
- Keep the research per prospect to a compact structured note (a few fields), because
  it will be fed into the generation step at volume, so keep it cheap.
- **Never put `estimated_gmv_usd` in the note.** It is a routing input only. Dropping
  it here is what guarantees it cannot reach an email, since generation only sees the
  note. Record the persona it produced, not the number itself.
- **Do not state a scraped estimate as fact.** The note should read "appears to be on
  Eventbrite," not "is on Eventbrite," so downstream copy inherits the uncertainty.

## Output (per prospect)
A small structured record, e.g.:
```
{ "relevance_angle": "...", "title_context": "...", "company_context": "...",
  "notable_signal": "...", "current_competitor": "appears to be Eventbrite",
  "competitor_confidence": "high | low | unknown",
  "vertical": "Party | Live Performance | Festival | Other Social Communities | ...",
  "persona": "Premium | Pro", "persona_basis": "gmv | competitor | defaulted",
  "needs_human_review": false }
```
`estimated_gmv_usd` is deliberately absent: it decides `persona` and then stops.
`persona_basis` is `gmv` whenever GMV had a value, since GMV overrides the competitor
signal. `vertical` is carried through because generation needs it for framing.
