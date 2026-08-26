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

## Regex

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
