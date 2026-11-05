"""DecisionService: context -> rules -> flags + decision log + audit, in one transaction.

LEARNING NOTES
- *One transaction*: the decision row, the flags it sets, the lifecycle update and the audit events
  either all commit or none do. Without that, a crash between "flag set" and "decision logged"
  leaves a suppressed customer with no record of why.
- The full input context is stored with each decision. Replaying a decision months later means
  re-running `rules.evaluate(policy_at_that_version, stored_context)` and getting the same answer.
- Unknown customer => no flags, no risk score; rules still run on the message alone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from ..audit import AuditLog
from ..contracts import DecisionResult
from ..db import Conn, one
from . import lifecycle, risk
from .flags import FlagStore
from .rules import Policy, evaluate, load_policy, rank_offers


def utcnow() -> datetime:
    return datetime.now(UTC)


class DecisionService:
    def __init__(self, conn: Conn, audit: AuditLog | None = None, policy: Policy | None = None):
        self.conn = conn
        self.audit = audit or AuditLog(conn)
        self.policy = policy or load_policy()
        self.flags = FlagStore(conn, self.audit, self.policy)
        self.risk = risk.default_model()

    # -- context gathering --------------------------------------------------------------------------
    def customer(self, customer_id: str | None) -> dict[str, Any] | None:
        if not customer_id:
            return None
        return self.conn.execute("SELECT * FROM customers WHERE customer_id = %s", (customer_id,)).fetchone()

    def txn_age_days(self, txn_id: str | None, now: datetime) -> int | None:
        if not txn_id:
            return None
        row = self.conn.execute("SELECT txn_date FROM transactions WHERE txn_id = %s", (txn_id,)).fetchone()
        return (now.date() - row["txn_date"]).days if row else None

    def context(
        self, customer_id: str | None, category: str, recommended_action: str, role: str,
        now: datetime, txn_id: str | None = None, txn_age_days: int | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        cust = self.customer(customer_id)
        flags = self.flags.active(cust["customer_id"]) if cust else []
        if cust and self.flags.in_cooling_off(cust["customer_id"], now):
            flags.append("cooling_off")
        return {
            "customer_id": customer_id if cust else None,
            "category": category,
            "recommended_action": recommended_action,
            "role": role,
            "txn_age_days": txn_age_days if txn_age_days is not None else self.txn_age_days(txn_id, now),
            "risk_score": round(self.risk.score(cust["features"]), 3) if cust else None,
            "risk_model": self.risk.version,
            "flags": flags,
            "lifecycle_stage": cust["lifecycle_stage"] if cust else None,
        }

    # -- the decision --------------------------------------------------------------------------------
    def decide(
        self, customer_id: str | None, category: str, recommended_action: str = "answer",
        role: str = "officer", actor: str = "system", now: datetime | None = None,
        txn_id: str | None = None, txn_age_days: int | None = None,
    ) -> DecisionResult:  # fmt: skip
        now = now or utcnow()
        ctx = self.context(customer_id, category, recommended_action, role, now, txn_id, txn_age_days)
        out = evaluate(self.policy, ctx)
        flags_after = [f for f in ctx["flags"] if f != "cooling_off"] + out.set_flags
        candidates, suppressed = rank_offers(self.policy, out, flags_after)

        with self.conn.transaction():
            cid = ctx["customer_id"]
            if cid:
                for f in out.set_flags:
                    reason = next(r["reason_code"] for r in self.policy.rules if f in r["then"].get("set_flags", []))
                    self.flags.set_flag(cid, f, reason, actor, now)
                self._update_stage(cid, now)
            result = DecisionResult(
                customer_id=cid,
                queue=out.queue,
                priority=out.priority,  # type: ignore[arg-type]
                reason_codes=out.reason_codes,
                actions=out.actions,
                needs_approval=out.requires_approval,
                flags_set=out.set_flags,
                suppressed_actions=suppressed,
                candidate_actions=candidates,
                policy_version=self.policy.version,
            )
            row = one(
                self.conn,
                "INSERT INTO decisions (ts, customer_id, context, result, policy_version) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (now, cid, Jsonb(ctx), Jsonb(result.model_dump()), self.policy.version),
            )
            result.decision_id = row["id"]
            self.audit.record(
                "decision_made", actor=actor, case_id=cid, decision_id=row["id"],
                reason_code=",".join(out.reason_codes) or None, policy_version=self.policy.version,
                rules_fired=out.fired, queue=out.queue,
            )  # fmt: skip
        return result

    def clear_flag(self, customer_id: str, flag: str, actor: str, roles: set[str], now: datetime | None = None) -> None:
        now = now or utcnow()
        with self.conn.transaction():
            self.flags.clear(customer_id, flag, actor, roles, now)
            self._update_stage(customer_id, now)

    def marketing_suppressed(self, customer_id: str, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return bool(self.flags.active(customer_id)) or self.flags.in_cooling_off(customer_id, now)

    def refresh_stage(self, customer_id: str, now: datetime) -> str:
        """Re-evaluate the stage without a new event (e.g. cooling-off just ended)."""
        with self.conn.transaction():
            return self._update_stage(customer_id, now)

    def _update_stage(self, customer_id: str, now: datetime) -> str:
        cust = self.customer(customer_id)
        assert cust is not None
        new = lifecycle.next_stage(
            cust["lifecycle_stage"], set(self.flags.active(customer_id)), self.flags.in_cooling_off(customer_id, now)
        )
        if new != cust["lifecycle_stage"]:
            self.conn.execute("UPDATE customers SET lifecycle_stage=%s WHERE customer_id=%s", (new, customer_id))
        return new


def load_customers(conn: Conn, customers: list[dict[str, Any]], txns: list[dict[str, Any]] | None = None) -> None:
    """Seed customers (and optionally transactions) from data/generated/*.jsonl rows."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO customers (customer_id, name, lifecycle_stage, vulnerable, features) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            [(c["customer_id"], c["name"], c["lifecycle_stage"], c["vulnerable"], Jsonb(c)) for c in customers],
        )
        if txns:
            cur.executemany(
                "INSERT INTO transactions VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                [
                    (t["txn_id"], t["customer_id"], date.fromisoformat(t["date"]), t["merchant"], t["amount"])
                    for t in txns
                ],
            )
