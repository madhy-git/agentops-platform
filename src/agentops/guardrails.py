"""Input/output guardrails: PII redaction, prompt-injection detection, tool policy."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_PII = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?61|0)[ -]?\d(?:[ -]?\d){8}(?!\d)"),
    "TFN": re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"),
    # Australian BSB is always written with a hyphen; a bare 6-digit number is too ambiguous to redact.
    "BSB": re.compile(r"\b\d{3}-\d{3}\b"),
}
_INJECTION = [
    re.compile(p, re.I | re.M)
    for p in (
        r"ignore (all |any |the |your )*(previous|prior|above|earlier|system) (instructions|rules|prompt)",
        r"ignore (all |any |the |your )*(instructions|rules|prompt) (above|before)",
        r"disregard (the |your |all )*(system|previous|above) (prompt|instructions|rules)",
        r"forget (everything|all|what) (you were|you've been|you have been|you were) (told|given|instructed)",
        r"\bnew (system )?instructions\s*:",
        r"^\s*(system|assistant|developer)\s*:",
        r"reveal (your )?(system )?prompt",
        r"you are now (in )?(developer|dan|jailbreak|admin) mode",
        r"act as (an? )?(unrestricted|unfiltered)",
    )
]
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_SPACED_LETTERS = re.compile(r"\b(?:[a-z] ){3,}[a-z]\b", re.I)


def _normalize(text: str) -> str:
    """Undo cheap obfuscation: look-alike Unicode, zero-width chars, s p a c e d letters, extra whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = _SPACED_LETTERS.sub(lambda m: m.group().replace(" ", ""), text)
    return re.sub(r"[ \t]+", " ", text)
# Tools the agent may call without a human in the loop.
READ_ONLY_TOOLS = {"lookup_case", "search_policy"}


@dataclass(frozen=True)
class Redaction:
    text: str
    found: dict[str, int]


def redact_pii(text: str) -> Redaction:
    """Replace PII with typed placeholders; order matters (cards before TFN/phone, BSB last)."""
    found: dict[str, int] = {}
    for label in ("EMAIL", "CARD", "PHONE", "TFN", "BSB"):
        text, n = _PII[label].subn(f"[{label}]", text)
        if n:
            found[label] = n
    return Redaction(text, found)


def detect_injection(text: str) -> bool:
    """A speed bump, not a wall: regexes catch known phrasings only. Least privilege is the real defence."""
    text = _normalize(text)
    return any(p.search(text) for p in _INJECTION)


def tool_allowed(tool: str, approved: bool) -> bool:
    """Read-only tools always pass; anything that mutates state needs approval."""
    return tool in READ_ONLY_TOOLS or approved
