"""Timer worker: approval SLAs (scenario S7, naive version).

Usage: uv run python -m agentops.workflow.timers      # polls every 30 s until stopped

LEARNING NOTES
- `tick(now)` is *idempotent*: it only acts on rows whose reminded_at / escalated_at is still NULL
  and stamps them in the same UPDATE. Run it twice, or from two workers, and nothing happens twice.
  That (plus state in Postgres) is why it survives restarts.
- `FOR UPDATE SKIP LOCKED` lets several workers share the queue without blocking each other.
- What this naive version can't do well (and Phase 5 Temporal does): exact timers instead of
  polling, per-request workflow history, retries with backoff as a built-in, and versioned
  workflow code. Break this one first (stop the worker for an hour; change SLAs mid-flight) to feel why.
- A timeout escalates and reassigns. It NEVER approves.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..audit import AuditLog
from ..db import Conn
from .approvals import ApprovalQueue


class TimerWorker:
    def __init__(self, conn: Conn, audit: AuditLog | None = None):
        self.conn = conn
        self.audit = audit or AuditLog(conn)
        self.queue = ApprovalQueue(conn, self.audit)

    def tick(self, now: datetime) -> dict[str, list[int]]:
        done: dict[str, list[int]] = {"reminded": [], "escalated": []}
        with self.conn.transaction():
            # 50% of SLA elapsed: remind the assignee once.
            for r in self._claim(
                "UPDATE approval_requests SET reminded_at=%(now)s WHERE id IN (SELECT id FROM approval_requests "
                "WHERE status='pending' AND reminded_at IS NULL AND created_at + (sla_due - created_at)/2 <= %(now)s "
                "FOR UPDATE SKIP LOCKED) RETURNING *",
                now,
            ):
                self.audit.record(
                    "approval_reminder", case_id=str(r["case_id"]), approval_id=r["id"], assigned_to=r["assigned_to"]
                )
                done["reminded"].append(r["id"])
            # 100% of SLA: escalate and reassign to the least-loaded manager. Status stays 'pending'.
            for r in self._claim(
                "UPDATE approval_requests SET escalated_at=%(now)s WHERE id IN (SELECT id FROM approval_requests "
                "WHERE status='pending' AND escalated_at IS NULL AND sla_due <= %(now)s FOR UPDATE SKIP LOCKED) RETURNING *",
                now,
            ):
                manager = self.queue._least_loaded("manager", exclude=r["requested_by"])
                self.conn.execute("UPDATE approval_requests SET assigned_to=%s WHERE id=%s", (manager, r["id"]))
                self.audit.record("approval_escalated", case_id=str(r["case_id"]), approval_id=r["id"],
                                  from_user=r["assigned_to"], to_user=manager)  # fmt: skip
                done["escalated"].append(r["id"])
        return done

    def _claim(self, sql: str, now: datetime) -> list[dict[str, Any]]:
        return self.conn.execute(sql, {"now": now}).fetchall()


def main(interval_s: float = 30.0) -> None:  # pragma: no cover - long-running loop
    from .. import db
    from ..decision.service import utcnow
    from .actions import ActionExecutor
    from .cases import CaseStore

    conn = db.connect()
    db.migrate(conn)
    audit = AuditLog(conn)
    # On start-up, finish any action a previous crash left half-done (S8), then poll timers (S7).
    recovered = ActionExecutor(conn, audit, CaseStore(conn, audit)).recover()
    print(f"recovered {len(recovered)} in-flight actions")
    worker = TimerWorker(conn, audit)
    while True:
        print(worker.tick(utcnow()))
        time.sleep(interval_s)


if __name__ == "__main__":
    main()
