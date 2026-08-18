#!/usr/bin/env python3
"""Validate generated emails against the committed copy rules.

Runs on every email before it reaches human review. FAIL findings block a campaign
from being review-ready; WARN findings surface for human judgment.

Each check exists because a rule in config/ or instructions/ was broken in practice.
Checks are independent: one failure never suppresses another, so a reviewer sees
every problem in one pass instead of fixing them one at a time.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANNED = ROOT / "config" / "banned-phrases.md"

FAIL, WARN = "FAIL", "WARN"

# Approved stat wordings, from config/positioning.md. Any sentence containing 13% or
# 40% must match one of these. Restatements and hedges are what this catches.
APPROVED_STAT_PATTERNS = [
    re.compile(r"13%\s+of\s+(its|their)\s+tickets\s+through\s+the\s+posh\s+marketplace", re.I),
    re.compile(r"40%\s+better\s+than\s+other\s+platforms", re.I),
]
STAT_MENTION = re.compile(r"\b(13|40)\s*%")
HEDGES = re.compile(r"\b(about|around|roughly|approximately|up\s+to|nearly|over|~)\s*$", re.I)

# Cleared customers, from config/positioning.md.
CLEARED_CUSTOMERS = ["Caché Life", "Cache Life", "We Belong Here", "NARC Run Club", "NARC"]
# Only NARC has cleared figures; a numeral next to the other two means invention.
NO_FIGURE_CUSTOMERS = ["Caché Life", "Cache Life", "We Belong Here"]

# Length is a target, never a gate: check_length only ever emits WARN.
# Positional: messages 1 and 2 carry the package pitch; message 3 is a breakup.
LENGTH_TARGETS = {1: (80, 110), 2: (80, 110), 3: (40, 70)}

# Subject word count. Widened from 2-5 with the warmer voice, which pulls subjects
# toward short phrases rather than fragments.
SUBJECT_WORDS = (2, 6)

# Platform names that must never appear when current_competitor is unknown.
# Naming a platform the sender did not actually verify proves they did not look.
PLATFORM_NAMES = [
    "Eventbrite", "Resident Advisor", "RA", "DICE", "Dice", "Tixr", "Shotgun",
    "Plots", "TicketFairy", "Ticket Fairy", "Eventeny", "Eventnoire",
    "Ticketmaster", "Universe", "Ticketor", "Luma", "Partiful",
]

# Canonical acronyms and initialisms keep their standard casing in subject lines.
# Authoritative list; message-generation.md hard constraint 3 points here.
CANONICAL_ACRONYMS = {"RA", "NYC", "DJ", "RSVP", "VIP", "EDM", "LA", "SF", "NY",
                      "DM", "US", "UK", "QR", "AI", "B2B", "VIPs"}

DASHES = {"—": "em dash", "–": "en dash"}
SIGNOFF_HINTS = re.compile(r"^\s*(best|thanks|cheers|regards|sincerely)\b[,.]?\s*$", re.I | re.M)


@dataclass
class Finding:
    check: str
    severity: str
    detail: str


@dataclass
class EmailResult:
    label: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(f.severity == FAIL for f in self.findings)

    @property
    def status(self) -> str:
        if self.failed:
            return "FAIL"
        return "WARN" if self.findings else "PASS"


def load_banned(path: pathlib.Path = BANNED) -> tuple[list[str], list[re.Pattern]]:
    """Parse literal and regex entries from config/banned-phrases.md."""
    if not path.exists():
        raise RuntimeError(f"banned-phrases.md not found at {path}")
    literals: list[str] = []
    regexes: list[re.Pattern] = []
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        low = line.strip().lower()
        if low.startswith("## literal"):
            section = "literal"
            continue
        if low.startswith("## regex"):
            section = "regex"
            continue
        if low.startswith("## "):
            section = None
            continue
        m = re.match(r"^\s*-\s*`(.+)`\s*$", line)
        if not m or section is None:
            continue
        entry = m.group(1)
        if section == "literal":
            literals.append(entry)
        else:
            try:
                regexes.append(re.compile(entry, re.I))
            except re.error as e:
                raise RuntimeError(f"Bad regex in banned-phrases.md: {entry!r} ({e})")
    return literals, regexes


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


# ---- individual checks --------------------------------------------------------

def check_no_dashes(subject: str, body: str) -> list[Finding]:
    out = []
    for ch, name in DASHES.items():
        for field_name, text in (("subject", subject), ("body", body)):
            if ch in text:
                i = text.index(ch)
                out.append(Finding("no_dashes", FAIL,
                    f"{name} in {field_name}: ...{text[max(0,i-30):i+30]!r}..."))
    return out


def check_approved_stats(subject: str, body: str) -> list[Finding]:
    out = []
    for sent in _sentences(f"{subject}\n{body}"):
        if not STAT_MENTION.search(sent):
            continue
        if not any(p.search(sent) for p in APPROVED_STAT_PATTERNS):
            out.append(Finding("approved_stats", FAIL,
                f"13%/40% stat not in approved wording: {sent!r}"))
            continue
        for m in STAT_MENTION.finditer(sent):
            if HEDGES.search(sent[:m.start()]):
                out.append(Finding("approved_stats", FAIL,
                    f"hedged stat (stats are platform averages, quoted exactly): {sent!r}"))
    return out


def check_subject_shape(subject: str, body: str) -> list[Finding]:
    out = []
    words = subject.split()
    lo, hi = SUBJECT_WORDS
    if not lo <= len(words) <= hi:
        out.append(Finding("subject_shape", FAIL,
            f"subject is {len(words)} words, rule is {lo} to {hi}: {subject!r}"))
    bad = []
    for w in words:
        stripped = w.strip(".,!?:;'\"()")
        if not any(c.isupper() for c in stripped):
            continue
        # Canonical acronyms keep their casing, including a plural "s" (DMs).
        if stripped.upper() in CANONICAL_ACRONYMS:
            continue
        if stripped.endswith("s") and stripped[:-1].upper() in CANONICAL_ACRONYMS:
            continue
        bad.append(stripped)
    if bad:
        out.append(Finding("subject_shape", FAIL,
            f"subject must be lowercase except canonical acronyms; offending "
            f"word(s) {bad}: {subject!r}"))
    return out


def check_footer(subject: str, body: str, *, footer: str, token: str) -> list[Finding]:
    out = []
    if not body.rstrip().endswith(footer):
        out.append(Finding("footer_present", FAIL,
            "body does not end with the exact footer block"))
    n = body.count(token)
    if n != 1:
        out.append(Finding("footer_present", FAIL,
            f"unsubscribe token appears {n} times, expected exactly 1"))
    return out


def check_no_real_optout_url(subject: str, body: str) -> list[Finding]:
    out = []
    for m in re.finditer(r"(https?://\S+|mailto:\S+)", body):
        out.append(Finding("no_real_optout_url", FAIL,
            f"literal URL or mailto in body, opt-out must be the merge tag: {m.group(0)!r}"))
    return out


def check_banned(subject: str, body: str, *, literals, regexes) -> list[Finding]:
    out = []
    hay = f"{subject}\n{body}"
    low = hay.lower()
    for phrase in literals:
        if phrase.lower() in low:
            out.append(Finding("banned_phrases", FAIL, f"banned phrase: {phrase!r}"))
    for rx in regexes:
        m = rx.search(hay)
        if m:
            out.append(Finding("banned_phrases", FAIL,
                f"banned pattern {rx.pattern!r} matched {m.group(0)!r}"))
    return out


def check_gmv_leak(subject: str, body: str) -> list[Finding]:
    out = []
    for m in re.finditer(r"\$\s?\d[\d,.]*\s*(k|m|million|thousand)?", f"{subject} {body}", re.I):
        out.append(Finding("gmv_leak", FAIL,
            f"currency figure in copy; estimated_gmv_usd must never be written: {m.group(0)!r}"))
    return out


def check_case_studies(subject: str, body: str) -> list[Finding]:
    out = []
    hay = f"{subject}\n{body}"
    named = {c for c in CLEARED_CUSTOMERS if c.lower() in hay.lower()}
    # Treat "NARC" and "NARC Run Club" as one customer.
    canonical = {("NARC Run Club" if n.startswith("NARC") else
                  "Caché Life" if n.lower().startswith("cach") else n) for n in named}
    if len(canonical) > 1:
        out.append(Finding("case_study_rules", FAIL,
            f"more than one case study in a single email: {sorted(canonical)}"))
    for cust in NO_FIGURE_CUSTOMERS:
        for m in re.finditer(re.escape(cust), hay, re.I):
            window = hay[max(0, m.start() - 120): m.end() + 120]
            if re.search(r"\d", window.replace(cust, "")):
                out.append(Finding("case_study_rules", FAIL,
                    f"numeral near {cust!r}, which has no cleared figures: {window.strip()!r}"))
                break
    return out


def check_no_invented_platform(subject: str, body: str, *,
                               competitor_known: bool) -> list[Finding]:
    """When the prospect's platform is unknown, no platform may be named.

    Guessing a competitor from the vertical or the company name is the most expensive
    error in a cold email: a confidently wrong platform proves the sender never
    looked. No data means ask generically.
    """
    if competitor_known:
        return []
    out = []
    hay = f"{subject}\n{body}"
    for name in PLATFORM_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", hay):
            out.append(Finding("invented_platform", FAIL,
                f"named {name!r} but current_competitor is unknown for this contact; "
                f"the no-platform fallback must ask the generic setup question"))
    return out


def check_model_wrote_footer(subject: str, raw_body: str, *, footer_markers) -> list[Finding]:
    """Run against the RAW model output, before assembly. Detects prompt drift."""
    out = []
    for marker in footer_markers:
        if marker.lower() in raw_body.lower():
            out.append(Finding("model_wrote_footer", WARN,
                f"model emitted footer content ({marker!r}); assembly owns this now, "
                f"so the prompt has drifted"))
    if SIGNOFF_HINTS.search(raw_body):
        out.append(Finding("model_wrote_footer", WARN,
            "model emitted a sign-off line; assembly owns this now"))
    return out


def check_length(subject: str, body: str, *, position: int, footer: str) -> list[Finding]:
    """Word counts exclude the assembled sign-off and footer."""
    copy = body.replace(footer, "")
    copy = re.sub(r"\n\s*\w+\s*\nPosh\s*$", "", copy.strip())
    n = len(copy.split())
    lo, hi = LENGTH_TARGETS.get(position, LENGTH_TARGETS[1])
    if not lo <= n <= hi:
        return [Finding("length", WARN,
            f"email {position} is {n} words, target is {lo} to {hi}")]
    return []


# ---- driver -------------------------------------------------------------------

def validate_email(subject: str, body: str, *, position: int, footer: str, token: str,
                   literals, regexes, raw_body: str | None = None,
                   label: str = "", competitor_known: bool = True) -> EmailResult:
    res = EmailResult(label=label or f"message_{position}")
    res.findings += check_no_dashes(subject, body)
    res.findings += check_approved_stats(subject, body)
    res.findings += check_subject_shape(subject, body)
    res.findings += check_footer(subject, body, footer=footer, token=token)
    res.findings += check_no_real_optout_url(subject, body)
    res.findings += check_banned(subject, body, literals=literals, regexes=regexes)
    res.findings += check_gmv_leak(subject, body)
    res.findings += check_case_studies(subject, body)
    res.findings += check_no_invented_platform(subject, body,
                                               competitor_known=competitor_known)
    res.findings += check_length(subject, body, position=position, footer=footer)
    if raw_body is not None:
        markers = [m for m in footer.splitlines() if m.strip()]
        res.findings += check_model_wrote_footer(subject, raw_body, footer_markers=markers)
    return res


def report(results: list[EmailResult]) -> str:
    """Human-readable summary. Says plainly what is not machine-checked."""
    lines = ["=" * 72, "VALIDATION REPORT", "=" * 72]
    n_fail = sum(1 for r in results if r.failed)
    for r in results:
        lines.append(f"\n[{r.status}] {r.label}")
        for f in r.findings:
            lines.append(f"    {f.severity}  {f.check}: {f.detail}")
        if not r.findings:
            lines.append("    (no findings)")
    lines += [
        "", "-" * 72,
        f"{len(results) - n_fail} of {len(results)} emails passed. "
        f"{n_fail} failed.",
        "BATCH IS NOT REVIEW-READY." if n_fail else "Batch is review-ready.",
        "",
        "Not machine-checked, still needs human review:",
        "  - one clear CTA per email (question marks are too noisy a proxy)",
        "  - whether a cited case study is genuinely relevant to this prospect",
        "  - whether the personalization line is actually specific to them",
        "  - whether a competitor reference is phrased so a wrong guess still lands",
    ]
    return "\n".join(lines)
