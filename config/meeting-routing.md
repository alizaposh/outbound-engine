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


## The hash is SALTED, and that is load-bearing (fixed 2026-09-25)

The owner is `sha256("meeting-owner:" + email) % 6`. The salt is not decoration.

It was `sha256(email) % 6`, which collided with `split_by_sender --batch K/N` --
that filter selects contacts on `hash % N` of the **same unsalted string**. With
`--batch 1/2` the filter consumes the low bit, and because the pool size is even,
`% 6` inherits that parity:

| | reachable owners |
|---|---|
| `--batch 1/2` | Carl, Henry, Lawrence (even indices) |
| `--batch 2/2` | Caroline, Kate, Zach (odd indices) |

The first 1,314-contact round was routing every meeting to three of six calendars, and
nothing reported it: each individual assignment was valid, deterministic and
sender-independent. It surfaced only by running the real list through the function and
counting. **Two hashes of one string are independent only if something distinguishes
them** -- `run_generation.pick_variant` takes a `salt` for exactly this reason. Any new
per-contact hash needs its own.

## The contact OWNER follows the calendar (added 2026-09-25)

When a draft actually hands a prospect someone's booking link, that person becomes the
HubSpot contact owner -- otherwise a prospect books with Kate while the record stays
unowned and nobody is accountable for the relationship.

Three conditions, all required (`reply_check.assign_meeting_owner`):

1. **The link appears in the FINAL draft.** Not the intent label: the link is offered
   to the classifier on every reply and included only where warranted, so the draft
   text is the ground truth. A decline that never offers a meeting reassigns nobody.
2. **The contact has no owner today.** 90 of the first 1,314 were already owned by
   people with real relationships. A round robin never displaces a human's book.
3. **The name resolves to a HubSpot owner id**, matched on first name like everywhere
   else. An unresolvable name is reported and skipped, never written as a blank.

**On reply, not at enrolment**, deliberately: ownership then means "this rep has a live
conversation" rather than putting ~205 cold, unanswered contacts into each of six reps'
dashboards and owner-based workflows.

**Every meeting owner therefore needs a HubSpot owner record.** All six had one when
this shipped. A new row in the table above without one still sends the link and logs a
warning instead of assigning.


## Starter Kit: the low-commitment CTA (added 2026-09-30)

A standing group session prospects can drop into. **This is not a meeting** -- nobody's
calendar is booked and no rep is committed -- which is exactly why it can be offered
where a booking link cannot.

```
starter_kit_url: https://posh.vip/s/1165?t=planhat-playbook-tracking
starter_kit_when: Tuesdays at 5:30pm
```

**When it is offered: an `objection` that names NO recognised competitor.**

That is a specific and currently empty-handed case. A prospect who says "we have a
business deal with our website creator who provides our links and ticketing" has an
incumbent, but not one in `PLATFORM_ALIASES`, so:

- `current_competitor` is not written -- there is no platform to write
- `recycle_objection_days` does not apply, because that requires a named platform
- no re-engagement task is created
- and `outbound_status = replied` lapses after 30 days, so they become re-mailable

They get a draft and nothing else, despite often being warm. The real 2026-09-29 reply
this was built from read "I've proposed the idea of going through Posh" -- a prospect
actively advocating for us internally, with no path back.

**Why it is safe here when a booking link is not.** `instructions/reply-handling.md`
forbids a booking link on objections because "a meeting you are forbidden to justify
forces you to invent a justification" -- told to offer a call on an objection, the model
once produced "reserved seating is actually something we handle well", a capability
claim about a product it has never seen documentation for. The Starter Kit carries no
such pressure: it is the same session for everyone, it makes no claim about this
prospect's situation, and it asks for nothing but an hour they may or may not spend.

**The sentence is appended in CODE, not written by the model.** Same reasoning as the
sign-off and the footer. An instruction in the prompt is a suggestion; six separate
copy rules in this engine were "fixed" by instruction and then broken again, and each
one was only settled by enforcing it outside the model. The model is told the offer
exists so it does not write a competing version.

**Not offered on:** `interested` or `question` (they get the booking link -- a warmer
ask for a warmer signal), `not_interested`, `asked_to_stop`, `not_qualified`,
`wrong_contact`, or an objection that DID name a competitor (those already get a
180-day cooldown and a dated task, so they have a path). Widening it to a competitor
objection would be defensible; it is deliberately not done yet, because that case is
not the one that was empty-handed.


### The 7-day nudge (`scripts/starter_kit_nudge.py`, added 2026-09-30)

An `interested` or `question` reply that we answered with a **booking link** and that
has been silent for `--quiet-days` (7) gets ONE follow-up offering the Starter Kit
instead. It does not repeat the calendar link: the prospect declined that ask by not
taking it, and offering it twice is the same request in a smaller font.

**It QUEUES, it does not send.** The row enters the reply review queue like any
classified reply and goes out through `send_replies.py` after a human approves. Not
timidity about a fixed template -- it keeps ONE send path, which already re-checks
suppression at send time, refuses two replies on a thread per run, honours `cc`, stamps
`sent_at`, and records `outbound_starter_kit_offered` from the body that actually went.

**Nine reasons it will refuse**, checked live rather than trusted from the sheet, since
the row was written when the reply arrived and any of these can change after: a meeting
booked (by status OR the native field, which can lead the status), opted out,
suppressed, bounced, disqualified, handed off to a rep, the Starter Kit already offered,
our answer not yet sent, and **the prospect having replied since** -- someone who wrote
back is owed a human response, not a canned nudge.

**Two things stop it eating its own output.** The queue dedups on
`smartlead_message_id`, and the row carries a derived one
(`nudge-starter-kit:<original>`), so a re-run cannot double-queue. And `decide()`
refuses any row whose `review_reason` is the nudge's own. That second guard exists
because the nudge row carries `intent=interested` and eventually a `sent_at`, so it
re-enters the candidate pool by itself -- today it is saved only by having no calendar
link in its body, which is accidental and would stop being true if anyone added one.

**Morning slot only, after `sync_meetings`.** The order is load-bearing: the nudge
refuses to chase anyone who has booked, and `sync_meetings` is what makes that true for
today's bookings. It measures days of silence, so a second run in the same day can
discover nothing.
