# Config: Positioning

The single source of truth for what the system is allowed to say about Posh.
Message generation must stay inside this file.

## What we sell
Posh is an all-in-one platform for event organizers to create, promote, and scale
in-real-life experiences, and for attendees to discover personalized social events
with transparent pricing.

In one sentence: Posh helps organizers run and grow ticketed IRL events on one
platform, with a built-in marketplace that puts their events in front of new attendees.

## Who it's for
Broadly, anyone who hosts in-person events, experiences, or shows.

For **outbound specifically**, the highest-value targets are **Premium and Pro
organizers currently using a competitor** (Eventbrite, Dice, Tixr, RA, Shotgun,
TicketFairy, Plots). Free-tier organizers are typically already on Posh or very
early-stage, so treat them as expansion, not cold outbound. See `personas.md`.

Primary problems we solve:
- Manual, disjointed event ops (RSVPs, guest approval, payouts, tracking spread
  across multiple tools).
- Weak marketing conversion / heavy reliance on manual Instagram promotion.
- Ticketing tools that don't match a premium brand or drive their own audience.
- Lack of growth data and repeat-attendee insight.

## Value propositions (approved for external use)

> **No numeric performance stats (retired 2026-08-25).** The 13% marketplace share and
> the 40% conversion figures were removed: the sales team confirmed they were inaccurate
> and the reps did not use them. There is no approved percentage or figure for
> marketplace share, conversion, or any other performance claim. Describe the advantages
> qualitatively. Customer case studies below are a separate approved category.

- **Marketplace distribution:** events reach attendees already browsing the Posh
  marketplace, which is organic demand the organizer didn't have to source. **No share
  or volume figure** attaches to this.
- **A better deal than their current tool:** Posh can put together a more competitive
  offer than an organizer's current ticketing solution: dedicated account support,
  financial incentives, a marketing push, and more. **Bundled and unquantified, exactly
  as worded here.** See "Commercial terms" below: the *existence* of a tailored offer is
  approved, its *contents* are not.

## Proof: approved case studies
All three stories below are **cleared for external use in cold outbound**, including
their outcomes. Name them directly. No further sign-off is needed. Figures may be
cited only where a bullet marks them cleared.

- **Caché Life** (NYC nightlife/music): switched from TicketFairy for better brand
  alignment, and improved marketing conversion via Posh text blasts.
  **Fits:** nightlife, music, and upscale **Premium** organizers.
- **We Belong Here** (multi-day festival): the marketplace drove organic growth.
  **Fits:** festival and large-scale **Pro** organizers.
- **NARC Run Club** (community-focused run club, co-founders Noah and Omari):
  transitioned from free events to a sustainable paid business, adding brand
  partnerships and grant funding.
  **Cleared figures:** 34 events on Posh, 6 months on Posh, 500+ total attendees.
  **Fits:** community-focused and grassroots organizers **who already sell tickets**,
  run clubs, and recurring community events. Strongest for smaller paid organizers who
  are growing, or who previously ran free events and now sell tickets.
  **Never cite NARC to an organizer running only free events today.** Its free-to-paid
  arc is a relatability angle for smaller *paid* organizers, not a signal to target
  free ones. Free-only organizers are excluded from cold outbound entirely; see
  `personas.md`.

### Using a case study: HARD RULES
- **Relevance is the gate.** Cite a case study only when it genuinely applies to that
  prospect's situation and strengthens the specific point the email is making. Never
  drop one in as filler, as social-proof padding, or as a default closer.
- **Match the story to the prospect.** Caché Life goes to nightlife and upscale
  Premium organizers. We Belong Here goes to festival and large-scale Pro organizers.
  NARC Run Club goes to community-focused and grassroots organizers who already sell
  tickets, run clubs, and recurring community events, and it is strongest for smaller
  paid organizers who are growing or who moved from free events to paid. Never cite it
  to an organizer running only free events today. If none fits, cite none: no case
  study is better than a mismatched one. Persona definitions live in `personas.md`.
- **At most one case study per email.** Never stack two or more.
- **Stay inside what is written above.** Those bullets are the full approved scope.
  **NARC Run Club's figures are cleared** (34 events on Posh, 6 months on Posh, 500+
  total attendees) and may be cited in outbound exactly as written. **Caché Life and
  We Belong Here have no cleared figures**, so any number attached to them would be
  invented. Never invent, extrapolate, round, or restate any customer figure.
- **Any customer not listed here still needs explicit approval before being named.**

## Commercial terms: what the copy may and may not promise

**The principle: the existence of a tailored offer is sayable. Its terms are not.**
Nobody has priced this prospect at cold-email time, so any specific term in a cold
email is a number someone would later have to honor or walk back with a real
prospect. That is a materially worse failure than clumsy copy.

**Allowed**, and no more specific than this:
- That Posh can put together a **competitive** or **custom offer / proposal** for them.
- That **financial incentives** are part of what gets worked out with organizers,
  mentioned vaguely and bundled with the rest of the package, exactly as the voice
  anchor does: "dedicated account support, financial incentives, marketing push and
  more."
- That **dedicated account support** is available. This is a real capability, not a
  commercial term, and it may be described concretely.

**Never**, in any email:
- **Lower or reduced fees, rates, pricing, or commission.** Not as a promise, not as a
  possibility, not hedged with "could" or "depending on your volume".
- **A credit of any kind**: flat credit, account credit, credit toward anything.
- **A free or discounted period**: free month, first month free, a discounted trial.
- **Any percentage or dollar figure attached to an offer**: "20% off", "$500 credit".
- **A time-boxed offer**: "this quarter", "this month", "your first month", "limited
  time". Urgency implies terms that expire, which implies terms.

**NOT this** (both from real generated copy, one sentence):
> "Lower fees on a subset of your events, or a flat credit toward your first month on
> Posh, depending on your volume."

Two prohibited terms at once: a fee promise and a credit promise. The hedge
("depending on your volume") does not rescue it. Neither would "could" or "may".

**THIS**, the allowed vague form, from the voice anchor:
> "We've been putting together very competitive offers this year, all focused on
> helping organizers drive better reach, earlier conversions, and generating extra
> revenue with dedicated account support, financial incentives, marketing push and
> more."

Same promise of value, no term anyone has to honor. Enforced by
`check_commercial_terms` in `scripts/validate.py` as a hard FAIL, and deliberately not
auto-repaired: rewriting a commercial claim is an editorial decision, not a mechanical
one.

## Prohibited claims: HARD RULES
- No invented customers, logos, metrics, or results.
- **No specific or quantified commercial terms.** See "Commercial terms" above. The
  offer's existence is approved; its contents are not.
- **Nameable customers, cleared as of 2026-09-01 — six, and only these six:**
  Caché Life, We Belong Here, NARC Run Club, **We Met IRL**, **Palm Tree Festival**,
  **VibeApple**. The last three were cleared by the person running outbound on
  2026-09-01. Any other customer requires explicit approval first, and the validator
  (`CLEARED_CUSTOMERS` in `scripts/validate.py`) FAILs an unlisted name.

  Match the name to the prospect's world rather than reaching for the biggest one:

  | Prospect type | Name to use |
  |---|---|
  | Nightlife venue | VibeApple, Caché Life |
  | Festival / large-scale music | Palm Tree Festival, We Belong Here |
  | Dating, in-person networking, community | We Met IRL |
  | Run club / recurring community events | NARC Run Club |

- **NOT cleared, and asked for anyway: Lamborghini, Adidas, NBA, Celsius, HBO, Complex.**
  The SDR copy spec of 2026-09-01 lists these as comparables for brand and
  sponsorship-led prospects. They were **not** cleared, so they FAIL validation and must
  not appear. Recorded explicitly rather than quietly omitted, because the spec still
  asks for them and someone will otherwise assume it was an oversight. Naming a real
  company as a customer in cold outbound is a permissions question, not a copy
  preference. **Consequence: there is no cleared comparable for a brand-led prospect** —
  route those to the closest cleared name by event type instead.
- **Never invent or extrapolate a customer figure.** The only cleared customer figures
  are NARC Run Club's (34 events on Posh, 6 months on Posh, 500+ total attendees),
  cited exactly as written. **Every other nameable customer has no cleared figures** —
  Caché Life, We Belong Here, We Met IRL, Palm Tree Festival and VibeApple — so
  attaching a number to any of them means inventing it. Name them, do not quantify them.

- **The $37M Series B is an APPROVED claim (cleared 2026-09-01).** It may be stated in
  email 2 only, where the company proof belongs. It is company funding, not a
  performance metric, so it is exempt from the "no numeric stats" rule below — that rule
  governs marketplace share, conversion and results claims. The Fortune article covering
  it may be linked in email 2 **only as a visible plain URL**, never as anchor text, and
  the default is no link at all: the sentence carries the credibility on its own.
- **Never use a case study that doesn't fit the prospect, and never more than one per
  email.** See "Using a case study" above.
- **No numeric performance stats in copy:** no percentage or figure for marketplace
  share, conversion, or any other performance claim. Describe advantages qualitatively.
  The validator FAILs any percentage in a body (`check_approved_stats` in
  `scripts/validate.py`).
- **Competitor observations are allowed; invented claims about them are not** (revised
  2026-08-26). The blanket "no competitor disparagement" rule was removed because it got
  in the way of copy the sales lead endorsed: "I often notice that organizers on
  Eventbrite face operational challenges, such as having your guest lists, payouts, and
  promotion all living in three different places." That is an observation about where a
  workflow lands, and it is the line that gives the email its human tone.
  What still holds, and why each one is narrower than "no disparagement":
  - **Never invent a shortcoming or a capability.** "built for small creators", "not
    built for someone running your scale" are assertions about another product that we
    cannot support. Fabrication, not tone.
  - **Never characterize all competitors at once.** "most ticketing platforms ..." is a
    claim about a market we have not surveyed.
  - **Never open with a diagnosis of their tool.** "Managing events on [platform] works,
    but ..." is the cold-diagnosis opener the AEs rejected on its own merits.
  - **No head-to-head comparison claims:** "unlike Eventbrite", "better than DICE".
  These stay enforced in `config/banned-phrases.md`.
- No guarantees of revenue, attendance, or outcomes.
- [FILL IN any regulated or brand claims Legal wants excluded]

## Sender identity & compliance basics
- Legal company name for footers: Posh Group Inc.
- Physical mailing address for footers: 40 Crosby St, New York, NY 10013
- Opt-out: honored via suppression list; never contact an opt-out again. The opt-out
  link itself is rendered by Smartlead's unsubscribe token at send time, never
  hand-written into copy. See `instructions/message-generation.md`
  (Compliance in the copy).
