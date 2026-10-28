"""Typed triage agent (PydanticAI) with tool calling and a deterministic offline model for CI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from .rag import KeywordRetriever, Retriever

Category = Literal["hardship", "dispute", "fraud", "complaint", "general"]

CASES = {
    "C-1001": {"customer": "A. Smith", "product": "Everyday account", "open_issues": 0, "vulnerable": False},
    "C-1002": {"customer": "B. Jones", "product": "Credit card", "open_issues": 2, "vulnerable": True},
}


class TriageResult(BaseModel):
    category: Category
    severity: Literal["low", "medium", "high"]
    summary: str = Field(max_length=300)
    recommended_action: Literal["answer", "escalate", "refund_review", "freeze_card", "hardship_review"]
    needs_human: bool
    citations: list[str] = Field(default_factory=list)


@dataclass
class Deps:
    retriever: Retriever


def build_agent(model) -> Agent[Deps, TriageResult]:
    agent: Agent[Deps, TriageResult] = Agent(
        model,
        deps_type=Deps,
        output_type=TriageResult,
        instructions=(
            "You triage banking customer messages. Use search_policy to ground decisions and cite policy ids. "
            "Anything involving hardship, fraud, disputes over 500 dollars or vulnerable customers needs a human."
        ),
    )

    @agent.tool
    def lookup_case(ctx: RunContext[Deps], case_id: str) -> dict:
        """Read-only case lookup."""
        return CASES.get(case_id, {"error": "not found"})

    @agent.tool
    def search_policy(ctx: RunContext[Deps], query: str) -> list[dict]:
        """Retrieve policy passages with citations."""
        return [{"source": p.source, "text": p.text} for p in ctx.deps.retriever.search(query)]

    return agent


_RULES = (
    ("fraud", ("fraud", "scam", "unauthorised", "stolen"), "high", "freeze_card", True),
    ("hardship", ("hardship", "can't pay", "cannot pay", "lost my job", "struggling"), "high", "hardship_review", True),
    ("dispute", ("dispute", "refund", "charged twice", "wrong charge"), "medium", "refund_review", True),
    ("complaint", ("complaint", "unhappy", "ombudsman", "terrible service"), "medium", "escalate", True),
)


def offline_model() -> FunctionModel:
    """Deterministic stand-in for an LLM so tests and evals run with no API keys.
    It still exercises the real tool-calling and structured-output path."""

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returned = {p.tool_name for m in messages for p in m.parts if isinstance(p, ToolReturnPart)}
        user = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
        text = user if isinstance(user, str) else str(user)
        if "search_policy" not in returned:
            return ModelResponse(parts=[ToolCallPart("search_policy", {"query": text})])
        low = text.lower()
        cat, sev, act, human = "general", "low", "answer", False
        for c, words, s, a, h in _RULES:
            if any(w in low for w in words):
                cat, sev, act, human = c, s, a, h
                break
        cites = []
        for m in messages:
            for p in m.parts:
                if isinstance(p, ToolReturnPart) and p.tool_name == "search_policy":
                    cites = [r["source"].split()[0] for r in p.content][:2]
        out = {"category": cat, "severity": sev, "summary": f"{cat} message triaged as {sev} severity.",
               "recommended_action": act, "needs_human": human, "citations": cites}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, out)])

    return FunctionModel(fn)
