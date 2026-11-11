"""Typed triage agent (PydanticAI) plus a deterministic offline model for CI.

LEARNING NOTES
- *Structured output*: the agent must return a TriageResult (contracts.py). PydanticAI exposes
  the schema to the model as an "output tool"; if the model's answer fails validation, the error
  is sent back and the model gets another try. The schema is a guardrail, not just a type hint.
- *Tool calling*: the model decides when to call `search_policy` / `lookup_case`. Tool results
  can change the outcome (a vulnerable customer forces human review), something no prompt alone
  can guarantee.
- *Least privilege*: both tools are read-only. Anything that changes state goes through the
  approval and decision layers, never through the agent directly.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from . import prompts
from .contracts import TriageResult
from .guardrails import scan_retrieved
from .rag.base import Retriever

# Phase 0-3 case source. Phase 4 swaps this for the MCP Case Tools server (mcp_tools.py) via Deps.
CASES: dict[str, dict[str, Any]] = {
    "C-1001": {"customer": "A. Smith", "product": "Everyday account", "open_issues": 0, "vulnerable": False},
    "C-1002": {"customer": "B. Jones", "product": "Credit card", "open_issues": 2, "vulnerable": True},
}


@dataclass
class Deps:
    """Everything a tool needs, injected per run. Tests pass fakes; production passes real clients."""

    retriever: Retriever
    roles: frozenset[str] = frozenset({"officer"})  # whose entitlements retrieval must respect (Phase 2)
    case_lookup: Callable[[str], dict[str, Any]] = field(default=lambda cid: CASES.get(cid, {"error": "not found"}))


def build_agent(model: Model | str) -> Agent[Deps, TriageResult]:
    prompt = prompts.load("triage")
    agent: Agent[Deps, TriageResult] = Agent(model, deps_type=Deps, output_type=TriageResult, instructions=prompt.text)

    @agent.tool
    def lookup_case(ctx: RunContext[Deps], case_id: str) -> dict[str, Any]:
        """Read-only case lookup."""
        return ctx.deps.case_lookup(case_id)

    @agent.tool
    def search_policy(ctx: RunContext[Deps], query: str) -> list[dict[str, str]]:
        """Retrieve policy passages with citations, filtered to the caller's entitlements."""
        hits = ctx.deps.retriever.search(query, roles=ctx.deps.roles)
        # Indirect prompt injection defence (Phase 3): retrieved text is *data*. Passages that look
        # like instructions are dropped before the model sees them, and the drop is visible in tests.
        return [{"source": p.source, "text": p.text} for p in hits if not scan_retrieved(p.text)]

    return agent


# --- Offline stand-in model ----------------------------------------------------------------------

# (category, trigger words, severity, action, needs_human). Deliberately keyword-based, so the
# paraphrase cases in evals/golden.jsonl show exactly where a rules engine stops generalising.
_RULES = (
    ("fraud", ("fraud", "scam", "unauthorised", "stolen"), "high", "freeze_card", True),
    ("hardship", ("hardship", "can't pay", "cannot pay", "lost my job", "struggling"), "high", "hardship_review", True),
    ("dispute", ("dispute", "refund", "charged twice", "wrong charge"), "medium", "refund_review", True),
    ("complaint", ("complaint", "unhappy", "ombudsman", "terrible service"), "medium", "escalate", True),
)
# C-1234 (static demo cases) or WB-1234 (MCP Case Tools, Wattle profile).
_CASE_ID = re.compile(r"\b(?:C|WB)-\d{4}\b")


def rule_triage(text: str, case: dict[str, Any], policy_hits: list[dict[str, Any]]) -> dict[str, Any]:
    """The offline "model's" decision, as a plain function. Shared by every framework adapter in
    benchmarks/ so a framework comparison compares frameworks, not two different rule sets."""
    low = text.lower()
    cat, sev, act, human, conf = "general", "low", "answer", False, 0.7
    rationale = "No fraud, hardship, dispute or complaint keyword found, so treated as a general enquiry."
    for c, words, s, a, h in _RULES:
        hit = next((w for w in words if w in low), None)
        if hit:
            cat, sev, act, human, conf = c, s, a, h, 0.9
            rationale = f'The message contains "{hit}", a {c} indicator, so it is triaged as {c} ({s} severity).'
            break
    if case.get("vulnerable"):
        human, act = True, "escalate" if act == "answer" else act
        rationale += " The linked case is flagged vulnerable, so a human must review it."
    return {
        "category": cat,
        "severity": sev,
        "summary": f"{cat} message triaged as {sev} severity.",
        "recommended_action": act,
        "needs_human": human,
        "confidence": conf,
        "citations": [r["source"].split()[0] for r in policy_hits][:2],
        "rationale": rationale,
    }


def offline_model() -> FunctionModel:
    """Deterministic stand-in for an LLM so tests and evals run with no API keys.

    It plays the model's side of the conversation turn by turn:
      turn 1 -> call search_policy;  turn 2 -> call lookup_case if a case id is present;
      last turn -> call the output tool with a TriageResult.
    """

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # Tool results seen so far, by tool name: this is how the "model" remembers earlier turns.
        returns: dict[str, Any] = {
            p.tool_name: p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)
        }
        user = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
        text = user if isinstance(user, str) else str(user)

        if "search_policy" not in returns:
            return ModelResponse(parts=[ToolCallPart("search_policy", {"query": text})])
        case_id = _CASE_ID.search(text)
        if case_id and "lookup_case" not in returns:
            return ModelResponse(parts=[ToolCallPart("lookup_case", {"case_id": case_id.group()})])

        case = returns.get("lookup_case") or {}
        policy_hits = returns["search_policy"] if isinstance(returns["search_policy"], list) else []
        out = rule_triage(text, case if isinstance(case, dict) else {}, policy_hits)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, out)])

    return FunctionModel(fn, model_name="offline-rules")
