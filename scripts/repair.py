#!/usr/bin/env python3
"""Deterministic repairs applied to generated copy before assembly and validation.

Two classes of defect are mechanical rather than editorial, so code fixes them
instead of asking the model again:

  normalize_dashes()  punctuation only, no meaning changes
  snap_stats()        replaces a reworded approved stat with its exact wording

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

# The only approved wordings, from config/positioning.md. verify_canon() asserts
# these still match the file, so a positioning edit cannot leave repair snapping
# copy to a stale claim.
CANON_13 = "The average event sells 13% of its tickets through the Posh marketplace"
CANON_40 = "Posh events convert 40% better than other platforms"

# A clause is only snapped when it is actually making the approved claim. Guards
# against unrelated uses of the same numbers, e.g. "a 13% discount".
TOPIC_13 = re.compile(r"ticket|marketplace|sell|sales|discover", re.I)
TOPIC_40 = re.compile(r"convert|conversion|better|perform", re.I)

STAT_RE = re.compile(r"\b(13|40)\s*%")
CLAUSE_SPLIT = re.compile(r"(,\s+(?:which|and|so|but|because)\b|:\s+)")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])(\s+)")

EM, EN = "—", "–"


class RepairError(RuntimeError):
    """Raised when repair cannot run safely."""


@dataclass(frozen=True)
class RepairRecord:
    kind: str
    before: str
    after: str
    note: str = ""


# ---- canonical-source verification -------------------------------------------

def verify_canon(path: pathlib.Path = POSITIONING) -> None:
    """Fail if positioning.md no longer contains the wordings we snap to."""
    text = re.sub(r"[*_`]", "", path.read_text(encoding="utf-8"))
    text = re.sub(r"\s+", " ", text)
    for needle in ("13% of its tickets through the Posh marketplace",
                   "Posh events convert 40% better"):
        if needle.lower() not in text.lower():
            raise RepairError(
                f"{path.name} no longer contains {needle!r}. repair.py would snap copy "
                f"to wording positioning.md does not approve. Update CANON_* together "
                f"with positioning.md."
            )


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


# ---- stats --------------------------------------------------------------------

def snap_stats(text: str) -> tuple[str, list[RepairRecord]]:
    """Replace the clause making a 13%/40% claim with the exact approved wording,
    preserving the clauses around it."""
    records: list[RepairRecord] = []
    parts = SENTENCE_SPLIT.split(text)

    for si, sent in enumerate(parts):
        if not STAT_RE.search(sent):
            continue
        clauses = CLAUSE_SPLIT.split(sent)
        changed = False
        for ci, clause in enumerate(clauses):
            found = STAT_RE.search(clause)
            if not found:
                continue
            is13 = found.group(1) == "13"
            if not (TOPIC_13 if is13 else TOPIC_40).search(clause):
                records.append(RepairRecord(
                    "stat", clause.strip(), clause.strip(),
                    note="skipped: number is not making the approved claim"))
                continue

            canon = CANON_13 if is13 else CANON_40
            lead_ws = clause[:len(clause) - len(clause.lstrip())]
            trailing = "." if clause.rstrip().endswith((".", "!", "?")) else ""
            new = canon + trailing
            # Only ever uppercase at a sentence start. Never lowercase: the canonical
            # wording begins with a proper noun in the 40% case.
            at_sentence_start = ci == 0 or clauses[ci - 1].strip().endswith((".", "!", "?"))
            if at_sentence_start:
                new = new[0].upper() + new[1:]
            new = lead_ws + new

            if clause.strip() != new.strip():
                records.append(RepairRecord("stat", clause.strip(), new.strip()))
                clauses[ci] = new
                changed = True
        if changed:
            parts[si] = "".join(clauses)

    return "".join(parts), records


# ---- driver -------------------------------------------------------------------

def repair(body: str) -> tuple[str, list[RepairRecord]]:
    """Dashes first, then stats: dash repair can split a stat sentence, and the stat
    snapper needs clean sentence boundaries to find the right clause."""
    verify_canon()
    body, r1 = normalize_dashes(body)
    body, r2 = snap_stats(body)
    return body, r1 + r2


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
    verify_canon()
    print("canonical wordings verified against positioning.md")
    print(f"\nhard-constraints block ({MESSAGE_GEN.name}):\n")
    print(load_hard_constraints())
