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

## Open: when the mailbox is assigned
`instructions/campaign-creation.md` currently assigns mailboxes at campaign-creation
time, which happens *after* generation and approval. Assembly needs the mailbox
*during* generation, to know whose name to sign. The recommended fix is to assign the
mailbox at generation time, store it with the prospect, and have campaign creation
honor that assignment rather than re-deciding. Not yet implemented, so for now the
caller passes the mailbox explicitly.
