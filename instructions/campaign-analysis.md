# Instruction: Campaign Analysis

**Purpose:** Read campaign performance from Smartlead and turn it into reusable
improvements, not one-off tweaks.

## The script: `scripts/campaign_report.py` (built 2026-09-10)

```bash
python scripts/campaign_report.py                        # active campaigns
python scripts/campaign_report.py --include-completed    # everything
python scripts/campaign_report.py --campaign 3921033     # one
```

Read-only. Not in the heartbeat — this is a report a person sits down and reads, not a
job that keeps state correct. Thresholds and the intent buckets live in
`config/analysis-defaults.md`.

### It refuses to quote a rate below 200 delivered, and that is the point

A cold reply rate sits near 2–5%. On a 25-contact campaign, one reply is "4%" — a number
whose 95% interval runs from roughly 0% to 20%. It cannot be told apart from zero, or
from triple itself. But it reads as a fact, gets compared against the next campaign's
"8%", and produces a copy change built on a single email. **A report that prints that
number is worse than no report**, because it manufactures confidence in exactly the
decision it exists to inform.

So below the floor it prints counts, shows the interval to make the uncertainty concrete,
and says how many more sends are needed. **Expect this to fire on the first review** —
the first campaign is 25 contacts. That is the correct output, not a missing feature.

- **200 buys "is this working", not "which copy is better".** Separating a 2% rate from a
  5% one at 95% confidence needs sample sizes in the low thousands **per variant**.
- **Every rate carries a Wilson interval, and the interval is the part to read.** Two
  campaigns whose intervals overlap have not been shown to differ, however far apart the
  point estimates look. Wilson rather than the textbook formula because the normal
  approximation returns [0%, 0%] for zero replies — "certainly zero" — which is both
  wrong and the most dangerous thing this report could print.
- **What to do at low volume instead: read the replies themselves.** At n=25 the *text*
  of one reply carries more information than any rate computed from it. That is how the
  incumbency misclassification was found, and no aggregate would have surfaced it.

### Two things it reports that the Smartlead dashboard cannot

- **A human reply rate.** Smartlead's `reply_count` includes auto-responders. This
  excludes `out_of_office` and `automated_reply` via our own classification, so the
  number means "people answered" rather than "mail came back". Rates are computed on
  **delivered**, not sent — a bounce never reached a human.
- **Outcome, not volume.** Replies split positive / negative / deferred from
  `outbound_reply_intent`, so a campaign whose replies are all declines is not scored as
  a success. `not_now` is deliberately *deferred* rather than positive: scoring
  postponements as wins would flatter the copy.

### The reconciliation line is the one to act on

Replies are counted from HubSpot intents, so **a lead with no HubSpot contact contributes
nothing** and its reply is invisible. The report therefore cross-checks our count against
Smartlead's and prints `** UNACCOUNTED REPLIES **` when Smartlead saw more than we
classified. Two causes: a lead with no HubSpot contact, or a reply `reply_check` never
processed. Resolve it before trusting any other number on the page.

## Metrics to pull (from Smartlead, the source of truth for sending/replies)
- Positive replies, negative replies, total reply rate.
- Bounce rate (watch for deliverability trouble).
- Unsubscribe / opt-out activity.
- Per-mailbox and per-domain health.

## Outcome metrics (your project's real signals)
- **Meetings booked per week** (primary outcome; stretch target ~10/week).
- **AE adoption:** how many AEs request campaigns and how often.

## Turn results into rules
- Compare across campaigns and messaging approaches.
- When one approach clearly wins or loses, encode the lesson as a rule in
  `instructions/message-generation.md`, `config/personas.md`, or `config/positioning.md`.
- Flag deliverability problems immediately (pause mailboxes/domains as needed).

## Cadence: WEEKLY (decided 2026-09-02)

One review per week, feeding the next week's campaigns.

**Why weekly and not faster.** The sequence itself spans a week — email 2 lands 3 days
after email 1 and email 3 four days after that — so a campaign has not finished speaking
until roughly day 7. Reading reply rates on day 2 measures email 1 alone and invites a
copy change based on a third of the sequence. Weekly is the first point at which a batch
has actually run.

**Why not slower.** Deliverability is the exception and does not wait for the review:
**bounce rate and spam signals get acted on the day they appear**, per "Flag deliverability
problems immediately" above. A weekly cadence governs the *copy and targeting* loop, not
the safety loop.

### What the weekly review is for

- Compare the week's campaigns against previous ones and **turn what won or lost into a
  rule**, not a one-off edit. The rule goes in `instructions/message-generation.md`,
  `config/personas.md`, `config/positioning.md`, or `config/banned-phrases.md` — whichever
  owns that decision.
- **Sample size before conclusion.** A 34-lead batch produces single-digit replies. That
  is enough to catch something badly wrong and **not** enough to declare one opener better
  than another. Say which of the two you are doing.
- Check `outbound_sender` performance separately once more than one sender is live: a
  persona difference is easy to mistake for a copy difference.

### What it is NOT

Not a substitute for the daily heartbeat. The three scheduled routines
(`instructions/scheduled-tasks.md`) handle replies, unsubscribes and bounces every
weekday; this review reads the *aggregate* and changes the rules. A weekly cadence for
analysis does not mean a weekly cadence for handling a prospect who replied.
