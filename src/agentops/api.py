"""HTTP API (FastAPI). Every endpoint except /health needs a bearer token (auth.py).

LEARNING NOTES
- `create_app(conn)` is an *app factory*: tests build an app around a throwaway database schema;
  production builds one around the real database. No global connection hidden at import time.
- Thin on purpose: the API maps HTTP to service calls and domain errors to status codes
  (403 forbidden, 404 unknown, 409 conflict). Business rules live in the service, decision and
  workflow layers, where they are unit-testable.
- Who you are changes what you can do (Phase 4 done-when): officers triage and ask the copilot;
  specialists approve their own domain; managers approve anything, escalate and read the audit log.
- Customers use the same API under /portal (portal.py). Staff endpoints require a staff role explicitly;
  "any valid token" stopped being safe the day customers could get tokens (see /cases/{id}/transition).
- Note: psycopg here is synchronous, so DB calls inside async endpoints block the event loop.
  Fine for a learning app; production would use an async pool (psycopg AsyncConnectionPool).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import db, personas, telemetry
from .audit import AuditLog
from .auth import Principal, current_principal, dev_token, require
from .config import settings
from .copilot import Copilot, CopilotAnswer
from .db import Conn
from .decision.flags import FlagPermissionError
from .portal import portal_router
from .rag.pg import PgRetriever, ensure_ingested
from .service import TriageService
from .workflow.approvals import ApprovalError
from .workflow.cases import TRANSITIONS, InvalidTransition

STAFF_ROLES = ("officer", "manager", "fraud_specialist", "hardship_specialist", "disputes_officer")
READ_ROLES = (*STAFF_ROLES, "compliance")  # may look at cases, but compliance never changes them


class TriageRequest(BaseModel):
    message: str
    customer_id: str | None = None
    txn_id: str | None = None


class Decision(BaseModel):
    approve: bool
    reason: str = ""


class Question(BaseModel):
    question: str
    session_id: str | None = None


class Transition(BaseModel):
    to: str


class DevLogin(BaseModel):
    username: str


def _role_for_rules(p: Principal) -> str:
    """The rules distinguish officer vs manager requests (R5). Specialists request as officers."""
    return "manager" if "manager" in p.roles else "officer"


def create_app(conn: Conn | None = None) -> FastAPI:
    conn = conn or db.connect()
    telemetry.init()
    # One pod at a time: replicas starting together would otherwise race to migrate and ingest (db.startup_lock).
    with db.startup_lock(conn):
        db.migrate(conn)  # no-op when already applied (tests pass a freshly migrated scratch schema)
        ensure_ingested(conn)  # first start: chunk + embed the policy corpus (~10 s, then cached)
        personas.seed_demo_customers(conn)  # the portal's demo customers (idempotent)
    retriever = PgRetriever(conn, audit=AuditLog(conn))
    svc = TriageService(conn, retriever=retriever)
    copilot = Copilot(conn, retriever=retriever)
    app = FastAPI(title="AgentOps Platform", version="0.4.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        """Can this pod actually serve? Kubernetes' readiness AND liveness probes use this, not /health.

        LEARNING NOTE: found by killing the Postgres pod in the local cluster. The API holds one long-lived
        connection; after the database restarted, every request failed (AdminShutdown) while /health kept
        answering 200, so Kubernetes saw a healthy pod and never fixed it. A probe must check what the pod
        needs to do its job. Failing liveness here restarts the pod, which opens a fresh connection.
        The fuller fix, not built yet, is a connection pool that reconnects by itself (psycopg_pool).
        """
        try:
            conn.execute("SELECT 1")
        except psycopg.Error:
            raise HTTPException(503, "database unavailable") from None
        return {"status": "ready"}

    @app.get("/me")
    def me(p: Principal = Depends(current_principal)) -> dict[str, Any]:
        return {"user": p.user, "roles": sorted(p.roles), "customer_id": p.customer_id}

    # --- demo sign-in (personas.py explains the two guards) ---------------------------------------------------
    def dev_login_enabled() -> bool:
        s = settings()
        return s.dev_login and not s.jwt_jwks_url

    @app.get("/auth/personas")
    def list_personas() -> dict[str, Any]:
        enabled = dev_login_enabled()
        return {"enabled": enabled, "personas": [personas.as_dict(x) for x in personas.personas()] if enabled else []}

    @app.post("/auth/dev-login")
    def dev_login(body: DevLogin) -> dict[str, Any]:
        if not dev_login_enabled():
            raise HTTPException(404, "not found")  # don't advertise that a demo login exists
        who = personas.find(body.username)
        if who is None:
            raise HTTPException(401, "unknown demo user")
        svc.audit.record("dev_login", actor=who.username, roles=list(who.roles))
        token = dev_token(who.username, list(who.roles), ttl_s=8 * 3600, customer_id=who.customer_id)
        return {"token": token, "persona": personas.as_dict(who)}

    @app.post("/triage")
    def triage(req: TriageRequest, p: Principal = Depends(require(*STAFF_ROLES))) -> dict[str, Any]:
        o = svc.triage(req.message, actor=p.user, customer_id=req.customer_id, role=_role_for_rules(p),
                       txn_id=req.txn_id, roles=p.roles)  # fmt: skip
        return {
            "status": o.status,
            "case_id": o.case_id,
            "approval_id": o.approval_id,
            "result": o.result.model_dump() if o.result else None,
            "decision": o.decision.model_dump() if o.decision else None,
            "model": o.model_used.name if o.model_used else None,
            "route_reason": o.route.reason if o.route else None,
            "failed_models": o.failed_models,
            "redactions": o.redactions,
            "reason": o.reason,
            "prompt_version": o.prompt_version,
        }

    @app.get("/approvals/mine")
    def my_approvals(p: Principal = Depends(require(*STAFF_ROLES))) -> list[dict[str, Any]]:
        rows = svc.approvals.pending_for(p.user, set(p.roles))
        # The approver needs context to decide: what the customer said and who they are (still PII-redacted).
        for a in rows:
            case = conn.execute(
                "SELECT c.summary, c.priority, c.customer_id, cu.name AS customer_name FROM cases c "
                "LEFT JOIN customers cu USING (customer_id) WHERE c.id = %s",
                (a["case_id"],),
            ).fetchone()
            a.update(case or {})
        return rows

    @app.post("/approvals/{approval_id}/decision")
    def decide(approval_id: int, d: Decision, p: Principal = Depends(require(*STAFF_ROLES))) -> dict[str, Any]:
        try:
            req, effect = svc.decide(approval_id, d.approve, p.user, set(p.roles), d.reason)
        except KeyError:
            raise HTTPException(404, "unknown approval") from None
        except ApprovalError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {**req, "effect": effect}

    # --- staff workspace ----------------------------------------------------------------------------------------
    @app.get("/cases")
    def list_cases(
        state: str | None = None, limit: int = 100, p: Principal = Depends(require(*READ_ROLES))
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT c.*, cu.name AS customer_name, a.id AS approval_id, a.status AS approval_status, "
            "a.assigned_to AS approver, a.sla_due, a.escalated_at FROM cases c "
            "LEFT JOIN customers cu USING (customer_id) "
            "LEFT JOIN LATERAL (SELECT * FROM approval_requests ar WHERE ar.case_id = c.id ORDER BY ar.id DESC LIMIT 1) a ON true "
            "WHERE (%(state)s::text IS NULL OR c.state = %(state)s) ORDER BY c.id DESC LIMIT %(limit)s",
            {"state": state, "limit": min(max(limit, 1), 500)},
        ).fetchall()
        return list(rows)

    @app.get("/cases/{case_id}")
    def get_case(case_id: int, p: Principal = Depends(require(*READ_ROLES))) -> dict[str, Any]:
        try:
            case = svc.cases.get(case_id)
        except KeyError:
            raise HTTPException(404, "unknown case") from None
        decision = None
        if case["decision_id"]:
            row = conn.execute("SELECT result FROM decisions WHERE id = %s", (case["decision_id"],)).fetchone()
            decision = row["result"] if row else None
        approvals = conn.execute(
            "SELECT * FROM approval_requests WHERE case_id = %s ORDER BY id", (case_id,)
        ).fetchall()
        customer = None
        if case["customer_id"]:
            customer = customer_view(case["customer_id"])
        # Additive: the original case columns stay at the top level, so older clients keep working.
        return {**case, "decision": decision, "approvals": list(approvals), "customer": customer,
                "allowed_transitions": sorted(TRANSITIONS.get(case["state"], set()))}  # fmt: skip

    def customer_view(customer_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT customer_id, name, lifecycle_stage, vulnerable FROM customers WHERE customer_id = %s",
            (customer_id,),
        ).fetchone()
        if row is None:
            return None
        return {**row, "active_flags": svc.decisions.flags.active(customer_id)}

    @app.get("/customers/{customer_id}")
    def get_customer(customer_id: str, p: Principal = Depends(require(*READ_ROLES))) -> dict[str, Any]:
        c = customer_view(customer_id)
        if c is None:
            raise HTTPException(404, "unknown customer")
        return c

    @app.get("/stats")
    def stats(p: Principal = Depends(require(*READ_ROLES))) -> dict[str, Any]:
        by_state = {r["state"]: r["n"] for r in conn.execute("SELECT state, count(*) AS n FROM cases GROUP BY state")}
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE status = 'pending') AS pending, "
            "count(*) FILTER (WHERE status = 'pending' AND sla_due < now()) AS overdue, "
            "count(*) FILTER (WHERE status = 'pending' AND assigned_to = %s) AS mine, "
            "count(*) FILTER (WHERE status <> 'pending' AND decided_at > now() - interval '24 hours') AS decided_24h "
            "FROM approval_requests",
            (p.user,),
        ).fetchone()
        return {"cases_by_state": by_state, "approvals": dict(row or {})}

    @app.post("/cases/{case_id}/transition")
    def transition(case_id: int, t: Transition, p: Principal = Depends(require(*STAFF_ROLES))) -> dict[str, Any]:
        from .decision.service import utcnow

        try:
            return svc.cases.transition(case_id, t.to, p.user, set(p.roles), utcnow())
        except InvalidTransition as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/customers/{customer_id}/flags/{flag}/clear")
    def clear_flag(customer_id: str, flag: str, p: Principal = Depends(require(*STAFF_ROLES))) -> dict[str, str]:
        try:
            svc.decisions.clear_flag(customer_id, flag, p.user, set(p.roles))
        except FlagPermissionError as e:
            raise HTTPException(403, str(e)) from e
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return {"cleared": flag}

    @app.get("/audit")
    def audit(
        case_id: str | None = None, p: Principal = Depends(require("manager", "compliance"))
    ) -> list[dict[str, Any]]:
        return svc.audit.events(case_id)

    @app.post("/copilot")
    async def ask(q: Question, p: Principal = Depends(require(*STAFF_ROLES))) -> dict[str, Any]:
        a = await copilot.ask(q.question, p, q.session_id or str(uuid.uuid4()))
        return a.__dict__

    @app.post("/copilot/stream")
    async def ask_stream(q: Question, p: Principal = Depends(require(*STAFF_ROLES))) -> EventSourceResponse:
        """Server-Sent Events: `delta` events carry text; one final `done` event carries sources."""
        session = q.session_id or str(uuid.uuid4())

        async def events() -> AsyncIterator[dict[str, str]]:
            async for item in copilot.stream(q.question, p, session):
                if isinstance(item, CopilotAnswer):
                    yield {"event": "done", "data": json.dumps(item.__dict__ | {"session_id": session})}
                else:
                    yield {"event": "delta", "data": item}

        return EventSourceResponse(events())

    app.include_router(portal_router(conn, svc, copilot))
    return app
