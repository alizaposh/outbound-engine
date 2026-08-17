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

## Literal

- `strategic positioning on the marketplace`
  Invented feature. Appears nowhere in `positioning.md`, and prohibited claims forbids
  inventing capabilities. Produced by Haiku on the first real generation run.
- `built for small creators`
  Competitor disparagement, and an invented claim about other platforms. From the same
  run.
- `not built for someone running your scale`
  Same sentence as above, second half. Listed separately so a partial reuse still hits.
- `most ticketing platforms`
  Disparagement opener. Any sentence starting this way is characterizing competitors
  rather than winning on Posh's strengths.
- `organic discovery alone`
  Restates the approved 13% marketplace stat in unapproved wording. The stat must
  appear only as written in `positioning.md`.

## Regex

- `unlike\s+(eventbrite|dice|tixr|shotgun|resident\s+advisor|ra|plots|ticketfairy|eventeny|eventnoire)`
  Direct competitor comparison, which is disparagement by construction.
- `better\s+than\s+(eventbrite|dice|tixr|shotgun|resident\s+advisor|plots|ticketfairy)`
  Same, in comparative form. Note this deliberately does NOT match the approved
  "convert 40% better than other platforms", which names no competitor.
- `(we|posh)\s+guarantee`
  Guarantees are prohibited outright, whatever follows.
- `(will|guaranteed to)\s+sell\s+out`
  Outcome promise. "help sell out your next event?" as a question is approved; a
  statement that it will happen is not.
