# Config: Meeting Routing

Who a booked meeting belongs to, and the link used to book it. **Read this instead of
hardcoding a name.** `instructions/reply-handling.md` drives interested replies to a
meeting; the person and link come from here, so changing the owner is a config edit in
one place rather than a search across instruction files.

## Booking links: the SENDER'S OWN calendar (changed 2026-10-14)

**A prospect books with the person who emailed them.** Someone who has been writing to
Carl gets Carl's link. `reply_check.booking_link_for` matches the contact's
`outbound_sender` (written once at enrolment) against this table.

**This replaced a team round robin (2026-09-24 to 2026-10-14)** that hashed each contact
to one of six calendars regardless of sender. In practice it handed prospects a stranger's
calendar on the warmest reply we get, and Aliza was switching links back to the sender by
hand before approving. Henry and Lawrence are not senders, so they no longer receive
outbound meetings; their rows stay in case either starts sending.

| Meeting owner | Booking link |
|---|---|
| Carl | `https://meetings.hubspot.com/carl-newmark` |
| Lawrence | `https://meetings.hubspot.com/lawrence-hennessy` |
| Caroline | `https://meetings.hubspot.com/creyda` |
| Henry | `https://meetings.hubspot.com/henry377` |
| Zach | `https://meetings.hubspot.com/zach-hickman` |
| Kate | `https://meetings.hubspot.com/kate-burge` |

**Every active sender needs a row here.** A sender with none gets the fallback's calendar
below, and the draft names that person ("with Zach on our team") rather than "with me".

**Brooke is a sender with no row** (departed 2026-09-24). A late reply from one of her
contacts gets the fallback's calendar.

**Fallback meeting owner: `Zach`**. Used when there is no sender to match -- a
Smartlead-only lead with no HubSpot record -- or the sender has no row above. Without it such a lead gets a draft with no link at all, which is worse:
a warm prospect who cannot book is a lost meeting, where one booking with Zach is a
meeting. The reviewer is told the fallback was used.

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


## ~~The hash is SALTED~~ HISTORICAL (2026-09-25 to 2026-10-14)

The round robin chose `sha256("meeting-owner:" + email) % 6`. The salt mattered because
`split_by_sender --batch K/N` hashes the same address, and unsalted the two collided:
each batch could only reach three of six calendars. The lesson outlives the round robin:
**any new per-contact hash needs its own salt.**

## The contact OWNER follows the calendar (added 2026-09-25)

When a draft actually hands a prospect someone's booking link (normally the sender's),
that person becomes the HubSpot contact owner -- otherwise a prospect books with Kate
while the record stays unowned and nobody is accountable for the relationship.

Three conditions, all required (`reply_check.assign_meeting_owner`):

1. **The link appears in the FINAL draft.** Not the intent label: the link is offered
   to the classifier on every reply and included only where warranted, so the draft
   text is the ground truth. A decline that never offers a meeting reassigns nobody.
2. **The contact has no owner today.** 90 of the first 1,314 were already owned by
   people with real relationships. A round robin never displaces a human's book.
3. **The name resolves to a HubSpot owner id**, matched on first name like everywhere
   else. An unresolvable name is reported and skipped, never written as a blank.

**On reply, not at enrolment**, deliberately: ownership then means "this rep has a live
conversation" rather than putting hundreds of cold, unanswered contacts into each
sender's dashboard and owner-based workflows.

**Every meeting owner therefore needs a HubSpot owner record.** All six had one when
this shipped. A new row in the table above without one still sends the link and logs a
warning instead of assigning.


## Starter Kit: the low-commitment CTA (added 2026-09-30)

A standing group session prospects can drop into. **This is not a meeting** -- nobody's
calendar is booked and no rep is committed -- which is exactly why it can be offered
where a booking link cannot.

```
starter_kit_url: https://posh.vip/s/1165
starter_kit_when: Tuesdays at 5:30pm
```

**The tracking parameter was REMOVED 2026-09-30** (`?t=planhat-playbook-tracking`).
Aliza's call, and the clean form is also the safer one to hold here: every consumer of
this value tests `url in body`, so the SHORTER string matches a body carrying either
form. Had the config kept the longer URL and a reviewer sent the short one, the offer
would have reached the prospect and `outbound_starter_kit_offered` would never have
been written -- an invisible hole in the only metric measuring this CTA. **Keep this
value the shortest form that identifies the link.**

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
