# ADR 0010: Keep PydanticAI and the YAML rules engine; LangGraph and OPA stay as benchmarked variants

- **Status:** accepted
- **Date:** 2026-11-04
- **Phase:** 7

## Context
project.md's stretch phase: run the same golden set on another agent framework, and optionally swap YAML rules for OPA, then commit a results table with spread and cost.

## Results (offline; `docs/evals/framework-benchmark.md`)
| Framework | Accuracy | Escalation recall | p50 overhead | Tokens / case | Adapter LOC |
|---|---|---|---|---|---|
| PydanticAI (agent loop) | 1.000 ± 0 | 1.000 ± 0 | ~2.4 ms | ~370 | 12 |
| LangGraph (retrieve → [lookup] → classify) | 1.000 ± 0 | 1.000 ± 0 | ~0.4 ms | ~311 | 54 |

OPA/Rego vs Python rules engine: **2,000 / 2,000 contexts agree** (`tests/unit/test_opa_parity.py`), after one fix.

## What building them taught
- **The graph's first version missed a vulnerable customer** (recall 0.923): in an agent loop the model chooses to call `lookup_case`; in a graph every capability must be an explicit node. Explicit is auditable, but you must think of everything up front.
- **Rego orders values across types** (`null < 121` is true), so an unknown transaction age fired R3b in 80/2000 contexts. Two implementations of one policy are only safe with an exhaustive parity test.
- Offline numbers compare *framework overhead*, not model quality. The live run (same harness) is where tokens, cost and accuracy differ for real.

## Decision
- Keep **PydanticAI** for the product: typed structured output and tool calling with the least adapter code, and the agent can decide to look things up.
- Keep the **YAML rules engine**: one Python service doesn't need a shared policy engine. Adopt OPA if several services (or languages) must enforce the same policy, or policy bundles need to ship independently of code.
- Both variants stay in the repo with their parity tests, so the decision can be revisited with live data.
- MLflow (optional in project.md) was not built: the risk model is trained from seeded data in milliseconds and documented by a model card.
