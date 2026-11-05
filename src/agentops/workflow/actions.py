"""Idempotent action execution and crash recovery (scenario S8).

LEARNING NOTES
- The hard problem with side effects isn't running them, it's running them *exactly once* when
  processes crash, requests retry and users double-click. Three steps, each safe to repeat:
    1. claim:   INSERT actions(idempotency_key, status='started'). A second claim with the same key
                finds the existing row instead of starting again.
    2. effect:  call the downstream system WITH the same key. It must ignore a repeated key
                (here: core_banking_ledger has UNIQUE(idempotency_key)).
    3. finish:  mark the action succeeded and move the case to `actioned`.
- If the process dies between 2 and 3, the row stays 'started' ("unknown state"). `recover()` asks
  the downstream system whether the key was applied and finishes the bookkeeping. No guessing and
  no blind retry that could double-charge.
- The key is derived from the approval (`approval-<id>`), so every retry of the same approval
  carries the same key. Random keys per attempt would defeat the whole mechanism.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from ..audit import AuditLog
from ..db import Conn, one
from .cases import CaseStore

EFFECTS = {
    "block_card": "card frozen",
    "refund_review": "refund review opened",
    "hardship_review": "hardship review opened",
    "escalate": "escalated to officer queue",
}


def idempotency_key(approval_id: int) -> str:
    return f"approval-{approval_id}"


class CoreBanking:
    """Fake downstream system. Honours idempotency keys the way a well-behaved payments API does."""

    def __init__(self, conn: Conn):
        self.conn = conn

    def apply(self, key: str, action: str, customer_id: str | None) -> bool:
        cur = self.conn.execute(
            "INSERT INTO core_banking_ledger (idempotency_key, action, customer_id) VALUES (%s,%s,%s) "
            "ON CONFLICT (idempotency_key) DO NOTHING",
            (key, action, customer_id),
        )
        return bool(cur.rowcount)  # False = already applied earlier: not an error, just a repeat

    def was_applied(self, key: str) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM core_banking_ledger WHERE idempotency_key=%s", (key,)).fetchone()
            is not None
        )


class ActionExecutor:
    def __init__(self, conn: Conn, audit: AuditLog, cases: CaseStore):
        self.conn, self.audit, self.cases = conn, audit, cases
        self.bank = CoreBanking(conn)

    def execute(self, approval: dict[str, Any], actor: str, now: datetime) -> str:
        key = idempotency_key(approval["id"])
        case = self.cases.get(approval["case_id"])
        # Step 1: claim. If the row already exists, someone ran (or is running) this exact action.
        claimed = self.conn.execute(
            "INSERT INTO actions (idempotency_key, case_id, approval_id, action, status, started_at) "
            "VALUES (%s,%s,%s,%s,'started',%s) ON CONFLICT (idempotency_key) DO NOTHING",
            (key, case["id"], approval["id"], approval["action"], now),
        ).rowcount
        if not claimed:
            existing = one(self.conn, "SELECT * FROM actions WHERE idempotency_key=%s", (key,))
            if existing["status"] == "succeeded":
                return str(existing["result"])  # a retry: return the original result, do nothing new
            return self.recover_one(key, actor, now)

        # Step 2: the side effect, carrying the key.
        self.bank.apply(key, approval["action"], case["customer_id"])
        if os.getenv("AGENTOPS_CRASH_AFTER_SIDE_EFFECT"):  # S8 drill hook: die like `kill -9` would
            os._exit(137)
        # Step 3: bookkeeping.
        return self._finish(key, approval, case, actor, now)

    def _finish(self, key: str, approval: dict[str, Any], case: dict[str, Any], actor: str, now: datetime) -> str:
        effect = EFFECTS.get(approval["action"], approval["action"])
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE actions SET status='succeeded', result=%s, finished_at=%s WHERE idempotency_key=%s",
                (effect, now, key),
            )
            self.audit.record("action_executed", actor=actor, case_id=str(case["id"]), action=approval["action"],
                              effect=effect, idempotency_key=key, approval_id=approval["id"])  # fmt: skip
        if self.cases.get(case["id"])["state"] == "approved":
            self.cases.transition(case["id"], "actioned", actor, {"system"}, now)
        return effect

    def recover_one(self, key: str, actor: str, now: datetime) -> str:
        """Resolve an action stuck in 'started' by asking the downstream system what happened."""
        row = one(self.conn, "SELECT * FROM actions WHERE idempotency_key=%s", (key,))
        approval = one(self.conn, "SELECT * FROM approval_requests WHERE id=%s", (row["approval_id"],))
        case = self.cases.get(row["case_id"])
        if not self.bank.was_applied(key):
            # The crash happened before the effect: safe to apply now (same key, so still exactly once).
            self.bank.apply(key, approval["action"], case["customer_id"])
        return self._finish(key, approval, case, actor, now)

    def recover(self, actor: str = "system", now: datetime | None = None) -> list[str]:
        """Run at worker start-up: finish every action left 'started' by a crash."""
        from ..decision.service import utcnow

        stuck = self.conn.execute("SELECT idempotency_key FROM actions WHERE status='started'").fetchall()
        return [self.recover_one(r["idempotency_key"], actor, now or utcnow()) for r in stuck]
