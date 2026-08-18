# Config: Generation-failure fallback copy

The static 3-email sequence used when generation fails for a contact **after every
retry is exhausted** (`generate_with_retry` in `scripts/run_generation.py`). It exists
so a failed contact produces something usable instead of an empty row.

> **This file is deliberately NOT in `RULEBOOK_FILES`.** `scripts/run_generation.py`
> feeds `config/positioning.md`, `config/personas.md`, and
> `instructions/message-generation.md` into the generation prompt verbatim. This copy
> must never reach the model: a ready-made sequence sitting in the prompt is something
> the model would start echoing, which would quietly template real output. It is read
> only on the failure path.

## Rules this copy must keep

- **No contact-specific data of any kind.** No first name, company, job title,
  vertical, or platform. Generation failed, so nothing about this prospect was
  established. It has to be safe for the nameless `info@` contacts, which is exactly
  who has been failing.
- **Name no platform**, for the same reason the branch-2 no-platform fallback names
  none: a guess proves the sender did not look. See `config/personas.md` (Branch 2)
  and the "When the current platform is unknown" pattern in
  `instructions/message-generation.md`, which this copy is derived from.
- **It must pass the validator on its own terms**: no dashes, subjects 2 to 7 words
  lowercase, no banned CTA family, no quantified commercial terms, at most one stat
  across the sequence (this copy uses none), and it ends at the CTA so
  `scripts/assemble.py` can append the sign-off and footer.
- **A row using this copy is never a success.** The runner marks it
  `GENERATION_FAILED_FALLBACK` and keeps `generation_error` populated. Do not let it
  read as normal output.

## The copy

Message 1 asks the generic setup question. Message 2 develops dedicated account
support, one concrete capability. Message 3 is the breakup and carries distribution as
the remaining facet. Same structure the generated sequences follow.

```json
{
  "message_1": {
    "subject": "your ticketing setup",
    "body": "Hey there,\n\nHope this finds you well. Reaching out to see if you're locked in on your current ticketing setup, or whether there's an opportunity to compare what Posh could put together in a custom proposal.\n\nWe've been putting together very competitive offers this year, all focused on helping organizers drive better reach, earlier conversions, and generating extra revenue with dedicated account support, financial incentives, marketing push and more.\n\nWould love to hear about your plans this year and see what we can bring to the table. Open to connecting?"
  },
  "message_2": {
    "subject": "dedicated support on posh"
  , "body": "Hey there,\n\nDedicated account support is the part of Posh that organizers tend to notice first. Every organizer works with a real person rather than a support queue: someone who knows your calendar, helps get a launch in front of the right attendees, and makes sure payouts and guest lists behave on event day.\n\nFor a lean team that is the difference between running the night and firefighting through it, and it means one person to call when something changes late.\n\nHappy to walk through what that looks like for your events. Want me to put something together?"
  },
  "message_3": {
    "subject": "last note from me",
    "body": "Hey there,\n\nLast note from me. The other piece is distribution: the Posh marketplace puts your events in front of attendees who are already looking for something to go to, on top of the promotion you are already doing.\n\nIf you ever want to see what a custom proposal would look like, just say the word. Either way, good luck with the season."
  }
}
```
