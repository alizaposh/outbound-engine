# Config: Banned Phrases

Phrases that must never appear in generated copy. `scripts/validate.py` reads this
file and fails any email containing a match. Editing this file changes the validator;
no code change needed.

Two sections. **Literal** entries match case-insensitively as substrings. **Regex**
entries are Python regular expressions, also case-insensitive. One entry per line, in
backticks. Lines outside the two lists are ignored, so comment freely.

Add to this list whenever a review catches a phrasing the rules already forbid but the
model produced anyway. Each entry should note why, so nobody removes it later without
understanding what it prevented.

**Removed 2026-08-26, both CTA entries, by explicit decision from the person running
outbound.** Recorded rather than quietly dropped, so the reversals are visible if the AEs
raise them again.

- `any opportunity to compare what posh could put together` — banned on AE feedback
  (Ashley: "reads like the spam I get"), un-banned because it appears in the sales team's
  own live email.
- `worth a (quick) conversation / chat / call / comparison / look` — the vague-ask family.
  Banned after "worth a quick comparison" and "worth a conversation about whether that
  pencils out" shipped in real runs.

**Consequence worth stating plainly: no CTA phrasing is machine-checked any more.** This
file still catches invented features, competitor disparagement, retired stats, local-
community claims, and outcome promises, but the CTA is now judged by humans in review
only. The "name the thing you will do rather than softening the ask" guidance in
`instructions/message-generation.md` is therefore advice, not an enforced rule, and the
places that called it a hard FAIL have been corrected so the docs do not claim an
enforcement that no longer exists.

## Literal

- `strategic positioning on the marketplace`
  Invented feature. Appears nowhere in `positioning.md`, and prohibited claims forbids
  inventing capabilities. Produced by Haiku on the first real generation run.
- `built for small creators`
  An INVENTED claim about another product, which is why this survives the 2026-08-26
  relaxation: observations about a competitor's workflow are allowed now, assertions
  about what their product is built for are not. We cannot support it. From the same run.
- `not built for someone running your scale`
  Same sentence as above, second half. Listed separately so a partial reuse still hits.
- `most ticketing platforms`
  A claim about a whole market we have not surveyed. Kept after the blanket
  "no competitor disparagement" rule was dropped on 2026-08-26: naming where ONE
  named platform's workflow lands is an observation and is now allowed, but
  characterizing every competitor at once is still an unsupported claim.
- `organic discovery alone`
  Restates a retired marketplace stat. No numeric or quantified marketplace claim is
  approved (see `config/positioning.md`); the marketplace is described qualitatively.

- `one thing that stands out`
  Formulaic message-2 opener the voice rules forbid.
- `community in New York`
  The voice anchor's closing clause is illustrative only. Prospecting is national and
  no local-community claim is approved anywhere.

### Added 2026-09-01 from the SDR copy spec

Marketing polish, §2. Each is named in the spec as the register we are trying to leave.

- `excited to`
  Marketing voice. The spec's test is whether you would say it on the phone.
- `reaching out because i was impressed by`
  Flattery with no specific object, which §2 bans outright.
- `in today's competitive landscape`
  Filler that says nothing about this prospect.
- `love what you're building`
  The spec's own example of a generic compliment. A compliment must name a specific
  thing: the room, the city, a booked act.

Softeners, §9. These exist to apologise for the ask, and the spec bans the whole family.

- `no worries if not`
- `totally understand if this isn't a priority`
- `if this isn't a priority`
- `sorry to bother`
- `apologies for the interruption`

Breakup theatrics, §8. Email 3 is one line and closes the loop; it does not perform.

- `before i close your file`
- `one last time`
- `last attempt`
- `i'll stop reaching out`

## Regex

- `\b(where\s+we\s+(add|help|drive|deliver)|add(s)?\s+the\s+most|biggest\s+(lift|difference|impact|gain)|most\s+valuable|the\s+most\s+value)\b`
  **Ranking the offer elements** (2026-09-11). Shape 2B read "the marketing side is
  usually where we add the most", flagged by the person running outbound as untrue, and
  the model had invented its own variants ("biggest lift", "usually where organizers see
  the biggest difference") — 8 of 36 emails on the first real list carried some form of
  it. Two faults in one: it is a performance claim about relative results, which the
  retired-stats rule forbids, and ranking the bundle undercuts a bundle that is approved
  precisely because it is unquantified and undifferentiated. Name the elements neutrally
  or leave them out.
- `\btext[- ]?blast`
  **A customer-specific detail stretched into a product claim** (2026-09-11).
  `positioning.md` mentions Posh text blasts in exactly one place — inside the Caché Life
  case study, as something that improved *their* marketing conversion. It is not listed
  as a general capability. Real copy twice framed it as one: "having your guest list and
  text blasts in the same place as ticketing" to a run club, and "text blasts to your own
  list built right into the platform". Both passed every other check, because the figures
  they cited were cleared and nothing else tripped.
  **If text blasts become an approved capability, delete this entry** — it is banned
  because it is unapproved, not because it is untrue. Until then, a detail that belongs
  to one customer's story must not be recycled as a feature for everyone.
- `marketplace[^.]{0,40}\b(automatically|automatic)\b`
  **Outcome promise by implication** (2026-09-11). Real copy: "The marketplace brings new
  attendees to events automatically, which is usually where organizers see the biggest
  lift." `positioning.md` allows the marketplace *mechanism* — discovery by attendees
  already browsing Posh — and forbids performance claims. "Automatically" converts a
  mechanism into a guaranteed result delivered without effort, which is a performance
  claim wearing different clothes, and it is not something we control. Say "our
  marketplace can bring new attendees through discovery".
- `\bthe marketplace\b`
  **Ambiguous ownership** (2026-09-11). "The marketplace" leaves a prospect guessing which
  one is meant — theirs, the industry's, or ours. Distribution is only an advantage if it
  is identifiably OURS, so it is "our marketplace" or "the Posh marketplace". Caught in
  review on list 1914; the rule existed nowhere before, which is why the model had no
  reason to prefer either form.

- `unlike\s+(eventbrite|dice|tixr|shotgun|resident\s+advisor|ra|plots|ticketfairy|eventeny|eventnoire)`
  Direct competitor comparison, which is disparagement by construction.
- `better\s+than\s+(eventbrite|dice|tixr|shotgun|resident\s+advisor|plots|ticketfairy)`
  Same, in comparative form. Note this deliberately does NOT match the approved
  "convert 40% better than other platforms", which names no competitor.
- `(we|posh)\s+guarantee`
  Guarantees are prohibited outright, whatever follows.
- `managing events on\s+\w+.{0,30}\bworks,?\s+but`
  The cold-diagnosis opener named in the Voice anchor's this-not-that pair.
- `(huge|large|active)\s+(and\s+\w+\s+)?community\s+in\s+[A-Z]`
  Any local-community claim. National prospecting, no city-specific claim approved.
- `(will|guaranteed to)\s+sell\s+out`
  Outcome promise. "help sell out your next event?" as a question is approved; a
  statement that it will happen is not.

### Regex added 2026-09-01 from the SDR copy spec

- `\b(next|following|upcoming)\s+(season|year)\b`
  §4: the cold sequence never proposes a conversation about a future season, a renewal
  window, or next year's calendar. It asks one present-tense question. Timing talk is
  **reply-triggered only** — when a prospect says they are locked in, that is where the
  future-planning thread starts, and it lives in the reply handler, not here.
- `\brenewal\s+(window|date|period)\b`
  Same rule, the other phrasing.
- `\b(rev(enue)?[- ]?share|take[- ]?rate|per[- ]?ticket fee)\b`
  §5: incentives stay qualitative. We may signal there is real room to go beyond
  standard terms; we may never name a rate. Overlaps `check_commercial_terms`, kept
  because a phrase ban is legible to a human reading this file.
- `\b(guarantee|minimum)\s+(of\s+)?\$?\d`
  A quantified floor is a commercial term, which belongs on the call.
