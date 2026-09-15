# The outbound dashboard in HubSpot

**What this gives you:** every engine metric as a number you can click to get the exact
contacts behind it.

`scripts/build_reporting.py` has already created the thirteen lists. This file is the
part that cannot be automated: **assembling the dashboard itself.** The reports and
dashboards APIs (`/reports/v2/reports`, `/reports/v2/dashboards`) both return 404 on this
portal, so the tiles go on by hand, once. Budget five minutes.

---

## The lists (already created)

Each is a DYNAMIC active list, so membership updates itself — nothing of ours runs to
refresh them. All are prefixed `Outbound — ` so they sort together in the lists tool.

| List | ID | What it means |
|---|---|---|
| Outbound — Enrolled | 1944 | Every contact the engine has ever sent to. **The denominator.** |
| Outbound — In sequence | 1945 | Currently receiving emails 1–3 |
| Outbound — Replied (human) | 1946 | A real person answered. Excludes auto-responders |
| Outbound — Meetings booked | 1947 | Booked *after* we enrolled them. **The outcome metric** |
| Outbound — Positive replies | 1948 | `interested`, `question` |
| Outbound — Negative replies | 1949 | `not_interested`, `objection`, `not_qualified`, `asked_to_stop` |
| Outbound — Deferred (come back later) | 1950 | `not_now`, `wrong_contact`. A date, not a loss |
| Outbound — Auto-responders | 1951 | `out_of_office`, `automated_reply`. **Not** replies |
| Outbound — No response | 1952 | Sequence finished, nobody answered. Contactable again |
| Outbound — Opted out | 1953 | Asked to stop or unsubscribed. Never contact again |
| Outbound — Bounced | 1954 | Undeliverable |
| Outbound — Suppressed | 1955 | Excluded from every future campaign |
| Outbound — Paused for out-of-office | 1956 | Frozen until `outbound_resume_after` |

The intent buckets are **not** written in this file or in the script. They are parsed
from `config/analysis-defaults.md`, the same block the weekly report parses, so the
dashboard and the report cannot disagree. Move `positive_intents` there and re-run
`build_reporting.py` to see the diff.

---

## Read this before you add a single tile

**Status and intent are two different axes. Do not add them together.**

- `outbound_status` is a **lifecycle state**: every enrolled contact has exactly one, so
  those tiles sum to the Enrolled total.
- `outbound_reply_intent` is **what the reply said**: only repliers have one, and it
  persists after the status moves on.

As of 2026-09-15 all three repliers sit at a *different* status — one `replied`, one
`opted_out`, one `disqualified`. So "Replied (human) = 3" overlaps the Opted out tile.
That is correct behaviour, not double counting, but a tile row that adds intent counts to
status counts will produce a number that means nothing.

Group the dashboard the same way:

```
row 1  volume     Enrolled · In sequence · No response
row 2  outcomes   Replied (human) · Meetings booked · Positive · Negative · Deferred
row 3  hygiene    Opted out · Bounced · Suppressed · Auto-responders · Paused for OOO
```

---

## Build it

1. **Reports → Dashboards → Create dashboard.** Name it `Outbound engine`. Start from
   **blank**, not a template — the templates are built on native sales properties this
   engine deliberately does not write in v1 (see `config/hubspot-properties.md`), so
   every tile would read zero.
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

| Tile | Written by | When |
|---|---|---|
| Enrolled | `create_campaign.py` | on campaign creation |
| In sequence | `create_campaign.py` | on campaign creation |
| Replied, Positive/Negative/Deferred, Auto-responders | `reply_check.py` | every heartbeat |
| **Meetings booked** | **`sync_meetings.py`** | **morning heartbeat** |
| No response | `close_sequences.py` | morning heartbeat |
| Opted out | `reply_check.py`, `sync_unsubscribes.py` | morning heartbeat |
| Bounced | `sync_bounces.py` | morning heartbeat |
| Suppressed | `sync_unsubscribes.py` | morning heartbeat |
| Paused for OOO | `reply_check.py`, cleared by `resume_sequences.py` | every heartbeat |

**Meetings booked was the gap.** `meeting_booked` was named as the outcome state in
`config/hubspot-properties.md` and defended against overwriting in four separate
scripts, and **nothing ever wrote it** — so before 2026-09-15 this tile would have read
zero permanently, no matter how many meetings the engine produced. `sync_meetings.py`
reads the native `engagements_last_meeting_booked` that every HubSpot booking link in
`config/meeting-routing.md` populates, and promotes the status. It refuses to credit a
booking that predates enrolment; see its guarantee 2.

---

## Known caveat: the Enrolled tile reads one high

Contact `aliza.mayer@gmail.com` (id `218660792892`) still carries
`outbound_last_campaign_id = 3930942`, the reply-handling test campaign that was deleted
from Smartlead on 2026-09-15. Real enrolled is **61** (36 on 3955179 + 25 on 3921033);
the tile says 62, and since that address will never reply it drags every rate down
slightly and permanently.

To fix, clear the property on that one contact:

```bash
./.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "scripts")
from reply_check import HubSpotWriter
from eligibility import env_token
print(HubSpotWriter(env_token(), True).write("218660792892",
      {"outbound_last_campaign_id": ""}))
PY
```

Nothing else points at 3930942, so this is the whole of the cleanup.
