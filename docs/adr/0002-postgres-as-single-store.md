# ADR 0002: Postgres as the single store (state, audit, flags, vectors, sessions)

- **Status:** accepted
- **Date:** 2026-11-04
- **Phase:** 0

## Context
The roadmap needs persistent approvals, an immutable audit log, a flag store (Phase 1), vector search (Phase 2), session memory and workflow state (Phase 4). Each could have its own specialised store.

## Options considered
| Option | For | Against |
|---|---|---|
| One Postgres + pgvector | One thing to run, back up and secure; transactions span state and audit; RDS on AWS | Not the fastest vector index at very large scale |
| Postgres + dedicated vector DB + Redis | Best-of-breed per job | Three systems, no cross-store transactions, more IAM and ops for a small team |
| SQLite locally, Postgres in prod | Zero setup | Tests run on a different engine than prod: triggers, locking, JSONB and pgvector behave differently |

## Decision
One Postgres (pgvector image) for everything. Tests run against real Postgres using a throwaway schema per test (`db.scratch_schema`). The Phase 0 SQLite audit option is removed.

## Consequences
- A state change and its audit event commit in one transaction, so they can't disagree.
- The audit log's immutability is enforced by a database trigger, not by convention.
- Local dev needs Docker. CI uses a Postgres service container.
- Revisit if vector search exceeds roughly 10M chunks or needs sub-10ms latency.
