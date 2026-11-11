"""Customer self-service API (`/portal/*`): raise a request, track it, ask the help assistant.

LEARNING NOTES
- Same pipeline as staff triage (redaction, injection guard, agent, rules R1-R7, case, approval), so a
  customer's "my card was stolen" lands in the fraud specialist's queue exactly like an officer's would.
  What differs is what comes BACK: customers see plain-language status, never reason codes, risk scores,
  model names, queue names, flags or who approved. Internal detail is for staff; outcomes are for customers.
- Every query is scoped by `p.customer_id` from the signed token. There is no `customer_id` parameter
  anywhere in this router, so there is nothing to tamper with. Someone else's case answers 404 (not 403),
  which doesn't even confirm the case exists (tests/integration/test_portal.py).
- The customer timeline is built from `case_state_changed` audit events, i.e. from the same append-only
  record the auditors read. One source of truth, translated for each audience, instead of a second
  status field that can drift from it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .auth import Principal, require
from .copilot import Copilot, CopilotAnswer
from .db import Conn
from .service import TriageService

# Case state -> what the customer sees. `step` drives the progress bar (0 received .. 3 done).
STATUS: dict[str, tuple[str, str, int]] = {
    "new": ("Received", "We've received your request.", 0),
    "in_progress": ("Being reviewed", "Our team is looking at your request.", 1),
    "escalated": ("Being reviewed", "A senior team member is looking at your request.", 1),
    "reopened": ("Being reviewed", "We've reopened your request and are looking at it again.", 1),
    "pending_approval": ("With a specialist", "A specialist is reviewing your request.", 2),
    "approved": ("Approved", "A specialist has approved the next step.", 2),
    "rejected": ("Being reviewed", "A specialist has reviewed your request; our team will follow up.", 1),
    "actioned": ("Action taken", "We've taken action on your request.", 3),
    "resolved": ("Resolved", "Your request has been resolved.", 3),
    "closed": ("Closed", "This request is closed.", 3),
}
TOPIC = {
    "fraud": "Card security",
    "hardship_specialist": "Financial hardship support",
    "disputes": "Transaction dispute",
    "disputes_officer": "Transaction dispute",
    "complaints": "Complaint",
    "general": "General enquiry",
}
# What a completed action means to the customer (actions.py effects are internal ledger strings).
ACTION_DONE = {
    "block_card": "Your card has been blocked to protect you. A replacement will be arranged.",
    "hardship_review": "Your hardship application has been approved for review; we'll be in touch about options.",
    "refund_review": "Your refund request has been approved for review.",
}


class NewRequest(BaseModel):
    message: str = Field(min_length=3, max_length=2000)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    session_id: str | None = None


def reference(case_id: int) -> str:
    return f"WB-{case_id:06d}"


def _summary(case: dict[str, Any], approval: dict[str, Any] | None) -> dict[str, Any]:
    label, detail, step = STATUS.get(case["state"], ("Being reviewed", "Our team is looking at your request.", 1))
    if case["state"] == "actioned" and approval and approval["action"] in ACTION_DONE:
        detail = ACTION_DONE[approval["action"]]
    expected_by = approval["sla_due"] if approval and case["state"] == "pending_approval" else None
    return {
        "id": case["id"],
        "reference": reference(case["id"]),
        "topic": TOPIC.get(case["queue"], "General enquiry"),
        "status": label,
        "status_detail": detail,
        "step": step,
        "message": case["summary"],  # the customer's own words, PII-redacted
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "expected_by": expected_by,
    }


def portal_router(conn: Conn, svc: TriageService, copilot: Copilot) -> APIRouter:
    r = APIRouter(prefix="/portal", tags=["portal"])
    customer = require("customer")

    def latest_approval(case_id: int) -> dict[str, Any] | None:
        row: dict[str, Any] | None = conn.execute(
            "SELECT action, status, sla_due FROM approval_requests WHERE case_id = %s ORDER BY id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return row

    def own_case(case_id: int, p: Principal) -> dict[str, Any]:
        row: dict[str, Any] | None = conn.execute(
            "SELECT * FROM cases WHERE id = %s AND customer_id = %s", (case_id, p.customer_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "no such request")  # same answer whether it's missing or someone else's
        return row

    @r.get("/me")
    def me(p: Principal = Depends(customer)) -> dict[str, Any]:
        row = conn.execute("SELECT name FROM customers WHERE customer_id = %s", (p.customer_id,)).fetchone()
        return {"user": p.user, "customer_id": p.customer_id, "name": row["name"] if row else p.user}

    @r.post("/requests")
    def raise_request(req: NewRequest, p: Principal = Depends(customer)) -> dict[str, Any]:
        # role="officer" for the rules: a customer-raised regulated action needs a specialist's approval (R5).
        o = svc.triage(
            req.message, actor=p.user, customer_id=p.customer_id, role="officer", roles=frozenset({"customer"})
        )
        if o.status == "blocked" or o.case_id is None:
            raise HTTPException(422, "We couldn't process that message. Please rephrase it, or call us on 13 00 00.")
        return _summary(svc.cases.get(o.case_id), latest_approval(o.case_id))

    @r.get("/cases")
    def my_cases(p: Principal = Depends(customer)) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM cases WHERE customer_id = %s ORDER BY id DESC LIMIT 50", (p.customer_id,)
        ).fetchall()
        return [_summary(c, latest_approval(c["id"])) for c in rows]

    @r.get("/cases/{case_id}")
    def my_case(case_id: int, p: Principal = Depends(customer)) -> dict[str, Any]:
        case = own_case(case_id, p)
        events = conn.execute(
            "SELECT ts, data FROM audit_events WHERE case_id = %s AND event IN ('case_state_changed', 'case_closed') "
            "ORDER BY id",
            (str(case_id),),
        ).fetchall()
        timeline: list[dict[str, Any]] = []
        for e in events:
            data = e["data"]
            if data.get("rejected"):  # refused transition attempts are for auditors, not customers
                continue
            label, detail, _ = STATUS.get(data.get("to_state", ""), ("Updated", "", 1))
            if timeline and timeline[-1]["status"] == label:  # e.g. new -> in_progress both read "reviewed"
                continue
            ts: datetime = e["ts"]
            timeline.append({"at": ts, "status": label, "detail": detail})
        return {**_summary(case, latest_approval(case_id)), "timeline": timeline}

    @r.post("/assistant/stream")
    async def assistant(q: Question, p: Principal = Depends(customer)) -> EventSourceResponse:
        """Help assistant over customer-readable articles only. Same SSE shape as /copilot/stream."""
        session = q.session_id or str(uuid.uuid4())

        async def events() -> AsyncIterator[dict[str, str]]:
            async for item in copilot.stream(q.question, p, session):
                if isinstance(item, CopilotAnswer):
                    done = {"sources": item.sources, "session_id": session, "answered_by": item.answered_by}
                    yield {"event": "done", "data": json.dumps(done)}
                else:
                    yield {"event": "delta", "data": item}

        return EventSourceResponse(events())

    return r
