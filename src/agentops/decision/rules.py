"""A small rules engine over policies/rules.yaml. Pure functions: no database, no clock.

LEARNING NOTES
- Keeping evaluation pure (context in, outcome out) makes it trivially unit-testable and lets the
  replay harness (evals/replay.py) run thousands of journeys in milliseconds.
- Why not a full engine like OPA/Rego? One choice per layer: a 100-line evaluator is enough to
  learn the ideas (reason codes, versioning, composition). Phase 7 can swap in OPA behind the same
  `evaluate` signature and compare.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..config import REPO_ROOT

RULES_PATH = REPO_ROOT / "policies" / "rules.yaml"
PRIORITY = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


@dataclass(frozen=True)
class Policy:
    version: str
    raw: dict[str, Any]
    sha: str  # content hash: catches edits that forgot to bump `version`

    @property
    def rules(self) -> list[dict[str, Any]]:
        return list(self.raw["rules"])

    @property
    def regulated(self) -> set[str]:
        return set(self.raw["regulated_actions"])


def load_policy(path: Path | None = None) -> Policy:
    # Feature flag: AGENTOPS_POLICY_FILE=policies/rules-next.yaml trials a new rule set; unset to roll back.
    path = path or Path(os.getenv("AGENTOPS_POLICY_FILE", RULES_PATH))
    if not path.is_absolute():
        path = REPO_ROOT / path
    text = path.read_text()
    raw = yaml.safe_load(text)
    return Policy(str(raw["version"]), raw, hashlib.sha256(text.encode()).hexdigest()[:12])


def _match(value: Any, cond: Any) -> bool:
    """One condition against one context value. Unknown (None) never matches a comparison."""
    if not isinstance(cond, dict):
        return bool(value == cond)
    if value is None:
        return False
    (op, arg), *_ = cond.items()
    match op:
        case "in":
            return value in arg
        case "gt":
            return bool(value > arg)
        case "lt":
            return bool(value < arg)
        case "contains":
            return arg in value
        case "contains_any":
            return any(a in value for a in arg)
        case "not_contains":
            return arg not in value
    raise ValueError(f"unknown operator {op!r}")


@dataclass
class Outcome:
    """What the rules decided, before anything is written. DecisionService turns it into a DecisionResult."""

    queue: str = "general"
    priority: str = "low"
    reason_codes: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    set_flags: list[str] = field(default_factory=list)
    requires_approval: bool = False
    suppress_kinds: list[str] = field(default_factory=list)
    rank_first: list[str] = field(default_factory=list)
    fired: list[str] = field(default_factory=list)


def evaluate(policy: Policy, context: dict[str, Any]) -> Outcome:
    out = Outcome()
    ctx = dict(context)
    ctx["flags"] = list(ctx.get("flags", []))
    recommended = policy.raw["action_map"].get(ctx.get("recommended_action", ""), None)
    if recommended and recommended != "answer":
        out.actions.append(recommended)

    for rule in policy.rules:
        # Recompute derived fields so this rule sees what earlier rules did (see rules.yaml notes).
        # Blocked actions no longer count: R3 blocking a refund must stop R5 asking approval for it.
        # (Found by the replay harness, journey J5: blocks used to apply only at the very end.)
        ctx["regulated_action"] = any(a in policy.regulated and a not in out.blocked_actions for a in out.actions)
        if not all(_match(ctx.get(k), v) for k, v in rule["when"].items()):
            continue
        then = rule["then"]
        out.fired.append(rule["id"])
        out.reason_codes.append(rule["reason_code"])
        if "queue" in then and PRIORITY[then.get("priority", "low")] >= PRIORITY[out.priority]:
            out.queue, out.priority = then["queue"], then.get("priority", out.priority)
        out.actions += [a for a in then.get("actions", []) if a not in out.actions]
        out.blocked_actions += then.get("block_actions", [])
        for f in then.get("set_flags", []):
            if f not in ctx["flags"]:
                out.set_flags.append(f)
                ctx["flags"].append(f)  # later rules (R6, R7) see the new flag immediately
        out.requires_approval |= bool(then.get("requires_approval"))
        out.suppress_kinds += then.get("suppress_kinds", [])
        out.rank_first += then.get("rank_first", [])

    # A blocked action is removed even if an earlier rule or the model asked for it (R3 vs refund).
    out.actions = [a for a in out.actions if a not in out.blocked_actions]
    return out


def rank_offers(policy: Policy, outcome: Outcome, flags: list[str]) -> tuple[list[str], list[str]]:
    """Next-best-action (UC7): returns (ranked candidates, suppressed). Pure and explainable."""
    candidates: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for o in policy.raw["offers"]:
        hidden_by_kind = o["kind"] in outcome.suppress_kinds  # R7: marketing off
        hidden_by_debt = o["adds_debt"] and "hardship_flag" in flags  # never add debt during hardship
        (suppressed if hidden_by_kind or hidden_by_debt else candidates).append(o)
    # Base order: value minus risk. R6 then lifts retention/support to the front.
    # Rounded: 0.7 - 0.3 is 0.39999999999999997 in floating point, which silently breaks ties
    # against 0.5 - 0.1 = 0.4. Ties then fall back to file order, which is stable and reviewable.
    candidates.sort(key=lambda o: -round(o["value"] - o["risk"], 6))
    candidates.sort(key=lambda o: 0 if o["kind"] in outcome.rank_first else 1)
    return [o["id"] for o in candidates], [o["id"] for o in suppressed]
