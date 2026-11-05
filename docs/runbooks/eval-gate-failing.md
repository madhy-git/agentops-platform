# Runbook: eval gate failing in CI

1. Read *which* metric failed in the CI log (`EVAL GATE FAILED: [...]`). Each one points to a different layer:
   | Metric | Look at |
   |---|---|
   | escalation_recall / category_accuracy | prompt, model alias, `agent.py` |
   | injection_block_rate / false_positive_rate | `guardrails.py`, `evals/redteam.yaml` |
   | entitlement_leak_rate | `rag/pg.py` SQL, corpus front matter — **treat as a security incident** (see suspected-data-leak) |
   | citation_faithfulness | prompt, retrieval |
   | suppression_correctness | `policies/rules.yaml`, `decision/` |
2. Reproduce locally: `uv run python evals/run_evals.py --report` and read the failure analysis section.
3. Do **not** lower a threshold to make the build green. A threshold changes only with an ADR and a live baseline showing it was set wrongly.
4. If the change was intended (e.g. a new category), update the golden set *with a reviewer* and say so in the PR.
