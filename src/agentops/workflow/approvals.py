"""Approval requests: who must approve what, by when, and who may not.

LEARNING NOTES
- *Domain routing*: a card block goes to a fraud specialist, a hardship review to a hardship
  specialist. Managers can approve any domain. (project.md "Personas and roles")
- *Separation of duties*: the requester can never approve their own request. Checked here AND by a
  CHECK constraint in the database (defence in depth).
- *Assignment by workload*: the approver in the domain with the fewest open requests gets it.
- *SLA*: each request has a due time. Timers (timers.py) remind at 50% and escalate at 100%.
  A timeout NEVER approves. It only gets a human's attention.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..audit import AuditLog
from ..db import Conn, one

# Which specialist role approves which action.
DOMAIN_OF_ACTION = {
    "block_card": "fraud",
    "hardship_review": "hardship",
    "refund_review": "disputes",
    "compensation": "complaints",
    "escalate": "general",
}
APPROVER_ROLE = {"fraud": "fraud_specialist", "hardship": "hardship_specialist", "disputes": "disputes_officer",
                 "complaints": "manager", "general": "manager"}  # fmt: skip
SLA = {"fraud": timedelta(hours=1), "hardship": timedelta(hours=24), "disputes": timedelta(hours=48),
       "complaints": timedelta(hours=24), "general": timedelta(hours=8)}  # fmt: skip

# Staff directory for assignment (fictional). In production: the identity provider's groups.
STAFF: dict[str, set[str]] = {
    "officer-1": {"officer"},
    "officer-2": {"officer"},
    "fraud-1": {"officer", "fraud_specialist"},
    "fraud-2": {"officer", "fraud_specialist"},
    "hardship-1": {"officer", "hardship_specialist"},
    "disputes-1": {"officer", "disputes_officer"},
    "manager-1": {"manager"},
    "manager-2": {"manager"},
    "compliance-1": {"viewer", "compliance"},
}


class ApprovalError(PermissionError):
    pass


def can_approve(roles: set[str], domain: str) -> bool:
    return "manager" in roles or APPROVER_ROLE[domain] in roles


class ApprovalQueue:
    def __init__(self, conn: Conn, audit: AuditLog):
        self.conn, self.audit = conn, audit

    def _least_loaded(self, role: str, exclude: str | None = None) -> str | None:
        """Pick the approver with that role who has the fewest pending requests (ties: by name)."""
        people = sorted(u for u, r in STAFF.items() if role in r and u != exclude)
        if not people:
            return None
        rows = self.conn.execute(
            "SELECT assigned_to, count(*) AS n FROM approval_requests WHERE status='pending' GROUP BY assigned_to"
        ).fetchall()
        load = {r["assigned_to"]: r["n"] for r in rows}
        return min(people, key=lambda u: (load.get(u, 0), u))

    def request(
        self, case_id: int, decision_id: int, action: str, requested_by: str, now: datetime, seeded_bad: bool = False
    ) -> dict[str, Any]:
        domain = DOMAIN_OF_ACTION.get(action, "general")
        assignee = self._least_loaded(APPROVER_ROLE[domain], exclude=requested_by)
        row = one(
            self.conn,
            "INSERT INTO approval_requests (case_id, decision_id, action, domain, requested_by, assigned_to, created_at, "
            "sla_due, seeded_bad) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (case_id, decision_id, action, domain, requested_by, assignee, now, now + SLA[domain], seeded_bad),
        )
        self.audit.record("approval_requested", actor=requested_by, case_id=str(case_id), approval_id=row["id"],
                          action=action, domain=domain, assigned_to=assignee, sla_due=row["sla_due"].isoformat())  # fmt: skip
        return row

    def get(self, approval_id: int) -> dict[str, Any]:
        return one(self.conn, "SELECT * FROM approval_requests WHERE id = %s", (approval_id,))

    def pending_for(self, user: str, roles: set[str]) -> list[dict[str, Any]]:
        """What this person should look at: assigned to them, or (managers) everything escalated."""
        rows = self.conn.execute(
            "SELECT * FROM approval_requests WHERE status='pending' AND (assigned_to=%s OR (%s AND escalated_at IS NOT NULL)) "
            "ORDER BY sla_due",
            (user, "manager" in roles),
        ).fetchall()
        return list(rows)

    def decide(
        self, approval_id: int, approve: bool, user: str, roles: set[str], now: datetime, reason: str = ""
    ) -> dict[str, Any]:
        denied = None
        with self.conn.transaction():
            req = one(self.conn, "SELECT * FROM approval_requests WHERE id = %s FOR UPDATE", (approval_id,))
            if req["status"] != "pending":
                raise ValueError("already decided")
            if user == req["requested_by"]:
                denied = "separation of duties: you can't approve your own request"
            elif not can_approve(roles, req["domain"]):
                denied = f"{req['domain']} approvals need {APPROVER_ROLE[req['domain']]} or manager"
            else:
                status = "approved" if approve else "rejected"
                row = one(
                    self.conn,
                    "UPDATE approval_requests SET status=%s, decided_by=%s, decided_at=%s, reason=%s WHERE id=%s RETURNING *",
                    (status, user, now, reason, approval_id),
                )
                took = (now - req["created_at"]).total_seconds()
                self.audit.record("approval_decided", actor=user, case_id=str(req["case_id"]), approval_id=approval_id,
                                  status=status, reason=reason, seconds_to_decide=took)  # fmt: skip
        if denied:
            # Outside the transaction so the record of the attempt isn't rolled back (see cases.py).
            self.audit.record("action_denied", actor=user, case_id=str(req["case_id"]), approval_id=approval_id,
                              reason_code="APPROVAL_NOT_PERMITTED", detail=denied)  # fmt: skip
            raise ApprovalError(denied)
        return row
