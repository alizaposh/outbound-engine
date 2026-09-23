# AI Outbound Email Engine

**What it is.** An automated outbound system that takes a HubSpot list, writes a
personalized 3-email sequence per contact, sends from warmed mailboxes, and handles
every reply — classifying it, updating HubSpot, and drafting a response for approval.

**What stays human.** Nothing sends without a person approving the exact wording. The
engine drafts, files, and schedules; it does not decide what to say to a prospect.

---

## How a campaign happens

| # | Step | Who |
|---|---|---|
| 1 | Rep submits a HubSpot list in Slack | Rep |
| 2 | Every contact is filtered against 10 eligibility gates | Engine |
| 3 | 3 emails written per contact, checked against a copy rulebook | Engine |
| 4 | Copy reviewed and approved row by row in a Google Sheet | **Outbound owner** |
| 5 | Campaign built in Smartlead and launched | Engine builds, human launches |

Picked up within 5 minutes of submission. A rep gets the review link back in the same
Slack thread.

---

## Every reply type has a defined path

This is the part that matters. There are ten possible classifications and none of them
is a dead end.

| Reply means | HubSpot status | Re-engage date set | Goes to a human |
|---|---|---|---|
| **Interested** | Replied | — | Yes, with booking link |
| **Question** | Replied | — | Yes, with booking link |
| **Objection** (named a competitor) | Replied | — | Yes |
| **Not now** | Replied | **Their date, or +90 days** | Yes |
| **Not interested** | Replied | **+180 days** | Yes |
| **Not qualified** (no ticketed events) | Disqualified | — | Yes |
| **Wrong contact** | Disqualified | — | Yes |
| **Asked to stop** | Opted out + suppressed | Never | Yes |
| **Out of office** | *unchanged* | **Sequence resumes on their return date, or +14 days** | No |
| **Automated reply** | *unchanged* | Sequence resumes immediately | No |

**Worked example.** A prospect replies *"we're under contract with DICE until next
summer."* The engine:

1. Classifies it **not now** (a timing answer, not a rejection)
2. Writes **`Recycle After` = the date they named** — they re-enter outreach then, automatically
3. Writes **`Current Competitor` = DICE** on the contact record
4. Stops the remaining follow-ups
5. Queues a short reply acknowledging the timing for approval

Six months later a rep opens that contact and sees who they're with and when they're
free — without opening the email thread.

---

## What we record from replies

Replies are the best source of CRM data we have, so we keep it:

- **Current Competitor** — when they name what they use. Matched against our existing
  list of platforms, so an unrecognized name is flagged for a human rather than guessed.
- **Recycle After** — when they'll be ready, in their own words where they give a date.
- **Lifecycle → Disqualified** — only for a structural non-fit, e.g. "we don't run
  ticketed events." Deliberately *not* applied when they name a competitor: using
  someone else makes them a prospect, not a bad fit.
- **Reply intent** — every reply is labeled, so we can report on outcome mix, not just
  volume.

---

## Machine replies are handled separately

Roughly a third of replies are not from a person. Treating them as real replies would
waste reviewer time and stall good leads.

- **Out of office** — the sequence is paused, not ended, and restarts on the date the
  auto-reply names (or 14 days). Their status is deliberately left unchanged: being on
  holiday is not an outcome.
- **Automated replies** (ticket systems, org auto-responders, unmonitored mailboxes) —
  logged and the sequence resumes. No draft is written; no reviewer sees them.

Both are identified by *form*, not content — an org auto-responder describing its own
services is still a machine, however much its text reads like a qualification signal.

---

## Safeguards

- **Nothing sends without human approval.** The approval allowlist for automatic sending
  is empty and enforced in code.
- **Stop means stop.** An unsubscribe or "remove me" suppresses the contact permanently
  and everywhere.
- **No double-contact.** Checked daily: no contact can be in two live campaigns, and
  contacts already in a HubSpot sequence are excluded before we write to them.
- **Claims are checked.** Generated copy is validated against a list of prohibited
  claims before a human ever sees it.
- **Every activity is logged to HubSpot**, three times a day, so a rep opening a contact
  sees what we sent and when.

---

## Where it stands today (23 Sep 2026)

| | |
|---|---|
| Contacts enrolled | 247 |
| Emails delivered | 510 |
| Bounces | **0** |
| Human replies | 9 |
| Human reply rate | **1.8%** (range 0.9–3.3%) |
| Sending identities | 3 reps, 12 mailboxes, 4 domains |

The range matters more than the number: at this volume the rate tells us the system is
working, not which copy works best.

---

## Next: is the booking link the right ask?

**Today** every interested reply gets a calendar link. It is the fastest path to a
meeting and it assumes the prospect is ready to commit time to a call.

**The open question.** A booking link asks for a 30-minute commitment from someone whose
only signal was "tell me more." A lower-commitment step — pricing, a short overview, a
self-serve view of what a proposal would contain — may convert more of them, and may
convert a different *kind* of buyer: the one who wants to evaluate before they talk.

**Proposed test.** Split interested replies between the current booking link and a
self-serve alternative, measuring meetings booked and opportunities created, not clicks.

**What has to be true first, honestly:**

- **Volume.** Comparing two variants reliably needs thousands of delivered emails per
  arm. We are at 510 total. At the current rate this is a Q1 test, not a Q4 one.
- **Measurement.** We deliberately run with click tracking off for deliverability, so
  "did they click the link" is not available. The test has to be measured on outcomes in
  HubSpot — meetings booked — which the engine now records automatically.
- **A destination.** A self-serve arm needs somewhere to send people. That is a page,
  not a copy change.

**Cheaper first step.** Read the interested replies qualitatively for the next ~50 and
note how many ask a question before they would book. If most want information first, the
test is worth building. If most book, the current CTA is already right.
