"""Cost-aware model router: pick the cheapest model whose capability tier covers the task.

LEARNING NOTES
- Most messages are simple, so sending all of them to a frontier model wastes money and adds
  latency. The router estimates task *complexity* (1-3) and picks the cheapest tier >= it.
- Model names are LiteLLM *aliases* (agentops-tier1/2/3), not provider model ids. The real model
  behind each alias lives in deploy/litellm/config.yaml, so changing provider never touches this file.
- `budget_tier` caps spend: in a cost incident you can force everything down to tier 2.
- The fallback chain only goes *up* a tier: falling back to a weaker model on a high-risk case
  would trade safety for availability, which is the wrong trade in a regulated setting.
- Prices are illustrative per-1k-token blends; replace with your provider's current pricing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Kept in sync with the agent's high-risk categories. A shared keyword list was a real bug:
# "stolen" routed to tier 2 because only the agent's rules knew it meant fraud.
HIGH_RISK_TERMS = (
    "hardship", "dispute", "fraud", "legal", "ombudsman", "complaint", "scam", "deceased",
    "stolen", "unauthorised", "can't pay", "cannot pay", "lost my job",
)  # fmt: skip


@dataclass(frozen=True)
class ModelSpec:
    name: str  # LiteLLM alias
    tier: int  # 1 = small/fast, 3 = frontier
    usd_per_1k_tokens: float


DEFAULT_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("agentops-tier1", 1, 0.001),
    ModelSpec("agentops-tier2", 2, 0.006),
    ModelSpec("agentops-tier3", 3, 0.02),
)


@dataclass(frozen=True)
class RouteDecision:
    model: ModelSpec
    complexity: int
    reason: str


def complexity(text: str, needs_tools: bool = False) -> int:
    """Cheap heuristic. Its job is to be fast and conservative, not clever."""
    score = 1
    lowered = text.lower()
    if len(text) > 600 or needs_tools:
        score = 2
    if any(t in lowered for t in HIGH_RISK_TERMS) or len(text) > 2000:
        score = 3
    return score


def route(
    text: str, needs_tools: bool = False, models: Sequence[ModelSpec] = DEFAULT_MODELS, budget_tier: int = 3
) -> RouteDecision:
    need = min(complexity(text, needs_tools), budget_tier)
    for m in sorted(models, key=lambda m: m.usd_per_1k_tokens):
        if m.tier >= need:
            return RouteDecision(m, need, f"complexity={need}: cheapest model with tier>={need}")
    return RouteDecision(models[-1], need, "fallback to highest tier")


def fallback_chain(decision: RouteDecision, models: Sequence[ModelSpec] = DEFAULT_MODELS) -> list[ModelSpec]:
    """Models to try, in order, if the chosen one errors or times out (upward only)."""
    return [decision.model] + [m for m in sorted(models, key=lambda m: m.tier) if m.tier > decision.model.tier]
