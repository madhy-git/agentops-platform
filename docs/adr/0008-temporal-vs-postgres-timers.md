# ADR 0008: When Temporal is (and isn't) worth it for approvals

- **Status:** accepted: keep the Postgres worker as default; Temporal available behind the same activities
- **Date:** 2026-11-04
- **Phase:** 5

## Context
Approval SLAs need timers (remind at 50%, escalate at 100%) that survive restarts and never auto-approve. Phase 4 built a naive version (Postgres rows + polling worker). Phase 5 rebuilt it on Temporal.

## What we measured / observed
| | Postgres timer worker (`workflow/timers.py`) | Temporal (`workflow/temporal_approval.py`) |
|---|---|---|
| Survives worker crash | Yes: state in rows, every step idempotent | Yes: durable timers on the server; history replay |
| Escalation after downtime | On next poll (≤ poll interval) | Immediately on restart (drill: **1 s** after worker B started) |
| Timer precision | Poll interval (30 s default) | Exact |
| Retries with backoff | Hand-written (none for actions yet) | Built in (`RetryPolicy`); chaos test: 2 failures, then exactly-once success |
| Per-request history | Audit log only | Full event history per workflow, queryable stage |
| Code constraints | None | Workflow code must be deterministic (no DB, clock, random); sandboxed |
| Extra infrastructure | None (Postgres already there) | Temporal cluster (dev: 1 container; prod: Temporal Cloud or a cluster) |
| Testing | Plain SQL + fake clock | Time-skipping test server (fast) but can't simulate downtime; real server drill needed |
| Lines of code | ~90 | ~120 + worker wiring |

## Decision
- Keep the **Postgres worker as the default**: one approval type, coarse SLAs (hours), and idempotent steps already give restart safety with no new infrastructure.
- Use **Temporal** when any of these become true: multi-step processes with compensation (e.g. dispute → chargeback → merchant response → credit), sub-minute timers, many long-lived waits with retries against flaky downstreams, or a need for per-case execution history beyond the audit log.

## Consequences
- Both engines share the same activities (DB writes, idempotent action executor), so switching is wiring, not rewriting.
- The database stays the source of truth for who approved what (separation of duties); Temporal owns time and orchestration.
- Lessons that only surfaced by building it: the test server can't simulate downtime; sticky workflow caches need care when workers restart (`max_cached_workflows=0` in tests); sync code (PydanticAI `run_sync`) can't run inside async drills.
