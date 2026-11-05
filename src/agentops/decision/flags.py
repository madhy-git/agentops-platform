"""Customer flag store (Postgres).

LEARNING NOTES
- Who may *clear* a flag is a policy decision (rules.yaml `flags:`), checked here on every clear.
  Setting is done by rules; clearing is done by accountable people. That asymmetry is the point:
  it should be easy to protect a customer and deliberate to stop protecting them.
- Every set and clear is audited with actor, reason code and policy version.
- `now` is passed in rather than read from the clock, so the replay harness can move time forward
  ("31 days later...") and test cooling-off windows without sleeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..audit import AuditLog
from ..db import Conn
from .rules import Policy


class FlagPermissionError(PermissionError):
    pass


class FlagStore:
    def __init__(self, conn: Conn, audit: AuditLog, policy: Policy):
        self.conn, self.audit, self.policy = conn, audit, policy

    def active(self, customer_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT flag FROM customer_flags WHERE customer_id = %s AND cleared_at IS NULL ORDER BY flag",
            (customer_id,),
        ).fetchall()
        return [r["flag"] for r in rows]

    def in_cooling_off(self, customer_id: str, now: datetime) -> bool:
        """True if no flag is active but the last one cleared within the cooling-off window."""
        if self.active(customer_id):
            return False
        row = self.conn.execute(
            "SELECT max(cleared_at) AS last FROM customer_flags WHERE customer_id = %s", (customer_id,)
        ).fetchone()
        last = row["last"] if row else None
        return last is not None and now - last < timedelta(days=self.policy.raw["cooling_off_days"])

    def set_flag(self, customer_id: str, flag: str, reason_code: str, actor: str, now: datetime) -> bool:
        """Set a flag. Idempotent: setting an already-active flag is a no-op (returns False)."""
        cur = self.conn.execute(
            "INSERT INTO customer_flags (customer_id, flag, set_at, set_by, reason_code, policy_version) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (customer_id, flag) WHERE cleared_at IS NULL DO NOTHING",
            (customer_id, flag, now, actor, reason_code, self.policy.version),
        )
        if cur.rowcount:
            self.audit.record(
                "flag_set", actor=actor, case_id=customer_id, flag=flag,
                reason_code=reason_code, policy_version=self.policy.version,
            )  # fmt: skip
        return bool(cur.rowcount)

    def clear(self, customer_id: str, flag: str, actor: str, actor_roles: set[str], now: datetime) -> None:
        allowed = set(self.policy.raw["flags"][flag]["cleared_by"])
        if not allowed & actor_roles:
            raise FlagPermissionError(
                f"{actor} ({sorted(actor_roles)}) may not clear {flag}; needs one of {sorted(allowed)}"
            )
        cur = self.conn.execute(
            "UPDATE customer_flags SET cleared_at=%s, cleared_by=%s WHERE customer_id=%s AND flag=%s AND cleared_at IS NULL",
            (now, actor, customer_id, flag),
        )
        if not cur.rowcount:
            raise KeyError(f"{flag} not active for {customer_id}")
        self.audit.record(
            "flag_cleared", actor=actor, case_id=customer_id, flag=flag, policy_version=self.policy.version
        )
