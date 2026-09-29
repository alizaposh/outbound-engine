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
- **Subject on message_1 only.** Messages 2 and 3 are threaded replies that inherit
  the thread subject, so they carry no `subject` field. A failed contact must thread
  exactly like a normal one.
- **It must pass the validator on its own terms**: no dashes, a 2 to 7 word lowercase
  subject on message_1, no banned CTA family, no quantified commercial terms, at most
  one stat across the sequence (this copy uses none), and it ends at the CTA so
  `scripts/assemble.py` can append the sign-off and footer.
- **A row using this copy is never a success.** The runner marks it
  `GENERATION_FAILED_FALLBACK` and keeps `generation_error` populated. Do not let it
  read as normal output.

## The copy

Rewritten 2026-08-25 against the sales-team rules. Message 1 asks the generic setup
question and names the offer without quantifying it. Message 2 uses the approved
**"here's the simple version" outcome list** shape (§4 of
`instructions/message-generation.md`), which is the sanctioned exception to one idea per
email: outcomes, not features, kept scannable. Message 3 is a short breakup that offers
to close the thread rather than pitching again.

What the rewrite fixed, so it does not creep back:
- The old message 1 opened with "whether there's an opportunity to compare what Posh
  could put together in a custom proposal" — the stiff-pitch CTA AEs flagged as reading
  like AI and inbox spam. It escaped the banned literal only by saying "there's" instead
  of "any".
- The old message 2 said "firefighting through it", the exact phrase §5 names as an AI
  tell (_West Coast Makers flagged it_).
- The old message 3 asked to see "what a custom proposal would look like", the same
  banned construction.

Known WARN: message 2 runs 101 words against the 45 to 90 target, because the
five-outcome list is long. Length is a target and never a gate, and this shape is
deliberately a list. Drop a bullet or two if you want it inside the target.

```json
{
  "message_1": {
    "subject": "your ticketing setup",
    "body": "Hey %FIRST_NAME%,\n\nHope this finds you well! Reaching out to see if you're locked in on your current ticketing setup, or open to seeing what else is out there?\n\nWe've been putting together very competitive offers this year, all focused on helping organizers drive better reach, earlier conversions, and generating extra revenue with dedicated account support, financial incentives, marketing push and more.\n\nLet me know if you're open to connecting, would love to hear more about your plans this year and see what we can bring to the table!"
  },
  "message_2": {
    "body": "Hey %FIRST_NAME%,\n\nI know you may still be figuring out whether Posh is relevant for what you're building, so here's the simple version. Organizers usually come to us when they want to:\n\n- Sell more tickets\n- Reach more of the right people\n- Own their attendee community\n- Make check-in, payouts, promo, and event setup easier\n- Build a more repeatable event business\n\nIf any of those are priorities, it'd probably be worth pulling together a quick comparison. Happy to show you what other organizers are doing on Posh and where it may or may not fit, want me to?"
  },
  "message_3": {
    "body": "Hey %FIRST_NAME%,\n\nShould I close this out for now, or would it still be helpful to grab 15 minutes and see where Posh could support? Totally fine either way, just didn't want to lose the thread."
  }
}
```

## This copy now SHIPS WITHOUT REVIEW (2026-09-24)

It used to land in the review sheet unapproved, so a human saw every fallback before it
went out. `export_review.AUTO_APPROVE_STATUSES` now includes
`GENERATION_FAILED_FALLBACK`, on the reasoning that this file is already human-written
and human-reviewed -- re-approving it per contact was a gate with no reader.

Two consequences to keep in mind when editing below:

1. **A mistake here reaches prospects directly.** There is no longer a person between
   this file and the send. Treat an edit like a production change.
2. **Every fallback contact in a run receives an IDENTICAL email**, one body per sender.
   That is tolerable at the 4.9% rate the 1,314-contact round produced and is not
   tolerable at 30%, which is why `run_generation.py` warns above 10%. If the rate
   climbs, fix generation -- do not rewrite this file to be more personal, because it
   has no contact data to personalise with beyond the greeting.

The greeting is templated: `%FIRST_NAME%` is replaced per contact, falling back to
"there" when the name is missing. Keep that placeholder in any new copy -- all 64
fallbacks in the first large round had a name on file and would otherwise have opened
"Hey there," to someone whose name we knew.
