#!/usr/bin/env python3
"""The weekly campaign review: pull the numbers, and refuse to overstate them.

Implements the metrics in `instructions/campaign-analysis.md`. **Read-only.** It touches
no campaign, writes nothing to HubSpot, and sends nothing.

    Smartlead (sent, bounced, unsubscribed)  +  HubSpot (outbound_reply_intent)
        -> counts always, RATES ONLY WHEN THE SAMPLE SUPPORTS THEM

**The refusal is the feature, not a caveat on it.** A cold reply rate sits near 2-5%. On
the first campaign -- 25 contacts -- a single reply is "4%", a number whose 95% interval
runs from roughly 0% to 20%. It is indistinguishable from zero and from triple itself,
and yet it reads as a fact, gets compared against the next campaign's "8%", and produces
a copy change built on one email. A report that prints that number is worse than no
report, because it manufactures false confidence in exactly the decision it exists to
inform. So below `min_delivered_for_rate` this prints counts and says plainly what is
still missing.

Four things it does that the Smartlead dashboard cannot:

  1. **A HUMAN reply rate.** Smartlead's `reply_count` includes auto-responders. This
     excludes `out_of_office` and `automated_reply` using our own classification, so the
     number means "people answered" rather than "mail came back".
  2. **Outcome, not just volume.** Replies are split positive / negative / deferred from
     `outbound_reply_intent`, so a campaign getting replies that are all declines is not
     scored as a success.
  3. **A confidence interval on every rate**, by Wilson score. The interval is the part
     to read: two campaigns whose intervals overlap have not been shown to differ,
     however far apart their point estimates look.
  4. **Rates on DELIVERED, not sent.** A bounce never reached a human; leaving bounces in
     the denominator understates the true rate.

**Where it goes.** `--write` appends one row per campaign to the Campaign Report tab, and
`--slack` posts the headline. Both need `--apply`. Without either flag it just prints.

The Sheet is the important half: **a single run is a snapshot and cannot show a trend**,
and the useful question is almost never "what is the rate today" but "is it moving".
Rows accumulating week over week is what makes that answerable, and what lets a human
chart it with none of this code involved. The `reply_rate` cell is left EMPTY below the
threshold rather than written and flagged -- a number in a cell gets charted and quoted
by someone who never saw the caveat, and an empty cell cannot be plotted.

Runs in the `weekly` heartbeat slot on Mondays. Two Slack messages land that morning by
design: this report's own detailed post, and the heartbeat's health line confirming the
job ran. They answer different questions and neither replaces the other.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import sys
import urllib.error
import urllib.request
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eligibility import HubSpot, env_token, env_value, load_config  # noqa: E402
from reply_check import INTENTS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANALYSIS_CONFIG = ROOT / "config" / "analysis-defaults.md"
SL_BASE = "https://server.smartlead.ai/api/v1"
READ_PROPS = ["email", "outbound_reply_intent", "outbound_status", "outbound_sender",
              "outbound_last_campaign_id"]


def load_analysis_config() -> dict:
    """Parsed from config/analysis-defaults.md, never restated here.

    The intent-list check is the important part. These lists partition every intent the
    classifier can produce, so an intent present in one and absent from the other would
    be silently dropped from every total -- a reply that happened and appears nowhere.
    Refusing to start is the only safe response.
    """
    cfg = load_config(ANALYSIS_CONFIG)
    for key in ("min_delivered_for_rate",):
        if not isinstance(cfg.get(key), int) or cfg[key] < 0:
            raise RuntimeError(f"{ANALYSIS_CONFIG.name}: {key} must be a non-negative "
                               f"integer, got {cfg.get(key)!r}")
    buckets = ("positive_intents", "negative_intents", "neutral_intents",
               "machine_intents")
    listed: list[str] = []
    for b in buckets:
        if not isinstance(cfg.get(b), list):
            raise RuntimeError(f"{ANALYSIS_CONFIG.name}: {b} must be a list")
        listed += cfg[b]
    dupes = [i for i, n in Counter(listed).items() if n > 1]
    if dupes:
        raise RuntimeError(f"{ANALYSIS_CONFIG.name}: {dupes} appear in more than one "
                           "bucket, so they would be double-counted")
    missing = sorted(set(INTENTS) - set(listed))
    unknown = sorted(set(listed) - set(INTENTS))
    if missing or unknown:
        raise RuntimeError(
            f"{ANALYSIS_CONFIG.name} and INTENTS in reply_check.py disagree.\n"
            f"  classified but unbucketed (would vanish from every total): {missing}\n"
            f"  bucketed but not a real intent: {unknown}\n"
            "Fix the config; do not let the report run with a hole in it.")
    # The shared parser converts ints but leaves floats as strings, and a string here is
    # not a loud failure: `"0.95" * 100` is valid Python that silently produces a
    # 400-character string. Coerce and range-check rather than trusting the type.
    try:
        cfg["confidence"] = float(cfg.get("confidence", 0.95))
    except (TypeError, ValueError):
        raise RuntimeError(f"{ANALYSIS_CONFIG.name}: confidence must be a number "
                           f"between 0 and 1, got {cfg.get('confidence')!r}") from None
    if not 0 < cfg["confidence"] < 1:
        raise RuntimeError(f"{ANALYSIS_CONFIG.name}: confidence must be between 0 and 1 "
                           f"(0.95, not 95), got {cfg['confidence']!r}")
    return cfg


def wilson(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval, as (low, high) proportions.

    Wilson rather than the textbook normal approximation because the numbers here are
    exactly where that approximation fails: small n and proportions near zero. For 0
    replies out of 25 the normal formula returns [0.0, 0.0] -- "certainly zero" -- which
    is both wrong and the most dangerous thing this report could print. Wilson gives
    [0, 0.13].
    """
    if n <= 0:
        return (0.0, 0.0)
    z = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}.get(round(confidence, 2), 1.960)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def needed_for_rate(delivered: int, floor: int) -> int:
    """How many more delivered emails before a rate will be shown."""
    return max(0, floor - delivered)


class Smartlead:
    """Read-only. This script has no write path of any kind."""

    def __init__(self, key: str):
        self.key = key
        self.calls = 0

    def get(self, path: str):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(f"{SL_BASE}{path}{sep}api_key={self.key}",
                                     headers={"User-Agent": "outbound-engine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.calls += 1
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"GET {path} -> {e.code}: {(e.read() or b'').decode()[:200]}") from None

    def campaigns(self) -> list[dict]:
        return self.get("/campaigns") or []

    def analytics(self, cid) -> dict:
        return self.get(f"/campaigns/{cid}/analytics") or {}

    def leads(self, cid) -> list[dict]:
        out, offset = [], 0
        while True:
            d = self.get(f"/campaigns/{cid}/leads?offset={offset}&limit=100")
            rows = d.get("data") or []
            if not rows:
                return out
            out += rows
            offset += len(rows)
            if offset >= int(d.get("total_leads") or 0):
                return out


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


SHEET_COLUMNS = ["run_date", "campaign_id", "campaign_name", "status", "leads", "sent",
                 "bounced", "delivered", "human_replies", "positive", "negative",
                 "deferred", "machine", "unaccounted", "reply_rate", "rate_low",
                 "rate_high"]


def sheet_row(r: dict, cfg: dict, today: str) -> list:
    """One history row. **The rate cells stay EMPTY below the threshold.**

    Not written-and-flagged, empty. A number in a spreadsheet cell gets charted,
    averaged and quoted in a meeting by someone who never saw the caveat attached to it,
    and "4%" from one reply in 25 is exactly the figure that starts an argument about
    copy. An empty cell cannot be plotted. Every count beside it is real and always
    written, so nothing is lost by waiting.
    """
    d, h = r["delivered"], r["human_replies"]
    show = d >= cfg["min_delivered_for_rate"]
    lo, hi = wilson(h, d, cfg["confidence"]) if show else (None, None)
    unaccounted = max(0, r["sl_replies"] - (h + r["machine"]))
    return [today, str(r["id"]), r["name"], r["status"], r["leads"], r["sent"],
            r["bounced"], d, h, r["positive"], r["negative"], r["neutral"],
            r["machine"], unaccounted,
            round(h / d, 4) if show and d else "",
            round(lo, 4) if show else "", round(hi, 4) if show else ""]


def write_history(rows: list[dict], cfg: dict, today: str, apply_changes: bool) -> str:
    """Append one row per campaign to the Campaign Report tab. Idempotent per day."""
    import review_queue as rq
    svc, _ = rq.sheets_service()
    surfaces = rq.load_surface_config()
    sid = surfaces["REPLY_REVIEW_SHEET_ID"]
    tab = surfaces.get("CAMPAIGN_REPORT_TAB") or "Campaign Report"

    existing = []
    try:
        existing = (svc.spreadsheets().values()
                    .get(spreadsheetId=sid, range=f"{tab}!A1:Q")
                    .execute(num_retries=rq.SHEETS_RETRIES).get("values") or [])
    except Exception:
        existing = []                      # tab does not exist yet

    if not apply_changes:
        return (f"would write {len(rows)} row(s) to {tab!r} "
                f"({len(existing)} row(s) there now)")

    if not existing:
        # Create the tab on first use rather than making it a manual setup step.
        try:
            svc.spreadsheets().batchUpdate(
                spreadsheetId=sid,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}]}
            ).execute(num_retries=rq.SHEETS_RETRIES)
        except Exception:
            pass                            # already exists but is empty
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{tab}!A1",
            valueInputOption="RAW", body={"values": [SHEET_COLUMNS]}
        ).execute(num_retries=rq.SHEETS_RETRIES)
        existing = [SHEET_COLUMNS]

    # Idempotence on (run_date, campaign_id): a re-run after a failure adds nothing.
    already = {(r[0], r[1]) for r in existing[1:] if len(r) > 1}
    new = [sheet_row(r, cfg, today) for r in rows
           if (today, str(r["id"])) not in already]
    if not new:
        return f"{tab!r}: already has today's row for every campaign; nothing appended"
    svc.spreadsheets().values().append(
        spreadsheetId=sid, range=f"{tab}!A1",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": new}).execute(num_retries=rq.SHEETS_RETRIES)
    return f"appended {len(new)} row(s) to {tab!r} ({len(existing) - 1} were there)"


def slack_summary(rows: list[dict], cfg: dict, today: str) -> str:
    """The weekly nudge. Headline only -- the Sheet holds the detail and the history."""
    floor = cfg["min_delivered_for_rate"]
    d = sum(r["delivered"] for r in rows)
    h = sum(r["human_replies"] for r in rows)
    p = sum(r["positive"] for r in rows)
    unacc = sum(max(0, r["sl_replies"] - (r["human_replies"] + r["machine"]))
                for r in rows)
    lines = [f"📊 *Weekly campaign review* · {today}",
             f"{len(rows)} campaign(s) · {d} delivered · {h} human repl(y/ies) · "
             f"{p} positive"]
    if d < floor:
        lo, hi = wilson(h, d, cfg["confidence"]) if d else (0, 0)
        lines.append(f"*No rate yet* — {d} delivered is below the {floor} needed. "
                     f"{h}/{d} is anywhere from {pct(lo)} to {pct(hi)}.")
        lines.append(f"~{floor - d} more delivered before this can be read. "
                     f"The counts are real; the rate is not.")
    else:
        lo, hi = wilson(h, d, cfg["confidence"])
        lines.append(f"*Human reply rate {pct(h / d)}*  [{pct(lo)} – {pct(hi)}]")
        lines.append("Read the interval, not the point estimate.")
    if unacc:
        lines.append(f"⚠️ *{unacc} unaccounted repl(y/ies)* — Smartlead saw more than we "
                     f"classified. Usually a lead with no HubSpot contact.")
    lines.append("_Full history, one row per campaign per week, is in the "
                 "Campaign Report tab._")
    return "\n".join(lines)


def report_campaign(sl: Smartlead, hs: HubSpot, camp: dict, cfg: dict) -> dict:
    """Everything for one campaign. Returns the numbers; printing is the caller's job."""
    cid = camp.get("id")
    a = sl.analytics(cid)
    leads = sl.leads(cid)
    emails = [(r.get("lead") or {}).get("email", "").strip().lower() for r in leads]
    emails = [e for e in emails if e]

    sent = int(a.get("sent_count") or 0)
    bounced = int(a.get("bounce_count") or 0)
    unsub = int(a.get("unsubscribed_count") or 0)
    delivered = max(0, sent - bounced)

    # Our classification, not Smartlead's reply_count -- see the module docstring.
    contacts = hs.search_by_email(emails, READ_PROPS) if emails else {}
    intents = Counter((p.get("outbound_reply_intent") or "").strip()
                      for p in contacts.values())
    intents.pop("", None)

    def bucket(name):
        return sum(intents.get(i, 0) for i in cfg[name])

    human = bucket("positive_intents") + bucket("negative_intents") + \
        bucket("neutral_intents")
    return {
        "id": cid, "name": camp.get("name", ""), "status": camp.get("status", ""),
        # Smartlead's own count, kept ONLY to reconcile against ours. It is not used in
        # any rate: it includes auto-responders. See print_campaign for why it is here.
        "sl_replies": int(a.get("reply_count") or 0),
        "leads": len(leads), "sent": sent, "bounced": bounced, "unsub": unsub,
        "delivered": delivered, "intents": intents, "human_replies": human,
        "positive": bucket("positive_intents"), "negative": bucket("negative_intents"),
        "neutral": bucket("neutral_intents"), "machine": bucket("machine_intents"),
        "matched": len(contacts), "unmatched": len(set(emails)) - len(contacts),
        "senders": Counter((p.get("outbound_sender") or "(unset)").strip()
                           for p in contacts.values()),
    }


def print_campaign(r: dict, cfg: dict) -> None:
    floor, conf = cfg["min_delivered_for_rate"], cfg["confidence"]
    print(f"\n{'=' * 78}\n{r['id']}  {r['name']}   [{r['status']}]\n{'=' * 78}")
    print(f"  {r['leads']} lead(s) enrolled, {r['sent']} email(s) sent, "
          f"{r['bounced']} bounced -> {r['delivered']} delivered")
    if r["unmatched"]:
        print(f"  NOTE: {r['unmatched']} lead(s) have no HubSpot contact, so their "
              "replies cannot be classified and are missing from every count below.")

    print(f"\n  Replies (human, by our classification -- excludes auto-responders):")
    print(f"    positive  {r['positive']:4}   {', '.join(cfg['positive_intents'])}")
    print(f"    negative  {r['negative']:4}   {', '.join(cfg['negative_intents'])}")
    print(f"    deferred  {r['neutral']:4}   {', '.join(cfg['neutral_intents'])}")
    print(f"    ------------------")
    print(f"    human     {r['human_replies']:4}")
    if r["machine"]:
        print(f"    (plus {r['machine']} auto-responder(s), excluded from every rate)")

    # RECONCILIATION. Ours comes from HubSpot intents, Smartlead's from mail arriving.
    # Smartlead's should be the HIGHER of the two, because it counts auto-responders that
    # we deliberately exclude. If it is higher by MORE than the auto-responders we found,
    # replies happened that we never classified -- a lead with no HubSpot contact, or a
    # reply the poller never processed -- and those are invisible in every number above.
    ours = r["human_replies"] + r["machine"]
    if r["sl_replies"] > ours:
        gap = r["sl_replies"] - ours
        print(f"\n  ** UNACCOUNTED REPLIES: Smartlead recorded {r['sl_replies']}, we "
              f"classified {ours}. {gap} repl(y/ies) are missing from")
        print(f"     everything above.** Usual cause is a lead with no HubSpot contact "
              f"({r['unmatched']} here);")
        print(f"     the other is a reply reply_check never processed. Worth resolving "
              f"before trusting these counts.")
    elif r["sl_replies"] < ours:
        print(f"\n  NOTE: we classified {ours} repl(y/ies) but Smartlead recorded only "
              f"{r['sl_replies']}. Unexpected;\n     Smartlead should be the higher of "
              f"the two since it also counts auto-responders.")

    print()
    if r["delivered"] < floor:
        short = needed_for_rate(r["delivered"], floor)
        lo, hi = wilson(r["human_replies"], r["delivered"], conf) if r["delivered"] else (0, 0)
        print(f"  NO RATES: {r['delivered']} delivered is below the "
              f"{floor} needed for a usable read.")
        if r["delivered"]:
            print(f"    For scale, {r['human_replies']}/{r['delivered']} is anywhere from "
                  f"{pct(lo)} to {pct(hi)} at {int(conf * 100)}% confidence.")
            print(f"    That interval is why no rate is quoted: it spans "
                  f"{'zero and ' if lo == 0 else ''}several times itself.")
        print(f"    ~{short} more delivered email(s) before this campaign can be read.")
        print(f"    Counts above are real and worth reading. The RATE is not yet.")
    else:
        for label, k in (("human reply", "human_replies"), ("positive", "positive"),
                         ("bounce", "bounced"), ("unsubscribe", "unsub")):
            n = r["delivered"] if k != "bounced" else r["sent"]
            lo, hi = wilson(r[k], n, conf)
            print(f"    {label + ' rate':22} {pct(r[k] / n) if n else 'n/a':>7}   "
                  f"[{pct(lo)} – {pct(hi)}]")
        print(f"\n    Read the intervals, not the point estimates. Two campaigns whose "
              f"intervals\n    overlap have not been shown to differ.")

    live = {s: n for s, n in r["senders"].items() if s != "(unset)"}
    if len(live) > 1:
        print(f"\n  By sender: {dict(live)}  (per-sender rates need the same "
              f"{floor} floor EACH)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Weekly campaign review. Read-only; refuses to quote unsupported rates.")
    ap.add_argument("--campaign", help="one campaign id; default is every campaign")
    ap.add_argument("--include-completed", action="store_true",
                    help="also report campaigns that have finished")
    ap.add_argument("--write", action="store_true",
                    help="append this run to the Campaign Report tab (history).")
    ap.add_argument("--slack", action="store_true",
                    help="post the headline summary to the heartbeat channel.")
    ap.add_argument("--apply", action="store_true",
                    help="required alongside --write/--slack to actually write or post.")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the interval maths and the config guard, no API calls")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()

    cfg = load_analysis_config()
    key = env_value("SMARTLEAD_API_KEY")
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not set")
    sl, hs = Smartlead(key), HubSpot(env_token())

    camps = ([{"id": a.campaign, "name": f"(id {a.campaign})", "status": "?"}]
             if a.campaign else sl.campaigns())
    if not a.campaign and not a.include_completed:
        camps = [c for c in camps if (c.get("status") or "").upper() != "COMPLETED"]
    if not camps:
        print("no campaigns to report on. Use --include-completed to see finished ones.")
        return 0

    print(f"CAMPAIGN REVIEW  ({len(camps)} campaign(s))")
    print(f"rates shown only at >= {cfg['min_delivered_for_rate']} delivered; "
          f"{int(cfg['confidence'] * 100)}% intervals")
    rows = []
    for c in camps:
        r = report_campaign(sl, hs, c, cfg)
        rows.append(r)
        print_campaign(r, cfg)

    tot_d = sum(r["delivered"] for r in rows)
    tot_h = sum(r["human_replies"] for r in rows)
    tot_p = sum(r["positive"] for r in rows)
    print(f"\n{'=' * 78}\nACROSS ALL {len(rows)} CAMPAIGN(S)\n{'=' * 78}")
    print(f"  {tot_d} delivered, {tot_h} human repl(y/ies), {tot_p} positive")
    if tot_d < cfg["min_delivered_for_rate"]:
        print(f"  Still below the {cfg['min_delivered_for_rate']} floor IN TOTAL, so "
              "there is no campaign-level\n  copy conclusion to draw yet. That is the "
              "honest answer, not a missing feature.")
        print(f"  What to do meanwhile: read the individual replies. At this volume the "
              "TEXT of\n  a reply is worth more than any rate computed from it.")
    else:
        lo, hi = wilson(tot_h, tot_d, cfg["confidence"])
        print(f"  human reply rate {pct(tot_h / tot_d)}  [{pct(lo)} – {pct(hi)}]")
        print("  Comparing two variants needs thousands per variant, not hundreds. This "
              "total\n  supports 'is it working', not 'which copy is better'.")
    today = dt.date.today().isoformat()
    if a.write:
        print(f"\nhistory: {write_history(rows, cfg, today, a.apply)}")
    if a.slack:
        text = slack_summary(rows, cfg, today)
        print("\n" + "-" * 78 + f"\n{text}\n" + "-" * 78)
        if a.apply:
            from heartbeat import post_to_slack
            post_to_slack(text)
            print("posted to Slack")
        else:
            print("(not posted: --slack needs --apply)")

    print(f"\n{sl.calls} Smartlead calls, {hs.calls} HubSpot calls. "
          f"Smartlead and HubSpot were only read from.")
    if (a.write or a.slack) and not a.apply:
        print("DRY RUN: --apply was not passed, so nothing was written or posted.")
    return 0


def _self_test() -> int:
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"{label}: got {got!r}, want {want!r}")

    # The case the whole report exists for: zero replies must NOT read as certainly zero.
    lo, hi = wilson(0, 25)
    check("0/25 lower bound is 0", round(lo, 4), 0.0)
    check("0/25 upper bound is ~13%, not 0", 0.12 < hi < 0.15, True)
    # The textbook normal approximation would give [0,0] here. That is the bug Wilson
    # avoids, and the reason this function is not three lines of p +/- z*sqrt(pq/n).
    check("a single reply in 25 is not distinguishable from zero",
          wilson(1, 25)[0] < 0.01, True)
    check("...and its upper bound is many times the point estimate",
          wilson(1, 25)[1] > 0.15, True)

    # Interval must narrow as n grows, or the threshold argument is meaningless.
    w25, w200, w2000 = (wilson(1, 25), wilson(8, 200), wilson(80, 2000))
    width = [round(h - l, 4) for l, h in (w25, w200, w2000)]
    check("intervals narrow with n", width == sorted(width, reverse=True), True)
    check("even 8/200 is still a wide read", (w200[1] - w200[0]) > 0.03, True)

    check("n=0 does not divide by zero", wilson(0, 0), (0.0, 0.0))
    check("all replied is capped at 100%", wilson(10, 10)[1], 1.0)
    check("shortfall maths", needed_for_rate(25, 200), 175)
    check("no shortfall when over the floor", needed_for_rate(500, 200), 0)

    # The guard that stops a reply vanishing from the totals.
    cfg = load_analysis_config()
    listed = sum((cfg[b] for b in ("positive_intents", "negative_intents",
                                   "neutral_intents", "machine_intents")), [])
    check("every classifier intent is bucketed", sorted(listed), sorted(INTENTS))
    check("the floor is loaded from config, not hardcoded",
          isinstance(cfg["min_delivered_for_rate"], int), True)
    # The shared parser hands floats back as strings, and `"0.95" * 100` is valid Python
    # that yields a 400-character string rather than an error. Caught live on the first
    # run; the type check is what stops it recurring silently.
    check("confidence is a real float, not the string that came out of the parser",
          isinstance(cfg["confidence"], float), True)
    check("confidence is a proportion, not a percentage", 0 < cfg["confidence"] < 1, True)

    print(f"{len(fails)} FAILED" if fails else "all pure cases passed")
    for f in fails:
        print(f"  FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
