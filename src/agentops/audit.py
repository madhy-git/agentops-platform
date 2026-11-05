"""Append-only audit log in Postgres.

LEARNING NOTES
- Every regulated step writes an AuditEvent. Together they let you *replay* a case: who did
  what, when, under which policy and prompt version, and which trace shows the details.
- trace_id is read from the current OpenTelemetry span, so an auditor can jump from an audit row
  to the exact trace (model, latency, tool calls) and back.
- Immutability is enforced by a database trigger (migrations/001_core.sql), not by this class.
  Controls belong at the lowest layer that can enforce them.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from psycopg.types.json import Jsonb

from .contracts import AuditEvent, AuditEventType
from .db import Conn


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


class AuditLog:
    def __init__(self, conn: Conn):
        self.conn = conn

    def record(self, event: AuditEventType, actor: str = "system", **fields: Any) -> AuditEvent:
        # Known columns go to columns (indexable, queryable); everything else lands in `data`.
        cols = {k: fields.pop(k) for k in ("case_id", "reason_code", "policy_version", "prompt_version") if k in fields}
        ev = AuditEvent(event=event, actor=actor, trace_id=current_trace_id(), data=fields, **cols)  # validates
        self.conn.execute(
            "INSERT INTO audit_events (event, schema_version, trace_id, case_id, actor, reason_code, "
            "policy_version, prompt_version, data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                ev.event,
                ev.schema_version,
                ev.trace_id,
                ev.case_id,
                ev.actor,
                ev.reason_code,
                ev.policy_version,
                ev.prompt_version,
                Jsonb(ev.data),
            ),
        )
        return ev

    def events(self, case_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        """Read back events in order. With case_id, this is the replay of one case."""
        if case_id:
            rows = self.conn.execute(
                "SELECT * FROM audit_events WHERE case_id = %s ORDER BY id LIMIT %s", (case_id, limit)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM audit_events ORDER BY id LIMIT %s", (limit,)).fetchall()
        return [dict(r) for r in rows]
