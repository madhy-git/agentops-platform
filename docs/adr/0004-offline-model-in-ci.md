# ADR 0004: Deterministic offline model in CI; live runs for quality numbers

- **Status:** accepted
- **Date:** 2026-11-04
- **Phase:** 0

## Context
CI must run on every push without provider keys, cost or flakiness. But a gate that never calls a real model can't measure model quality.

## Decision
CI uses a rule-based `FunctionModel` that drives the real agent loop (tool calls, structured output, validation). Quality baselines come from scheduled or manual live runs (`AGENTOPS_MODE=live`), recorded in `docs/evals/`. Golden cases tagged `paraphrase` gate only in live mode.

## Consequences
- CI proves wiring, gating, guardrails and contracts; it does not prove the model is good.
- The paraphrase gap stays visible in every offline run, and a test fails if it silently closes (someone taught the rules the test's words).
- Thresholds must eventually be set from the *live* baseline's spread, not from offline numbers.
