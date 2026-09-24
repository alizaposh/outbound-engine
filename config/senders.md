# Config: Senders

Maps each Smartlead sending mailbox to the first name that signs its emails. The
assembly step (`scripts/assemble.py`) looks up the mailbox a campaign will send from
and appends the sign-off in code. The model never writes a sign-off.

**Real sender identities, filled in 2026-08-26** from the Smartlead account
(`GET /api/v1/email-accounts`). Every row's first name matches that mailbox's Smartlead
`from_name` exactly, which is what the first rule below requires. All 12 mailboxes had
`warmup: ACTIVE` when this was recorded.

## Mailbox to sender

3 sender identities across 4 warmed domains, 12 mailboxes.

| mailbox                            | first name |
|------------------------------------|------------|
| carl.newmark@vibeposhvip.com       | Carl       |
| carl.newmark@coreposhvip.com       | Carl       |
| carl.newmark@poshvippulse.com      | Carl       |
| carl.newmark@poshviphub.com        | Carl       |
| brooke.carrobis@vibeposhvip.com    | Brooke     |
| brooke.carrobis@coreposhvip.com    | Brooke     |
| brooke.carrobis@poshvippulse.com   | Brooke     |
| brooke.carrobis@poshviphub.com     | Brooke     |
| zach.hickman@vibeposhvip.com       | Zach       |
| zach.hickman@coreposhvip.com       | Zach       |
| zach.hickman@poshvippulse.com      | Zach       |
| zach.hickman@poshviphub.com        | Zach       |

Smartlead `from_name` is the full name ("Carl Newmark"); the sign-off is first-name
only ("Carl"), which is the same identity written the way a person signs a short email.
The rule that the sign-off must match the `From` name is about *identity*, not about
reproducing the string.

**Keep this in sync with Smartlead.** These rows are a copy of live account state, so a
mailbox added, removed, or renamed there must be changed here too. An unmapped mailbox
aborts the batch (see Rules), which is the intended way to find out.

## Departed senders — no NEW contacts, existing threads unchanged

Names listed here keep their rows in the table above and are **excluded from being
assigned new contacts**. Both halves matter:

- **Excluded from assignment**, because a departed rep must not be introduced to anyone
  new. Left unlisted, the 1,400-lead round would have given Brooke ~466 contacts.
- **Kept in the mailbox table**, because a prospect she already wrote to is mid-thread
  with *her*. The sign-off on that thread, and any reply in it, is still hers — we
  cannot retroactively make somebody else the author of an email already sent.

| Departed | Since | Note |
|---|---|---|
| Brooke | 2026-09-24 | Left the company. Not a meeting owner in `meeting-routing.md`, so no booking ever reached her. Her campaign `Aliza-2026-09-16-Brooke` was **PAUSED 2026-09-24** with 45 closing emails unsent — see below. |

**Her four mailboxes now display "Caroline Reyda" over `brooke.carrobis@…` addresses**, a
stopgap while new mailboxes are purchased. **They are NOT in use and should not be**, for
two reasons:

1. **A display name that disagrees with the address is a phishing pattern**, and spam
   filters weight it. On cold mail from domains with ~500 lifetime sends, that is not a
   cosmetic issue. It buys two days of calendar time on a 1,400-contact round (5.8 days
   for email 1 instead of 3.9) and costs a deliverability signal on a third of it.
2. **It made a live campaign incoherent.** 45 queued closing emails would have arrived as
   "Caroline Reyda" in the From, signed "Brooke" in the body, to prospects who had had
   two emails from Brooke. Worse than either name alone: it reads as a mistake or a
   spoof. That is why the campaign is paused rather than left to finish — the closer is
   a breakup line needing no reply, so not sending it is the smallest of the bad options.

**Caroline still receives meetings from every round** — she is in the
`meeting-routing.md` rotation — so nothing about this stopgap was needed to get her
meetings. When real mailboxes arrive, add her with a matching address and name, remove
this section, and the round-robin picks her up as a sender automatically.

**When her mailboxes are reassigned**, update the table above to the new address and
name, remove the row here, and reassign `outbound_sender` on her contacts — that
property is write-once precisely so a prospect keeps hearing from one person, and the
premise fails when that person has gone.

## Adding a sender as the team grows

**This table is the source of truth, and as of 2026-09-17 the code derives from it.**
`slack_intake.known_senders()` and `split_by_sender.senders_and_mailboxes()` both read
these rows; neither holds a list of names. They used to, and that fails in the worst
available way for a growing team: the new name goes into the Slack dropdown, the parser
does not recognise it, and the rep's explicit "all from me" request **silently falls back
to a split** with a reply that reads like a success.

Four steps, in order:

1. **Connect and warm the mailbox in Smartlead.** Until warmup is ACTIVE it should not
   carry a campaign. `GET /email-accounts` reports `warmup_details.status`.
2. **Add the row here.** First name only in the right column, matching that mailbox's
   Smartlead `from_name` exactly (the rule above). This is the step that makes the engine
   aware of them — verified by temporarily adding a fourth sender: the parser accepted the
   new name immediately and the "not one of..." message updated itself.
3. **Add the name to the Slack form dropdown** ("Who should this come from"). The only
   manual duplication left, because the form lives in Slack Workflow Builder and no API
   writes it.
4. **Check they have a HubSpot owner record with a matching FIRST NAME.**
   `split_by_sender.owner_to_sender()` resolves owner ids by matching first names at
   runtime — the same pattern `excluded_owners` uses in `pre-send-defaults.md`, and for
   the same reason. Without a match the sender can still SEND, but rule 2 cannot apply, so
   their own HubSpot-owned contacts will be routed to a colleague. The script prints
   `no HubSpot owner matches <name>` when this is the case; it is a warning, not an error.

**Also add them to `config/meeting-routing.md`** with their booking link, or replies from
their prospects fall back to the fallback sender's calendar.

## Email-1 intro line

The self-introduction email 1 opens with, one per sender identity. **Supplied to the
generator per run** (`research_note` in `scripts/run_generation.py` passes the sending
mailbox's line); the model must never pick one. It used to live as a three-row table in
the rulebook, which the model read as a menu: a 34-contact run came back with the wrong
name in 18 of 34 emails, signing "Carl" while the body said "I'm Brooke".

**A sender may have SEVERAL rows.** One is picked per contact, so the same mailbox does
not open every email with the identical sentence. **Every row for a sender must name that
sender**, and `assemble.py` asserts it: when these lived as a free menu in the rulebook, a
34-contact run signed "Carl" while the body said "I'm Brooke" in 18 of 34 emails. Variety
is allowed inside a sender's own lines and nowhere else.

| first name | intro line |
|------------|------------|
| Carl       | I'm Carl, I run partnerships at Posh. |
| Carl       | I'm Carl, I manage partnerships at Posh. |
| Brooke     | I'm Brooke, I run partnerships at Posh. |
| Brooke     | I'm Brooke, I manage partnerships at Posh. |
| Zach       | I'm Zach, I run partnerships at Posh. |
| Zach       | I'm Zach, I manage partnerships at Posh. |

- **It belongs at the OPENING of email 1**, not the end. Placement is set by the voice
  anchor in `instructions/message-generation.md`.
- One line per sender, used across all campaigns for now.
- **All three senders now use the same two lines** (changed 2026-09-14). Zach's used to
  read "I help organizers get set up on Posh", which fit while he was the SDR and the
  single meeting owner. He was promoted to AE, so he is a partnerships correspondent like
  Carl and Brooke and introduces himself the same way. Nothing in the copy should still
  imply he occupies a different role.

## Rules
- **The sign-off name must match the mailbox's `From` name.** A signature that
  disagrees with the sending identity is a deliverability signal and a compliance
  problem, not a cosmetic mismatch.
- **An unmapped mailbox is a hard failure.** Assembly aborts the batch rather than
  signing with a blank, a guess, or a bare "Posh". Add the mailbox here first.
- **One row per mailbox.** Duplicate mailbox entries abort the batch too, since the
  correct name would be ambiguous.
- Names are first-name only. The line "Posh" is appended after it automatically, so
  do not include it here.
- **Which persona sends does not change who takes the meeting.** All three sign their
  own emails, and each sender's meetings land on their OWN calendar
  (`config/meeting-routing.md`). Changed 2026-09-14: meetings used to route to Zach
  regardless of sender, because he was the SDR and the only person taking them. He was
  promoted to AE, so all three are correspondents who take their own meetings.

## Resolved 2026-08-31: when the mailbox is assigned
The mailbox is assigned at **generation** time (the caller passes `--mailbox`), and
`scripts/run_generation.py` now records `sender` and `mailbox` on every output row.
`scripts/create_campaign.py` **honors** that assignment rather than re-deciding it: it
refuses a CSV that mixes senders and refuses mailboxes belonging to anyone but the person
who signed the copy.

This matters more than it looked. A Smartlead campaign **rotates across its assigned
mailboxes**, so one campaign holding copy from three senders would send an email signed
"Carl" from Brooke's mailbox. Run campaign creation once per sender.

## The sending mailboxes are engine-only and unwatched (confirmed 2026-09-09)

No forwarding is configured on any of the 12 mailboxes, so a prospect's reply lands in a
`vibeposhvip.com` / `coreposhvip.com` / `poshviphub.com` / `poshvippulse.com` inbox that
**no human reads**. Smartlead reads them over IMAP; `scripts/reply_check.py` classifies
and queues them.

**This is the better arrangement, not an oversight.** Carl, Brooke and Zach are real Posh
employees with HubSpot seats (`carl@posh.vip`, `brooke@posh.vip`, `zach@posh.vip`). If
these mailboxes forwarded to them, a prospect reply would reach a human **before** the
review queue — and that human could answer directly, bypassing classification, the queue,
the HubSpot write-back and the draft review. Two people would be answering the same
prospect while the engine had no idea. Not forwarding removes that entirely.

**The dependency it creates, and the thing that covers it.** The review queue is the
**only** path from a prospect's reply to a person. If the engine stops — routines paused,
machine asleep, token expired — replies accumulate in inboxes nobody opens, and a warm
prospect goes unanswered with no signal. That is precisely why the Slack heartbeat posts
on quiet runs: **silence in the channel means broken, not calm**
(`instructions/scheduled-tasks.md`).

**If that ever changes and forwarding is switched on**, the coordination question comes
back and needs an answer first: who replies, the human or the queue, and how does each
know what the other did.
