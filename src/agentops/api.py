"""HTTP API (FastAPI). Every endpoint except /health needs a bearer token (auth.py).

LEARNING NOTES
- `create_app(conn)` is an *app factory*: tests build an app around a throwaway database schema;
  production builds one around the real database. No global connection hidden at import time.
- Thin on purpose: the API maps HTTP to service calls and domain errors to status codes
  (403 forbidden, 404 unknown, 409 conflict). Business rules live in the service, decision and
  workflow layers, where they are unit-testable.
- Who you are changes what you can do (Phase 4 done-when): officers triage and ask the copilot;
  specialists approve their own domain; managers approve anything, escalate and read the audit log.
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

from . import db, telemetry
from .audit import AuditLog
from .auth import Principal, current_principal, require
from .copilot import Copilot, CopilotAnswer
from .db import Conn
from .decision.flags import FlagPermissionError
from .rag.pg import PgRetriever, ensure_ingested
from .service import TriageService
from .workflow.approvals import ApprovalError
from .workflow.cases import InvalidTransition

STAFF_ROLES = ("officer", "manager", "fraud_specialist", "hardship_specialist", "disputes_officer")


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
        return {"user": p.user, "roles": sorted(p.roles)}

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
    def my_approvals(p: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
        return svc.approvals.pending_for(p.user, set(p.roles))

    @app.post("/approvals/{approval_id}/decision")
    def decide(approval_id: int, d: Decision, p: Principal = Depends(current_principal)) -> dict[str, Any]:
        try:
            req, effect = svc.decide(approval_id, d.approve, p.user, set(p.roles), d.reason)
        except KeyError:
            raise HTTPException(404, "unknown approval") from None
        except ApprovalError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {**req, "effect": effect}

    @app.get("/cases/{case_id}")
    def get_case(case_id: int, p: Principal = Depends(require(*STAFF_ROLES, "compliance"))) -> dict[str, Any]:
        try:
            return svc.cases.get(case_id)
        except KeyError:
            raise HTTPException(404, "unknown case") from None

    @app.post("/cases/{case_id}/transition")
    def transition(case_id: int, t: Transition, p: Principal = Depends(current_principal)) -> dict[str, Any]:
        from .decision.service import utcnow

        try:
            return svc.cases.transition(case_id, t.to, p.user, set(p.roles), utcnow())
        except InvalidTransition as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/customers/{customer_id}/flags/{flag}/clear")
    def clear_flag(customer_id: str, flag: str, p: Principal = Depends(current_principal)) -> dict[str, str]:
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

    return app
