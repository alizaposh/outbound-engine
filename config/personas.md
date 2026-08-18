# Config: Personas

Per-persona guidance for message generation. Outbound targets **Premium** and **Pro**
organizers who are currently on a competitor platform. This is also where stakeholder
feedback ("for this persona, lead with X, not Y") gets encoded as a reusable rule.

## How to identify which persona

### Routing rule: `estimated_gmv_usd` is a hard override
Check GMV first. When it has a value it decides the track and **overrides the
competitor signal**, whatever platform the prospect appears to be on.
- **`estimated_gmv_usd` >= $50,000 → Pro track.**
- **`estimated_gmv_usd` < $50,000 → Premium track.**
- **`estimated_gmv_usd` blank → fall through to the competitor signal below.**

> **Threshold note.** The true Pro line is **$100,000**. The gate is deliberately set
> at **$50,000** to keep lead volume workable for early campaigns, so the $50k to
> $100k band routes to Pro on purpose and is wider than the real definition. Revisit
> once volume allows and move it back toward $100,000.

### Competitor signal
Used when GMV is blank, and always for the switch angle regardless of how the
prospect was routed.
- **Current platform** (the biggest tell, and the thing to displace):
  Eventbrite / Instagram / Plots / RA / Eventeny / Eventnoire → likely **Premium**;
  Dice / Tixr / Shotgun / large-scale Eventbrite → likely **Pro**.
- **Event volume & attendance:** ~1 to 6 events/mo, 30 to 100 attendees → Premium;
  monthly/quarterly large-scale, 50+ to thousands, multi-city → Pro.
- **Ticket price:** ~$5 to $100 → Premium; higher / festival pricing → Pro.
- **Are they already selling tickets?** This is the cold-outbound gate, not a
  Premium/Pro tell. A community, grassroots, or recurring-event organizer who charges
  for tickets is **Premium**, even if smaller or less polished than a nightlife brand.
  An organizer running only free events is **not a cold-outbound target** at all.
If unclear, default to Premium framing and flag for human review.

## Persona: Premium organizer
Covers two groups with the same core needs (less manual work, brand fit, growth), at
different stages. Both must **already be selling tickets**.
- **Typical profile, established:** mature organizers / small businesses; 1 to 6
  events/month; 30 to 100 attendees; tickets ~$5 to $100; strong branding; lean teams
  (1 to 3 people).
- **Typical profile, smaller community and grassroots:** community, grassroots, and
  recurring-event organizers (run clubs, meetups, recurring series) who are **already
  charging for tickets**, just at a less polished or lower-volume level than nightlife
  or festival brands. Earlier in the journey, same needs. Often still building
  consistency, so growth and repeat attendance matter to them.
- **Boundary:** an organizer running only free events today is out of scope for cold
  outbound regardless of how promising they look. See "Not a cold-outbound target"
  below.
- **Likely on now:** Eventbrite, Instagram, Plots, RA.
- **What they care about:** a platform that matches their premium aesthetic; less
  manual work (text blasts, follow-up campaigns); fast RSVPs, guest approval, simple
  payouts; growth data; responsive support.
- **Lead with:** the operational headache + brand mismatch of their current tool.
  Posh automates the manual marketing (text blasts, follow-ups) and matches a premium
  brand, with the marketplace bringing new attendees. The stats land well here, but
  use at most one across the whole sequence (see message-generation.md).
- **Avoid:** heavy enterprise / "scale to thousands" language. They're lean, so
  don't overwhelm them.
- **Preferred CTA:** a concrete offer that invites a reply. Example: "Any
  opportunity to compare what Posh could put together for your next one? Let me know
  if you're open to connecting." Keep the opener reply-based, with no booking link
  yet. Offer a specific time or scheduling link only once they show interest.

## Persona: Pro organizer
- **Typical profile:** high-revenue operators; monthly/quarterly festivals or large
  activations; 50+ to thousands of attendees; multi-city; mature teams; complex
  marketing/production; partner with sponsors/venues/vendors; **often already
  comparing ticketing platforms.**
- **Likely on now:** Dice, Tixr, Instagram, Eventbrite, Shotgun.
- **What they care about:** platform scalability/reliability; strategic partnership +
  high-touch sales/success; affiliate/ambassador tools for organic growth; deep
  analytics.
- **Lead with:** the competitive offer (dedicated support, financial incentives,
  marketing push) plus scale and organic growth. They're in evaluation mode, so the
  custom-proposal ask lands well. Use at most one stat across the whole sequence.
- **Avoid:** "easy, lightweight tool" framing. Too basic, and it undersells the
  platform.
- **Preferred CTA:** a concrete offer, which lands especially well since they're
  already comparing. Example: "Any opportunity to compare what Posh could put together
  in a custom proposal for your next run of events? Happy to pull together a tailored
  comparison." Reply-based first; scheduling link once interested.

## Not a cold-outbound target: Free tier
- Free-tier organizers (RSVP-only, $0 tickets, 1 to 50 attendees, often new to event
  tech) are typically already on Posh or very early. Handle as **product-led
  expansion / upsell**, not cold outbound. If one appears in a cold list, flag it
  rather than send.
- **This exclusion is about what they do today, not their history.** An organizer who
  used to run free events and now sells tickets is a valid **Premium** target. An
  organizer running only free events today is not, however promising the trajectory
  looks. Selling tickets today is the line.

## Routing branches: what to do when signals are missing

Blank `estimated_gmv_usd` is common, so routing every such lead to a human queue
would defeat the system. Three branches, checked in order. Always record which one
fired in `persona_basis`, so a reviewer can see how a given email got framed.

### Branch 1: signals present
`estimated_gmv_usd` and/or `current_competitor` are usable. Route by the normal rule
above (GMV is the hard override; competitor routes when GMV is blank) and generate
from the main voice anchor, naming the platform. `persona_basis` is `gmv` or
`competitor`.

### Branch 2: signals missing, lead otherwise valid
GMV and/or competitor are missing, but the lead is a real organizer with a company or
brand identity worth writing to. **Generate.** Do not queue it.
- **Persona:** route on whatever secondary signal exists, in this order:
  `vertical`, then `jobtitle`, then company type. `Festival` and large-scale signals
  lean Pro; everything else leans Premium.
- **If no secondary signal supports a confident call**, write a single
  persona-neutral version: the package and the offer, without Premium's
  manual-work framing or Pro's scale framing.
- **Record it:** `persona_basis` is `fallback: vertical`, `fallback: jobtitle`,
  `fallback: company-type`, or `fallback: neutral`.
- **Copy:** if `current_competitor` is missing or unusable (blank, "Other",
  "Unknown"), use the **no-platform fallback** in
  `instructions/message-generation.md` (Voice anchor, "When the current platform is
  unknown"). Ask the generic setup question and name no platform. If the competitor
  is usable, the main anchor applies as normal.

### Branch 3: not enough to write a credible email
No company or brand identity, not an organizer, or the row is junk. **Flag for human
review and generate nothing.** `persona_basis` is `flag: insufficient`.

This escape hatch matters more than it looks: lead qualification is deferred out of
v1, so this branch is currently the only thing standing between a garbage row and an
email going out to it. Do not widen branch 2 to swallow it.
