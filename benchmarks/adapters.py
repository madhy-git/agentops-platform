"""One triage task, two agent frameworks, behind the same interface (Phase 7).

LEARNING NOTES
- An *adapter* hides each framework behind `triage(text) -> Result`, so the benchmark harness can't
  accidentally favour one. Same golden set, same prompt text, same retriever, same model alias.
- The two designs are genuinely different, and that's part of what you're comparing:
    PydanticAI: an *agent loop*. The model decides to call search_policy / lookup_case as tools.
    LangGraph:  an explicit *graph*. retrieve -> classify is fixed in code; the model only classifies.
  The graph makes the control flow auditable and cheaper (one model call); the agent loop is more flexible
  (the model can choose to look up a case). Neither is "better" in general.
- Offline, both drive the same rule-based stand-in (agent.rule_triage), so accuracy must be equal and only
  framework overhead differs. A difference in accuracy offline would mean an adapter bug.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from agentops import prompts
from agentops.agent import _CASE_ID, CASES, Deps, build_agent, rule_triage
from agentops.config import settings
from agentops.contracts import TriageResult
from agentops.guardrails import scan_retrieved
from agentops.llm import model_for
from agentops.rag.memory import KeywordRetriever
from agentops.router import DEFAULT_MODELS

SPEC = DEFAULT_MODELS[1]  # benchmark at one tier so cost/latency compare like for like


@dataclass
class Result:
    output: TriageResult
    input_tokens: int
    output_tokens: int
    latency_ms: float


class Adapter(Protocol):
    name: str

    def triage(self, text: str) -> Result: ...


class PydanticAIAdapter:
    name = "pydantic-ai"

    def __init__(self) -> None:
        self.agent = build_agent(model_for(SPEC))
        self.retriever = KeywordRetriever()

    def triage(self, text: str) -> Result:
        t0 = time.perf_counter()
        run = self.agent.run_sync(text, deps=Deps(self.retriever))
        u = run.usage
        return Result(run.output, u.input_tokens, u.output_tokens, (time.perf_counter() - t0) * 1000)


# --- LangGraph -------------------------------------------------------------------------------------


class _State(TypedDict, total=False):
    text: str
    passages: list[dict[str, str]]
    case: dict[str, Any]
    result: TriageResult
    usage: tuple[int, int]


def _rule_chat_model() -> Any:
    """A LangChain chat model that answers with the same rules as the PydanticAI offline model."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class RuleChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "offline-rules"

        def _generate(self, messages: list[Any], stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
            text = str(messages[-1].content).split("MESSAGE:", 1)[-1].strip()
            sources = [
                line.split("]")[0].lstrip("[")
                for line in str(messages[-1].content).splitlines()
                if line.startswith("[")
            ]
            case = json.loads(str(messages[-1].content).split("CASE:", 1)[1].split("\n", 1)[0] or "{}")
            out = rule_triage(text, case, [{"source": s} for s in sources])
            prompt_tokens = sum(len(str(m.content).split()) for m in messages)
            msg = AIMessage(content=TriageResult(**out).model_dump_json(),
                            usage_metadata={"input_tokens": prompt_tokens, "output_tokens": 40, "total_tokens": prompt_tokens + 40})  # fmt: skip
            return ChatResult(generations=[ChatGeneration(message=msg)])

    return RuleChatModel()


def _live_chat_model() -> Any:
    from langchain_openai import ChatOpenAI

    s = settings()
    return ChatOpenAI(
        model=SPEC.name, base_url=s.litellm_base_url, api_key=s.litellm_api_key, timeout=30, max_retries=0
    )


class LangGraphAdapter:
    name = "langgraph"

    def __init__(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langgraph.graph import END, START, StateGraph

        self.retriever = KeywordRetriever()
        live = settings().live
        llm = _live_chat_model() if live else _rule_chat_model()
        instructions = prompts.load("triage").text

        def retrieve(state: _State) -> _State:
            hits = self.retriever.search(state["text"], roles={"officer"})
            return {"passages": [{"source": p.source, "text": p.text} for p in hits if not scan_retrieved(p.text)]}

        def lookup(state: _State) -> _State:
            # Added after the first benchmark run: without this node the graph never learned that C-1002 is a
            # vulnerable customer, and escalation recall was 0.923. In an agent loop the *model* chooses to look
            # a case up; in a graph every capability must be an explicit node and edge.
            m = _CASE_ID.search(state["text"])
            return {"case": CASES.get(m.group(), {}) if m else {}}

        def has_case_id(state: _State) -> str:
            return "lookup" if _CASE_ID.search(state["text"]) else "classify"

        def classify(state: _State) -> _State:
            ctx = "\n".join(f"[{p['source']}] {p['text']}" for p in state["passages"])
            case = json.dumps(state.get("case", {}))
            msgs = [SystemMessage(instructions + "\nReturn JSON matching the TriageResult schema."),
                    HumanMessage(f"CONTEXT:\n{ctx}\nCASE:{case}\n\nMESSAGE: {state['text']}")]  # fmt: skip
            if live:
                structured = llm.with_structured_output(TriageResult, include_raw=True)
                r = structured.invoke(msgs)
                um = r["raw"].usage_metadata or {}
                return {"result": r["parsed"], "usage": (um.get("input_tokens", 0), um.get("output_tokens", 0))}
            ai = llm.invoke(msgs)
            um = ai.usage_metadata or {}
            return {
                "result": TriageResult.model_validate_json(ai.content),
                "usage": (um["input_tokens"], um["output_tokens"]),
            }

        g = StateGraph(_State)
        g.add_node("retrieve", retrieve)
        g.add_node("lookup", lookup)
        g.add_node("classify", classify)
        g.add_edge(START, "retrieve")
        g.add_conditional_edges("retrieve", has_case_id, {"lookup": "lookup", "classify": "classify"})
        g.add_edge("lookup", "classify")
        g.add_edge("classify", END)
        self.graph = g.compile()

    def triage(self, text: str) -> Result:
        t0 = time.perf_counter()
        s = self.graph.invoke({"text": text})
        return Result(s["result"], s["usage"][0], s["usage"][1], (time.perf_counter() - t0) * 1000)


ADAPTERS = [PydanticAIAdapter, LangGraphAdapter]
