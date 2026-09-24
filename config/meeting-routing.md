# Config: Meeting Routing

Who a booked meeting belongs to, and the link used to book it. **Read this instead of
hardcoding a name.** `instructions/reply-handling.md` drives interested replies to a
meeting; the person and link come from here, so changing the owner is a config edit in
one place rather than a search across instruction files.

## Booking links: a ROUND ROBIN across the sales team (changed 2026-09-24)

**The meeting no longer belongs to whoever sent the email.** Sending identities and
meeting owners are now separate lists, because they answer different questions: who can
credibly write to a prospect (3 warmed identities) versus who has capacity to take the
call (the whole team). Tying them together meant every meeting from a Brooke campaign
landed on Brooke, whatever her calendar looked like.

| Meeting owner | Booking link |
|---|---|
| Carl | `https://meetings.hubspot.com/carl-newmark` |
| Lawrence | `https://meetings.hubspot.com/lawrence-hennessy` |
| Caroline | `https://meetings.hubspot.com/creyda` |
| Henry | `https://meetings.hubspot.com/henry377` |
| Zach | `https://meetings.hubspot.com/zach-hickman` |
| Kate | `https://meetings.hubspot.com/kate-burge` |

**Assignment is per contact and DETERMINISTIC** — a hash of their email address, not
`random()`. Re-running the reply check must hand the same prospect the same calendar; a
prospect who was shown Kate's link on Monday and Caroline's on Tuesday has watched the
company look disorganised, and the reply queue is re-read on every heartbeat.

**The draft NAMES the owner when it is not the sender.** "You can grab a time with
Caroline on our team here: <link>" rather than "with me". At one or two fallbacks a
month an unexplained calendar switch was tolerable; as the normal path across 1,400
contacts it is not. The prospect finds out at the point of booking either way — the only
choice is whether we tell them first.

**Brooke is a SENDER but not a meeting owner** (no link supplied 2026-09-24). That is
allowed and the two lists are independent, but it is worth stating out loud so it is a
decision rather than an oversight: Brooke writes to prospects and never receives their
meetings. Add a row above if that is not intended.

**Fallback meeting owner: `Zach`**. Used only when a lead has NO contact email to hash
-- a Smartlead-only lead with no HubSpot record -- and the sender is not themselves a
meeting owner. Without it such a lead gets a draft with no link at all, which is worse:
a warm prospect who cannot book is a lost meeting, where one booking with Zach is a
meeting. The reviewer is told the fallback was used.

**HubSpot's own round-robin scheduling pages would be better than this** and were
recommended first: one team link where HubSpot distributes by real availability, so a
rep who is fully booked or on leave is skipped. This list distributes blindly — it does
not know anyone's calendar. Replace the six rows with a single team link if one is
created, and this whole mechanism collapses to one row.

**The fallback NEVER applies to a named sender with no row here.** That is a config gap —
somebody added a sender to `senders.md` and forgot this file — and it affects every
contact that sender mails, so it stays a hard error.

**This replaced a single owner.** Every meeting used to route to Zach regardless of who
sent the email, because he was the SDR and the only person taking them. He was promoted
to AE on 2026-09-14, so he is a correspondent like Carl and Brooke and takes his own
meetings. **A prospect who has been corresponding with Carl should not be handed Zach's
calendar** — that was a deliberate handoff while one person owned meetings, and it is
now just confusing.

- **Which sender is looked up from the CONTACT, not the campaign.** `outbound_sender` is
  written once at enrolment and never changed, so a reply months later still resolves to
  the person who actually wrote to them. Using the campaign would break as soon as a
  contact appeared in two.
- **Links are HubSpot meetings links**, so a booking lands natively in HubSpot — which is
  what lets the native "Date of last meeting booked in meetings tool" property carry the
  date, per `config/hubspot-properties.md`. A non-HubSpot scheduler would break that.
- **Adding a sender means adding a row here.** A sender with no row is a hard error in
  `scripts/reply_check.py`: it refuses to draft rather than silently omitting the link or
  falling back to someone else's calendar. Handing a prospect the wrong person's calendar
  is worse than a draft that stops for a human.
- **Never paste a booking link into an opener.** Per `config/personas.md` the cold
  sequence is reply-based; a scheduling link appears only after the prospect shows
  interest.

## ~~Sender personas vs meeting owner~~ HISTORICAL

> **Superseded 2026-09-14.** This section works through whether a persona-fronted email
> should hand the meeting to someone else, which was the live question while Zach was the
> SDR and sole meeting owner. Each sender now takes their own meetings, so there is no
> handoff to design. Kept because the persona/mailbox reasoning above it is still
> accurate and the trade-offs are worth not re-deriving.

## Sender personas vs meeting owner (historical)

These are different things and the distinction drives the open question below.

- **12 mailboxes across 4 warmed domains** (`vibeposhvip.com`, `coreposhvip.com`,
  `poshvippulse.com`, `poshviphub.com`).
- **Zach holds 3 of them.** The other **9 are separate sender personas** — a different
  human name signs those emails (mailbox → sign-off mapping in `config/senders.md`).
- So for 9 of 12 mailboxes, the person who sent the cold email is **not** the person
  who takes the meeting. That handoff needs a defined shape.

## Handoff model: persona-fronted, Zach-owned (decided 2026-08-21)

The sending persona stays the correspondent; the meeting belongs to Zach.

- **The sending persona remains the thread correspondent.** Whoever's name signs the
  cold email keeps signing the replies. There is **no automatic mid-thread identity
  swap** — the engine never silently substitutes one human for another in a live thread.
- **On `interested` and `question` replies, the persona shares Zach's booking link.**
  The meeting lands on Zach's calendar even though a different persona is writing.
- **Substantive live conversations escalate to Zach** via human review. He decides, per
  thread, whether to introduce himself. That judgment is deliberately his and not the
  handler's: whether a mid-thread introduction reads as a natural handoff or as a
  bait-and-switch depends on the specific conversation.
- **This applies to all 12 mailboxes**, including Zach's own 4. On his mailboxes the
  correspondent and the meeting owner simply happen to be the same person, so no
  escalation-for-identity is needed — only the normal escalation for a substantive
  conversation.

What the reply handler does with this: draft the reply in the persona's voice, include
the sender's own booking link from this file, and flag the thread for that sender once the
conversation goes beyond a first reply.

## Consumers

- `instructions/reply-handling.md` — the action map's "drive to a meeting" actions.
- `config/personas.md` — CTA guidance ("scheduling link once interested").
- `config/senders.md` — mailbox → sign-off name, which decides whether a given thread
  is a Zach mailbox or one of the 9.
