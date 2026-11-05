# Postmortem (drill): tier-2 model outage

- **Type:** simulated incident (drill), blameless
- **Date:** 2026-11-04
- **Scenario:** S9. The `agentops-tier2` model fails every request with `ConnectionError`.

## Summary
Every request routed to tier 2 fell back to tier 3. Quality held (escalation recall 1.0, category accuracy 1.0) and cost rose about 70%. The drill found that **every** affected request first tried the dead tier: 12 failed attempts for 12 requests. With a real 30 s provider timeout, each affected customer would have waited 30 s before the fallback answered.

## Timeline (drill clock)
| Step | What happened |
|---|---|
| T+0 | Tier 2 starts failing (outage factory in `evals/baseline.py`) |
| T+0 | First `model_failed` audit event; fallback to tier 3 succeeds |
| T+0 to end | 12 `model_failed` events, one per tier-2-routed request. No breaker, so no learning between requests |
| After fix | Circuit breaker added; same drill: **3** `model_failed` events, then tier 2 skipped |

## Impact (measured)
| | Before fix | After fix |
|---|---|---|
| Escalation recall | 1.0 | 1.0 |
| Failed attempts on the dead tier | 12 | 3 |
| Total cost (golden set) | $0.148 | $0.148 |
| Worst-case added latency per request at 30 s timeout | 30 s × every request | 30 s × first 3 requests only |

## What went well
- The upward-only fallback kept every high-risk case on a capable model. No quality loss.
- Every failure was audited with model and error type, which made the count trivial.

## What went wrong
- No circuit breaker: the system never "learned" the tier was down.
- The cost increase was invisible to operators until the drill. There's no alert on cost per case yet.

## Action items
| Action | Status |
|---|---|
| Circuit breaker on model calls (`resilience.py`), with test | **Done** (`tests/integration/test_pipeline.py::test_circuit_breaker_stops_paying_for_a_dead_tier`) |
| Runbook for model outage | **Done** (`docs/runbooks/model-outage.md`) |
| Cost-per-case alert | Open (Phase 6 FinOps: budget alert) |
| Shared breaker state across replicas | Open (only matters with more than one replica) |
