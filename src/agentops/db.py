"""Postgres access and a tiny migration runner.

LEARNING NOTES
- No ORM on purpose: plain SQL keeps every query visible, which matters when you later need
  to prove *where* an entitlement filter is applied (Phase 2) or why a row was locked (Phase 4).
- Migrations are numbered `.sql` files applied in order and recorded in `schema_migrations`.
  Each phase adds one file, so `migrations/` doubles as a history of how the design grew.
- `schema` lets tests run against an isolated, throwaway Postgres schema (see tests/conftest.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from typing import Any, TypeAlias

import psycopg
from psycopg.rows import dict_row

from .config import database_url

# Every connection returns rows as dicts (row_factory=dict_row). The alias tells mypy so, which
# lets the rest of the code index rows by column name without `# type: ignore`.
Conn: TypeAlias = psycopg.Connection[dict[str, Any]]


def one(conn: Conn, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    """Run a query that must return exactly one row (e.g. INSERT ... RETURNING *)."""
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise KeyError("no row returned")
    return row


def connect(url: str | None = None, schema: str | None = None) -> Conn:
    # autocommit=True: each statement commits on its own. Where several writes must succeed or
    # fail together (e.g. state change + audit event) we open an explicit `with conn.transaction()`.
    conn = psycopg.connect(url or database_url(), autocommit=True, row_factory=dict_row)
    if schema:
        # `public` stays on the path so the pgvector extension's types are visible.
        conn.execute(f'SET search_path TO "{schema}", public')
    return conn


@contextmanager
def scratch_schema(prefix: str = "scratch") -> Iterator[Conn]:
    """A freshly migrated, isolated schema that is dropped afterwards.

    Used by tests and by eval runs, so an eval never pollutes (or depends on) real data.
    """
    schema = f"{prefix}_{uuid.uuid4().hex[:10]}"
    admin = connect()
    admin.execute(f'CREATE SCHEMA "{schema}"')
    conn = connect(schema=schema)
    try:
        migrate(conn)
        yield conn
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()


# Any fixed 64-bit number works as an advisory-lock key; every process that runs start-up work must use the same one.
STARTUP_LOCK_KEY = 0x4147_454E_544F_5053  # "AGENTOPS" in hex, so it's recognisable in pg_locks


@contextmanager
def startup_lock(conn: Conn) -> Iterator[None]:
    """Serialise start-up work (migrations, corpus ingestion) across every pod sharing this database.

    LEARNING NOTES
    - Found when moving to Kubernetes: 2 API replicas + 1 worker all start at once, and migrate() and
      ensure_ingested() are check-then-act ("is it applied? no -> apply"). Without a lock, two pods both
      see "not applied" and both try (duplicate-key errors, or a crash loop on first deploy).
    - A Postgres *advisory* lock is a named mutex in the database itself: no extra infrastructure, and it
      is released automatically if the pod dies (the session ends), so a crash can't leave it stuck.
    - The second pod waits, then finds the work already done and skips it. Start-up stays idempotent.
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (STARTUP_LOCK_KEY,))
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (STARTUP_LOCK_KEY,))


def migrate(conn: Conn) -> list[str]:
    """Apply any migration files not yet recorded. Returns the names applied this call."""
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    files = sorted(
        (f for f in resources.files("agentops.migrations").iterdir() if f.name.endswith(".sql")), key=lambda f: f.name
    )
    applied = []
    for f in files:
        if f.name in done:
            continue
        # One transaction per file: a half-applied migration is worse than none.
        with conn.transaction():
            conn.execute(f.read_text().encode())  # bytes: psycopg runs the whole multi-statement file
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
        applied.append(f.name)
    return applied
