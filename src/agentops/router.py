"""Cost-aware model router: cheapest model whose capability tier covers the task."""
from __future__ import annotations

from dataclasses import dataclass

HIGH_RISK_TERMS = ("hardship", "dispute", "fraud", "legal", "ombudsman", "complaint", "scam", "deceased")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    tier: int  # 1 = small/fast, 3 = frontier
    usd_per_1k_tokens: float


# Names are provider-qualified PydanticAI model strings; swap for your own deployments.
DEFAULT_MODELS = (
    ModelSpec("bedrock:anthropic.claude-haiku", 1, 0.001),
    ModelSpec("bedrock:anthropic.claude-sonnet", 2, 0.006),
    ModelSpec("azure:gpt-frontier", 3, 0.02),
)


@dataclass(frozen=True)
class RouteDecision:
    model: ModelSpec
    complexity: int
    reason: str


def complexity(text: str, needs_tools: bool = False) -> int:
    score = 1
    lowered = text.lower()
    if len(text) > 600 or needs_tools:
        score = 2
    if any(t in lowered for t in HIGH_RISK_TERMS) or len(text) > 2000:
        score = 3
    return score


def route(text: str, needs_tools: bool = False, models=DEFAULT_MODELS, budget_tier: int = 3) -> RouteDecision:
    need = min(complexity(text, needs_tools), budget_tier)
    for m in sorted(models, key=lambda m: m.usd_per_1k_tokens):
        if m.tier >= need:
            return RouteDecision(m, need, f"complexity={need}: cheapest model with tier>={need}")
    return RouteDecision(models[-1], need, "fallback to highest tier")


def fallback_chain(decision: RouteDecision, models=DEFAULT_MODELS) -> list[ModelSpec]:
    """Models to try, in order, if the chosen one errors or times out."""
    return [decision.model] + [m for m in sorted(models, key=lambda m: m.tier) if m.tier > decision.model.tier]
