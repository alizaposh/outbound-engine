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

**Removed 2026-08-26: `any opportunity to compare what posh could put together`.** It was
banned on AE feedback (Ashley: "reads like the spam I get") and has been un-banned by an
explicit call from the person running outbound: the phrasing is acceptable and appears in
the sales team's own live email. Recorded rather than quietly dropped, so the reversal is
visible if the AEs raise it again. **The vague "worth a ..." family stays banned** and is
a separate rule: that one is a non-offer, not a stiff offer.

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
- `worth\s+a\s+(quick\s+|short\s+)?(conversation|chat|call|comparison|look)\b`
  The vague-ask CTA family. Was a literal for "worth a quick conversation", which
  missed siblings: "worth a quick comparison" and "worth a conversation about whether
  that pencils out" both shipped in real runs. The CTA must be a concrete offer. Note
  this matches only the "worth a ..." framing, so "happy to put together a tailored
  comparison, want me to?" is untouched. Hard FAIL, never auto-repaired: rewriting a
  CTA is editorial, not mechanical.
- `(will|guaranteed to)\s+sell\s+out`
  Outcome promise. "help sell out your next event?" as a question is approved; a
  statement that it will happen is not.
