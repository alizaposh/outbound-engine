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

# NO numeric performance stat is approved (retired 2026-08-25: the figures were
# inaccurate and the reps did not use them). The list stays as the seam a future
# approved wording would go into; empty means every stat mention fails.
APPROVED_STAT_PATTERNS: list = []
# Deliberately ANY percentage, not just the two retired figures. The rule is "no numeric
# stats", so a future invented "converts 30% better" must fail too: matching only 13|40
# would let anything else through because nothing would be looking for it.
# [ \t]* not \s*, so it cannot span a newline, and a negative lookahead for the
# unsubscribe tag. Without both, the footer's ZIP code followed by
# "%unsubscribe-text%" on the next line was read as a percentage stat, so every
# email reported a phantom stat mention.
STAT_MENTION = re.compile(r"\b\d+[ \t]*%(?!unsubscribe)")

# Cleared customers, from config/positioning.md.
# Cleared to name in cold outbound. Extended 2026-09-01 on explicit sign-off from the
# person running outbound: We Met IRL, Palm Tree Festival and VibeApple were added, the
# original three kept.
#
# NEVER NAMEABLE, because they are NOT CUSTOMERS. Confirmed 2026-09-02 by the person
# running outbound: "not actual customers, we should not reference them ever." The SDR's
# copy spec listed them as comparables for brand-led prospects, which would have put a
# FABRICATED customer claim into cold email to strangers. They are banned by name in
# FABRICATED_CUSTOMERS below rather than merely left out of the cleared list, so the
# failure says why.
CLEARED_CUSTOMERS = ["Caché Life", "Cache Life", "We Belong Here", "NARC Run Club", "NARC",
                     "We Met IRL", "Palm Tree Festival", "VibeApple"]
# Only NARC has cleared figures; a numeral next to any other named customer means
# invention. The three added in 2026-09 have no cleared figures either.
NO_FIGURE_CUSTOMERS = ["Caché Life", "Cache Life", "We Belong Here",
                       "We Met IRL", "Palm Tree Festival", "VibeApple"]

# Length is a target, never a gate: check_length only ever emits WARN.
# Positional: messages 1 and 2 carry one angle each; message 3 is a breakup.
# Recalibrated twice, downward both times.
#   original      {1,2: (80,110), 3: (40,70)}
#   2026-08-25    {1,2: (45,90),  3: (20,50)}
#   2026-08-26a   {1: (35,65),  2: (30,60), 3: (18,42)}
#   2026-08-26b   below
# The 65-word ceiling was too tight and cost more than it saved. Squeezed to fit, email 1
# lost the concrete middle that carried its tone and read "cobbled together". The email
# the sales lead actually endorsed runs about 85 words of body: it names the vertical and
# city, lists the three things that scatter (guest lists, payouts, promotion), and closes
# with a "so ..." consequence. Length was never the real problem; vagueness was. A longer
# concrete email beats a short choppy one, so the ceiling is set around that email.
#   2026-09-01    {1: (35,75), 2: (40,90), 3: (10,30)}  SDR spec caps
# Note email 2's ceiling went UP, the only one that did: it now carries the company
# proof and both levers, which email 1 deliberately withholds.
LENGTH_TARGETS = {1: (35, 75), 2: (40, 90), 3: (10, 30)}

# Subject word count. Widened 2-5 -> 2-6 -> 2-7 as the warmer SDR voice settled, then to
# 2-8 on 2026-08-26: organization names on this list run long ("If You Know You Know" is
# four words on its own), and a subject naming the organizer is worth more than a word
# saved. It pulls subjects toward short natural phrases rather than clipped fragments.
SUBJECT_WORDS = (2, 8)

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

# Quantified commercial terms, from config/positioning.md ("Commercial terms").
# The existence of a tailored offer is approved copy; its contents are not. Nobody has
# priced the prospect at cold-email time, so a named term is one a human later has to
# honor or walk back. That outranks a clumsy CTA, so this is a hard FAIL.
# Deliberately does NOT match the approved vague form: "financial incentives" bundled
# with the rest of the package, as the voice anchor writes it.
COMMERCIAL_TERMS = [
    re.compile(r"\b(lower|lowered|reduced|reduce|discounted|discount|cheaper|cut|"
               r"waive[ds]?|waiving)\s+(the\s+|your\s+|our\s+)?"
               r"(platform\s+|ticket\s+|per[-\s]ticket\s+|service\s+)?"
               r"(fee|fees|rate|rates|pricing|price|prices|commission|commissions)\b", re.I),
    re.compile(r"\b(fee|fees|rate|rates|pricing|commission|commissions)\b[^.!?]{0,40}?"
               r"\b(waived|reduced|lowered|discounted|cut)\b", re.I),
    re.compile(r"\b(flat|account|onboarding|sign[-\s]?up|signup|starting)\s+credit\b", re.I),
    re.compile(r"\bcredits?\s+(toward|towards|on|against)\b", re.I),
    re.compile(r"\b(free|complimentary|no[-\s]cost)\s+(first\s+)?(month|quarter|trial)\b", re.I),
    re.compile(r"\b(first|next)\s+(month|event|events)\b[^.!?]{0,20}?\bfree\b", re.I),
    re.compile(r"\b\d+\s*(%|percent)\s+(off|lower|less|reduced|cheaper)\b", re.I),
    re.compile(r"\bpercent\s+off\b", re.I),
    re.compile(r"\bno\s+(platform\s+|ticket\s+|service\s+)?fees?\b", re.I),
    re.compile(r"\$\s?\d[\d,.]*\s*(k\b|credit|off|back)", re.I),
]

# Urgency implies terms that expire, which implies terms. Only fires next to offer
# language, so "your plans this quarter" is fine. "this year" is absent on purpose:
# the voice anchor says "putting together very competitive offers this year".
TIME_BOXED = re.compile(
    r"\b(this\s+(quarter|month)|your\s+first\s+month|first\s+month|"
    r"next\s+\d+\s+days|limited\s+time|through\s+the\s+end\s+of\s+(the\s+)?(month|quarter)|"
    r"before\s+the\s+end\s+of\s+(the\s+)?(month|quarter))\b", re.I)
OFFER_CONTEXT = re.compile(
    r"\b(offer|offers|deal|deals|incentive|incentives|pricing|price|credit|credits|"
    r"fee|fees|rate|rates|discount|promo|promotion|proposal|package)\b", re.I)

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
    """No numeric performance stat is approved, so any percentage is a FAIL.

    The hedge check that used to live here is gone with the approved wordings: when
    nothing may be quoted, there is no such thing as quoting it loosely.
    """
    out = []
    for sent in _sentences(f"{subject}\n{body}"):
        if not STAT_MENTION.search(sent):
            continue
        if any(p.search(sent) for p in APPROVED_STAT_PATTERNS):
            continue                      # empty today; the seam for a future approval
        out.append(Finding("approved_stats", FAIL,
            f"no numeric performance stats are approved; describe advantages "
            f"qualitatively: {sent!r}"))
    return out


def _name_tokens(names) -> set[str]:
    """Words drawn from this contact's own proper nouns, lowercased.

    An organizer's brand name is a legitimate proper noun even when it breaks the
    casing rule: "the LAB" is all caps and "LAB's" is a possessive of it, and neither
    is shouting. Without this the subject "quick question about the LAB's ticketing"
    FAILs, which is correct copy failing a rule aimed at marketing-headline casing.
    """
    out = set()
    for n in names or ():
        for w in re.findall(r"[\w'&-]+", str(n)):
            out.add(w.lower().removesuffix("'s"))
        # Also the whole chunk with punctuation removed, so a name carrying internal
        # punctuation matches as one word. "Mic.RO" tokenises to {mic, ro} above, which
        # never matches the subject word "Mic.RO"; this adds "micro", and _norm_token
        # normalises the subject word the same way.
        for chunk in str(n).split():
            flat = re.sub(r"[^0-9A-Za-z]", "", chunk).lower()
            if flat:
                out.add(flat)
    return out


def _norm_token(word: str) -> str:
    """A subject word reduced to the same shape as _name_tokens entries."""
    return re.sub(r"[^0-9A-Za-z']", "", word).lower().removesuffix("'s")


def check_subject_shape(subject: str, body: str, *, position: int = 1,
                        allowed_names=()) -> list[Finding]:
    """Shape-check the subject. Emails 2 and 3 are threaded replies and inherit the
    thread subject, so an EMPTY subject is correct for them and skips the check.

    Two things this deliberately still catches: an empty subject on email 1 (FAIL, a
    threaded sequence still needs its opener subject), and a NON-empty subject on 2 or 3
    (shape-checked as normal, so a stray invented subject does not slip through).

    Casing (revised 2026-08-25): lowercase is the house style, with three carve-outs.
    CANONICAL_ACRONYMS keep their casing, and a normal capitalized proper noun
    ("Philadeep") is allowed, because company and venue names appear in real subjects
    and lowercasing them looked broken. Still FAIL: ALL CAPS words, mixed-case oddities
    like "eventBrite", and a Title Cased subject, which is the marketing-headline
    register the rule exists to prevent.
    """
    out = []
    known = _name_tokens(allowed_names)
    words = subject.split()
    if not words and position in (2, 3):
        return out
    lo, hi = SUBJECT_WORDS
    # The prospect's own name counts as ONE word however long it is. "If You Know You
    # Know" is a five-word organization, and counting each token made a tight subject
    # read as nine words and FAIL. The cap exists to stop rambling subjects, not to
    # penalise a contact for their band name.
    billable = [w for w in words if _norm_token(w) not in known]
    effective = len(billable) + (1 if len(billable) < len(words) else 0)
    if not lo <= effective <= hi:
        detail = (f"subject is {effective} words, rule is {lo} to {hi}"
                  + (f" (the prospect's name counted as one)" if effective != len(words) else "")
                  + f": {subject!r}")
        out.append(Finding("subject_shape", FAIL, detail))
    bad = []
    capitalized = []          # words starting uppercase, for the Title Case check below
    alpha_words = []
    for w in words:
        stripped = w.strip(".,!?:;'\"()")
        if not stripped or not any(c.isalpha() for c in stripped):
            continue
        alpha_words.append(stripped)
        # A word from this contact's own name or organization is a proper noun by
        # definition, whatever its casing. Possessives normalise: LAB's -> lab.
        if (stripped.lower().removesuffix("'s") in known
                or _norm_token(stripped) in known):
            if stripped[0].isupper():
                capitalized.append(stripped)
            continue
        if stripped[0].isupper():
            capitalized.append(stripped)
        if not any(c.isupper() for c in stripped):
            continue
        # Canonical acronyms keep their casing, including a plural "s" (DMs).
        if stripped.upper() in CANONICAL_ACRONYMS:
            continue
        if stripped.endswith("s") and stripped[:-1].upper() in CANONICAL_ACRONYMS:
            continue
        # ALL CAPS is shouting, or an acronym nobody approved. Single letters are
        # exempt: "I" and initials are not what this rule is for.
        letters = [c for c in stripped if c.isalpha()]
        if len(letters) > 1 and all(c.isupper() for c in letters):
            bad.append(stripped)
            continue
        # A normal capitalized proper noun is allowed: company, venue, and person names
        # are real words in a subject, and forcing "philadeep" lowercase looked broken.
        # Shape required is strict: one leading capital, everything after it lowercase.
        if stripped[0].isupper() and stripped[1:] == stripped[1:].lower():
            continue
        bad.append(stripped)        # anything else, e.g. "eventBrite", "MailChimp"
    if bad:
        out.append(Finding("subject_shape", FAIL,
            f"subject must be lowercase except canonical acronyms and proper nouns; "
            f"offending word(s) {bad}: {subject!r}"))
    # Title Case is the thing the lowercase rule exists to stop: a subject where every
    # word is capitalized reads like a marketing headline, not like a person typing.
    # Proper nouns are allowed individually, so this aggregate check is what still
    # catches "Compare Your Ticketing Setup Today".
    if len(alpha_words) >= 2 and len(capitalized) == len(alpha_words):
        out.append(Finding("subject_shape", FAIL,
            f"subject is Title Cased (every word capitalized); write it as a person "
            f"would type it: {subject!r}"))
    return out


SENTENCE_END = re.compile(r"[.!?]['\")]?(?:\s|$)")


def _count_sentences(para: str) -> int:
    """Sentence count, tolerant of the things that are not sentence ends.

    Decimals, initials, and common abbreviations are masked first so "15 min." or
    "e.g." does not read as a boundary.
    """
    masked = re.sub(r"\d\.\d", "0 0", para)
    masked = re.sub(r"\b(e\.g|i\.e|Mr|Mrs|Ms|Dr|vs|etc|approx|no)\.", r"\1 ", masked, flags=re.I)
    masked = re.sub(r"\b[A-Z]\.", "X ", masked)          # initials
    return len(SENTENCE_END.findall(masked.strip())) or (1 if masked.strip() else 0)


MIDDLE_MAX_SENTENCES = 2


def check_middle_paragraph(subject: str, body: str, *, footer: str) -> list[Finding]:
    """The middle paragraph carries at most TWO sentences.

    Was ONE sentence for a few hours on 2026-08-26 and that was wrong. A hard cap of one,
    plus a repair that truncated the second, produced exactly the "cobbled together" read
    the sales lead flagged: the middle is where the concrete detail lives, and cutting it
    left a bare assertion. The endorsed email has a two-sentence middle.

    Three or more is still bloat, and that is what this catches. The thing to police is
    VAGUENESS, not sentence count, and vagueness is not machine-checkable: "which is the
    part most ticketing tools are worst at" is an opinion with no content, while "the
    operational side (guest lists, payouts, promotion) ends up living in three different
    places" is substance, and no regex separates them. That judgement lives in
    config/message-shapes.md and in review.

    The MIDDLE is what is enforced, not the whole email. The opening paragraph
    legitimately carries two sentences (the sender's intro line, then the reason for
    reaching out), and the closing paragraph is the CTA. Only what sits between them is
    capped, because that is where every observed instance of bloat lived.

    Bullet lists are exempt: shape 2B is deliberately a scannable list of outcomes.
    """
    copy = body.replace(footer, "")
    copy = re.sub(r"\n\s*\w+\s*\nPosh\s*$", "", copy.strip())
    paras = [p.strip() for p in re.split(r"\n\s*\n", copy) if p.strip()]
    # drop a bare greeting line so paragraph positions mean what they look like
    if paras and len(paras[0].split()) <= 4 and paras[0].rstrip().endswith(","):
        paras = paras[1:]
    if len(paras) < 3:
        return []                     # opener + CTA only: there is no middle to check
    out = []
    for i, para in enumerate(paras[1:-1], start=2):
        if re.search(r"^\s*[-*\u2022]", para, re.M):
            continue                  # a deliberate list, not prose
        n = _count_sentences(para)
        if n > MIDDLE_MAX_SENTENCES:
            out.append(Finding("middle_paragraph", FAIL,
                f"paragraph {i} has {n} sentences, max is {MIDDLE_MAX_SENTENCES}: "
                f"{para[:110]!r}"))
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


ANCHOR_TAG = re.compile(r"<a\s[^>]*href=", re.I)


def check_links(subject: str, body: str, *, position: int) -> list[Finding]:
    """Link policy from the SDR spec, section 3.

    No link of any kind in email 1 or email 3. Email 2 may carry ONE plain visible URL
    (the Fortune Series B piece), never as anchor text where the display string hides
    the destination -- that is the shape phishing uses, and it is what makes a link a
    deliverability risk rather than a credibility one.

    mailto: stays banned everywhere: the opt-out is the merge tag, never a literal
    address.
    """
    out = []
    hay = f"{subject}\n{body}"
    if ANCHOR_TAG.search(hay):
        out.append(Finding("links", FAIL,
            "hyperlinked anchor text; a link must be a visible plain URL"))
    for m in re.finditer(r"mailto:\S+", hay):
        out.append(Finding("links", FAIL,
            f"literal mailto {m.group(0)!r}; the opt-out is the merge tag"))
    urls = [m.group(0) for m in re.finditer(r"https?://\S+", hay)]
    if urls and position != 2:
        out.append(Finding("links", FAIL,
            f"no links are allowed in email {position}: {urls!r}"))
    elif len(urls) > 1:
        out.append(Finding("links", FAIL,
            f"email 2 may carry at most one link: {urls!r}"))
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


# The ONE approved currency figure: Posh's own Series B, cleared 2026-09-01 for email 2.
# Everything else that looks like money is still a FAIL, because the check exists to stop
# a prospect's estimated_gmv_usd leaking into copy they can read. Exempting one exact
# string keeps that guarantee; loosening the pattern would not.
APPROVED_FIGURE = re.compile(r"\$\s?37\s?(m\b|million)", re.I)


def _mask_approved(text: str) -> str:
    """Blank the approved Series B figure so money checks cannot trip on it."""
    return APPROVED_FIGURE.sub("SERIESB", text)


# Our internal lead classification. Routes the persona and picks the comparable; must
# never be printed. Matched only as a DESCRIPTOR ("party organizers"), which is how it
# leaked, so "Palm Tree Festival" as a cleared customer name still passes.
INTERNAL_CATEGORIES = ("party", "live performance", "other social communities",
                       "nightlife", "festival")
CATEGORY_LEAK = re.compile(
    r"\b(" + "|".join(INTERNAL_CATEGORIES) + r")\s+(organiz|promot|venue|event|client)",
    re.I)


def check_category_leak(subject: str, body: str) -> list[Finding]:
    """FAIL if our internal vertical is used to describe the prospect.

    "live performance organizers in Los Angeles" and "party organizers" both shipped in a
    real batch, and "Other Social Communities organizers" was one draw away. The label is
    ours, not theirs, and a prospect should never be shown the bucket we filed them in.
    Say "organizers".
    """
    out = []
    for m in CATEGORY_LEAK.finditer(f"{subject}\n{body}"):
        out.append(Finding("category_leak", FAIL,
            f"internal vertical used as a descriptor: {m.group(0)!r}. Say 'organizers'; "
            f"the classification is for routing, not for copy"))
    return out


def check_gmv_leak(subject: str, body: str) -> list[Finding]:
    out = []
    hay = _mask_approved(f"{subject} {body}")
    for m in re.finditer(r"\$\s?\d[\d,.]*\s*(k|m|million|thousand)?", hay, re.I):
        out.append(Finding("gmv_leak", FAIL,
            f"currency figure in copy; estimated_gmv_usd must never be written: {m.group(0)!r}"))
    return out


# Named companies that are NOT customers and must never be referenced (2026-09-02).
# Banned explicitly, not just omitted from CLEARED_CUSTOMERS, for three reasons: the
# error can explain that the claim is false rather than merely unapproved; a careless
# future addition to the cleared list cannot re-enable them; and the record shows these
# were specifically proposed and specifically rejected as untrue.
FABRICATED_CUSTOMERS = ("Lamborghini", "Adidas", "NBA", "Celsius", "HBO")
# "Complex" is also a real word, so it is matched only in customer-claim context --
# "organizers like Complex" fails, "a complex setup" does not.
CONTEXTUAL_FABRICATED = ("Complex",)
CLAIM_CONTEXT = r"(work(ing)? with|run(ning)? ticketing for|organizers like|clients?|customers?|power(ing)?|partners? with|like)"


# Comparative and superlative claims about price or market position. Unsupportable by
# anything in positioning.md, and until 2026-09-08 nothing checked for them: the only
# thing stopping "we are the cheapest platform" was the model choosing not to write it.
# That became too thin once reps could pass a campaign angle into the prompt.
#
# Deliberately NARROW. A bare "best" is approved copy -- email 2 says "this is usually
# the best time of year for us to get a strong offer across" -- so only "best" attached
# to the product is banned.
SUPERLATIVE_CLAIMS = (
    re.compile(r"\b(cheapest|least expensive)\b", re.I),
    re.compile(r"\bcheaper than\b", re.I),
    re.compile(r"\blowest\b[^.]{0,20}\b(fee|fees|price|prices|cost|costs|rate|rates)\b", re.I),
    re.compile(r"\bbest\s+(ticketing|platform|option|choice|value|solution)\b", re.I),
    re.compile(r"(?:\B#1\b|\bnumber one\b)", re.I),
    re.compile(r"\b(more|less)\s+expensive\s+than\b", re.I),
)


def check_superlatives(subject: str, body: str) -> list[Finding]:
    """FAIL comparative or superlative claims about price or market position.

    Nothing in config/positioning.md supports them, and they are the shape a
    rep-supplied campaign angle is most likely to push copy towards -- "tell them we're
    cheaper". The offer's existence is sayable; its superiority is not.
    """
    out = []
    hay = f"{subject}\n{body}"
    for rx in SUPERLATIVE_CLAIMS:
        m = rx.search(hay)
        if m:
            out.append(Finding("superlative_claim", FAIL,
                f"unsupportable comparative claim {m.group(0)!r}; nothing in "
                f"positioning.md supports a price or market-position comparison"))
    return out


def check_fabricated_customers(subject: str, body: str) -> list[Finding]:
    """FAIL any reference to a company that is not a customer.

    This is not the same failure as naming an unapproved-but-real customer. These
    companies do not use Posh, so naming them is an invented claim about a third party,
    sent to a stranger. It is the single most damaging thing this copy could contain.
    """
    out = []
    hay = f"{subject}\n{body}"
    for name in FABRICATED_CUSTOMERS:
        if re.search(rf"\b{re.escape(name)}\b", hay):
            out.append(Finding("fabricated_customer", FAIL,
                f"{name!r} is NOT a Posh customer and must never be referenced "
                f"(config/positioning.md). Naming it invents a claim about a third party"))
    for name in CONTEXTUAL_FABRICATED:
        if re.search(rf"{CLAIM_CONTEXT}\s+(\w+\s+){{0,2}}\b{re.escape(name)}\b", hay, re.I):
            out.append(Finding("fabricated_customer", FAIL,
                f"{name!r} referenced as a customer or partner; it is NOT one "
                f"(config/positioning.md)"))
    return out


def check_case_studies(subject: str, body: str, *, allowed_names=()) -> list[Finding]:
    out = []
    # Masked first: "we run ticketing for Caché Life, and just closed a $37M Series B"
    # otherwise reads as a figure attached to Caché Life, when it is OUR funding sitting
    # in a neighbouring clause.
    hay = _mask_approved(f"{subject}\n{body}")
    # Blank the prospect's own name before looking for numerals. "90s Til Dawn" carries a
    # digit, and sitting near a no-figure customer it read as a fabricated statistic about
    # that customer. Their band name is not a claim about Caché Life.
    for n in allowed_names or ():
        if str(n).strip():
            hay = re.sub(re.escape(str(n)), "PROSPECT", hay, flags=re.I)
    named = {c for c in CLEARED_CUSTOMERS if c.lower() in hay.lower()}
    # Treat "NARC" and "NARC Run Club" as one customer.
    canonical = {("NARC Run Club" if n.startswith("NARC") else
                  "Caché Life" if n.lower().startswith("cach") else n) for n in named}
    if len(canonical) > 1:
        out.append(Finding("case_study_rules", FAIL,
            f"more than one case study in a single email: {sorted(canonical)}"))
    # A MEETING LENGTH IS NOT A CUSTOMER METRIC. "Free for 15 minutes this week?" is the
    # CTA, and when it landed within the window of a no-figure customer it FAILed 2 of 36
    # emails on a real run -- copy that was otherwise clean at 53 words. This masks
    # durations before the numeral search, which is a PRECISION fix and not a loosening:
    # a span of minutes, hours, days, weeks or months cannot express "We Met IRL grew
    # 40%", so removing it cannot hide a fabricated performance figure. Any other numeral
    # near the name still FAILs.
    hay = re.sub(r"\b\d+\s*(?:-|\s)?\s*(minute|min|hour|hr|day|week|month)s?\b",
                 "DURATION", hay, flags=re.I)
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


def check_commercial_terms(subject: str, body: str) -> list[Finding]:
    """No specific or quantified commercial term may appear in a cold email.

    Not auto-repaired, for the same reason the CTA family isn't: rewriting a commercial
    claim is editorial. A vague, bundled "financial incentives" is approved and must
    keep passing; naming what the incentive actually is must not.
    """
    out = []
    hay = f"{subject}\n{body}"
    for rx in COMMERCIAL_TERMS:
        m = rx.search(hay)
        if m:
            out.append(Finding("commercial_terms", FAIL,
                f"specific commercial term {m.group(0)!r}; the offer's existence is "
                f"sayable, its terms are not (config/positioning.md, Commercial terms)"))
    for sent in _sentences(hay):
        t = TIME_BOXED.search(sent)
        if t and OFFER_CONTEXT.search(sent):
            out.append(Finding("commercial_terms", FAIL,
                f"time-boxed offer {t.group(0)!r} next to offer language; urgency "
                f"implies terms that expire: {sent!r}"))
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


# Email 2's why-now beat, in either of its two approved forms. Deliberately CONTENT-level
# rather than an exact-string match on the supplied line: the model may legitimately
# reword slightly, and requiring the exact sentence would FAIL honest copy. What must not
# happen is the beat disappearing.
WHY_NOW_MARKETPLACE = re.compile(r"\bmarketplace\b", re.I)
WHY_NOW_SEASON = re.compile(
    r"(holiday|season|next couple of months|run[- ]up|time of year)", re.I)


def check_why_now(subject: str, body: str, *, position: int = 2) -> list[Finding]:
    """Email 2 must carry exactly one why-now beat: our marketplace OR the season.

    **Why this is a check and not just an instruction.** The shape guidance tells the
    model the shapes are "register and structure targets, not templates", which it
    correctly read as licence to rewrite the middle -- and on a real 36-contact run one
    contact's email 2 lost the why-now line entirely and invented "guest list and text
    blasts" in its place, a capability framing that is approved only inside one case
    study. The instruction was strengthened at the same time as this was added, but an
    instruction that has already been overridden once is not a guarantee.

    BOTH beats present is also a finding: they dilute each other, and two of them break
    email 2's 90-word cap, which is the whole reason the two share one slot.
    """
    if position != 2:
        return []
    has_mk = bool(WHY_NOW_MARKETPLACE.search(body))
    has_se = bool(WHY_NOW_SEASON.search(body))
    if has_mk and has_se:
        return [Finding("why_now", WARN,
                        "email 2 invokes BOTH the marketplace and the season; they share "
                        "one slot on purpose and two reasons dilute each other")]
    if not has_mk and not has_se:
        return [Finding("why_now", FAIL,
                        "email 2 has no why-now beat: neither our marketplace nor the "
                        "season. The supplied why_now_line was dropped, which is how a "
                        "rewritten middle section smuggles in an unapproved claim")]
    return []


def check_intro_first(subject: str, body: str, *, position: int = 1,
                      sender_name: str = "") -> list[Finding]:
    """Email 1's sender introduction must be the FIRST paragraph after the greeting.

    The skeleton in config/message-shapes.md is greeting, then `{sender.intro_line}`,
    then the opener, and the prompt states the order explicitly. **Nineteen checks ran on
    every email and not one of them looked at beat order**, so when the model swapped two
    paragraphs it passed clean. Caught on a live intake run:

        Hey Garrett,
        We reached out a while back. Is it better timing now?      <- opener
        I'm Brooke, I run partnerships at Posh.                    <- intro, too late

    It reads as a stranger referring to a shared history before saying who they are,
    which is worse than either beat alone and is the exact impression the intro exists to
    prevent. Every other email in the same batch had it right, which is why a prose rule
    was never going to be enough -- the model gets it right most of the time, and "most"
    is what a validator is for.

    Position 1 only. Emails 2 and 3 are threaded replies with no greeting and no
    re-introduction by design.
    """
    if position != 1 or not sender_name:
        return []
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    if len(paras) < 3:
        return []
    intro_at = next((i for i, p in enumerate(paras)
                     if re.search(rf"\bI'?m {re.escape(sender_name)}\b", p, re.I)), None)
    if intro_at is None:
        return []                      # a missing intro is check_length's problem, not this
    # paras[0] is the greeting. The intro belongs at index 1.
    if intro_at > 1:
        return [Finding("intro_order", FAIL,
                        f"the sender introduction is paragraph {intro_at + 1}; it must "
                        f"come directly after the greeting, before the opener. Shape is "
                        f"greeting, intro, opener (config/message-shapes.md).")]
    return []


# ---- driver -------------------------------------------------------------------

def validate_email(subject: str, body: str, *, position: int, footer: str, token: str,
                   literals, regexes, raw_body: str | None = None,
                   label: str = "", competitor_known: bool = True,
                   allowed_names=(), sender_name: str = "") -> EmailResult:
    res = EmailResult(label=label or f"message_{position}")
    res.findings += check_no_dashes(subject, body)
    res.findings += check_approved_stats(subject, body)
    res.findings += check_subject_shape(subject, body, position=position,
                                        allowed_names=allowed_names)
    res.findings += check_middle_paragraph(subject, body, footer=footer)
    res.findings += check_footer(subject, body, footer=footer, token=token)
    res.findings += check_links(subject, body, position=position)
    res.findings += check_banned(subject, body, literals=literals, regexes=regexes)
    res.findings += check_gmv_leak(subject, body)
    res.findings += check_category_leak(subject, body)
    res.findings += check_why_now(subject, body, position=position)
    res.findings += check_case_studies(subject, body, allowed_names=allowed_names)
    res.findings += check_fabricated_customers(subject, body)
    res.findings += check_superlatives(subject, body)
    res.findings += check_no_invented_platform(subject, body,
                                               competitor_known=competitor_known)
    res.findings += check_commercial_terms(subject, body)
    res.findings += check_length(subject, body, position=position, footer=footer)
    res.findings += check_intro_first(subject, body, position=position,
                                      sender_name=sender_name)
    if raw_body is not None:
        markers = [m for m in footer.splitlines() if m.strip()]
        res.findings += check_model_wrote_footer(subject, raw_body, footer_markers=markers)
    return res


def check_stat_budget(messages: list[tuple[int, str, str]]) -> list[Finding]:
    """Sequence-level: counts stat mentions across all three messages.

    Kept as a backstop only. Since 2026-08-25 no numeric stat is approved, so every
    mention already FAILs check_approved_stats per message and this WARN is redundant
    in practice. It stays because it is the only check that sees the whole sequence at
    once, so it would be the seam if a single stat were ever re-approved.
    """
    hits: list[tuple[int, str]] = []
    for position, subject, body in messages:
        for m in STAT_MENTION.finditer(f"{subject}\n{body}"):
            # group(0), not group(1): STAT_MENTION was broadened from \b(13|40)\s*% to
            # \b\d+\s*% when the two approved stats were retired, which removed the
            # capture group. group(1) raised IndexError and took the whole run down the
            # first time a generated email contained any percentage at all.
            hits.append((position, m.group(0).strip()))
    if len(hits) <= 1:
        return []
    where = ", ".join(f"m{p}:{s}" for p, s in hits)
    distinct = {s for _, s in hits}
    kind = ("the same stat repeats" if len(distinct) == 1
            else "more than one distinct stat appears")
    return [Finding("stat_budget", WARN,
        f"{len(hits)} stat mentions across the sequence ({where}); {kind}. "
        f"The rule is at most one stat per 3-email sequence: lead with the package "
        f"and the offer, not a number.")]


GREETING_LINE = re.compile(r"^\s*(hey|hi|hello)?[\w' .]{0,40},\s*$", re.I)


def opening_sentence(body: str) -> str:
    """First real sentence of a body, skipping the greeting line."""
    for raw in body.strip().splitlines():
        line = raw.strip()
        if not line or GREETING_LINE.match(line):
            continue
        parts = _sentences(line)
        return parts[0] if parts else line
    return ""


def check_batch_opening_reuse(openings: list[tuple[str, int, str]]) -> list[Finding]:
    """Batch-level: the same opening sentence must not go to two prospects.

    Cannot live in validate_email, which sees one email at a time, nor in
    check_stat_budget, which sees one sequence. Verbatim reuse is only visible with the
    whole batch in hand, so it sits one more level up and the orchestrator calls it.

    WARN, not FAIL: no individual contact is defective here, and failing a contact for
    what a different contact's email happens to say would be wrong. It is the batch
    that reads machine-written, and repeated strings across many recipients are what
    spam heuristics are built to notice.
    """
    groups: dict[tuple[int, str], tuple[str, list[str]]] = {}
    for label, position, body in openings:
        s = opening_sentence(body)
        if not s:
            continue
        _, labels = groups.setdefault((position, s.lower()), (s, []))
        labels.append(label)
    out = []
    for (position, _), (sentence, labels) in sorted(groups.items()):
        uniq = sorted(set(labels))
        if len(uniq) > 1:
            out.append(Finding("batch_opening_reuse", WARN,
                f"message {position} opens with the same sentence for {len(uniq)} "
                f"contacts ({', '.join(uniq)}): {sentence!r}"))
    return out


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


# ---- self-test ----------------------------------------------------------------
# No test framework in this repo, so the shape rules verify themselves: run
#   ./.venv/bin/python scripts/validate.py
# Exits non-zero on any failure, so it works as a pre-commit check.

SUBJECT_SHAPE_CASES = [
    # (subject, position, expect_fail, why)
    ("still using RA for Philadeep events?", 1, False,
     "canonical acronym + capitalized proper noun, rest lowercase"),
    ("Compare Your Ticketing Setup Today", 1, True,
     "Title Cased: every word capitalized"),
    ("still running events through RA?", 1, False, "canonical acronym"),
    ("eventeny working out for dogwood arts?", 1, False, "all lowercase"),
    ("your ticketing setup", 1, False, "all lowercase"),
    ("running events at the berry farm?", 1, False, "all lowercase"),
    ("BIG SALE on tickets", 1, True, "ALL CAPS word is shouting"),
    ("still using eventBrite?", 1, True, "mixed-case oddity, not a proper-noun shape"),
    ("quick question about Dogwood Arts", 1, False,
     "two proper nouns, but the subject is not wholly capitalized"),
    ("Philadeep events", 1, False,
     "proper noun + lowercase word: not Title Case, this is the shape we want"),
    ("Philadeep Events", 1, True,
     "both words capitalized: Title Case even at two words"),
    ("", 1, True, "empty subject on email 1 still fails"),
    ("", 2, False, "empty subject on a threaded reply is correct"),
    ("", 3, False, "empty subject on a threaded reply is correct"),
    ("This Is A Stray Invented Subject", 2, True,
     "a stray subject on email 2 is still shape-checked"),
    ("way too many words in this particular subject line here", 1, True,
     "over the word ceiling"),
]

# Middle-paragraph cases. The FAIL examples are real generated copy: prose rules could
# not stop them, which is why this is enforced in code.
MIDDLE_PARA_CASES = [
    ("Hey Rolando,\n\nI'm Carl, I run partnerships at Posh. Reaching out to see if you're "
     "locked in on RA?\n\nPosh keeps ticketing, guest list, and payouts in one place.\n\n"
     "Want me to put a comparison together?", False, "one-sentence middle: the target"),
    ("Hey there,\n\nI'm Carl, I run partnerships at Posh.\n\nSaw Gotham's Den is running "
     "ticketing through Eventbrite. We work with a lot of live performance venues in New "
     "York, and what tends to happen is the operational side (guest lists, payouts, "
     "promotion) ends up living in three different places.\n\nPosh pulls that into one "
     "platform, so you're not juggling tools on event night.\n\nWant me to put together a "
     "comparison for your next show?", False,
     "THE ENDORSED EMAIL: two-sentence opener, concrete middle, must pass"),
    ("Hey there,\n\nI'm Carl, I run partnerships at Posh. Reaching out about your setup?"
     "\n\nWant me to put a comparison together?", False,
     "opener plus CTA only: no middle to check"),
    ("Hi Leanne,\n\nI'm Carl, I run partnerships at Posh. Reaching out because I was "
     "curious how Main Street handles this. Is much of it still by hand?\n\n"
     "On Posh the guest list, promo, and payouts sit with the ticketing.\n\n"
     "Open to seeing what we would put together?", False,
     "TWO sentences in the OPENER are fine: intro line plus the reason"),
    ("Hey there,\n\nStill working out whether Posh fits? The short version, organizers "
     "come to us when they want to:\n\n- Sell more tickets\n- Reach more of the right "
     "people\n- Own their attendee community\n\nAny of those live for you?", False,
     "a bullet list is exempt: shape 2B is deliberately scannable"),
    ("Hey there,\n\nI'm Carl. Reaching out about your setup?\n\nPosh does ticketing in "
     "one place. It also handles payouts. And promo.\n\nWant a comparison?", True,
     "three sentences in the middle is still bloat"),
    ("Hey there,\n\nI'm Carl. Reaching out about your setup?\n\nPosh keeps it in one "
     "place. You are not juggling tools on event night.\n\nWant a comparison?", False,
     "two sentences in the middle is the endorsed shape"),
]

# Subjects that must PASS only because the contact's own proper nouns are supplied.
# Real failures from the 2026-08-26 run: an all-caps org name and a possessive of one.
SUBJECT_NAME_CASES = [
    ("quick question about the LAB's ticketing", ["the LAB"], False,
     "possessive of an all-caps org name is a proper noun, not shouting"),
    ("quick question about the LAB's ticketing", [], True,
     "without the org name there is no way to tell it from shouting"),
    ("still using RA for Philadeep events?", ["Philadeep"], False,
     "canonical acronym plus a supplied proper noun"),
    ("IYKYK ticketing setup", ["If You Know You Know", "IYKYK"], False,
     "org name that is itself an acronym"),
    ("BIG SALE on tickets", ["the LAB"], True,
     "shouting is still shouting when a name is supplied"),
    ("still using DICE for Rose Gold events?", ["Rose Gold Entertainment", "DICE"], False,
     "an all-caps COMPETITOR name is a proper noun too, not shouting"),
    ("still running Club Underground on DICE?", ["Club Underground", "DICE"], False,
     "org name plus all-caps platform name"),
]


STAT_BUDGET_CASES = [
    # (messages, expect_findings, why)
    ([(1, "s", "no numbers here"), (2, "", "none either"), (3, "", "clean")], False,
     "no percentages, nothing to report"),
    ([(1, "s", "we convert 40% better"), (2, "", "clean"), (3, "", "clean")], False,
     "a single mention is within budget (and already FAILs per-message)"),
    ([(1, "s", "13% of tickets"), (2, "", "converts 40% better"), (3, "", "")], True,
     "two mentions across the sequence"),
    ([(1, "s", "up 30% this year"), (2, "", "another 30% claim"), (3, "", "")], True,
     "arbitrary percentages must be counted too, not just the retired 13/40"),
]


def _self_test() -> int:
    failures = 0
    for body, expect_fail, why in MIDDLE_PARA_CASES:
        f = check_middle_paragraph("subj", body, footer="")
        got = any(x.severity == FAIL for x in f)
        ok = got == expect_fail
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} middle_paragraph "
              f"{'FAIL' if got else 'PASS'} (want {'FAIL' if expect_fail else 'PASS'})"
              f"  {why}")
        if not ok:
            for x in f:
                print(f"         {x.detail[:90]}")
    for subject, names, expect_fail, why in SUBJECT_NAME_CASES:
        f = check_subject_shape(subject, "body", position=1, allowed_names=names)
        got = any(x.severity == FAIL for x in f)
        ok = got == expect_fail
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} names={len(names)} "
              f"{'FAIL' if got else 'PASS'} (want {'FAIL' if expect_fail else 'PASS'})"
              f"  {why}")
    for messages, expect, why in STAT_BUDGET_CASES:
        try:
            got = bool(check_stat_budget(messages))
        except Exception as e:                      # a crash here took down a whole run
            print(f"  FAIL check_stat_budget raised {type(e).__name__}: {e}  ({why})")
            failures += 1
            continue
        ok = got == expect
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} stat_budget {'flags' if got else 'quiet'} "
              f"(want {'flags' if expect else 'quiet'})  {why}")
    for subject, position, expect_fail, why in SUBJECT_SHAPE_CASES:
        findings = check_subject_shape(subject, "body text", position=position)
        got_fail = any(f.severity == FAIL for f in findings)
        ok = got_fail == expect_fail
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {subject!r:52} pos={position} "
              f"{'FAIL' if got_fail else 'PASS'} (expected {'FAIL' if expect_fail else 'PASS'})"
              f"  {why}")
        if not ok:
            for f in findings:
                print(f"         {f.severity} {f.detail}")
    print(f"\n{len(SUBJECT_SHAPE_CASES) - failures}/{len(SUBJECT_SHAPE_CASES)} subject-shape cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    literals, regexes = load_banned()
    print(f"banned-phrases.md: {len(literals)} literals, {len(regexes)} regexes")
    print(f"LENGTH_TARGETS: {LENGTH_TARGETS}")
    print(f"APPROVED_STAT_PATTERNS: {APPROVED_STAT_PATTERNS} "
          f"(empty = no numeric stat is approved)\n")
    print("subject-shape cases:")
    raise SystemExit(_self_test())
