# Observability

Every request produces one trace: `triage` → `agent.run` (one per model attempt) → `decision`. Audit events carry the same `trace_id`, so you can go from "what was decided" to "how it was decided" and back.

## Span attributes
| Attribute | Meaning |
|---|---|
| `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | OpenTelemetry GenAI semantic conventions: any backend understands them |
| `agentops.cost_usd`, `agentops.prompt.version` | cost from measured tokens; which prompt ran |
| `model.tier`, `model.used`, `hitl`, `blocked`, `pii.redactions` | routing, fallback, human review, guard outcome (counts only, never PII) |
| `decision.reason_codes`, `decision.policy_version` | which rules fired, under which rule version |

## Jaeger (local, verified)
```bash
docker compose -f deploy/docker-compose.yml --profile tracing up -d jaeger
uv sync --all-extras
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run uvicorn agentops.api:create_app --factory
# open http://localhost:16686, service "agentops-platform"
```

## Langfuse (LLM-focused view; not run in this repo)
Langfuse accepts OTLP, so no code change is needed, only exporter settings:
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel   # or your self-hosted URL
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)"
```
Self-hosting Langfuse v3 needs Postgres, ClickHouse, Redis and S3-compatible storage. Use Langfuse's official docker-compose rather than adding four services here. Check their current docs before setting it up.

## Per-step latency and cost
`uv run python evals/run_evals.py --report` writes p50/p95 per span and total cost to `docs/evals/<version>-<mode>.md`.
