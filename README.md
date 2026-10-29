# AgentOps Platform

A small, tested reference implementation of the operational layer around an AI agent in a regulated setting (banking customer-message triage). The agent is the easy part; this repo is about running it safely.

## What it does

```
message -> PII redaction -> injection check -> cost-aware model router -> PydanticAI agent
        (tools: lookup_case, search_policy w/ citations) -> typed TriageResult
        -> human-in-the-loop gate for high-risk outcomes -> audit log
        every step traced with OpenTelemetry
```

| Capability | Where | Notes |
|---|---|---|
| Typed structured output + tool calling | `agent.py` | PydanticAI, `TriageResult` schema |
| Model router (cost vs capability, fallback chain) | `router.py` | cheapest model whose tier covers the task; budget cap |
| Guardrails | `guardrails.py` | PII redaction, prompt-injection detection, read-only tool policy |
| Human-in-the-loop approvals + audit log | `approvals.py` | fraud, hardship, disputes and complaints need a human |
| Retrieval with citations | `rag.py` | keyword retriever behind a `Retriever` protocol |
| Observability | `telemetry.py`, `service.py` | OpenTelemetry spans with model, tier and cost attributes |
| Evals as a release gate | `evals/` | golden set; CI fails if accuracy, escalation recall or injection blocking drops |
| API | `api.py` | FastAPI: `/triage`, `/approvals`, `/audit` |
| CI/CD, container | `.github/workflows/ci.yml`, `Dockerfile` | tests plus eval gate on every push |

## Run it

```bash
pip install -e ".[dev]"
pytest -q                        # 30 tests
PYTHONPATH=src python evals/run_evals.py   # eval gate (30-case golden set)
AGENTOPS_DB=audit.db uvicorn ...           # optional: persist the audit log to SQLite
pip install -e ".[otlp]" && OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn ...  # send traces to Jaeger
uvicorn agentops.api:app --reload
curl -s localhost:8000/triage -H 'content-type: application/json' \
  -d '{"message":"I think my card was stolen, call 0411 821 692"}'
```

## Honest scope

- **Offline mode (default):** a deterministic stand-in model runs the real tool-calling and structured-output path, so CI needs no API keys. Because it is rule-based, the eval numbers in offline mode prove the *pipeline and gating*, not model quality. Four golden cases are tagged `paraphrase` (no keywords the rules know). The offline model fails all four, so they are reported but only gate in live mode.
- **Live mode:** set `AGENTOPS_MODE=live` and provider credentials to run the routed Bedrock / Azure OpenAI models through PydanticAI. Run the same golden set there for meaningful quality numbers.
- **Not built yet (roadmap):** LlamaIndex + pgvector retriever (swap behind `Retriever`), LiteLLM gateway, durable human-approval workflows on Temporal, persistent approval/audit store (in-memory today), Terraform for EKS/AKS, OpenAI Agents SDK and Google ADK benchmark.
