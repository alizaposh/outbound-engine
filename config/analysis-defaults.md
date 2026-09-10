# Config: Campaign Analysis Defaults

Tunable values for the weekly campaign review. **This file is the source of truth.**
`scripts/campaign_report.py` parses the block below; it does not restate these numbers.

The logic these feed is in `instructions/campaign-analysis.md`. Read the cadence section
there before tuning anything here.

## Canonical values

```
# Below this many DELIVERED emails, the report prints counts only and refuses to show a
# reply rate. It is not a display preference -- it is the whole point of the report.
#
# A cold reply rate sits near 2-5%. At n=25 with one reply, "4%" has a 95% interval of
# roughly 0-20%: the number is indistinguishable from zero and from triple itself, yet it
# reads as a fact and invites a copy change. The first campaign is 25 contacts, so this
# threshold WILL fire on the first review, and that is the correct outcome.
#
# 200 is where the interval narrows enough to tell "working" from "not working" -- it is
# NOT enough to compare two variants, which needs thousands. See the note below.
min_delivered_for_rate: 200

# Confidence level for every interval printed. 0.95 -> the familiar 95% interval.
confidence: 0.95

# Which intents count as a positive outcome. Contested on purpose: this is the line the
# sales team is most likely to want moved, which is why it is config and not code.
positive_intents: [interested, question]

# Which count as a negative outcome.
negative_intents: [not_interested, objection, not_qualified, asked_to_stop]

# Neither: a deferral is not a loss, it is a date. Reported separately so a campaign that
# is mostly "come back in Q1" is not scored as a failure.
neutral_intents: [not_now, wrong_contact]

# NOT REAL REPLIES. Excluded from every reply count and every rate.
# Smartlead's own reply_count includes these, which is why its dashboard reads higher
# than this report. An auto-responder is not a human answering.
machine_intents: [out_of_office, automated_reply]
```

## Tuning notes

- **`min_delivered_for_rate = 200` is a floor for "is this working at all", not for
  "which copy is better".** Distinguishing a 2% reply rate from a 5% one at 95%
  confidence needs sample sizes in the low thousands per variant. The report will print a
  rate at 200 and an interval alongside it; **the interval is the part to read.** If two
  campaigns' intervals overlap, the difference between them is not evidence, however
  different the point estimates look.
- **Raising it is safe. Lowering it is not**, and not because of the code — the code
  handles n=1 fine. Lowering it means showing rates that cannot support the decisions
  people will make from them, which is the specific failure this file exists to prevent.
- **Rates are computed on DELIVERED, not sent.** Bounces never reached a human, so
  counting them in the denominator understates the rate by the bounce rate.
- **`positive_intents` excludes `not_now` deliberately.** A deferral with a captured
  return date is a real outcome and often becomes a meeting later, but scoring it as
  positive today would flatter the copy and hide a campaign that is mostly getting
  polite postponements.
- **Adding an intent here means adding it to `INTENTS` in `scripts/reply_check.py` too.**
  The report asserts the two agree at startup and refuses to run if they do not, because
  a silently unclassified intent would be dropped from every total.
