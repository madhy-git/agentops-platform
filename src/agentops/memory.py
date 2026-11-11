"""Copilot session memory in Postgres.

LEARNING NOTES (project.md "Session memory": summaries drift; PII and restricted facts persist)
- Memory is a *leak path*. An answer built from a restricted document is itself restricted, so each
  stored turn carries the intersection of its sources' allowed roles. Reading memory back applies
  the caller's CURRENT roles: if a manager is downgraded to officer, yesterday's manager-only
  answers drop out of their context.
- Sessions belong to one user. Another user can't read them, even with the session id.
- Turns are stored PII-redacted. Redact before you persist, or you'll be redacting forever.
- "Summary drift": a summary of a summary of a summary slowly invents things. Here the "summary" is
  just the most recent N visible turns, verbatim. Boring, but it can't drift.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .db import Conn
from .guardrails import redact_pii
from .rag.base import STAFF, Passage, held_roles


def derived_roles(passages: Iterable[Passage]) -> list[str]:
    """Who may see text derived from these passages: the intersection of their allowed roles."""
    allowed: set[str] | None = None
    for p in passages:
        roles = set(p.allowed_roles)
        if STAFF in roles:  # public: no restriction contributed
            continue
        allowed = roles if allowed is None else allowed & roles
    if allowed is None:
        return [STAFF]
    return sorted(allowed) or ["manager"]  # nobody overlaps: only managers may see a mixed answer


class SessionMemory:
    def __init__(self, conn: Conn, max_turns: int = 6):
        self.conn, self.max_turns = conn, max_turns

    def add(
        self, session_id: str, user: str, speaker: str, text: str, allowed_roles: list[str], sources: list[str]
    ) -> None:
        self.conn.execute(
            "INSERT INTO chat_turns (session_id, user_id, speaker, content, allowed_roles, sources) VALUES (%s,%s,%s,%s,%s,%s)",
            (session_id, user, speaker, redact_pii(text).text, allowed_roles, sources),
        )

    def history(self, session_id: str, user: str, roles: Iterable[str]) -> list[dict[str, Any]]:
        """Visible turns for this user, filtered by their roles *now*, most recent last."""
        held = sorted(held_roles(roles))
        rows = self.conn.execute(
            "SELECT speaker, content, sources FROM chat_turns WHERE session_id=%s AND user_id=%s "
            "AND allowed_roles && %s ORDER BY id DESC LIMIT %s",
            (session_id, user, held, self.max_turns),
        ).fetchall()
        return list(reversed(rows))
