# Instruction: Prospect Research

**Purpose:** Assemble a short, factual picture of each prospect and their company
*before* writing any copy, so messages are specific rather than generic.

## Inputs available
- HubSpot contact + associated company record.
- Any lead-source fields (Google Sheet / CSV columns provided with the request).
- The campaign brief (what problem/offer this campaign is about).

## What to pull for each prospect
- **Person:** first name, last name, job title, seniority, likely responsibilities.
- **Company:** name, industry, rough size, anything in HubSpot notes/properties that
  signals fit or a relevant trigger.
- **Relevance angle:** one sentence connecting *this person's likely priority* to the
  campaign's problem/offer. This is what makes the email specific.

## Rules
- Use only information you actually have. **Do not invent** facts, metrics, mutual
  connections, or events. If a field is missing, work with what's present.
- Do not compile personal data beyond what's needed to write a relevant B2B message.
- Keep the research per prospect to a compact structured note (a few fields), because
  it will be fed into the generation step at volume — keep it cheap.

## Output (per prospect)
A small structured record, e.g.:
```
{ "relevance_angle": "...", "title_context": "...", "company_context": "...",
  "notable_signal": "..." }
```

## TODO / [FILL IN]
- List the specific HubSpot properties that matter for *your* ICP (e.g. lifecycle
  stage, industry, a custom "use case" field) so research keys off the right signals.
