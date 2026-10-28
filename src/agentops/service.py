"""Triage pipeline: guardrails -> route -> agent (with fallback) -> HITL gate -> audit."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .agent import Deps, TriageResult, build_agent, offline_model
from .approvals import ApprovalStore
from .guardrails import detect_injection, redact_pii
from .rag import KeywordRetriever
from .router import RouteDecision, route
from .telemetry import tracer


@dataclass
class Outcome:
    status: str  # completed | pending_approval | blocked
    result: TriageResult | None
    route: RouteDecision | None
    redactions: dict[str, int]
    approval_id: int | None = None
    reason: str | None = None


class TriageService:
    def __init__(self, store: ApprovalStore | None = None, model_factory=None):
        self.store = store or ApprovalStore()
        self.retriever = KeywordRetriever()
        # AGENTOPS_MODE=live uses the routed provider model; default offline stub keeps CI key-free.
        live = os.getenv("AGENTOPS_MODE") == "live"
        self.model_factory = model_factory or ((lambda spec: spec.name) if live else (lambda spec: offline_model()))

    def triage(self, message: str) -> Outcome:
        with tracer().start_as_current_span("triage") as span:
            red = redact_pii(message)
            span.set_attribute("pii.redactions", sum(red.found.values()))
            if detect_injection(message):
                self.store.log("blocked", reason="prompt_injection")
                span.set_attribute("blocked", True)
                return Outcome("blocked", None, None, red.found, reason="prompt_injection")

            decision = route(red.text, needs_tools=True)
            span.set_attribute("model.name", decision.model.name)
            span.set_attribute("model.tier", decision.model.tier)
            span.set_attribute("model.usd_per_1k", decision.model.usd_per_1k_tokens)

            agent = build_agent(self.model_factory(decision.model))
            with tracer().start_as_current_span("agent.run"):
                result = agent.run_sync(red.text, deps=Deps(self.retriever)).output

            self.store.log("triaged", category=result.category, severity=result.severity, model=decision.model.name)
            if result.needs_human:
                appr = self.store.request(red.text, result.recommended_action)
                span.set_attribute("hitl", True)
                return Outcome("pending_approval", result, decision, red.found, appr.id)
            return Outcome("completed", result, decision, red.found)
