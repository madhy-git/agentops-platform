"""Shared fixtures.

LEARNING NOTE: each database test gets its *own Postgres schema*, created and migrated fresh and
dropped afterwards (db.scratch_schema). Tests can't leak state into each other, and they run on
the same engine as production. SQLite-in-tests / Postgres-in-prod hides real bugs: locking,
JSONB, triggers. Start Postgres first: `docker compose -f deploy/docker-compose.yml up -d postgres`.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentops import db, telemetry

telemetry.init(memory=True)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with db.scratch_schema("test") as c:
        yield c


@pytest.fixture
def spans() -> InMemorySpanExporter:
    exporter = telemetry.init(memory=True)
    assert exporter is not None
    exporter.clear()
    return exporter


@pytest.fixture(autouse=True)
def _reset_circuit_breaker() -> None:
    # The breaker is process-wide state: an outage simulated in one test must not leak into the next.
    from agentops.resilience import BREAKER

    BREAKER._states.clear()
