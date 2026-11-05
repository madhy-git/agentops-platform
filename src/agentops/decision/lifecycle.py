"""Customer lifecycle stage transitions (project.md "Customer lifecycle").

LEARNING NOTE: the same message means different things at different stages. "Can I increase my
limit?" is a growth opportunity for an everyday customer and a red flag for one in hardship.
The stage is therefore *state*, updated by events, and read by the rules, not guessed by a prompt.
"""

from __future__ import annotations

DISTRESS_FLAGS = {"fraud_flag", "hardship_flag", "complaint_open"}


def next_stage(current: str, active_flags: set[str], cooling_off: bool) -> str:
    if active_flags & DISTRESS_FLAGS:
        return "distress"
    if current == "distress":
        # Flags just cleared: recovery, with marketing still off during cooling-off.
        return "resolution"
    if current == "resolution" and not cooling_off:
        return "everyday"
    return current
