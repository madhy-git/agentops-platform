# Changelog

## 0.3.0 (Phase 3)
- Seven-metric release gate (accuracy, escalation recall, injection block rate, false-positive rate, leak rate, citation faithfulness, suppression correctness).
- Red-team set (direct, indirect, benign look-alikes) and per-guard metrics.
- Judge calibration harness, eval set-size experiment, shadow runs, failure capture.
- Prompt and rule feature flags; SLO, release and observability docs. Jaeger tracing verified.

## 0.2.x (Phases 0–2)
- Postgres store, LiteLLM wiring, data contracts, versioned prompts, baseline report.
- Decision service: rules R1–R7, flags, lifecycle, risk model, drift, replay (S6).
- Identity-aware RAG: pgvector, full-text, hybrid; leak tests; retrieval comparison.

## 0.1.0
- Triage agent, router, guardrails, naive approvals, OTel, eval gate.
