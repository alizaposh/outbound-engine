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
| Zach       | I'm Zach, I help organizers get set up on Posh. |
| Zach       | I'm Zach, I manage partnerships at Posh. |

- **It belongs at the OPENING of email 1**, not the end. Placement is set by the voice
  anchor in `instructions/message-generation.md`.
- One line per sender, used across all campaigns for now.
- Zach's differs on purpose: he is the SDR and meeting owner, so "I help organizers get
  set up" fits, while Carl and Brooke are partnerships correspondents.

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
  own emails, and every meeting books with Zach regardless
  (`config/meeting-routing.md`). Carl and Brooke are correspondents, not meeting owners.

## Resolved 2026-08-31: when the mailbox is assigned
The mailbox is assigned at **generation** time (the caller passes `--mailbox`), and
`scripts/run_generation.py` now records `sender` and `mailbox` on every output row.
`scripts/create_campaign.py` **honors** that assignment rather than re-deciding it: it
refuses a CSV that mixes senders and refuses mailboxes belonging to anyone but the person
who signed the copy.

This matters more than it looked. A Smartlead campaign **rotates across its assigned
mailboxes**, so one campaign holding copy from three senders would send an email signed
"Carl" from Brooke's mailbox. Run campaign creation once per sender.
