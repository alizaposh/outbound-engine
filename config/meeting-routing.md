# Config: Meeting Routing

Who a booked meeting belongs to, and the link used to book it. **Read this instead of
hardcoding a name.** `instructions/reply-handling.md` drives interested replies to a
meeting; the person and link come from here, so changing the owner is a config edit in
one place rather than a search across instruction files.

## Meeting owner (single)

| Field | Value |
|---|---|
| Name | Zach Hickman |
| Role | SDR |
| Booking link | `<ZACH_BOOKING_LINK>`  ← **placeholder, fill before any live send** |

- **One owner in v1.** Every meeting from every sender persona lands with Zach. There
  is no round-robin and no territory split.
- **The booking link is a placeholder.** Sending `<ZACH_BOOKING_LINK>` to a prospect
  would be a broken email; assembly must fail loudly rather than send the placeholder.
- **Never paste a booking link into an opener.** Per `config/personas.md`, both
  personas open reply-based; a scheduling link appears only after the prospect shows
  interest.

## Sender personas vs meeting owner

These are different things and the distinction drives the open question below.

- **12 mailboxes across 4 warmed domains** (`vibeposhvip.com`, `coreposhvip.com`,
  `poshvippulse.com`, `poshviphub.com`).
- **Zach holds 3 of them.** The other **9 are separate sender personas** — a different
  human name signs those emails (mailbox → sign-off mapping in `config/senders.md`).
- So for 9 of 12 mailboxes, the person who sent the cold email is **not** the person
  who takes the meeting. That handoff needs a defined shape.

## `[CONFIRM]` Handoff model — undecided, do not assume

When a conversation starts on one of the 9 non-Zach mailboxes, which happens?

- **Option A — book onto Zach's calendar.** The sender persona stays the
  correspondent and shares Zach's booking link, introducing him as the person who'll
  run the call.
- **Option B — Zach takes over the thread.** Once a live conversation starts, Zach
  joins or takes over the reply thread and books it himself.

**Do not pick one in code, copy, or config until this is decided.** It changes the
reply copy (whose name and calendar the prospect sees), whether a third party gets
introduced mid-thread, and how the reply handler drafts an interested response. Until
it is resolved, drafts from a non-Zach mailbox that reach the meeting step go to
**human review** rather than assuming a model.

## Consumers

- `instructions/reply-handling.md` — the action map's "drive to a meeting" actions.
- `config/personas.md` — CTA guidance ("scheduling link once interested").
- `config/senders.md` — mailbox → sign-off name, which decides whether a given thread
  is a Zach mailbox or one of the 9.
