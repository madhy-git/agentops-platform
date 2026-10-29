# AgentOps Platform

A small, tested reference implementation of the operational layer around an AI agent in a regulated setting: triaging customer messages for Wattle Bank, a fictional Australian bank. The agent is the easy part. This repo is about running it safely: what goes in, which model runs, who approves risky actions, and how quality is gated before release.

All data is synthetic. The full design and phased roadmap are in [project.md](project.md).

## Flow

```text
message -> PII redaction -> prompt-injection check -> cost-aware model router
        -> PydanticAI agent (tools: lookup_case, search_policy with citations)
        -> typed TriageResult -> human-in-the-loop gate -> approved action runs -> audit log
        (fallback to the next model if one fails; every step traced with OpenTelemetry)
```

## What's built

| Capability | Where | Notes |
|---|---|---|
| Typed structured output | `agent.py` | `TriageResult` schema with category, severity, action, `needs_human`, bounded `confidence`, citations |
| Tool calling | `agent.py` | `search_policy` (cited) and `lookup_case`; a vulnerable customer forces human review |
| Cost-aware model router | `router.py` | Cheapest model whose capability tier covers the task; budget cap |
| Fallback chain | `service.py` | If the routed model fails, the next tier up is tried; each failure is traced and audited |
| PII redaction | `guardrails.py` | Email, card, phone, TFN, BSB |
| Prompt-injection check | `guardrails.py` | Normalises text first (Unicode look-alikes, zero-width chars, spaced letters), then pattern checks |
| Human-in-the-loop | `service.py`, `approvals.py` | Fraud, hardship, dispute and complaint outcomes need approval; mutating actions run **only** after approval |
| Audit log | `approvals.py` | Every triage, block, model failure, approval and action; in memory or SQLite |
| Retrieval with citations | `rag.py` | Keyword retriever behind a `Retriever` protocol |
| Observability | `telemetry.py` | OpenTelemetry spans with model, tier and cost attributes; optional OTLP export |
| Eval gate | `evals/` | 30-case golden set; CI fails if accuracy, escalation recall or injection blocking drops |
| API | `api.py` | FastAPI |
| CI and container | `.github/workflows/ci.yml`, `Dockerfile` | Tests plus eval gate on every push |

## Run it

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                   # 30 tests
PYTHONPATH=src python evals/run_evals.py    # eval gate
uvicorn agentops.api:app --reload
```

### Demo (60 seconds)

```bash
# 1. A stolen-card message: PII redacted, routed by cost tier, held for approval
curl -s localhost:8000/triage -H 'content-type: application/json' \
  -d '{"message":"My card was stolen at the airport, call me on 0411 821 692"}'

# 2. Approve it: the action runs and the response includes "effect": "card frozen"
curl -s localhost:8000/approvals/1/decision -H 'content-type: application/json' \
  -d '{"approve": true, "reviewer": "fraud-specialist-1"}'

# 3. Replay what happened
curl -s localhost:8000/audit
```

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `POST` | `/triage` | `{"message": "..."}` returns status (`completed`, `pending_approval` or `blocked`), result, model used, failed models, redactions, approval id |
| `GET` | `/approvals` | Pending approvals |
| `POST` | `/approvals/{id}/decision` | `{"approve": bool, "reviewer": "..."}`; runs the action if approved; `409` if already decided |
| `GET` | `/audit` | Full audit trail |

### Configuration

| Variable | Default | Effect |
|---|---|---|
| `AGENTOPS_MODE` | offline | `live` calls the routed provider models instead of the offline stand-in |
| `AGENTOPS_DB` | unset (in memory) | Path to a SQLite file for the audit log |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Send traces over OTLP/HTTP (e.g. `http://localhost:4318` for Jaeger); needs `pip install -e ".[otlp]"` |

To view traces locally:

```bash
docker run -d -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
pip install -e ".[otlp]"
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn agentops.api:app
# open http://localhost:16686
```

## The eval gate

`evals/run_evals.py` runs every case in `evals/golden.jsonl` through the full pipeline and fails the build if any threshold is missed:

| Metric | Threshold | Why |
|---|---|---|
| Category accuracy | 0.9 | Messages reach the right queue |
| Escalation recall | **1.0** | A fraud, hardship, dispute or complaint case that skips human review is the failure that matters most |
| Injection block rate | 1.0 | Known attack phrasings never reach the agent |

Four cases are tagged `paraphrase`. They describe fraud, hardship or disputes without any keyword the offline rules know (e.g. "someone used my card without permission"). The offline model fails all four, which would drop escalation recall to 0.76. They are reported on every run but only count towards the gate in live mode. Adding their words to the rules would make the number pass without making the system better.

## Honest scope

- **Offline mode (default):** a deterministic, rule-based stand-in model runs the real tool-calling and structured-output path, so CI needs no API keys. Offline scores prove the *pipeline and gating*, not model quality.
- **Live mode:** `AGENTOPS_MODE=live` plus provider credentials runs the routed models through PydanticAI. No live baseline has been recorded yet.
- **Approvals are in memory.** The audit log is in memory or SQLite. Its append-only property is a convention, not enforced.
- **Approved actions are fakes** (they return a string). There are no idempotency keys and no separation of duties yet.
- **The injection check is a speed bump.** It catches known phrasings and cheap obfuscation, not paraphrase. Least privilege on tools is the real defence.

## Roadmap

Phases from [project.md](project.md). Each one ends with tests, recorded eval numbers, an ADR and a demo script.

| Phase | Scope |
|---|---|
| 0 | Postgres in docker-compose, persistent approvals and audit, LiteLLM, synthetic data generator, uv/ruff/mypy/pre-commit, data contracts, **live baseline report** |
| 1 | Decision service: YAML rules, customer flags, lifecycle, reason codes, risk model |
| 2 | Identity-aware hybrid RAG on pgvector, with entitlement filtering and leak tests |
| 3 | Evals, red-team set, indirect injection, Langfuse, versioned prompts |
| 4 | Copilot UI, Keycloak roles, MCP Case Tools integration, Postgres approval state machine, idempotency keys |
| 5–7 (stretch) | Temporal, AWS (EKS, Bedrock, CloudFormation), framework benchmark |

## Related

[MCP Case Tools](../mcp-case-tools): an MCP server exposing case tools with least-privilege roles, an enforced workflow and an audit trail. Planned as this agent's tool layer in Phase 4.
