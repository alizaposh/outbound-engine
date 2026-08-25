#!/usr/bin/env python3
"""Pre-send eligibility filter: lead list in, ELIGIBLE list + annotated list out.

Implements instructions/pre-send-eligibility-check.md. Runs BEFORE generation, as a
separate step -- run_generation.py stays HubSpot-free (CSV in, CSV out) and takes
--contacts eligible.csv from here.

Four guarantees this file exists to provide:

  1. THIS SCRIPT NEVER WRITES TO HUBSPOT. It reads and decides; nothing else. Leads
     are assumed to exist in HubSpot already (create_missing_contacts: false), so a
     lead with no record is an assumption violation: it stays ELIGIBLE but is called
     out loudly in the summary rather than quietly created.
  2. ABSENT IS NOT FALSE. Every gated property is checked to exist in the portal
     before any lead is evaluated. A property that has been renamed or deleted reads
     as empty, so its gate would pass everybody -- indistinguishable from a clean
     run. This aborts instead.
  3. AN UNRESOLVED OWNER IS A HARD ERROR. excluded_owners is a list of names, and a
     name that doesn't resolve to an ID would quietly make that rep's contacts
     eligible. Abort rather than skip.
  4. NO LEAD IS SILENTLY DROPPED. Every input row produces exactly one output row,
     including malformed ones (decision ERROR).

Values come from config/pre-send-defaults.md, which is the source of truth. Nothing
tunable is hardcoded here.

This never sends, never generates, and never writes to Smartlead.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "pre-send-defaults.md"
API = "https://api.hubapi.com"
SEARCH_BATCH = 100          # HubSpot caps an IN filter and a search page at 100
RATE_PAUSE = 0.12           # ~8 req/s, under HubSpot's burst ceiling

# Property -> the gate that reads it. Used by the preflight in guarantee 2, so a
# missing property names the gate it would have silently disabled.
GATED = {
    "hs_email_optout": "gate 1 opt-out (hard)",
    "outbound_suppressed": "gate 1 opt-out (hard)",
    "outbound_status": "gates 1+2 status (hard and soft)",
    "outbound_recycle_after": "gate 2 recycle (soft)",
    "lifecyclestage": "gate 3 lifecycle",
    "has_group": "gate 4 customer",
    "customer_success_manager": "gate 5 CSM",
    "hubspot_owner_id": "gate 6 owner",
    "hs_lead_status": "gate 7 lead status",
    "hs_sequences_is_enrolled": "gate 8 sequence",
    "notes_last_updated": "gate 9 recency",
    "notes_last_contacted": "gate 9 recency",
    "hs_last_sales_activity_timestamp": "gate 9 recency",
}
CARRY = ["firstname", "lastname", "jobtitle", "company"]  # transparency / handoff only

OUT_COLUMNS = ["email", "hubspot_contact_id", "decision", "reason", "exclusion_tier",
               "notes_last_updated", "notes_last_contacted",
               "hs_last_sales_activity_timestamp", "lifecyclestage", "hs_lead_status",
               "owner", "outbound_status", "outbound_recycle_after"]
# The shape run_generation.py --contacts expects.
ELIGIBLE_COLUMNS = ["hs_object_id", "first_name", "last_name", "email", "job_title",
                    "company", "current_competitor", "estimated_gmv_usd", "vertical"]


# ---- config -------------------------------------------------------------------

def load_config(path: pathlib.Path = CONFIG) -> dict:
    """Parse the canonical values block out of pre-send-defaults.md.

    Deliberately parses the config file rather than restating its values: a second
    copy is how the two drift apart. Handles only the subset the block uses --
    scalars, inline [a, b] lists, and '- item' lists -- and raises on anything else
    rather than guessing.
    """
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Canonical values\s*```(.*?)```", text, re.S)
    if not m:
        raise RuntimeError(f"{path}: no fenced 'Canonical values' block found")

    cfg: dict = {}
    key = None
    for raw in m.group(1).splitlines():
        line = raw.split("#", 1)[0].rstrip()      # strip comments
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):        # list item
            if key is None:
                raise RuntimeError(f"{path}: list item before any key: {raw!r}")
            cfg[key].append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            raise RuntimeError(f"{path}: cannot parse line: {raw!r}")
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if not val:                               # key introducing a list
            cfg[key] = []
            continue
        if val.startswith("[") and val.endswith("]"):
            cfg[key] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        elif val.lower() in ("true", "false"):
            cfg[key] = val.lower() == "true"
        elif re.fullmatch(r"-?\d+", val):
            cfg[key] = int(val)
        else:
            cfg[key] = val.strip('"').strip("'")
        key = None
    return cfg


def env_token() -> str:
    tok = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not tok:                                   # fall back to .env (git-ignored)
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("HUBSPOT_ACCESS_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not tok:
        raise RuntimeError("HUBSPOT_ACCESS_TOKEN not set (env or .env)")
    return tok


# ---- HubSpot ------------------------------------------------------------------

class HubSpot:
    """Read-only client. No method here writes -- see guarantee 1."""

    def __init__(self, token: str):
        self.token = token
        self.calls = 0

    def _call(self, method: str, path: str, body: dict | None = None, tries: int = 4):
        url = f"{API}{path}"
        for attempt in range(tries):
            req = urllib.request.Request(
                url, method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self.calls += 1
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = (e.read() or b"").decode()[:300]
                # A DAILY 429 is not a burst: backing off cannot clear it, and retrying
                # burns three sleeps before reporting a limit that resets tomorrow.
                # Fail immediately and say so, rather than looking like a flaky network.
                if e.code == 429 and '"DAILY"' in detail:
                    raise RuntimeError(
                        f"{method} {path} -> 429 DAILY API LIMIT REACHED for this HubSpot "
                        f"portal. Retrying will not help; the quota resets on HubSpot's "
                        f"daily cycle. Check Settings > Integrations > Private Apps for "
                        f"which app is consuming it.\n  {detail}") from None
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    time.sleep(2 ** attempt)      # 1s, 2s, 4s
                    continue
                raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None
        raise RuntimeError(f"{method} {path}: retries exhausted")

    def property_exists(self, name: str) -> bool:
        try:
            self._call("GET", f"/crm/v3/properties/contacts/{name}")
            return True
        except RuntimeError as e:
            if "-> 404" in str(e):
                return False
            raise

    def owners(self) -> dict[str, str]:
        out, after = {}, None
        while True:
            q = "?limit=100" + (f"&after={after}" if after else "")
            d = self._call("GET", f"/crm/v3/owners{q}")
            for o in d.get("results", []):
                name = f"{o.get('firstName') or ''} {o.get('lastName') or ''}".strip()
                if name:
                    out[name] = str(o["id"])
            after = (d.get("paging") or {}).get("next", {}).get("after")
            if not after:
                return out

    def search_by_email(self, emails: list[str], props: list[str]) -> dict[str, dict]:
        """Returns {lowercased email: properties}. Batches the IN filter."""
        found: dict[str, dict] = {}
        for i in range(0, len(emails), SEARCH_BATCH):
            chunk = emails[i:i + SEARCH_BATCH]
            after = None
            while True:
                body = {"filterGroups": [{"filters": [
                            {"propertyName": "email", "operator": "IN",
                             "values": chunk}]}],
                        "properties": props, "limit": SEARCH_BATCH}
                if after:
                    body["after"] = after
                d = self._call("POST", "/crm/v3/objects/contacts/search", body)
                for r in d.get("results", []):
                    p = dict(r.get("properties") or {})
                    p["hs_object_id"] = r["id"]
                    key = (p.get("email") or "").strip().lower()
                    if key:
                        found[key] = p
                after = (d.get("paging") or {}).get("next", {}).get("after")
                time.sleep(RATE_PAUSE)
                if not after:
                    break
        return found


# ---- gates --------------------------------------------------------------------

def as_date(v) -> dt.datetime | None:
    """HubSpot returns ISO strings or epoch millis depending on property and endpoint."""
    if v in (None, ""):
        return None
    s = str(v)
    if re.fullmatch(r"-?\d{10,}", s):
        return dt.datetime.fromtimestamp(int(s) / 1000, dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "yes", "1")


class Decision:
    __slots__ = ("decision", "reason", "tier")

    def __init__(self, decision: str, reason: str = "", tier: str = ""):
        self.decision, self.reason, self.tier = decision, reason, tier


def evaluate(p: dict, cfg: dict, owner_ids: dict[str, str], now: dt.datetime) -> Decision:
    """The nine gates, in order. First failure wins, so the reported reason is the
    most important one -- an opt-out reads as 'opted out', never as 'stale'."""
    g = lambda k: (p.get(k) or "")                                    # noqa: E731

    # -- gate 1: opt-out / undeliverable. HARD: never contact. --------------------
    if truthy(g("outbound_suppressed")):
        return Decision("EXCLUDED", "opted out (outbound_suppressed)", "hard")
    if truthy(g("hs_email_optout")):
        return Decision("EXCLUDED", "opted out (hs_email_optout)", "hard")
    status = g("outbound_status").strip()
    if status in cfg["status_hard_values"]:
        return Decision("EXCLUDED",
                        "opted out" if status == "opted_out" else "bounced", "hard")

    # -- gate 2: outbound status / recycle. SOFT: skip this campaign. -------------
    if status in cfg["status_skip_values"]:
        return Decision("EXCLUDED",
                        "in sequence" if status == "in_sequence" else status, "soft")
    recycle = as_date(g(cfg["recycle_property"]))
    if recycle and recycle > now:
        return Decision("EXCLUDED", f"recycling until {recycle.date()}", "soft")
    if status == "replied":
        # Spec gap, handled conservatively: nothing records WHEN the reply landed, so
        # the freshest activity timestamp stands in for it. With no timestamp at all
        # the reply cannot be dated, and skipping (reversible) beats mailing into a
        # live conversation. See the note in the run summary.
        stamps = [as_date(g(f)) for f in cfg["recency_fields"]]
        newest = max([s for s in stamps if s], default=None)
        window = int(cfg["status_recent_reply_skip_days"])
        if newest is None:
            return Decision("EXCLUDED", "replied (date unknown)", "soft")
        if (now - newest).days < window:
            return Decision("EXCLUDED", "replied recently", "soft")

    # -- gates 3-8: CRM state ----------------------------------------------------
    if g("lifecyclestage").strip() not in cfg["lifecycle_allow"]:
        return Decision("EXCLUDED",
                        f"lifecycle {g('lifecyclestage') or '(empty)'}", "soft")
    if g("has_group").strip().lower() == str(cfg["has_group_exclude_value"]).lower():
        return Decision("EXCLUDED", "existing customer (has_group)", "soft")
    if g(cfg["csm_property"]).strip():
        return Decision("EXCLUDED", "has CSM", "soft")
    owner = g("hubspot_owner_id").strip()
    if owner and owner in owner_ids.values():
        name = next(n for n, i in owner_ids.items() if i == owner)
        return Decision("EXCLUDED", f"owned by {name}", "soft")
    if g("hs_lead_status").strip() in cfg["lead_status_exclude"]:
        return Decision("EXCLUDED", f"lead status {g('hs_lead_status')}", "soft")
    if truthy(g(cfg["sequence_property"])):
        return Decision("EXCLUDED", "in HubSpot sequence", "soft")

    # -- gate 9: recency. Empty means never and passes. ---------------------------
    window = int(cfg["recency_window_days"])
    for f in cfg["recency_fields"]:
        d = as_date(g(f))
        if d and (now - d).days < window:
            return Decision("EXCLUDED", f"active in last {window}d ({f})", "soft")

    return Decision("ELIGIBLE", "", "")


# ---- run ----------------------------------------------------------------------

def read_leads(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Pre-send eligibility filter. Read-only unless --create-missing.")
    ap.add_argument("--leads", required=True, type=pathlib.Path,
                    help="CSV of leads; an 'email' column is required")
    ap.add_argument("--out", type=pathlib.Path,
                    help="annotated CSV, every input lead (default reviews/eligibility-<date>.csv)")
    ap.add_argument("--eligible-out", type=pathlib.Path,
                    help="ELIGIBLE-only CSV for run_generation.py --contacts")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    cfg = load_config()
    if cfg.get("create_missing_contacts"):
        print("ABORT: config sets create_missing_contacts: true, but this script never "
              "writes to HubSpot. Set it to false, or add a separate creation step.",
              file=sys.stderr)
        return 2
    now = dt.datetime.now(dt.timezone.utc)
    hs = HubSpot(env_token())

    # -- guarantee 2: absent is not false ---------------------------------------
    missing = {n: gate for n, gate in GATED.items() if not hs.property_exists(n)}
    if missing:
        print("ABORT: gated properties missing from the portal.", file=sys.stderr)
        for n, gate in sorted(missing.items()):
            print(f"  {n:<34} would silently disable {gate}", file=sys.stderr)
        print("A missing property reads as empty, so its gate passes everybody.",
              file=sys.stderr)
        return 2

    # -- guarantee 3: every excluded owner must resolve --------------------------
    all_owners = hs.owners()
    owner_ids, unresolved = {}, []
    for name in cfg["excluded_owners"]:
        if name in all_owners:
            owner_ids[name] = all_owners[name]
        else:
            unresolved.append(name)
    if unresolved:
        print("ABORT: excluded owners that do not resolve to a HubSpot owner ID:",
              file=sys.stderr)
        for n in unresolved:
            print(f"  {n}", file=sys.stderr)
        print("An unresolved name makes that rep's contacts eligible. Fix the name "
              "in config/pre-send-defaults.md or remove it.", file=sys.stderr)
        return 2

    leads = read_leads(a.leads)
    if a.limit:
        leads = leads[:a.limit]
    if not leads:
        print("no leads in input", file=sys.stderr)
        return 1

    emails, rows = [], []
    for lead in leads:
        e = (lead.get("email") or "").strip().lower()
        if e:
            emails.append(e)
        rows.append({"lead": lead, "email": e})

    props = sorted(set(GATED) | set(CARRY) | {"email", cfg["csm_property"],
                                              cfg["sequence_property"],
                                              cfg["recycle_property"]})
    found = hs.search_by_email(sorted(set(emails)), props) if emails else {}

    out_rows, eligible_rows, counts = [], [], {}
    for r in rows:
        lead, email = r["lead"], r["email"]
        if not email:
            out_rows.append({"email": "", "hubspot_contact_id": "",
                             "decision": "ERROR", "reason": "no email in input row",
                             "exclusion_tier": ""})
            counts["ERROR: no email"] = counts.get("ERROR: no email", 0) + 1
            continue

        p = found.get(email)
        if p is None:
            # Step 4. Leads are assumed to already exist in HubSpot, so this is an
            # assumption violation, not a normal path: nothing was verified against the
            # CRM for this lead and there is nowhere to write its reply status back to.
            # It stays ELIGIBLE (no record means no gate can fail) but is surfaced.
            d = Decision("ELIGIBLE", "NOT IN HUBSPOT - verify before sending")
            p, cid = {}, ""
        else:
            d = evaluate(p, cfg, owner_ids, now)
            cid = p.get("hs_object_id", "")

        key = d.reason or "ELIGIBLE"
        counts[key] = counts.get(key, 0) + 1
        out_rows.append({
            "email": email, "hubspot_contact_id": cid, "decision": d.decision,
            "reason": d.reason, "exclusion_tier": d.tier,
            "notes_last_updated": p.get("notes_last_updated", ""),
            "notes_last_contacted": p.get("notes_last_contacted", ""),
            "hs_last_sales_activity_timestamp":
                p.get("hs_last_sales_activity_timestamp", ""),
            "lifecyclestage": p.get("lifecyclestage", ""),
            "hs_lead_status": p.get("hs_lead_status", ""),
            "owner": p.get("hubspot_owner_id", ""),
            "outbound_status": p.get("outbound_status", ""),
            "outbound_recycle_after": p.get(cfg["recycle_property"], ""),
        })
        if d.decision == "ELIGIBLE":
            # Input CSV wins for the generation signals; HubSpot fills identity gaps.
            eligible_rows.append({
                "hs_object_id": cid,
                "first_name": lead.get("first_name") or p.get("firstname", ""),
                "last_name": lead.get("last_name") or p.get("lastname", ""),
                "email": email,
                "job_title": lead.get("job_title") or p.get("jobtitle", ""),
                "company": lead.get("company") or p.get("company", ""),
                "current_competitor": lead.get("current_competitor", ""),
                "estimated_gmv_usd": lead.get("estimated_gmv_usd", ""),
                "vertical": lead.get("vertical", ""),
            })

    stamp = now.date().isoformat()
    out = a.out or ROOT / "reviews" / f"eligibility-{stamp}.csv"
    elig = a.eligible_out or ROOT / "reviews" / f"eligible-{stamp}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    with elig.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ELIGIBLE_COLUMNS)
        w.writeheader()
        w.writerows(eligible_rows)

    n_elig = sum(1 for r in out_rows if r["decision"] == "ELIGIBLE")
    n_hard = sum(1 for r in out_rows if r["exclusion_tier"] == "hard")
    n_soft = sum(1 for r in out_rows if r["exclusion_tier"] == "soft")
    n_err = sum(1 for r in out_rows if r["decision"] == "ERROR")
    print(f"\n{len(out_rows)} leads in, one row out each ({hs.calls} API calls)")
    print(f"  {n_elig:5} ELIGIBLE  -> {elig}")
    print(f"  {n_hard:5} EXCLUDED hard (never contact)")
    print(f"  {n_soft:5} EXCLUDED soft (skip this campaign, reversible)")
    print(f"  {n_err:5} ERROR")
    print(f"\nby reason:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5} {k}")
    print(f"\nannotated list (all rows, for the review Sheet): {out}")

    absent = [r["email"] for r in out_rows
              if r["reason"].startswith("NOT IN HUBSPOT")]
    if absent:
        print(f"\n!! {len(absent)} ELIGIBLE leads have NO HubSpot record. Leads are "
              f"assumed to exist in HubSpot, so this means the list and the CRM "
              f"disagree —\n   nothing was verified for these, and there is nowhere to "
              f"write their reply status. Check them before sending:")
        for e in absent[:20]:
            print(f"     {e}")
        if len(absent) > 20:
            print(f"     ... and {len(absent) - 20} more (see {out})")

    undated = sum(1 for r in out_rows if r["reason"] == "replied (date unknown)")
    if undated:
        print(f"\n!! {undated} contacts have outbound_status=replied but NO activity "
              f"timestamp. A logged reply should have bumped one, so this points at "
              f"HubSpot\n   activity logging being off for that campaign. Skipped "
              f"conservatively; worth checking the campaign's logging toggle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
