# Instruction: Campaign Analysis

**Purpose:** Read campaign performance from Smartlead and turn it into reusable
improvements, not one-off tweaks.

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
