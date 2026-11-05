# SLOs and error budget

<!-- LEARNING NOTE: an SLO is a promise you can measure. Set targets from a measured baseline, not
from hope; until the live baseline exists, these are design targets (project.md "Metrics and SLOs"). -->

| SLI (what we measure) | Source | SLO (target) | Error budget | Status |
|---|---|---|---|---|
| Escalation recall on the golden set | `evals/run_evals.py` | 1.0, every release | none: a miss blocks release | Gated in CI |
| Entitlement leak rate | `evals/rag_compare.py`, gate | 0 | none | Gated in CI |
| Marketing suppression correctness | `evals/replay.py` | 100% of replayed steps | none | Gated in CI |
| Injection false-positive rate | red-team benign set | ≤ 5% | 5% of benign messages | Gated in CI |
| Triage p95 latency (end to end) | `triage` span | ≤ 4 s live (to confirm from baseline) | 1% of requests per 30 days over target | Reported |
| Model error rate after fallback | `model_failed` vs `triaged` audit events | ≤ 0.1% unrecovered | 0.1% per 30 days | Reported |
| Approval turnaround vs SLA (Phase 4) | approval timestamps | 95% decided within SLA | 5% | Reported |
| Cost per resolved case | `triaged` events `cost_usd` | within budget per tier (set after live baseline) | monthly budget | Reported |

**Using the error budget:** when a budget is spent, freeze prompt, model and rule changes (feature work continues) until the trend recovers. Safety SLOs (recall, leaks, suppression) have *no* budget: any miss stops the release.
