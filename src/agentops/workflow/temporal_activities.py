"""Temporal *activities* for the durable approval workflow (Phase 5).

LEARNING NOTES
- Activities are where side effects live: database writes, API calls, the core-banking action.
  Temporal retries them on failure (with backoff, per the workflow's RetryPolicy), which is only safe
  because each one is idempotent: reminders and escalations stamp a NULL column once; execution uses
  the same idempotency key as the naive version (workflow/actions.py).
- They reuse the Phase 4 building blocks. The difference between "naive" and "durable" is not the
  business logic, it's *who keeps the clock and the state of the process*.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from temporalio import activity

from .. import db
from ..audit import AuditLog
from ..decision.service import utcnow
from .actions import ActionExecutor
from .approvals import ApprovalQueue
from .cases import CaseStore

# Chaos hook for tests: fail the first N execute attempts to prove retries + idempotency work together.
_FAIL_FIRST = {"n": 0}


@dataclass
class ApprovalActivities:
    schema: str | None = None  # tests run against a scratch schema

    def _conn(self) -> db.Conn:
        return db.connect(schema=self.schema)

    @activity.defn
    def remind(self, approval_id: int) -> bool:
        with self._conn() as c:
            row = c.execute(
                "UPDATE approval_requests SET reminded_at=%s WHERE id=%s AND status='pending' AND reminded_at IS NULL RETURNING *",
                (utcnow(), approval_id),
            ).fetchone()
            if row:
                AuditLog(c).record("approval_reminder", case_id=str(row["case_id"]), approval_id=approval_id,
                                   assigned_to=row["assigned_to"], engine="temporal")  # fmt: skip
            return row is not None

    @activity.defn
    def escalate(self, approval_id: int) -> str | None:
        with self._conn() as c:
            audit = AuditLog(c)
            req = c.execute("SELECT * FROM approval_requests WHERE id=%s", (approval_id,)).fetchone()
            if not req or req["status"] != "pending" or req["escalated_at"] is not None:
                return None
            manager = ApprovalQueue(c, audit)._least_loaded("manager", exclude=req["requested_by"])
            c.execute(
                "UPDATE approval_requests SET escalated_at=%s, assigned_to=%s WHERE id=%s",
                (utcnow(), manager, approval_id),
            )
            audit.record("approval_escalated", case_id=str(req["case_id"]), approval_id=approval_id,
                         from_user=req["assigned_to"], to_user=manager, engine="temporal")  # fmt: skip
            return manager

    @activity.defn
    def status(self, approval_id: int) -> str:
        with self._conn() as c:
            row = c.execute("SELECT status FROM approval_requests WHERE id=%s", (approval_id,)).fetchone()
            return str(row["status"]) if row else "missing"

    @activity.defn
    def execute(self, approval_id: int) -> str:
        if _FAIL_FIRST["n"] > 0 or os.getenv("AGENTOPS_TEMPORAL_FAIL_ONCE") == "1":
            _FAIL_FIRST["n"] -= 1
            raise ConnectionError("core banking timeout (chaos)")
        with self._conn() as c:
            audit = AuditLog(c)
            req = c.execute("SELECT * FROM approval_requests WHERE id=%s", (approval_id,)).fetchone()
            assert req and req["status"] == "approved", "execute only runs for approved requests"
            return ActionExecutor(c, audit, CaseStore(c, audit)).execute(req, str(req["decided_by"]), utcnow())
