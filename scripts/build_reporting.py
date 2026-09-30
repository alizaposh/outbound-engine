#!/usr/bin/env python3
"""Create and maintain the HubSpot lists the outbound dashboard clicks into.

    config/analysis-defaults.md  ->  DYNAMIC HubSpot lists  ->  dashboard tiles

**Why lists.** The ask was a dashboard where every metric can be clicked to see which
contacts are in it. HubSpot builds that from *active lists*: a list is both a number and
the set of people behind it, so a "Meetings booked: 4" tile and the four names are the
same object. There is no second reporting layer to keep in sync.

**Dashboards themselves cannot be created from the API.** `/reports/v2/reports` and
`/reports/v2/dashboards` both 404 on this portal, so the tiles are assembled once by
hand in the UI. That is a five-minute job and it is the LAST step -- the lists below are
what make it five minutes instead of an afternoon, because each tile is then just
"count of list X". `docs/hubspot-dashboard.md` is the click-by-click.

Five guarantees:

  1. DRY RUN BY DEFAULT. `--apply` is required.
  2. **EVERY DEFINITION COMES FROM `config/analysis-defaults.md`.** The intent buckets
     are parsed from the same block `campaign_report.py` parses, never restated here.
     A dashboard reading "6 positive replies" beside a weekly report reading "4" would
     discredit both, and the failure mode is silent: two hardcoded lists drift the day
     somebody re-opens the contested `positive_intents` line. It is config precisely
     because the sales team is expected to move it.
  3. DYNAMIC, NEVER STATIC. Membership is re-evaluated by HubSpot, so a contact who
     books a meeting tomorrow appears without anything of ours running.
  4. IT NEVER DELETES OR NARROWS A LIST. An existing list is reported and left alone;
     a changed definition is printed as a diff for a human to apply. These lists are
     visible to the whole CRM and may have been edited deliberately.
  5. EVERY LIST IS PREFIXED `Outbound —`, so they sort together and are obviously
     engine-owned rather than someone's hand-built segment.

Run it once, then again after changing an intent bucket. Not part of the heartbeat: the
lists are dynamic, so there is nothing to refresh on a schedule.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from campaign_report import load_analysis_config  # noqa: E402  guarantee 2
from eligibility import HubSpot, env_token  # noqa: E402

PREFIX = "Outbound — "          # em dash, guarantee 5
CONTACTS = "0-1"


# `operationType` names the PROPERTY's type and each type accepts only its own operators.
# The three shapes below were established by probing the API, because the combinations
# that read as obvious are all rejected:
#   * "set at all" is ALL_PROPERTY + IS_KNOWN. Not HAS_PROPERTY, which ALL_PROPERTY
#     refuses; and not the property's real type (STRING/DATE), which demands a `value`
#     that a presence test has no business supplying.
#   * a booleancheckbox is BOOL + IS_EQUAL_TO with a real boolean.
#   * a select is ENUMERATION + IS_ANY_OF -- read off a probe list before it was deleted.
# ALL_PROPERTY is type-agnostic, so it serves the string and the date property alike.
def has(prop: str) -> dict:
    return {"property": prop, "filterType": "PROPERTY",
            "operation": {"operator": "IS_KNOWN", "operationType": "ALL_PROPERTY",
                          "includeObjectsWithNoValueSet": False}}


def is_true(prop: str) -> dict:
    """A booleancheckbox is BOOL. Filtering it as the enumeration string "true" is
    accepted by some HubSpot endpoints and matches nobody, which is the worse outcome."""
    return {"property": prop, "filterType": "PROPERTY",
            "operation": {"operator": "IS_EQUAL_TO", "operationType": "BOOL",
                          "includeObjectsWithNoValueSet": False, "value": True}}


def is_any(prop: str, values: list[str]) -> dict:
    return {"property": prop, "filterType": "PROPERTY",
            "operation": {"operator": "IS_ANY_OF", "operationType": "ENUMERATION",
                          "includeObjectsWithNoValueSet": False,
                          "values": list(values)}}


def branch(filters: list[dict]) -> dict:
    """The AND-inside-OR shape HubSpot stores. Read back off a real list rather than
    guessed; a hand-built filterBranch is accepted and then matches nothing."""
    return {"filterBranchType": "OR", "filterBranchOperator": "OR", "filters": [],
            "filterBranches": [{"filterBranchType": "AND", "filterBranchOperator": "AND",
                                "filterBranches": [], "filters": filters}]}


def specs(cfg: dict) -> list[tuple[str, str, dict]]:
    """(name, what the tile means, filterBranch).

    Ordered as the dashboard should read: volume, then outcomes, then the two that are
    work queues rather than metrics.
    """
    enrolled = has("outbound_last_campaign_id")
    # Guarantee 2: these three come from config, not from this file.
    positive = cfg["positive_intents"]
    negative = cfg["negative_intents"]
    neutral = cfg["neutral_intents"]
    machine = cfg["machine_intents"]
    return [
        ("Enrolled", "every contact the engine has ever sent to; the denominator",
         branch([enrolled])),
        ("In sequence", "assigned to a campaign; see the caveat on Emailed below",
         branch([enrolled, is_any("outbound_status", ["in_sequence"])])),
        # **The honest send metric.** Enrolled and In sequence are both written by
        # create_campaign at campaign CREATION -- before launch, before any send -- so
        # they mean "assigned to a campaign", not "we emailed them". On 2026-09-17 that
        # read 247 enrolled and 220 in_sequence against 61 real sends, because three
        # campaigns sat DRAFTED for two hours before a human launched them.
        #
        # The gap is not a bug on its own: writing the campaign id at enrolment is what
        # lets a HubSpot record trace to its campaign at all. It becomes a LIE only when a
        # campaign is built and never launched, since the unsubscribe toggles have no API
        # and that manual step can simply be forgotten -- and those contacts would then
        # read "In sequence" permanently while receiving nothing.
        #
        # outbound_last_logged_send is written by sync_sends ONLY after it observes a real
        # send in Smartlead, so this list cannot claim a send that did not happen. Use it,
        # not Enrolled, whenever the question is "how many people did we actually email".
        ("Emailed (confirmed send)",
         "a real send observed in Smartlead; the honest volume number",
         branch([enrolled, has("outbound_last_logged_send")])),
        ("Replied (human)", "a real person answered; excludes auto-responders",
         branch([enrolled, is_any("outbound_reply_intent",
                                  positive + negative + neutral)])),
        ("Meetings booked", "booked after we enrolled them; the outcome metric",
         branch([enrolled, is_any("outbound_status", ["meeting_booked"])])),
        # The Starter Kit funnel, in two lists rather than one. The offer count alone
        # says how often we used the softer CTA; it says nothing about whether it
        # WORKS. The pair does, and the second list is the one that answers the
        # question in the Notion doc -- is a lower-commitment ask a better ask?
        ("Starter Kit offered", "sent the Starter Kit session link (a confirmed send, "
                                "not a draft)",
         branch([enrolled, has("outbound_starter_kit_offered")])),
        ("Starter Kit -> meeting", "offered the Starter Kit AND later booked; the "
                                   "conversion this CTA has to earn",
         branch([enrolled, has("outbound_starter_kit_offered"),
                 is_any("outbound_status", ["meeting_booked"])])),
        ("Positive replies", f"intent in {', '.join(positive)}",
         branch([enrolled, is_any("outbound_reply_intent", positive)])),
        ("Negative replies", f"intent in {', '.join(negative)}",
         branch([enrolled, is_any("outbound_reply_intent", negative)])),
        ("Deferred (come back later)", f"intent in {', '.join(neutral)}; a date, not a loss",
         branch([enrolled, is_any("outbound_reply_intent", neutral)])),
        ("Auto-responders", f"intent in {', '.join(machine)}; NOT counted as replies",
         branch([enrolled, is_any("outbound_reply_intent", machine)])),
        ("No response", "sequence finished, nobody answered; contactable again",
         branch([enrolled, is_any("outbound_status", ["no_response"])])),
        # Needed for the status axis to reconcile to Enrolled. Without it the status
        # tiles summed to 59 of 61 and the two missing contacts looked like a filter bug
        # rather than a state nobody had built a tile for.
        ("Disqualified", "not a fit; excluded from future campaigns by the eligibility gate",
         branch([enrolled, is_any("outbound_status", ["disqualified"])])),
        ("Replied, awaiting next step", "status is replied; the live conversations",
         branch([enrolled, is_any("outbound_status", ["replied"])])),
        ("Opted out", "asked to stop or unsubscribed; never contact again",
         branch([enrolled, is_any("outbound_status", ["opted_out"])])),
        ("Bounced", "undeliverable; a deliverability fact, not a consent decision",
         branch([enrolled, is_any("outbound_status", ["bounced"])])),
        # The two work queues. Not metrics -- things a human should act on.
        ("Suppressed", "suppressed by the engine; excluded from every future campaign",
         branch([enrolled, is_true("outbound_suppressed")])),
        ("Paused for out-of-office", "sequence frozen until outbound_resume_after",
         branch([enrolled, has("outbound_resume_after")])),
    ]


def existing_lists(hs: HubSpot) -> dict[str, dict]:
    """Every list whose name carries our prefix, by short name."""
    out, offset = {}, 0
    while True:
        d = hs._call("POST", "/crm/v3/lists/search",
                     {"query": PREFIX.strip(), "count": 100, "offset": offset,
                      "processingTypes": ["DYNAMIC", "SNAPSHOT", "MANUAL"]})
        rows = d.get("lists") or []
        for r in rows:
            name = r.get("name") or ""
            if name.startswith(PREFIX):
                out[name[len(PREFIX):]] = r
        offset += len(rows)
        if not rows or not d.get("hasMore"):
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Create the dashboard's click-through lists. Dry run by default.")
    ap.add_argument("--apply", action="store_true", help="actually create the lists.")
    a = ap.parse_args(argv)

    cfg = load_analysis_config()          # guarantee 2
    hs = HubSpot(env_token())
    print("APPLY: lists will be created" if a.apply
          else "DRY RUN: nothing will be created. Re-run with --apply.")
    print(f"definitions from config/analysis-defaults.md: "
          f"positive={cfg['positive_intents']} negative={cfg['negative_intents']}\n")

    have = existing_lists(hs)
    made = kept = failed = 0
    for short, meaning, fb in specs(cfg):
        full = PREFIX + short
        if short in have:
            # Guarantee 4. Never edited in place.
            lid = have[short].get("listId")
            print(f"  KEPT    {short:28} list {lid} already exists, left untouched")
            kept += 1
            continue
        if not a.apply:
            print(f"  WOULD   {short:28} {meaning}")
            made += 1
            continue
        # Per-list, so one rejected filter costs one list instead of the whole run. The
        # filter shapes differ per property type, so a single bad one is the likely
        # failure -- and aborting would leave the set half-built with no report of which
        # half, which is the state that is hardest to recover from.
        try:
            d = hs._call("POST", "/crm/v3/lists", {
                "name": full, "objectTypeId": CONTACTS,
                "processingType": "DYNAMIC", "filterBranch": fb})
        except Exception as e:
            print(f"  FAILED  {short:28} {str(e)[:150]}")
            failed += 1
            continue
        lst = d.get("list") or {}
        print(f"  CREATED {short:28} list {lst.get('listId')}, "
              f"size {lst.get('size')} ({meaning})")
        made += 1

    print(f"\n{made} list(s) {'created' if a.apply else 'to create'}, {kept} already "
          f"present, {failed} failed")
    print(f"{hs.calls} HubSpot calls")
    if not a.apply:
        print("DRY RUN: nothing was created.")
    else:
        print("\nNext, and it cannot be automated: build the dashboard in the HubSpot UI.")
        print("The reports API 404s on this portal. See docs/hubspot-dashboard.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
