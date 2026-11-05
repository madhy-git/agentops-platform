"""Input guardrails: PII redaction, prompt-injection detection (direct and indirect), tool policy.

LEARNING NOTES
- Guardrails run *before* the model, so the model never sees raw PII or known attack strings.
- Every guard is a trade-off between precision (false positives annoy real customers), recall
  (misses let attacks through) and latency. evals/guard_metrics.py measures all three per guard.
- Regex injection detection is a speed bump, not a wall: it catches known phrasings and cheap
  obfuscation, never paraphrase. The real defence is least privilege: the agent's tools are
  read-only and every state change needs a human (see service.py, workflow/).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --- PII redaction ---------------------------------------------------------------------------

# Order matters: longer/more specific patterns first, so a card number isn't half-eaten as a
# phone number, and BSB (xxx-xxx) runs last so it can't consume part of a TFN.
_PII = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?61|0)[ -]?\d(?:[ -]?\d){8}(?!\d)"),
    "TFN": re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"),
    # BSB is always written with a hyphen; a bare 6-digit number is too ambiguous to redact.
    "BSB": re.compile(r"\b\d{3}-\d{3}\b"),
}


@dataclass(frozen=True)
class Redaction:
    text: str
    found: dict[str, int]  # counts per type: logged and traced, the values themselves never are


def redact_pii(text: str) -> Redaction:
    """Replace PII with typed placeholders such as [PHONE]; the model can still reason about it."""
    found: dict[str, int] = {}
    for label, pattern in _PII.items():
        text, n = pattern.subn(f"[{label}]", text)
        if n:
            found[label] = n
    return Redaction(text, found)


# --- Prompt-injection detection --------------------------------------------------------------

_INJECTION = [
    re.compile(p, re.I | re.M)
    for p in (
        r"ignore (all |any |the |your )*(previous|prior|above|earlier|system) (instructions|rules|prompt)",
        r"ignore (all |any |the |your )*(instructions|rules|prompt) (above|before)",
        r"ignore (all |any )?(your |the )?rules",
        r"disregard (the |your |all )*(system|previous|above) (prompt|instructions|rules)",
        r"forget (everything|all|what) (you were|you've been|you have been) (told|given|instructed)",
        r"\bnew (system )?instructions\s*:",
        r"^\s*(system|assistant|developer)( note)?( to [a-z ]+)?\s*:",
        r"reveal (your )?(system )?prompt",
        r"you are now (in )?(developer|dan|jailbreak|admin) mode",
        r"act as (an? )?(unrestricted|unfiltered)",
    )
]
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_SPACED_LETTERS = re.compile(r"\b(?:[a-z] ){3,}[a-z]\b", re.I)


def _normalize(text: str) -> str:
    """Undo cheap obfuscation before matching.

    NFKC folds look-alike Unicode (e.g. full-width letters) to plain ASCII; zero-width characters
    are deleted; "i g n o r e" becomes "ignore"; runs of spaces collapse.
    """
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = _SPACED_LETTERS.sub(lambda m: m.group().replace(" ", ""), text)
    return re.sub(r"[ \t]+", " ", text)


def detect_injection(text: str) -> bool:
    """Direct injection: the attack is in the user's own message."""
    text = _normalize(text)
    return any(p.search(text) for p in _INJECTION)


def scan_retrieved(text: str) -> bool:
    """Indirect injection: the attack hides in a *retrieved document* the user never wrote.

    Same patterns, different place in the pipeline. Returns True if the passage must be dropped.
    The prompt also tells the model retrieved text is data (prompts/triage.v1.md): two layers,
    because neither is reliable alone.
    """
    return detect_injection(text)


# --- Tool policy ------------------------------------------------------------------------------

# Tools the agent may call without a human in the loop. Everything else needs approval.
READ_ONLY_TOOLS = {"lookup_case", "search_policy", "get_case", "search_cases"}


def tool_allowed(tool: str, approved: bool) -> bool:
    """Least privilege: read-only tools always pass; anything that mutates state needs approval."""
    return tool in READ_ONLY_TOOLS or approved
