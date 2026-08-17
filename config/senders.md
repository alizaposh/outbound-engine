# Config: Senders

Maps each Smartlead sending mailbox to the first name that signs its emails. The
assembly step (`scripts/assemble.py`) looks up the mailbox a campaign will send from
and appends the sign-off in code. The model never writes a sign-off.

> ## ⚠️ PLACEHOLDER DATA. NOT SAFE FOR A LIVE SEND.
>
> Every row below is a placeholder. The real sender personas are part of the mailbox
> plan, which is gated on Smartlead setup (Phase 1). **Replace every
> `PLACEHOLDER_NAME` and every example address with real sender identities before any
> live send.** Signing a real prospect with a placeholder name misrepresents the
> sender, which the golden rules and CAN-SPAM both prohibit.

## Mailbox to sender

| mailbox                          | first name         |
|----------------------------------|--------------------|
| placeholder-1@example.invalid    | PLACEHOLDER_NAME_1 |
| placeholder-2@example.invalid    | PLACEHOLDER_NAME_2 |
| placeholder-3@example.invalid    | PLACEHOLDER_NAME_3 |

The addresses use `.invalid`, a reserved TLD that can never resolve, so a row that
reaches production by accident fails loudly instead of half-working.

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

## Open: when the mailbox is assigned
`instructions/campaign-creation.md` currently assigns mailboxes at campaign-creation
time, which happens *after* generation and approval. Assembly needs the mailbox
*during* generation, to know whose name to sign. The recommended fix is to assign the
mailbox at generation time, store it with the prospect, and have campaign creation
honor that assignment rather than re-deciding. Not yet implemented, so for now the
caller passes the mailbox explicitly.
