"""Input/output guardrails: PII redaction, prompt-injection detection, tool policy."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PII = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?61|0)[ -]?\d(?:[ -]?\d){8}(?!\d)"),
    "TFN": re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"),
}
_INJECTION = [
    re.compile(p, re.I)
    for p in (
        r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
        r"disregard (the )?(system|previous) (prompt|instructions)",
        r"reveal (your )?(system )?prompt",
        r"you are now (in )?(developer|dan|jailbreak) mode",
        r"act as (an? )?(unrestricted|unfiltered)",
    )
]
# Tools the agent may call without a human in the loop.
READ_ONLY_TOOLS = {"lookup_case", "search_policy"}


@dataclass(frozen=True)
class Redaction:
    text: str
    found: dict[str, int]


def redact_pii(text: str) -> Redaction:
    """Replace PII with typed placeholders; order matters (cards before TFN/phone)."""
    found: dict[str, int] = {}
    for label in ("EMAIL", "CARD", "PHONE", "TFN"):
        text, n = _PII[label].subn(f"[{label}]", text)
        if n:
            found[label] = n
    return Redaction(text, found)


def detect_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION)


def tool_allowed(tool: str, approved: bool) -> bool:
    """Read-only tools always pass; anything that mutates state needs approval."""
    return tool in READ_ONLY_TOOLS or approved
