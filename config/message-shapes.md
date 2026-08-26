# Config: Message shapes

Shapes for each of the three emails. **One per position is assigned per contact by
code** (`assign_shapes` in `scripts/run_generation.py`) and only those reach the model.

Selection is **signal-driven, never round-robin**:
- **Email 1 shape follows `volume_band`**, because a band says what the organizer needs.
  Job title drives the *register* separately (`role_register`), because a title says how
  to talk, not what to talk about.
- **Email 2 shape follows `volume_band`** too: a colder or unsized lead gets the summary
  shape, a sized one gets a single capability developed properly.
- **Email 3 shape follows the email-1 shape**, so the thread keeps one voice. A blunt
  opener should not end in a warm ramble.
- **Correctness gate, checked before any preference:** shapes 1A and 1D name the
  platform, so a contact whose competitor is unusable can never draw them.

> **This file is deliberately NOT in `RULEBOOK_FILES`.** Same reason as
> `config/generation-failure-fallback.md`: if the model saw all four it would blend them
> or drift to whichever it liked, which is how one exemplar became a template in the
> first place. A 34-contact run with a single anchor email produced the same paragraph
> structure 34 out of 34 times, the same opening clause 34/34, and the same closing
> question 34/34. Variety has to be a property of the pipeline, not of model discipline.

Each shape is a **register and structure target**, not a template. The bracketed values
are illustrative; every one comes from the research note. All four are validator-clean:
no dashes, no banned CTA family, no stats, no booking link, 45 to 90 words.

---

## Shape 1A: setup question

Opens by asking about their current tool. The safest shape, and the one to use when the
competitor is the most interesting thing we know.


**Subject example:** `eventbrite working out for Mo Mami?`


**Opening variants (code picks one; use it as the opening move):**
- Reaching out to see if you're locked in on your current ticketing setup with [competitor], or open to seeing what else is out there?
- Wanted to reach out and ask whether [org] is committed to [competitor] for the year, or still weighing options?
- Reaching out because I wasn't sure whether [competitor] is a long-term thing for [org] or just what you started on?

> Hey [first name],
>
> I'm [sender], I run partnerships at Posh. Reaching out to see if you're locked in on
> your current ticketing setup with [competitor], or open to seeing what else is out
> there?
>
> Posh keeps the ticketing, your guest list, and payouts in one place instead of three.
>
> Happy to put a quick comparison together, want me to?

## Shape 1B: their world first

Opens on **them**, not on the tool. Use when the organization name or vertical is the
most interesting thing we know.


**Subject example:** `Mo Mami's regular crowd`


**Opening variants (code picks one; use it as the opening move):**
- While looking at the event scene in [city], [org] stood out, so I wanted to reach out.
- I was going through who is building a real regular crowd in [city] and [org] came up, so thought I would reach out.
- [org] came up while I was looking at [vertical] organizers in [city], so wanted to say hello.

> Hey [first name],
>
> I'm [sender], I run partnerships at Posh. While looking at the event scene in [city],
> [org] stood out, so I wanted to reach out.
>
> On Posh your attendee list and text blasts sit with the ticketing, so reaching people
> who already came once takes minutes.
>
> Want me to show you how that would look?

## Shape 1C: one operational question

Opens with a genuine question and no pitch at all. Use when we know little beyond the
organization, since it asks rather than asserts.


**Subject: 2 to 4 words, and do not extend it.** Use one of these exactly:
`by hand?` · `after the ticket sells` · `the manual parts`

A tighter numeric bound is here because nothing else worked. Four attempts failed in
sequence: a generic example got the organization appended (7 of 10 FAILed), an
organization-bearing example was ignored, a shortened body question was copied and then
extended anyway. This shape's body opens with a question, and the model derives the
subject from that question rather than from an example, so the only reliable fix is to
prescribe the string instead of illustrating it.

The example already contains the organization, so substitute it rather than
appending it. A generic example ("what happens after the sale?") got the org
appended and ran to 9 words in 7 of 10 shape-1C emails.


**Opening variants (code picks one; use it as the opening move):**
- Reaching out because I was curious how [org] handles everything after a ticket sells, is much of that still by hand?
- Wanted to reach out and ask what happens at [org] once a ticket is sold, how much of it is still manual?
- Reaching out with one question about [org]: after the ticket sells, how much still runs on spreadsheets and DMs?

> Hi [first name],
>
> I'm [sender], I run partnerships at Posh. Reaching out because I was curious how [org]
> handles everything after a ticket sells, is much of that still by hand?
>
> On Posh the guest list, promo, and payouts sit with the ticketing.
>
> Open to seeing what we would put together?

## Shape 1D: short and warm

The shortest shape. Use for a busy or high-volume operator, where the other shapes would
pad. Short does not mean blunt: it still opens with a reason for reaching out.


**Subject example:** `Mo Mami on eventbrite`


**Opening variants (code picks one; use it as the opening move):**
- Reaching out since [org] is running on [competitor]. Open to seeing what else is out there?
- Wanted to reach out about [org]: open to seeing what else is out there before your next run?
- Reaching out because [org] is on [competitor] at the moment, worth a look at the alternative?

> Hey [first name],
>
> I'm [sender], I run partnerships at Posh. Reaching out since [org] is running on
> [competitor]. Open to seeing what else is out there?
>
> Posh does the ticketing, plus the part after the sale: your crowd, your promo, your
> payouts.
>
> Want me to put a comparison together?

---

## Email 2 shapes (threaded reply, no greeting, no re-introduction)

Email 2 is a reply on the same thread. It must read correctly if email 1 got no reply,
which is the normal case, so it may open as a light continuation but must not depend on
email 1 having been read. **Do not open every one "Quick follow-up."** That phrase
appeared in 25 of 34 emails on the 2026-08-26 run.

### Shape 2A: one capability, developed

For `established` and `scaled` bands, where we know enough to pick an angle.

> One thing I should have mentioned about [org]: your guest list and text blasts sit in
> the same place as your ticketing.
>
> So a reminder to everyone who came last time goes out in a couple of minutes.
>
> Want me to show you?

### Shape 2B: here is the simple version

For `emerging` and `unknown` bands, where a summary beats a deep angle. The sanctioned
exception to one-idea-per-email: it is a summary, not a feature dump, so keep it short.

> Still working out whether Posh fits [org]? The short version. Organizers come to us
> when they want to:
>
> - Sell more tickets
> - Reach more of the right people
> - Own their attendee community
> - Make check-in and payouts easier
>
> Any of those live for you?

### Shape 2C: the question they can answer in one line

For `unknown` band, where we still know little: it asks rather than tells, and a
one-line answer is easy to give.

> How are you handling promo at [org] right now, mostly by hand?
>
> On Posh it sits with the ticketing, so texting people who already came takes minutes.
>
> Want me to walk you through it?

## Email 3 shapes (the close: shortest of the three, 20 to 50 words)

Name that it is the last touch, ask one low-pressure question, exit graciously. **No
feature, no recap, and no booking link** (the scheduler belongs to the reply stage).
Email 3 may use a short greeting because it is brief enough to read as a friendly nudge.

**Shape 3 follows the email-1 shape** so the thread keeps one voice.

### Shape 3A: warm close (follows 1A or 1B)

> Hey [first name],
>
> Last note from me on this. If it would ever help to talk through how Posh could fit
> [org], just say the word.
>
> Otherwise, all the best with your season.

### Shape 3B: the direct question (follows 1C)

> Should I close this out for now, or would fifteen minutes on the calendar be useful?
>
> Totally fine either way, just did not want to let it go quiet.

### Shape 3C: blunt close (follows 1D)

> Last one from me. Something you want to look at this season, or should I leave it?
>
> Either way, good luck with the next run.

## Rules that apply to every shape

- **OPEN WITH A REASON FOR REACHING OUT, never with an assertion about them.** This is
  what makes the first line sound like a person. "Reaching out to see if you're locked in
  on your current ticketing setup" and "While looking at the event scene in [city], [org]
  stood out, so I wanted to reach out" both work. These do not:
  - "You're running [org] on [competitor] right now." Stating what we know about them,
    flatly, reads as surveillance rather than an introduction.
  - "Quick one about [org]:" Abrupt, and it opens on a demand rather than a reason.
  A cold email has to answer "why am I getting this?" in the first line. Assertions skip
  that question; a reason answers it.
- **The middle paragraph is ONE sentence, and it does not end in a "so ..." clause.**
  This is structural because a phrase blacklist does not hold: banning four explainer
  phrasings produced two fresh ones ("so that part stops eating your week", "so the part
  that actually scales a party business"). One sentence, full stop, move to the question.
- **CUT THE EXPLAINER CLAUSE.** State the thing and stop. Do not add a clause telling
  the prospect why it matters, what most tools get wrong, or what usually happens. These
  are the exact patterns to delete, all taken from real generated copy:
  - "which is the part most ticketing tools are worst at"
  - "that is the part that usually lives scattered across three tools"
  - "that is the part organizers tell us eats the week"
  - "most organizers only go looking when something starts to pinch"
  A rep does not explain the problem back to the person who has it. **Punchy, direct,
  light. Not sales, not marketing.**
- **Length is the constraint that makes the rest true.** A real email from the sales team
  runs about 60 words of body. Email 1 is 35 to 65 words, email 2 is 30 to 60, email 3 is
  18 to 42. If an email is over, the thing to cut is almost always an explainer clause or
  a second sentence in the middle paragraph, never the question.
- **One CTA. One.** Two asks ("let me know if you're open to connecting" plus "free for
  a 15 min chat?") is the pattern to avoid, however natural it feels when typing.
- **An exemplar's phrasing propagates, so nothing in one may sit next to a banned
  family.** Shape 1D once read "Worth knowing what else is out there" and three emails
  generalised it into "worth a quick call", which is a hard FAIL. If a phrase is one word
  away from something banned, it does not belong in an exemplar.
- **Use the opening variant you were handed** (`shapes.opening` in the research note),
  filled with this contact's details. Code picks one of the shape's variants per contact,
  because asking the model to "vary the first sentence" did nothing: within a shape, 13 of
  16 emails opened with byte-identical wording. Variety has to come from the pipeline.
- **Do not put an organization name of three or more words in the subject.** "still
  using RA for If You Know You Know?" is 9 words and FAILs. The body names them; the
  subject does not have to.
- **Shape 1C: never append the organization name to the subject.** "what happens after
  the sale?" is 5 words and does the job; "what happens after the sale at West Coast
  Makers?" is 9 and FAILs. The body already names them.
- **The subject is 2 to 7 words no matter which shape you were given.** Each shape shows
  a subject example at that length. Shape C's body opens with a long question and the
  first run mirrored it into 8 to 10 word subjects, failing 9 of 13 shape-C emails: the
  body question can be long, the subject cannot.
- **If naming the organization would push the subject past 7 words, leave it out.** The
  body already names them, so the subject does not have to. "what happens after the sale
  at 90s Til Dawn?" is 9 words and fails; "what happens after the sale?" is 5 and does
  the same job. Long organization names are common on this list.
- **Follow the assigned shape's structure and length.** Do not switch shapes, do not
  merge two, and do not fall back to a shape you have seen before.
- **The intro line goes where the shape puts it: near the top.** Use
  `sender.intro_line` verbatim. Shape C and D read fine with any of the three senders.
- **Fill it with THIS contact.** `organization`, `city`, `vertical`, `volume_angle`, and
  the competitor are all in the research note. A shape filled with generic nouns is the
  failure this file exists to prevent.
- **`volume_band` decides the angle** inside whichever shape you were given. Never state
  or imply the underlying figure (`config/personas.md`, "Volume bands").
- **Never claim Posh has a presence in any city.** Referencing *their* city is fine;
  asserting our footprint there is not.
- The hard constraints still govern: no dashes, no numeric stats, subject on email 1 only
  (2 to 7 words, lowercase plus proper nouns), no booking link in the cold sequence.
