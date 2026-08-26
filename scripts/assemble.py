#!/usr/bin/env python3
"""Assemble compliance-critical elements onto generated email bodies.

The model writes body copy only. This module owns the sign-off and the footer,
because those are the parts a missing instruction silently drops. Every value comes
from config; nothing is hardcoded and nothing falls back to a default.

Every failure here aborts. A half-assembled email is worse than no email: it looks
shippable while missing the sender identity or opt-out that make it legal to send.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSITIONING = ROOT / "config" / "positioning.md"
SENDERS = ROOT / "config" / "senders.md"

# The Smartlead unsubscribe merge tag, confirmed against Smartlead's help centre
# 2026-08-26. Percent-delimited, NOT curly braces: Smartlead substitutes this exact
# string wherever it appears in the body. Defined once here so it is never retyped.
UNSUBSCRIBE_TOKEN = "%unsubscribe-text%"
TOKEN_IS_PLACEHOLDER = False

# Having the right tag in the body is necessary and not sufficient. Two per-campaign UI
# settings decide whether it renders at all, and neither is visible to this code:
#   - "Add unsubscribe message in all emails" ON, which also enables the one-click
#     Unsubscribe Header Tag that Google requires of bulk senders.
#   - "Optimize Email Delivery" OFF. It disables HTML content and takes the unsubscribe
#     link with it, silently.
# So the send gate below does not clear on the tag alone: it is a campaign-creation
# check, in instructions/campaign-creation.md next to the activity-logging gate.
# Note a TEST send renders the link deliberately non-clickable, so a test cannot prove
# it works. Only a real first send can.

# Sentinel marking unreplaced rows in config/senders.md.
PLACEHOLDER_PREFIX = "PLACEHOLDER_NAME"


class AssemblyError(RuntimeError):
    """Raised for any condition that must stop the batch."""


@dataclass(frozen=True)
class SenderIdentity:
    legal_name: str
    address: str


def load_sender_identity(path: pathlib.Path = POSITIONING) -> SenderIdentity:
    """Parse the legal name and address out of positioning.md.

    positioning.md is the single source of truth. A missing key aborts rather than
    defaulting, because a stale or blank footer is exactly the failure this module
    exists to prevent.
    """
    if not path.exists():
        raise AssemblyError(f"positioning.md not found at {path}")
    text = path.read_text(encoding="utf-8")

    def grab(label: str) -> str:
        m = re.search(rf"^-\s*{re.escape(label)}:\s*(.+?)\s*$", text, re.MULTILINE)
        if not m:
            raise AssemblyError(
                f"Could not parse '{label}' from {path.name}. The footer cannot be "
                f"built without it. Check the 'Sender identity & compliance basics' "
                f"section."
            )
        return m.group(1).strip()

    return SenderIdentity(
        legal_name=grab("Legal company name for footers"),
        address=grab("Physical mailing address for footers"),
    )


def load_sender_map(path: pathlib.Path = SENDERS) -> dict[str, str]:
    """Parse the mailbox -> first name table from senders.md."""
    if not path.exists():
        raise AssemblyError(f"senders.md not found at {path}")

    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or line.count("|") < 3:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        mailbox, name = cells[0], cells[1]
        # Skip the header row and its separator.
        if mailbox.lower() == "mailbox" or set(mailbox) <= set("-: "):
            continue
        if not mailbox or not name:
            continue
        key = mailbox.lower()
        if key in mapping:
            raise AssemblyError(
                f"Duplicate mailbox '{mailbox}' in {path.name}. The correct sender "
                f"name would be ambiguous. Keep exactly one row per mailbox."
            )
        mapping[key] = name

    if not mapping:
        raise AssemblyError(f"No mailbox rows parsed from {path.name}.")
    return mapping


def resolve_sender_name(mailbox: str, sender_map: dict[str, str] | None = None) -> str:
    """Look up the first name that signs for this mailbox.

    An unmapped mailbox is a hard failure. Signing with a blank, a guess, or a bare
    'Posh' would misrepresent the sender.
    """
    if not mailbox or not mailbox.strip():
        raise AssemblyError(
            "No sending mailbox supplied. Assembly cannot choose a sign-off name "
            "without knowing which mailbox sends. See config/senders.md."
        )
    sender_map = sender_map if sender_map is not None else load_sender_map()
    name = sender_map.get(mailbox.strip().lower())
    if name is None:
        known = ", ".join(sorted(sender_map)) or "(none)"
        raise AssemblyError(
            f"Mailbox '{mailbox}' is not in config/senders.md, so there is no sender "
            f"name to sign with. Add a row for it before generating. "
            f"Known mailboxes: {known}"
        )
    return name


def is_placeholder_sender(name: str) -> bool:
    """True if this row has not been replaced with a real sender identity yet."""
    return name.upper().startswith(PLACEHOLDER_PREFIX)


def build_footer(identity: SenderIdentity | None = None) -> str:
    identity = identity or load_sender_identity()
    return f"{identity.legal_name}\n{identity.address}\n{UNSUBSCRIBE_TOKEN}"


def assemble(
    body: str,
    mailbox: str,
    *,
    identity: SenderIdentity | None = None,
    sender_map: dict[str, str] | None = None,
) -> str:
    """Append the sign-off and footer to a model-written body.

    `body` should be the message text only. If the model also wrote a sign-off or
    footer, that is prompt drift: validate.py flags it, and we do not silently
    double-append here, because quietly repairing drift hides it.
    """
    identity = identity or load_sender_identity()
    name = resolve_sender_name(mailbox, sender_map)
    return f"{body.rstrip()}\n\n{name}\nPosh\n\n{build_footer(identity)}"


def send_readiness_blockers(sender_map: dict[str, str] | None = None) -> list[str]:
    """Reasons this configuration must not be used for a live send.

    Returned rather than raised: generating drafts for review is fine in this state,
    sending is not.
    """
    sender_map = sender_map if sender_map is not None else load_sender_map()
    blockers: list[str] = []
    placeholders = sorted(m for m, n in sender_map.items() if is_placeholder_sender(n))
    if placeholders:
        blockers.append(
            f"config/senders.md still holds placeholder sender names for: "
            f"{', '.join(placeholders)}. Replace them during mailbox setup."
        )
    if TOKEN_IS_PLACEHOLDER:
        blockers.append(
            f"The unsubscribe token is still the placeholder {UNSUBSCRIBE_TOKEN}. "
            f"Confirm the real Smartlead merge tag before sending."
        )
    # Not a code condition: nothing here can see a campaign's UI settings. Surfaced on
    # every run so it cannot be forgotten between now and the first launch.
    blockers.append(
        f"Unsubscribe rendering is UNVERIFIED in a live campaign. The tag "
        f"{UNSUBSCRIBE_TOKEN} is correct, but per campaign a human must set "
        f"'Add unsubscribe message in all emails' ON and 'Optimize Email Delivery' OFF, "
        f"then confirm on the first real send that the link renders. See "
        f"instructions/campaign-creation.md."
    )
    return blockers


if __name__ == "__main__":
    ident = load_sender_identity()
    smap = load_sender_map()
    print(f"legal name: {ident.legal_name}")
    print(f"address:    {ident.address}")
    print(f"token:      {UNSUBSCRIBE_TOKEN}")
    print(f"\nmailboxes ({len(smap)}):")
    for mb, nm in sorted(smap.items()):
        flag = "  <-- PLACEHOLDER" if is_placeholder_sender(nm) else ""
        print(f"  {mb} -> {nm}{flag}")
    print("\nsend-readiness blockers:")
    for b in send_readiness_blockers(smap) or ["  (none)"]:
        print(f"  - {b}")
