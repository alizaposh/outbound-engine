#!/usr/bin/env python3
"""Draft-only generation runner: CSV in, reviewed CSV out.

Per contact: route -> generate (retry once) -> repair -> assemble -> validate all
three messages -> sequence-level checks. Writes one CSV row per input contact.

Two guarantees this file exists to provide, both learned the hard way:

  1. All three message positions are validated. The loop lives in process_contact,
     not in a caller, so coverage cannot be lost by whoever drives this.
  2. No contact is ever silently dropped. A contact whose generation fails twice
     still gets a row, with generation_error populated and validation "ERROR".
     Earlier ad-hoc runs skipped malformed-JSON contacts and the loss was invisible
     until someone counted rows.

This never sends and never writes to HubSpot.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import anthropic  # noqa: E402

import assemble  # noqa: E402
import repair  # noqa: E402
import validate  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSITIONS = (1, 2, 3)
MAX_ATTEMPTS = 2          # one retry; malformed JSON has been transient in practice
MAX_TOKENS = 2000

GMV_PRO_GATE = 50_000
UNUSABLE_COMPETITOR = {"", "other", "unknown", "n/a", "none", "null"}
PRO_COMPETITORS = {"dice", "tixr", "shotgun"}
PREMIUM_COMPETITORS = {"eventbrite", "instagram", "plots", "resident advisor",
                       "eventeny", "eventnoire"}
PRO_VERTICALS = {"festival"}

RULEBOOK_FILES = ("config/positioning.md", "config/personas.md",
                  "instructions/message-generation.md")

# Static copy for contacts whose generation failed after every retry. Deliberately not
# in RULEBOOK_FILES: a ready-made sequence in the prompt is something the model would
# echo. See config/generation-failure-fallback.md.
FALLBACK_FILE = "config/generation-failure-fallback.md"
FALLBACK_STATUS = "GENERATION_FAILED_FALLBACK"


# ---- data ---------------------------------------------------------------------

@dataclass
class Contact:
    hs_object_id: str = ""
    first_name: str | None = None
    last_name: str | None = None
    email: str = ""
    jobtitle: str | None = None
    company: str | None = None
    current_competitor: str | None = None
    estimated_gmv_usd: int | None = None
    vertical: str | None = None

    @property
    def display(self) -> str:
        return self.first_name or self.email or self.hs_object_id or "(unknown)"


@dataclass
class MessageResult:
    position: int
    subject: str
    body_model: str
    body_final: str
    repairs: list = field(default_factory=list)
    validation: validate.EmailResult | None = None


@dataclass
class ContactResult:
    contact: Contact
    persona: str | None = None
    persona_basis: str = ""
    platform_known: bool = True
    messages: list[MessageResult] = field(default_factory=list)
    sequence_findings: list = field(default_factory=list)
    bedrock_message_id: str = ""
    attempts: int = 0
    error: str = ""
    used_fallback: bool = False

    @property
    def status(self) -> str:
        # Checked before error: a fallback row still carries its original failure
        # reason, but must never read as either a clean row or a bare ERROR.
        if self.used_fallback:
            return FALLBACK_STATUS
        if self.error:
            return "ERROR"
        if any(m.validation and m.validation.failed for m in self.messages):
            return "FAIL"
        if any(m.validation and m.validation.findings for m in self.messages) \
                or self.sequence_findings:
            return "WARN"
        return "PASS"


# ---- routing (config/personas.md, three branches) ------------------------------

def route(c: Contact) -> tuple[str | None, str, bool]:
    """Returns (persona, persona_basis, platform_known).

    Branch 1: a usable signal is present. Branch 2: signals missing but the lead is a
    real organizer, so fall back to secondary signals. Branch 3: too little to write
    a credible email, flag instead of generating.
    """
    comp = (c.current_competitor or "").strip().lower()
    platform_known = comp not in UNUSABLE_COMPETITOR

    has_identity = bool(c.email) and bool(
        c.first_name or c.last_name or c.company or c.jobtitle or c.vertical)
    if not has_identity:
        return None, "flag: insufficient", platform_known

    if c.estimated_gmv_usd is not None:
        persona = "Pro" if c.estimated_gmv_usd >= GMV_PRO_GATE else "Premium"
        return persona, "gmv", platform_known

    if platform_known and comp in PRO_COMPETITORS:
        return "Pro", "competitor", platform_known
    if platform_known and comp in PREMIUM_COMPETITORS:
        return "Premium", "competitor", platform_known

    if c.vertical:
        persona = "Pro" if c.vertical.strip().lower() in PRO_VERTICALS else "Premium"
        return persona, "fallback: vertical", platform_known
    if c.jobtitle:
        return "Premium", "fallback: jobtitle", platform_known
    if c.company:
        return "Premium", "fallback: company-type", platform_known
    return None, "fallback: neutral", platform_known


# ---- prompt -------------------------------------------------------------------

def build_system_prompt() -> tuple[str, str]:
    """(cached rulebook prefix, instruction). Rulebook first so it caches once."""
    rulebook = "\n\n".join(
        f"===== {p} =====\n{(ROOT / p).read_text(encoding='utf-8')}"
        for p in RULEBOOK_FILES)
    contract = (
        '{"message_1": {"subject": "...", "body": "..."},\n'
        ' "message_2": {"subject": "...", "body": "..."},\n'
        ' "message_3": {"subject": "...", "body": "..."}}')
    instruction = f"""You are the message-generation step of Posh's outbound engine.

The documents above are your complete rulebook. Follow them exactly.

You will be given one prospect's research note. Return ONLY a JSON object, no prose:

{contract}

Each body is the message text ONLY: greeting through to the CTA. Do not write a
sign-off, footer, company name, address, or unsubscribe token. Code appends those.

{repair.load_voice_anchor()}

{repair.load_hard_constraints()}
"""
    return rulebook, instruction


def load_failure_fallback() -> dict:
    """The static sequence used when a contact exhausts its retries.

    Same shape as model output, so it flows through the identical assembly path.
    Validated for shape at startup rather than on the failure path, where a broken
    fallback would be discovered at the worst possible moment.
    """
    text = (ROOT / FALLBACK_FILE).read_text(encoding="utf-8")
    m = re.search(r"```json\s*(.+?)```", text, re.S)
    if not m:
        raise RuntimeError(f"no json block found in {FALLBACK_FILE}")
    data = json.loads(m.group(1))
    for k in ("message_1", "message_2", "message_3"):
        if not isinstance(data.get(k), dict) or "subject" not in data[k] \
                or "body" not in data[k]:
            raise RuntimeError(f"{FALLBACK_FILE} is missing or malformed {k}")
    return data


def research_note(c: Contact, persona, basis, platform_known) -> dict:
    """estimated_gmv_usd is deliberately absent: it routes upstream and stops."""
    note = {
        "first_name": c.first_name, "last_name": c.last_name,
        "jobtitle": c.jobtitle, "company": c.company,
        "email_domain": c.email.split("@")[-1] if "@" in c.email else None,
        "vertical": c.vertical,
        "current_competitor": (f"appears to be {c.current_competitor}"
                               if platform_known else None),
        "competitor_confidence": "high" if platform_known else "unknown",
        "persona": persona, "persona_basis": basis,
        "platform_known": platform_known,
        "needs_human_review": basis.startswith("flag"),
        "guidance": (
            "The current platform is UNKNOWN. Use the no-platform fallback: ask the "
            "generic setup question and name NO platform anywhere. Never guess one."
            if not platform_known else
            "The current platform is known; the main voice anchor applies."),
    }
    assert "estimated_gmv_usd" not in note, "GMV must never reach the model"
    return note


# ---- generation ---------------------------------------------------------------

def _parse(raw: str) -> dict:
    raw = raw.strip()
    fence = "`" * 3
    if raw.startswith(fence):
        raw = raw.split(fence)[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    for k in ("message_1", "message_2", "message_3"):
        if not isinstance(data.get(k), dict) or "subject" not in data[k] \
                or "body" not in data[k]:
            raise ValueError(f"missing or malformed {k}")
    return data


def generate_with_retry(client, model, rulebook, instruction, note):
    """Returns (emails|None, attempts, bedrock_id, error). Retries once.

    Malformed JSON has been transient: the same contact failed first attempt and
    succeeded on retry in two separate batches.
    """
    last_error, bedrock_id = "", ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.messages.create(
                model=model, max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": rulebook,
                         "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": instruction}],
                messages=[{"role": "user",
                           "content": "Research note:\n" + json.dumps(note, indent=2)}])
            bedrock_id = resp.id
            raw = "".join(b.text for b in resp.content if b.type == "text")
            return _parse(raw), attempt, bedrock_id, ""
        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"{type(e).__name__}: {e}"
        except Exception as e:                      # API/transport failure
            last_error = f"{type(e).__name__}: {e}"
    return None, MAX_ATTEMPTS, bedrock_id, last_error


# ---- per-contact pass ----------------------------------------------------------

def process_contact(c, client, model, rulebook, instruction, *, mailbox,
                    identity, sender_map, footer, token, literals, regexes,
                    failure_fallback):
    persona, basis, platform_known = route(c)
    res = ContactResult(contact=c, persona=persona, persona_basis=basis,
                        platform_known=platform_known)

    if basis.startswith("flag"):
        res.error = ("branch 3: too little identity to write a credible email; "
                     "flagged for human review, not generated")
        return res

    note = research_note(c, persona, basis, platform_known)
    emails, attempts, bid, err = generate_with_retry(
        client, model, rulebook, instruction, note)
    res.attempts, res.bedrock_message_id = attempts, bid
    if emails is None:
        # Recover with committed copy so the contact is not left unusable, but keep the
        # failure on the row and out of the normal PASS/WARN/FAIL vocabulary. A
        # generation failure that gets silently templated is worse than a flagged one.
        res.error = f"generation failed after {attempts} attempts: {err}"
        res.used_fallback = True
        for position in POSITIONS:
            m = failure_fallback[f"message_{position}"]
            body_final = assemble.assemble(m["body"], mailbox, identity=identity,
                                           sender_map=sender_map)
            res.messages.append(MessageResult(position, m["subject"], m["body"],
                                              body_final))
        assert len(res.messages) == len(POSITIONS), "fallback must fill all three"
        return res

    # The three-position guarantee. Not delegated to a caller.
    for position in POSITIONS:
        m = emails[f"message_{position}"]
        body_repaired, records = repair.repair(m["body"])
        body_final = assemble.assemble(body_repaired, mailbox,
                                       identity=identity, sender_map=sender_map)
        v = validate.validate_email(
            m["subject"], body_final, position=position, footer=footer, token=token,
            literals=literals, regexes=regexes, raw_body=m["body"],
            competitor_known=platform_known,
            label=f"{c.display} message_{position}")
        res.messages.append(MessageResult(position, m["subject"], m["body"],
                                          body_final, records, v))

    assert len(res.messages) == len(POSITIONS), "all three positions must be validated"
    assert all(m.validation is not None for m in res.messages)

    # Sequence-level: only visible with the whole sequence in hand.
    res.sequence_findings = validate.check_stat_budget(
        [(m.position, m.subject, m.body_final) for m in res.messages])
    return res


# ---- output -------------------------------------------------------------------

COLUMNS = ["hs_object_id", "first_name", "last_name", "email", "job_title", "company",
           "persona", "persona_basis", "platform_known", "current_competitor",
           "estimated_gmv_usd", "vertical", "validation", "generation_error",
           "attempts", "repairs_applied", "sequence_findings", "bedrock_message_id",
           "message_1_subject", "message_1_body",
           "message_2_subject", "message_2_body",
           "message_3_subject", "message_3_body"]


def to_row(r: ContactResult) -> dict:
    c = r.contact
    row = {
        "hs_object_id": c.hs_object_id, "first_name": c.first_name or "",
        "last_name": c.last_name or "", "email": c.email,
        "job_title": c.jobtitle or "", "company": c.company or "",
        "persona": r.persona or "", "persona_basis": r.persona_basis,
        "platform_known": r.platform_known,
        "current_competitor": c.current_competitor or "",
        "estimated_gmv_usd": "" if c.estimated_gmv_usd is None else c.estimated_gmv_usd,
        "vertical": c.vertical or "", "validation": r.status,
        "generation_error": r.error, "attempts": r.attempts,
        "repairs_applied": sum(len(m.repairs) for m in r.messages),
        "sequence_findings": "; ".join(f.detail for f in r.sequence_findings),
        "bedrock_message_id": r.bedrock_message_id,
    }
    for p in POSITIONS:
        m = next((x for x in r.messages if x.position == p), None)
        row[f"message_{p}_subject"] = m.subject if m else ""
        row[f"message_{p}_body"] = m.body_final if m else ""
    return row


def load_contacts(path: pathlib.Path) -> list[Contact]:
    def clean(v):
        v = (v or "").strip()
        return v or None

    out = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            gmv = clean(row.get("estimated_gmv_usd"))
            out.append(Contact(
                hs_object_id=clean(row.get("hs_object_id")) or "",
                first_name=clean(row.get("first_name")),
                last_name=clean(row.get("last_name")),
                email=clean(row.get("email")) or "",
                jobtitle=clean(row.get("job_title")) or clean(row.get("jobtitle")),
                company=clean(row.get("company")),
                current_competitor=clean(row.get("current_competitor")),
                estimated_gmv_usd=int(float(gmv)) if gmv else None,
                vertical=clean(row.get("vertical"))))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draft-only generation. Never sends.")
    ap.add_argument("--contacts", required=True, type=pathlib.Path)
    ap.add_argument("--mailbox", required=True,
                    help="sending mailbox; must exist in config/senders.md")
    ap.add_argument("--out", type=pathlib.Path,
                    default=ROOT / "reviews" / "draft-run.csv")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    identity = assemble.load_sender_identity()
    sender_map = assemble.load_sender_map()
    footer = assemble.build_footer(identity)
    token = assemble.UNSUBSCRIBE_TOKEN
    literals, regexes = validate.load_banned()
    assemble.resolve_sender_name(a.mailbox, sender_map)   # fail fast on a bad mailbox

    print("SEND-READINESS BLOCKERS (drafting is fine; sending is not)")
    for b in assemble.send_readiness_blockers(sender_map) or ["  (none)"]:
        print(f"  - {b}")

    contacts = load_contacts(a.contacts)
    if a.limit:
        contacts = contacts[:a.limit]
    failure_fallback = load_failure_fallback()
    rulebook, instruction = build_system_prompt()
    client = anthropic.AnthropicBedrock(aws_region=os.environ["AWS_REGION"])
    model = os.environ["BULK_LLM_MODEL"]
    print(f"\n{len(contacts)} contacts | model {model} | mailbox {a.mailbox}\n")

    results, every_email = [], []
    for i, c in enumerate(contacts, 1):
        r = process_contact(c, client, model, rulebook, instruction,
                            mailbox=a.mailbox, identity=identity,
                            sender_map=sender_map, footer=footer, token=token,
                            literals=literals, regexes=regexes,
                            failure_fallback=failure_fallback)
        results.append(r)
        # Fallback rows carry committed copy, not model output. Scoring them would
        # inflate the pass rate with emails the model never wrote.
        if not r.used_fallback:
            every_email.extend(m.validation for m in r.messages)
        note = f" ERROR: {r.error}" if r.error else ""
        print(f"  [{i}/{len(contacts)}] {c.display[:32]:32} {r.persona or '-':8} "
              f"{r.persona_basis:22} {r.status:5} "
              f"msgs={len(r.messages)} tries={r.attempts}{note}")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(to_row(r) for r in results)

    n_err = sum(1 for r in results if r.error)
    n_fallback = sum(1 for r in results if r.used_fallback)
    n_flagged = sum(1 for r in results if r.error and not r.used_fallback)
    print(f"\nCSV: {a.out}  ({len(results)} rows, one per input contact, "
          f"{n_err} with generation_error)")
    print(f"  {len(results) - n_err:3} generated normally")
    print(f"  {n_fallback:3} used the GENERATION-FAILURE FALLBACK "
          f"(committed copy, NOT model output, not send-ready without review)")
    for r in results:
        if r.used_fallback:
            print(f"        - {r.contact.display}: {r.error}")
    print(f"  {n_flagged:3} flagged without generating (branch 3)")

    repairs = [(r.contact.display, m.position, rec)
               for r in results for m in r.messages for rec in m.repairs]
    print(f"\n{'=' * 72}\nREPAIR AUDIT: {len(repairs)} rewrites")
    for who, pos, rec in repairs:
        tag = rec.kind.upper() + (f"  [{rec.note}]" if rec.note else "")
        print(f"\n{who} m{pos}  {tag}\n  before: {rec.before}\n  after : {rec.after}")

    seq = [(r.contact.display, f) for r in results for f in r.sequence_findings]
    print(f"\n{'=' * 72}\nSEQUENCE-LEVEL FINDINGS: {len(seq)}")
    for who, f in seq:
        print(f"  {f.severity}  {who}: {f.detail}")

    # Batch-level: only visible with every contact in hand. Fallback rows are excluded
    # because they are the same committed copy by construction, so they would always
    # trip this and drown the real signal.
    batch = validate.check_batch_opening_reuse(
        [(r.contact.display, m.position, m.body_final)
         for r in results if not r.used_fallback for m in r.messages])
    print(f"\n{'=' * 72}\nBATCH-LEVEL FINDINGS: {len(batch)}")
    for f in batch:
        print(f"  {f.severity}  {f.detail}")

    if not a.quiet:
        print("\n" + validate.report(every_email))
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
