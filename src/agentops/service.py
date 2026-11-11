"""Triage pipeline: guardrails -> route -> agent (fallback) -> decision -> case -> approval -> action.

LEARNING NOTES (read top to bottom alongside `triage`)
1. Redact PII first, so nothing downstream (model, traces, audit) ever holds raw PII.
2. Block known injections before spending a model call on them.
3. Route to the cheapest adequate model tier; run the agent with an *upward* fallback chain.
4. Record cost from real token usage, not from a per-call guess.
5. The decision service turns the model's *recommendation* into an *authorised* outcome (rules,
   flags, reason codes). Rules win: if R5 says approval, approval it is, whatever the model said.
6. Every triaged message opens a case (workflow/cases.py). Regulated outcomes create an approval
   request routed to the right specialist with an SLA (workflow/approvals.py).
7. Approved actions run exactly once through the idempotent executor (workflow/actions.py).
Every step is a span (OpenTelemetry) and an audit event; trace_id links the two.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from opentelemetry.trace import Span
from pydantic_ai.models import Model

from . import prompts
from .agent import Deps, build_agent
from .audit import AuditLog
from .config import settings
from .contracts import DecisionResult, TriageResult
from .db import Conn
from .decision.service import DecisionService, utcnow
from .guardrails import detect_injection, redact_pii
from .llm import PROVIDER_ERRORS, model_for
from .rag.base import Retriever
from .rag.memory import KeywordRetriever
from .resilience import BREAKER, CircuitBreaker
from .router import ModelSpec, RouteDecision, fallback_chain, route
from .telemetry import APPROVAL_DECISIONS, GUARDRAIL_BLOCKS, LLM_COST, LLM_TOKENS, TRIAGE_DURATION, TRIAGES, tracer
from .workflow.actions import ActionExecutor
from .workflow.approvals import ApprovalQueue
from .workflow.cases import CaseStore


class AllModelsFailed(RuntimeError):
    pass


# Only failures that a *different model* might fix trigger the fallback. Catching every Exception here
# once disguised a programming error (PydanticAI's run_sync called inside a running event loop) as a
# "model outage", twice. Bugs should crash loudly, not quietly cost a tier-3 call.


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
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    prompt_version: str | None = None
    decision: DecisionResult | None = None
    case_id: int | None = None


class TriageService:
    def __init__(
        self,
        conn: Conn,
        model_factory: Callable[[ModelSpec], Model | str] = model_for,
        retriever: Retriever | None = None,
        budget_tier: int = 3,  # cost cap: 2 forces everything to tier 2 or below (used by shadow runs)
        breaker: CircuitBreaker | None = None,
    ):
        self.conn = conn
        self.audit = AuditLog(conn)
        self.decisions = DecisionService(conn, self.audit)
        self.cases = CaseStore(conn, self.audit)
        self.approvals = ApprovalQueue(conn, self.audit)
        self.executor = ActionExecutor(conn, self.audit, self.cases)
        self.retriever = retriever or KeywordRetriever()
        self.model_factory = model_factory
        self.prompt = prompts.load("triage")
        self.budget_tier = budget_tier
        self.breaker = breaker or BREAKER

    # -- step 3: run the agent, falling back up the tiers -----------------------------------------
    def _deps(self, actor: str, roles: frozenset[str]) -> Deps:
        """Per-request tool dependencies. With AGENTOPS_CASE_SOURCE=mcp, cases come from MCP Case Tools as this user."""
        if settings().case_source == "mcp":
            from .mcp_tools import mcp_case_lookup

            return Deps(self.retriever, roles=roles, case_lookup=mcp_case_lookup(actor, roles))
        return Deps(self.retriever, roles=roles)

    def _run_with_fallback(
        self, text: str, routed: RouteDecision, span: Span, roles: frozenset[str], actor: str = "system"
    ) -> tuple[TriageResult, ModelSpec, list[str], float, Any]:
        failed: list[str] = []
        deps = self._deps(actor, roles)
        for spec in fallback_chain(routed):
            if not self.breaker.allow(spec.name):
                # Circuit open: skip straight to the next tier instead of waiting for another timeout.
                failed.append(f"{spec.name} (circuit open)")
                continue
            with tracer().start_as_current_span("agent.run") as run_span:
                # OpenTelemetry GenAI semantic conventions: standard attribute names so any
                # backend (Jaeger, Langfuse, X-Ray) understands model and token data.
                run_span.set_attribute("gen_ai.operation.name", "chat")
                run_span.set_attribute("gen_ai.request.model", spec.name)
                run_span.set_attribute("agentops.prompt.version", self.prompt.version)
                try:
                    run = build_agent(self.model_factory(spec)).run_sync(text, deps=deps)
                except PROVIDER_ERRORS as e:  # provider error, timeout, invalid output after retries
                    run_span.record_exception(e)
                    failed.append(spec.name)
                    self.breaker.record_failure(spec.name)
                    self.audit.record("model_failed", model=spec.name, error=type(e).__name__,
                                      circuit_open=self.breaker.is_open(spec.name))  # fmt: skip
                    continue
                self.breaker.record_success(spec.name)
                usage = run.usage  # a property in PydanticAI 2.x
                run_span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
                run_span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
                # Step 4: cost from measured tokens.
                cost = (usage.input_tokens + usage.output_tokens) / 1000 * spec.usd_per_1k_tokens
                run_span.set_attribute("agentops.cost_usd", cost)
                LLM_TOKENS.add(usage.input_tokens, {"model": spec.name, "direction": "input"})
                LLM_TOKENS.add(usage.output_tokens, {"model": spec.name, "direction": "output"})
                LLM_COST.add(cost, {"model": spec.name})
            span.set_attribute("model.used", spec.name)
            return run.output, spec, failed, cost, run
        raise AllModelsFailed(f"all models failed: {failed}")

    def triage(
        self, message: str, actor: str = "officer-1", customer_id: str | None = None,
        role: str = "officer", txn_id: str | None = None, roles: frozenset[str] | None = None,
        now: datetime | None = None,
    ) -> Outcome:  # fmt: skip
        started = time.perf_counter()
        now = now or utcnow()
        roles = roles or frozenset({role})
        with tracer().start_as_current_span("triage") as span:
            # Step 1: redact.
            red = redact_pii(message)
            span.set_attribute("pii.redactions", sum(red.found.values()))
            pv = {"prompt_version": self.prompt.version}
            self.audit.record("message_received", actor=actor, case_id=customer_id, chars=len(message), **pv)
            if red.found:
                self.audit.record("pii_redacted", case_id=customer_id, counts=red.found)

            # Step 2: block known injections.
            if detect_injection(message):
                self.audit.record(
                    "injection_blocked", actor=actor, case_id=customer_id, reason_code="PROMPT_INJECTION", kind="direct"
                )
                span.set_attribute("blocked", True)
                GUARDRAIL_BLOCKS.add(1, {"kind": "injection", "surface": "triage"})
                TRIAGES.add(1, {"status": "blocked", "category": "none", "model": "none"})
                return Outcome("blocked", None, None, red.found, reason="prompt_injection")

            # Step 3: route + run. Retrieval runs with the *caller's* entitlements (Phase 2).
            routed = route(red.text, needs_tools=True, budget_tier=self.budget_tier)
            span.set_attribute("model.tier", routed.model.tier)
            result, used, failed, cost, run = self._run_with_fallback(red.text, routed, span, roles, actor)
            self.audit.record(
                "triaged", actor=actor, case_id=customer_id, category=result.category, severity=result.severity,
                model=used.name, cost_usd=cost, **pv,
            )  # fmt: skip

            # Step 5: deterministic decision on top of the model's recommendation.
            with tracer().start_as_current_span("decision") as dspan:
                decision = self.decisions.decide(
                    customer_id, result.category, result.recommended_action, role, actor, now=now, txn_id=txn_id
                )
                dspan.set_attribute("decision.reason_codes", decision.reason_codes)
                dspan.set_attribute("decision.policy_version", decision.policy_version)

            # Step 6: open a case and, for regulated outcomes, request approval.
            case = self.cases.create(
                customer_id, decision.queue, decision.priority, red.text, decision.decision_id, actor, now
            )
            self.cases.transition(case["id"], "in_progress", actor, set(roles), now)
            span.set_attribute("case.id", case["id"])
            self._record_trace(case["id"], actor, routed, used, failed, red, run, result, decision, cost, started)
            base: dict[str, Any] = dict(
                model_used=used, failed_models=failed, cost_usd=cost, prompt_version=self.prompt.version,
                decision=decision, case_id=case["id"],
            )  # fmt: skip
            # OR, not AND: either the model or the rules can demand human review.
            if result.needs_human or decision.needs_approval:
                assert decision.decision_id is not None
                action = self._proposed_action(decision)
                req = self.approvals.request(case["id"], decision.decision_id, action, actor, now)
                self.cases.transition(case["id"], "pending_approval", actor, set(roles), now)
                span.set_attribute("hitl", True)
                lat = (time.perf_counter() - started) * 1000
                self._count(result, used, "pending_approval", lat)
                return Outcome("pending_approval", result, routed, red.found, req["id"], latency_ms=lat, **base)
            lat = (time.perf_counter() - started) * 1000
            self._count(result, used, "completed", lat)
            return Outcome("completed", result, routed, red.found, latency_ms=lat, **base)

    @staticmethod
    def _count(result: TriageResult, used: ModelSpec, status: str, latency_ms: float) -> None:
        # Low-cardinality labels only (see telemetry.py): category, status and model, never ids or text.
        TRIAGES.add(1, {"status": status, "category": result.category, "model": used.name})
        TRIAGE_DURATION.record(latency_ms, {"status": status})

    def _record_trace(
        self, case_id: int, actor: str, routed: RouteDecision, used: ModelSpec, failed: list[str], red: Any,
        run: Any, result: TriageResult, decision: DecisionResult, cost: float, started: float,
    ) -> None:  # fmt: skip
        """Store the AI decision trail for this case (migration 007): the conversation as sent, plus the outcome."""
        from opentelemetry import trace as otel
        from psycopg.types.json import Jsonb
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        ctx = otel.get_current_span().get_span_context()
        usage = run.usage
        self.conn.execute(
            "INSERT INTO model_traces (case_id, actor, trace_id, prompt_version, model, route_reason, failed_models, "
            "redacted_input, redactions, messages, output, decision, input_tokens, output_tokens, cost_usd, latency_ms) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                case_id, actor, f"{ctx.trace_id:032x}" if ctx.is_valid else None, self.prompt.version, used.name,
                routed.reason, Jsonb(failed), red.text, Jsonb(red.found),
                Jsonb(ModelMessagesTypeAdapter.dump_python(run.all_messages(), mode="json")),
                Jsonb(result.model_dump(mode="json")), Jsonb(decision.model_dump(mode="json")),
                usage.input_tokens, usage.output_tokens, cost, round((time.perf_counter() - started) * 1000, 1),
            ),
        )  # fmt: skip

    def _proposed_action(self, decision: DecisionResult) -> str:
        """The action a human is asked to approve: the first regulated one the rules allowed."""
        regulated = self.decisions.policy.regulated
        return next((a for a in decision.actions if a in regulated), "escalate")

    def decide(
        self, approval_id: int, approve: bool, user: str, roles: set[str] | None = None,
        reason: str = "", now: datetime | None = None,
    ) -> tuple[dict[str, Any], str | None]:  # fmt: skip
        """Record the human decision; only an approved request lets the action run (exactly once)."""
        now = now or utcnow()
        roles = roles or {"manager"}
        req = self.approvals.decide(approval_id, approve, user, roles, now, reason)
        APPROVAL_DECISIONS.add(1, {"domain": req["domain"], "outcome": "approved" if approve else "rejected"})
        to = "approved" if approve else "rejected"
        self.cases.transition(req["case_id"], to, user, roles, now, approval_id=approval_id)
        if not approve:
            self.cases.transition(req["case_id"], "in_progress", user, roles, now)  # back to the agent
            return req, None
        return req, self.executor.execute(req, user, now)
