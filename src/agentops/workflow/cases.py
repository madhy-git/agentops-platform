"""Case state machine.

    new -> in_progress -> pending_approval -> approved -> actioned -> resolved -> closed
                              |-> rejected -> in_progress
    any open state -> escalated (manager)       resolved/closed -> reopened -> in_progress

LEARNING NOTES
- Transitions are data (TRANSITIONS), not if-statements scattered through handlers. One table to
  review, one function (`transition`) that every state change goes through, one audit event each.
- Invalid transitions raise *and are audited*: an attempt to jump from new to actioned is a bug or
  an attack, and either way someone should see it.
- `SELECT ... FOR UPDATE` locks the row so two workers can't move the same case at once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..audit import AuditLog
from ..contracts import AuditEventType
from ..db import Conn, one

OPEN = {"new", "in_progress", "pending_approval", "approved", "rejected", "actioned", "escalated", "reopened"}
TRANSITIONS: dict[str, set[str]] = {
    "new": {"in_progress", "escalated"},
    "in_progress": {"pending_approval", "resolved", "escalated"},
    "pending_approval": {"approved", "rejected", "escalated"},
    "approved": {"actioned", "escalated"},
    "rejected": {"in_progress", "escalated"},
    "actioned": {"resolved", "escalated"},
    "resolved": {"closed", "reopened"},
    "closed": {"reopened"},
    "escalated": {"in_progress", "pending_approval", "resolved"},
    "reopened": {"in_progress"},
}
# Only managers may escalate or reopen; everything else follows from approvals and actions.
MANAGER_ONLY = {"escalated", "reopened"}


class InvalidTransition(ValueError):
    pass


class CaseStore:
    def __init__(self, conn: Conn, audit: AuditLog):
        self.conn, self.audit = conn, audit

    def create(
        self, customer_id: str | None, queue: str, priority: str, summary: str,
        decision_id: int | None, created_by: str, now: datetime,
    ) -> dict[str, Any]:  # fmt: skip
        row = one(
            self.conn,
            "INSERT INTO cases (customer_id, state, queue, priority, summary, decision_id, created_by, created_at, updated_at) "
            "VALUES (%s,'new',%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (customer_id, queue, priority, summary, decision_id, created_by, now, now),
        )
        self.audit.record("case_state_changed", actor=created_by, case_id=str(row["id"]), to_state="new")
        return row

    def get(self, case_id: int) -> dict[str, Any]:
        return one(self.conn, "SELECT * FROM cases WHERE id = %s", (case_id,))

    def transition(
        self, case_id: int, to: str, actor: str, roles: set[str], now: datetime, **audit: Any
    ) -> dict[str, Any]:
        problem = None
        with self.conn.transaction():
            case = one(self.conn, "SELECT * FROM cases WHERE id = %s FOR UPDATE", (case_id,))
            frm = case["state"]
            if to not in TRANSITIONS[frm]:
                problem = f"{frm} -> {to} is not an allowed transition"
            elif to in MANAGER_ONLY and not roles & {"manager", "system"}:
                problem = f"only a manager may move a case to {to}"
            else:
                row = one(
                    self.conn, "UPDATE cases SET state=%s, updated_at=%s WHERE id=%s RETURNING *", (to, now, case_id)
                )
                event: AuditEventType = "case_closed" if to == "closed" else "case_state_changed"
                self.audit.record(event, actor=actor, case_id=str(case_id), from_state=frm, to_state=to, **audit)
        if problem:
            # Audited AFTER the transaction closes. Recording it inside and then raising would roll the
            # audit row back with everything else, silently erasing the evidence of the attempt.
            # (Found by tests/integration/test_workflow.py.)
            self.audit.record("case_state_changed", actor=actor, case_id=str(case_id), from_state=frm,
                              to_state=to, rejected=problem)  # fmt: skip
            raise InvalidTransition(problem)
        return row
