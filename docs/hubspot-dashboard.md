# The outbound dashboard in HubSpot

**What this gives you:** every engine metric as a number you can click to get the exact
contacts behind it.

`scripts/build_reporting.py` has already created the sixteen lists. This file is the
part that cannot be automated: **assembling the dashboard itself.** The tiles go on by
hand, once. Budget five minutes.

## Do not spend time looking for a reports API — there isn't one

Settled 2026-09-15, after the portal's private app was granted `reporting.full.read`,
`reporting.full.write` and `reporting.full.edit`. **The scopes made no difference, and
the reason is worth recording so nobody re-runs this experiment:**

| Probe | Result | What it means |
|---|---|---|
| `/reports/v2/reports`, `/reports/v3/reports`, `/reporting/v{1,2,3}/reports`, `/reports/v*/dashboards`, `/reports/v3/custom-reports` | **404** | The endpoint does not exist. Scope-independent |
| `/dashboard/v2/dashboard` | **401** | Legacy endpoint; rejects private-app tokens outright |
| `/crm/v3/objects/reports` | **400** | `REPORT` is not a supported object type |
| `/events/v3/events`, `/analytics/v2/*` | **403** | Real, but need *web-analytics* scopes — website traffic, not outbound |

**404 is the load-bearing detail.** A 403 would mean "your token lacks permission", and
more scopes would fix it. A 404 means there is nothing behind the URL, so no grant can
open it. HubSpot's docs agree — report creation is documented as UI-only, the
`reporting-v2` reference now redirects to a *legacy* archive, and the community request
for a create/manage reports API is still open with no committed support.

What `reporting.full.write` *did* buy is not nothing: it is what lets
`build_reporting.py` create the sixteen lists. In HubSpot a list is simultaneously the
number and the click-through set behind it, so **the reporting layer is already built by
API.** Only the visual arrangement of tiles is manual.

---

## The lists (already created)

Each is a DYNAMIC active list, so membership updates itself — nothing of ours runs to
refresh them. All are prefixed `Outbound — ` so they sort together in the lists tool.

| List | ID | What it means |
|---|---|---|
| Outbound — Enrolled | 1944 | Every contact the engine has ever sent to. **The denominator.** |
| Outbound — In sequence | 1945 | Assigned to a campaign — see the caveat below |
| Outbound — Emailed (confirmed send) | 1979 | **A real send observed in Smartlead. The honest volume number** |
| Outbound — Replied (human) | 1946 | A real person answered. Excludes auto-responders |
| Outbound — Meetings booked | 1947 | Booked *after* we enrolled them. **The outcome metric** |
| Outbound — Positive replies | 1948 | `interested`, `question` |
| Outbound — Negative replies | 1949 | `not_interested`, `objection`, `not_qualified`, `asked_to_stop` |
| Outbound — Deferred (come back later) | 1950 | `not_now`, `wrong_contact`. A date, not a loss |
| Outbound — Auto-responders | 1951 | `out_of_office`, `automated_reply`. **Not** replies |
| Outbound — No response | 1952 | Sequence finished, nobody answered. Contactable again |
| Outbound — Disqualified | 1958 | Not a fit; excluded by the eligibility gate, not by suppression |
| Outbound — Replied, awaiting next step | 1959 | Status is `replied` — the live conversations |
| Outbound — Opted out | 1953 | Asked to stop or unsubscribed. Never contact again |
| Outbound — Bounced | 1954 | Undeliverable |
| Outbound — Suppressed | 1955 | Excluded from every future campaign |
| Outbound — Paused for out-of-office | 1956 | Frozen until `outbound_resume_after` |
| Outbound — Starter Kit offered | 2192 | Sent the Starter Kit session link (a confirmed send) |
| Outbound — Starter Kit -> signed up | 2398 | Signed up for a session on or after our offer |
| Outbound — Starter Kit -> session held | 2399 | That session ran. **A proxy for attendance** — HubSpot has sign-ups, not who joined |
| Outbound — Starter Kit -> meeting | 2193 | Offered the Starter Kit and later booked a 1:1 |

The intent buckets are **not** written in this file or in the script. They are parsed
from `config/analysis-defaults.md`, the same block the weekly report parses, so the
dashboard and the report cannot disagree. Move `positive_intents` there and re-run
`build_reporting.py` to see the diff.

**List 1941, `Outbound — Interested (needs follow-up)`, was DELETED on 2026-09-15** —
soft-deleted, so HubSpot keeps it restorable rather than purged. It was a probe built
while establishing that the lists API worked at all. List **1948 (`Positive replies`)**
supersedes it on definition — same intent filter, but scoped to enrolled contacts and
derived from config rather than hardcoded — but the real problem was the **name**, and it
was not a cosmetic one. The reasoning is kept here because it generalises to any list
added later.

`needs follow-up` claims the contact is waiting on a human. **That is never what the state
means.** Follow-up is drafted automatically by `reply_check.py` and sent automatically by
`send_replies.py`; the only human step is marking `Approve`, and that queue is the Reply
Review Queue Sheet, not HubSpot. When this was checked on 2026-09-15 the list's single
member, `breakalegparty@gmail.com`, had been answered at `14:06:40Z` that morning — so
the list was inviting a rep to duplicate a reply the engine had already sent.

**A truthful version cannot be built from existing properties, which is why this is a
deletion and not a rename.** Distinguishing "they replied and we have not answered" from
"they replied and we have" needs their-last-reply compared against our-last-send.
`outbound_last_logged_send` gives our side, and the native `hs_sales_email_last_replied`
gives theirs — but it is a **hidden** property, and HubSpot rejects property filters
against hidden properties outright (tested; `COMPARATIVE_DATE` is otherwise a valid
operation). Nothing the engine currently writes records "we answered this reply":
`send_replies.py` writes to the Sheet and to Smartlead, and nothing to HubSpot.

**1948 stays, and is accurate, because it is a cumulative metric rather than a queue.**
"How many positive replies has the engine produced" stays true after we answer; "who
still needs answering" does not. Keep that distinction when adding any future list — a
tile that reads as a to-do list has to be able to empty itself, and these cannot.

If a HubSpot-visible "waiting on us" list is wanted later, it needs an engine-written
property — `reply_check.py` setting it when it queues a draft and `send_replies.py`
clearing it after a successful send. That is a genuine change to two scripts, not a list
definition, and it would put a second copy of the queue beside the Sheet (see golden
rule 2 in `CLAUDE.md` on why the Sheet is the single record).

Deleting a DYNAMIC list touches no contact data — membership is computed on read, not
stored — so `breakalegparty@gmail.com` kept `outbound_status=replied`,
`outbound_reply_intent=interested` and its campaign id, and remains in list 1948. To
restore 1941, re-create it; the filter was `outbound_reply_intent IS_ANY_OF
[question, interested]` with no enrolment scope, which is the other reason 1948 is the
better list.

---

## "Enrolled" means assigned to a campaign, NOT emailed

Both `Enrolled` and `In sequence` are written by `create_campaign.py` at campaign
**creation**. A campaign is created DRAFTED and cannot send until a human sets the
unsubscribe options in the Smartlead UI and launches it, so **those two tiles move before
a single email goes out.** Observed 2026-09-17, in the two hours between the three
campaigns being built and launched:

```
Enrolled          247      <- assigned to a campaign
In sequence       220
Emailed (confirmed) 61     <- actually sent to
gap               186      = the three campaigns still sitting DRAFTED
```

**The gap is not a bug, and writing the id at enrolment is not a mistake** — it is the
only link from a HubSpot record to the campaign that mailed it, and nothing native
captures it. The number is also self-correcting: `sync_sends` runs in the morning
heartbeat and the confirmed-send count catches up within a day.

**It becomes a lie in one specific case: a campaign built and never launched.** The
unsubscribe toggles have no API, so that manual step can simply be forgotten, and those
contacts would read `In sequence` indefinitely while receiving nothing. Nothing in the
engine would flag it.

So: **when the question is "how many people have we actually emailed", read
`Emailed (confirmed send)` (list 1979), never `Enrolled`.** It is written only after
`sync_sends` observes a real send in Smartlead, so it cannot claim a send that did not
happen. Enrolled is the right denominator for rates — everyone assigned to the
campaign — and the wrong answer to "did we send it".

## Read this before you add a single tile

**Status and intent are two different axes. Do not add them together.**

- `outbound_status` is a **lifecycle state**: every enrolled contact has exactly one, so
  the six status tiles sum to Enrolled exactly. Verified 2026-09-15:
  `57 in sequence + 0 no response + 1 disqualified + 1 replied + 2 opted out + 0 bounced
  = 61 = Enrolled`. **Use that as your check after building** — if it doesn't add up,
  either a tile is filtered wrong or list membership is still recalculating.
- `outbound_reply_intent` is **what the reply said**: only repliers have one, and it
  persists after the status moves on.

As of 2026-09-15 all three repliers sit at a *different* status — one `replied`, one
`opted_out`, one `disqualified`. So "Replied (human) = 3" overlaps the Opted out and
Disqualified tiles. That is correct behaviour, not double counting, but a tile row that
adds intent counts to status counts will produce a number that means nothing.

`Disqualified` and `Replied, awaiting next step` exist **because of** that reconciliation.
The first pass shipped without them and the status tiles summed to 59 of 61 — a
two-contact shortfall that reads as a broken filter when it was really two documented
states nobody had built a tile for.

Group the dashboard the same way:

```
row 1  volume     Enrolled · In sequence · No response
row 2  outcomes   Replied (human) · Meetings booked · Positive · Negative · Deferred
row 3  pipeline   Replied awaiting next step · Disqualified
row 4  hygiene    Opted out · Bounced · Suppressed · Auto-responders · Paused for OOO
row 5  starter    Starter Kit offered · signed up · session held · meeting
```

Row 1 plus rows 3–4 are the status axis and must total Enrolled. Row 2 is the intent
axis and must not be added to them.

**Row 5 is its own funnel, deliberately NOT a value of `outbound_status`** (decided
2026-10-15). A contact offered the Starter Kit is still `replied`, then maybe
`meeting_booked`; folding it into the status axis would make it vanish the moment they
did anything else, and every script that branches on status would need to learn it.
Read row 5 left to right as a funnel, each tile a subset of the one before, and never
add it to rows 1–4.

---

## Build it

**BUILT 2026-09-15. The dashboard is `Outbound AI Email Engine Reporting`.** Use that
name when referring to it; the steps below are how it was made, kept for rebuilding it or
adding tiles.

Its numbers on the day it was built, as a baseline to compare against if a tile ever
looks wrong: Enrolled 61 · In sequence 57 · Replied (human) 3 · Meetings booked 0 ·
Positive/Negative/Deferred 1/1/1 · Opted out 2 · Disqualified 1 · Replied-awaiting 1 ·
Suppressed 2 · No response, Bounced, Auto-responders, Paused-for-OOO all 0.

1. **Reports → Dashboards → Create dashboard.** Start from **blank**, not a template —
   the templates are built on native sales properties this engine deliberately does not
   write in v1 (see `config/hubspot-properties.md`), so every tile would read zero.
2. For each metric: **Add report → Create custom report → Single object → Contacts.**
3. Set the visualization to **Summary / single number**.
4. Add one filter: **List membership → is a member of → `Outbound — <name>`.**
5. Save to the `Outbound engine` dashboard.
6. Repeat per row above.

**The click-through is then automatic** — a single-number tile in HubSpot drills into the
contributing records when you click it. That is the whole reason the metrics are defined
as list membership rather than as filters typed into each report: the list is the click
target, and it is reusable everywhere else in HubSpot (workflows, sequences, exports).

### Two tiles worth adding by hand

- **Reply rate over time.** Contacts, line chart, `outbound_reply_intent` is known,
  by month. Read `config/analysis-defaults.md` first: **below 200 delivered a rate is
  not evidence**, and the weekly report refuses to print one for exactly that reason.
  A dashboard has no such guard, so a 2% line on n=61 will look like a trend when it is
  noise. Consider leaving this off until volume justifies it.
- **Meetings by sender.** Contacts, bar chart, filtered to the Meetings booked list,
  broken down by `outbound_sender`. This is the one that answers "is the routing in
  `config/meeting-routing.md` working" — a sender with sends and no meetings is either
  a copy problem or a broken booking link.

---

## Where each number comes from

**Nothing in HubSpot reporting reads Smartlead directly.** Every tile is a DYNAMIC list
over `outbound_*` contact properties, and each of those properties is written by exactly
one script at one moment. The chain is: a script observes something in Smartlead or
HubSpot → writes an `outbound_*` property → HubSpot re-evaluates list membership (about a
minute later) → the tile changes. There is no other path, which is why a tile can only
ever be as truthful as the property behind it.

| Tile | Written by | When |
|---|---|---|
| Enrolled | `create_campaign.py` | **on campaign creation — NOT on send** |
| In sequence | `create_campaign.py` | **on campaign creation — NOT on send** |
| **Emailed (confirmed send)** | **`sync_sends.py`** | **after a real send is observed in Smartlead** |
| Replied, Positive/Negative/Deferred, Auto-responders | `reply_check.py` | every heartbeat |
| **Meetings booked** | **`sync_meetings.py`** | **every heartbeat** (morning only before 2026-10-15) |
| No response | `close_sequences.py` | morning heartbeat |
| Opted out | `reply_check.py`, `sync_unsubscribes.py` | morning heartbeat |
| Bounced | `sync_bounces.py` | morning heartbeat |
| Suppressed | `sync_unsubscribes.py` | morning heartbeat |
| Paused for OOO | `reply_check.py`, cleared by `resume_sequences.py` | every heartbeat |
| Starter Kit offered | `send_replies.py` | after a confirmed send |
| Starter Kit signed up / session held | `sync_starter_kit.py` | morning heartbeat |

**Meetings booked was the gap.** `meeting_booked` was named as the outcome state in
`config/hubspot-properties.md` and defended against overwriting in four separate
scripts, and **nothing ever wrote it** — so before 2026-09-15 this tile would have read
zero permanently, no matter how many meetings the engine produced. `sync_meetings.py`
reads the native `engagements_last_meeting_booked` that every HubSpot booking link in
`config/meeting-routing.md` populates, and promotes the status. It refuses to credit a
booking that predates enrolment; see its guarantee 2.

---

## Resolved: the Enrolled tile read one high

Contact `aliza.mayer@gmail.com` (id `218660792892`) carried
`outbound_last_campaign_id = 3930942`, the reply-handling test campaign deleted from
Smartlead on 2026-09-15. It inflated Enrolled to 62 against a true **61** (36 on 3955179
+ 25 on 3921033), and since that address will never reply it would have dragged every
rate down permanently. **Cleared 2026-09-15.** Nothing else pointed at 3930942.

To restore it, if a future test needs that contact enrolled again:

```bash
./.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "scripts")
from reply_check import HubSpotWriter
from eligibility import env_token
print(HubSpotWriter(env_token(), True).write("218660792892",
      {"outbound_last_campaign_id": "3930942"}))
PY
```

### Two consistency traps this exposed, both relevant when you read a tile

1. **HubSpot search is eventually consistent.** Counting immediately after the write
   still returned 62; it read 61 about ten seconds later. A count taken straight after a
   write is not verification of that write — read the property back directly instead.
2. **Dynamic list membership lags the search index, by considerably more.** The property
   was provably empty and the search was already reporting 61 while list 1944 still said
   62. Lists recalculate on HubSpot's own schedule, so **a tile disagreeing with a fresh
   query is normal for a while after any property change** and is not evidence that a
   filter is wrong.
