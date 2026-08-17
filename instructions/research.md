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
These three drive persona routing and personalization. Read them first.

- **`current_competitor`** (the platform they appear to be on now). **Primary routing
  signal.** Eventbrite / Instagram / Plots / RA point to **Premium**; Dice / Tixr /
  Shotgun / large-scale Eventbrite point to **Pro**. It also sharpens the opener: the
  switch angle (what their current tool makes hard) is the strongest hook available,
  so carry it into the research note as the relevance angle where it fits.
- **`estimated_gmv_usd`** (rough annual ticketing volume). **Routing only.** Use it as
  a scale check to confirm or correct the Premium/Pro call from `current_competitor`.
  Higher volume pulls toward Pro, lower toward Premium. **Never carry this number into
  the research note or any email.** Use it, then drop it. See the rule below.
- **`jobtitle`**. Who this person is and what they likely own, which sets whose problem
  the email should speak to (founder/owner, marketing, operations, talent/programming).
  Titles at these organizers are often informal, so read it for role, not seniority
  ranking.

**Reliability: `current_competitor` and `estimated_gmv_usd` are scraped estimates, not
ground truth.** They are good enough to route a persona and shape an angle, and not
good enough to assert as fact to a prospect. Treat them as informed guesses. When they
disagree with each other or with the lead source, prefer the more direct evidence and
flag the prospect for human review rather than guessing. `jobtitle` is CRM data and can
be treated as reliable, though it may be stale.

## What to pull for each prospect
- **Person:** first name, last name, `jobtitle`, likely responsibilities.
- **Company:** name, industry, rough size, anything in HubSpot notes/properties that
  signals fit or a relevant trigger.
- **Current platform:** `current_competitor`, plus whether it looks reliable.
- **Persona call:** Premium or Pro, routed from `current_competitor` and sanity-checked
  against `estimated_gmv_usd`. Record which signal drove it. If the two disagree, or
  neither is present, default to Premium framing and flag for human review, per
  `config/personas.md`.
- **Relevance angle:** one sentence connecting *this person's likely priority* to the
  campaign's problem/offer. This is what makes the email specific. Where
  `current_competitor` is present and credible, the switch angle usually belongs here.

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
  "persona": "Premium | Pro", "persona_basis": "competitor | gmv | both | defaulted",
  "needs_human_review": false }
```
`estimated_gmv_usd` is deliberately absent: it informs `persona` and then stops.
