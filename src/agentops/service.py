"""Triage pipeline: guardrails -> route -> agent (with fallback) -> HITL gate -> audit."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .agent import Deps, TriageResult, build_agent, offline_model
from .approvals import Approval, ApprovalStore
from .guardrails import detect_injection, redact_pii, tool_allowed
from .rag import KeywordRetriever
from .router import ModelSpec, RouteDecision, fallback_chain, route
from .telemetry import tracer

# Fake side effects for approved actions. In a real bank these call core-banking APIs.
ACTIONS = {
    "freeze_card": lambda text: "card frozen",
    "refund_review": lambda text: "refund review opened",
    "hardship_review": lambda text: "hardship review opened",
    "escalate": lambda text: "escalated to officer queue",
}


class AllModelsFailed(RuntimeError):
    pass


@dataclass
class Outcome:
    status: str  # completed | pending_approval | blocked
    result: TriageResult | None
    route: RouteDecision | None
    redactions: dict[str, int]
    approval_id: int | None = None
    reason: str | None = None
    model_used: ModelSpec | None = None  # differs from route.model when a fallback kicked in
    failed_models: list[str] = field(default_factory=list)


class TriageService:
    def __init__(self, store: ApprovalStore | None = None, model_factory=None):
        self.store = store or ApprovalStore(os.getenv("AGENTOPS_DB"))
        self.retriever = KeywordRetriever()
        # AGENTOPS_MODE=live uses the routed provider model; default offline stub keeps CI key-free.
        live = os.getenv("AGENTOPS_MODE") == "live"
        self.model_factory = model_factory or ((lambda spec: spec.name) if live else (lambda spec: offline_model()))

    def _run_with_fallback(self, text: str, decision: RouteDecision, span) -> tuple[TriageResult, ModelSpec, list[str]]:
        failed: list[str] = []
        for spec in fallback_chain(decision):
            with tracer().start_as_current_span("agent.run") as run_span:
                run_span.set_attribute("model.name", spec.name)
                try:
                    result = build_agent(self.model_factory(spec)).run_sync(text, deps=Deps(self.retriever)).output
                except Exception as e:  # provider error, timeout, invalid output after retries
                    run_span.record_exception(e)
                    failed.append(spec.name)
                    self.store.log("model_failed", model=spec.name, error=type(e).__name__)
                    continue
            span.set_attribute("model.used", spec.name)
            return result, spec, failed
        raise AllModelsFailed(f"all models failed: {failed}")

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

            result, used, failed = self._run_with_fallback(red.text, decision, span)

            self.store.log("triaged", category=result.category, severity=result.severity, model=used.name)
            if result.needs_human:
                appr = self.store.request(red.text, result.recommended_action)
                span.set_attribute("hitl", True)
                return Outcome("pending_approval", result, decision, red.found, appr.id,
                               model_used=used, failed_models=failed)
            return Outcome("completed", result, decision, red.found, model_used=used, failed_models=failed)

    def decide(self, approval_id: int, approve: bool, reviewer: str) -> tuple[Approval, str | None]:
        """Record the human decision; only an approved decision lets the mutating action run."""
        appr = self.store.decide(approval_id, approve, reviewer)
        if appr.status != "approved":
            return appr, None
        return appr, self.execute(appr.proposed_action, appr.case_text, approved=True)

    def execute(self, action: str, text: str, approved: bool) -> str | None:
        if action not in ACTIONS:
            return None
        if not tool_allowed(action, approved):
            self.store.log("action_denied", action=action, reason="no human approval")
            return None
        effect = ACTIONS[action](text)
        self.store.log("action_executed", action=action, effect=effect)
        return effect
