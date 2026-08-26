#!/usr/bin/env python3
"""Deterministic repairs applied to generated copy before assembly and validation.

One class of defect is mechanical rather than editorial, so code fixes it instead of
asking the model again:

  normalize_dashes()  punctuation only, no meaning changes

There is no stat repair. No numeric performance stat is approved any more (retired
2026-08-25: the figures were inaccurate and the reps did not use them), so there is
nothing to snap copy to. A percentage in generated copy is now a validator FAIL rather
than something code silently rewrites. See config/positioning.md.

Every rewrite returns a RepairRecord. Nothing is changed silently: the caller is
expected to surface the records, and validate.py still runs the same checks
afterwards, so a misfiring repair fails loudly rather than passing unnoticed.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSITIONING = ROOT / "config" / "positioning.md"
MESSAGE_GEN = ROOT / "instructions" / "message-generation.md"

HARD_CONSTRAINTS_BEGIN = "<!-- HARD-CONSTRAINTS:BEGIN -->"
HARD_CONSTRAINTS_END = "<!-- HARD-CONSTRAINTS:END -->"
VOICE_ANCHOR_BEGIN = "<!-- VOICE-ANCHOR:BEGIN -->"
VOICE_ANCHOR_END = "<!-- VOICE-ANCHOR:END -->"

CLAUSE_SPLIT = re.compile(r"(,\s+(?:which|and|so|but|because)\b|:\s+)")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])(\s+)")

EM, EN = "—", "–"

# A trailing sign-off the model wrote despite being told not to. Assembly appends the
# real one, so leaving this in produces a doubled sign-off. Mechanical, unlike a CTA.
SIGNOFF_LINE = re.compile(
    r"^\s*(thanks|thank you|best|best regards|cheers|regards|sincerely|warmly|"
    r"talk soon|all the best|appreciate it)\s*[,.!]?\s*$", re.I)
# A bare name line following a sign-off ("Thanks,\nAliza"). Only stripped when a
# sign-off was stripped immediately above it, so ordinary copy is never touched.
NAME_LINE = re.compile(r"^\s*[A-Z][\w.'-]*(\s+[A-Z][\w.'-]*)?\s*$")


class RepairError(RuntimeError):
    """Raised when repair cannot run safely."""


@dataclass(frozen=True)
class RepairRecord:
    kind: str
    before: str
    after: str
    note: str = ""


# ---- rulebook block loaders --------------------------------------------------
# verify_canon() lived here and is gone (2026-08-25). It asserted positioning.md still
# contained the approved stat wordings, which mattered only because snap_stats() rewrote
# copy to them. With no approved stats, there is nothing to keep in sync.

def _extract_block(path: pathlib.Path, begin: str, end: str, what: str) -> str:
    text = path.read_text(encoding="utf-8")
    try:
        block = text.split(begin, 1)[1].split(end, 1)[0]
    except IndexError:
        raise RepairError(
            f"Could not find the {begin} / {end} markers in {path.name}. The "
            f"generation prompt injects the {what} block verbatim and must not fall "
            f"back to a restatement."
        )
    block = block.strip()
    if not block:
        raise RepairError(f"The {what} block in {path.name} is empty.")
    return block


def load_voice_anchor(path: pathlib.Path = MESSAGE_GEN) -> str:
    """Extract the voice anchor for injection. Read from the file, never restated."""
    return _extract_block(path, VOICE_ANCHOR_BEGIN, VOICE_ANCHOR_END, "voice-anchor")


def load_hard_constraints(path: pathlib.Path = MESSAGE_GEN) -> str:
    """Extract the machine-checked rules block for injection into the prompt.

    Read from the file rather than restated here, so the spec and the prompt cannot
    drift apart.
    """
    text = path.read_text(encoding="utf-8")
    try:
        block = text.split(HARD_CONSTRAINTS_BEGIN, 1)[1].split(HARD_CONSTRAINTS_END, 1)[0]
    except IndexError:
        raise RepairError(
            f"Could not find the {HARD_CONSTRAINTS_BEGIN} / {HARD_CONSTRAINTS_END} "
            f"markers in {path.name}. The generation prompt injects that block "
            f"verbatim and must not fall back to a restatement."
        )
    block = block.strip()
    if not block:
        raise RepairError(f"The hard-constraints block in {path.name} is empty.")
    return block


# ---- dashes -------------------------------------------------------------------

def _fix_dashes_in_sentence(sent: str) -> str:
    # Numeric ranges first: 50-90 reads as a range, not punctuation.
    sent = re.sub(rf"(\d)\s*[{EM}{EN}]\s*(\d)", r"\1 to \2", sent)

    # Paired dashes wrapping an aside. A comma inside means it is a list, which
    # commas cannot bracket without producing a splice, so use parentheses.
    def _paired(m: re.Match) -> str:
        inner = m.group(1).strip()
        return f" ({inner}) " if "," in inner else f", {inner}, "

    sent = re.sub(rf"\s*[{EM}{EN}]\s*([^{EM}{EN}]+?)\s*[{EM}{EN}]\s*", _paired, sent)

    # Remaining single dashes.
    while True:
        m = re.search(rf"\s*[{EM}{EN}]\s*", sent)
        if not m:
            break
        head, tail = sent[:m.start()], sent[m.end():]
        # A list following the dash reads as an enumeration: use a colon.
        upto_end = re.split(r"(?<=[.!?])\s", tail, 1)[0]
        if "," in upto_end:
            sent = f"{head.rstrip()}: {tail.lstrip()}"
        else:
            t = tail.lstrip()
            t = t[0].upper() + t[1:] if t else t
            sent = f"{head.rstrip()}. {t}"
    return re.sub(r"\s{2,}", " ", sent).replace(" .", ".").replace(" ,", ",")


def normalize_dashes(text: str) -> tuple[str, list[RepairRecord]]:
    if EM not in text and EN not in text:
        return text, []
    records: list[RepairRecord] = []
    parts = SENTENCE_SPLIT.split(text)
    for i, part in enumerate(parts):
        if EM not in part and EN not in part:
            continue
        fixed = _fix_dashes_in_sentence(part)
        if fixed != part:
            records.append(RepairRecord("dash", part.strip(), fixed.strip()))
            parts[i] = fixed
    return "".join(parts), records


# ---- sign-off ------------------------------------------------------------------

def strip_signoff(text: str) -> tuple[str, list[RepairRecord]]:
    """Remove a model-written trailing sign-off so assembly's is the only one."""
    lines = text.rstrip().split("\n")
    records: list[RepairRecord] = []
    stripped_signoff = False

    while lines:
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        last = lines[-1]
        if SIGNOFF_LINE.match(last):
            lines.pop()
            records.append(RepairRecord("signoff", last.strip(), "(removed)",
                note="model wrote a sign-off; assembly appends the real one"))
            stripped_signoff = True
            continue
        # "Thanks,\nAliza": the name is the last line and the sign-off sits above it,
        # so look one line up before deciding. Only a name directly under a sign-off
        # is removed, which is why ordinary short closing lines are untouched.
        prev = next((l for l in reversed(lines[:-1]) if l.strip()), "")
        if (NAME_LINE.match(last) and len(last.split()) <= 2
                and SIGNOFF_LINE.match(prev)):
            lines.pop()
            records.append(RepairRecord("signoff", last.strip(), "(removed)",
                note="name line under a model-written sign-off"))
            continue
        break

    return "\n".join(lines).rstrip(), records


# ---- middle paragraph ----------------------------------------------------------

SENTENCE_SPLIT_PARA = re.compile(r"(?<=[.!?])\s+")


def trim_middle_paragraph(text: str) -> tuple[str, list[RepairRecord]]:
    """Cut every middle paragraph down to its first sentence.

    Mechanical for the same reason dash repair is: the rule is structural, not editorial.
    "The middle paragraph is one sentence" was written four times across
    config/message-shapes.md and instructions/message-generation.md and the model routed
    around it each time with fresh wording ("which is the part most ticketing tools are
    worst at", "so that part stops eating your week"). Blacklisting phrasings is
    whack-a-mole; cutting the second sentence is not.

    What is deliberately NOT touched:
      - the OPENING paragraph, which legitimately carries the sender's intro line and
        then the reason for reaching out,
      - the CLOSING paragraph, which is the CTA,
      - any paragraph containing a bullet list, since shape 2B is a scannable list.
    """
    records: list[RepairRecord] = []
    paras = re.split(r"(\n\s*\n)", text)          # keep separators so joins are exact
    blocks = [(i, s) for i, s in enumerate(paras) if i % 2 == 0 and s.strip()]
    if len(blocks) < 3:
        return text, records

    # A bare greeting is not a content paragraph, so positions mean what they look like.
    start = 1 if (len(blocks[0][1].split()) <= 4
                  and blocks[0][1].rstrip().endswith(",")) else 0
    middles = blocks[start + 1:-1]
    for idx, para in middles:
        if re.search(r"^\s*[-*\u2022]", para, re.M):
            continue
        sentences = [s for s in SENTENCE_SPLIT_PARA.split(para.strip()) if s.strip()]
        if len(sentences) <= 1:
            continue
        kept = sentences[0].strip()
        lead = para[:len(para) - len(para.lstrip())]
        paras[idx] = lead + kept
        records.append(RepairRecord(
            "middle_para", para.strip(), kept,
            note=f"cut {len(sentences) - 1} trailing sentence(s) from the middle paragraph"))
    return "".join(paras), records


# ---- driver -------------------------------------------------------------------

def repair(body: str) -> tuple[str, list[RepairRecord]]:
    """Sign-off, then dashes, then the middle paragraph.

    Order matters. Sign-off removal changes what the last paragraph is, which the middle
    trim depends on, and dash repair can split a sentence, which changes the sentence
    count the trim reads. Stat snapping used to run last and is gone: no numeric stat is
    approved, so a percentage is a validator FAIL rather than a silent rewrite."""
    body, r0 = strip_signoff(body)
    body, r1 = normalize_dashes(body)
    body, r2 = trim_middle_paragraph(body)
    return body, r0 + r1 + r2


def format_records(records: list[RepairRecord], indent: str = "    ") -> str:
    if not records:
        return f"{indent}(no repairs)"
    out = []
    for r in records:
        tag = f"{r.kind.upper()}" + (f"  [{r.note}]" if r.note else "")
        out.append(f"{indent}{tag}")
        out.append(f"{indent}  before: {r.before}")
        out.append(f"{indent}  after : {r.after}")
    return "\n".join(out)


if __name__ == "__main__":
    print(f"hard-constraints block ({MESSAGE_GEN.name}):\n")
    print(load_hard_constraints())
