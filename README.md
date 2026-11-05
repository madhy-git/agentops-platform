# AgentOps Platform

A tested reference implementation of the operational layer around an AI agent in a regulated setting: triaging customer messages and assisting staff at **Wattle Bank**, a fictional Australian bank. The agent is the easy part. This repo is about running it safely: what goes in, which model runs, what the rules allow, who approves, what the agent can touch, how quality is gated, and how it all runs in production.

It's also a **learning project**: every module opens with *LEARNING NOTES*, and progress is tracked in `../LEARNING_TRACKER.md`. All data is synthetic.

- **New here?** Read [docs/STRUCTURE.md](docs/STRUCTURE.md): a map of the code and one request traced end to end.
- **The plan:** [project.md](project.md) (Phases 0–7). **The reasons:** [docs/adr/](docs/adr/).

## What's built

| Area | Highlights | Phase |
|---|---|---|
| Triage agent | PydanticAI, typed `TriageResult`, tools, cost-aware router, upward fallback, circuit breaker | 0, 4 |
| Guardrails | PII redaction, direct + indirect injection, measured precision/recall/latency | 0, 3 |
| Decision service | YAML rules R1–R7, flags with lifetimes, lifecycle, next-best-action, risk model + drift | 1 |
| Identity-aware RAG | pgvector + full-text + hybrid; entitlement filter inside SQL; leak tests | 2 |
| Evals | 7-metric release gate, red-team set, judge calibration, set-size, shadow runs, failure capture | 3 |
| Observability | OpenTelemetry (GenAI conventions) → Jaeger; audit ↔ trace via `trace_id` | 0, 3 |
| Workflow | Case state machine, domain-routed approvals with SLAs, separation of duties, exactly-once actions | 4 |
| Identity | JWT (Keycloak verified locally; Cognito on AWS), role-aware API | 4, 6 |
| Copilot | Streamed (SSE), cited, relevance-thresholded, refers to specialists instead of leaking | 4 |
| MCP | Agent consumes `../mcp-case-tools` as the human's role | 4 |
| Durable workflows | Temporal approvals; real-server drill with genuine downtime | 5 |
| AWS | Nested CloudFormation, EKS + Pod Identity, RDS, Cognito, Bedrock; validated, **not deployed** | 6 |
| Variants | LangGraph benchmark; OPA/Rego rules with exhaustive parity test | 7 |

**Status:** 114 tests (unit, contract, integration, replay); ruff and mypy clean; eval gate passing offline.

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/) and Python 3.12 (uv installs it).

```bash
docker compose -f deploy/docker-compose.yml up -d postgres   # Postgres + pgvector on localhost:5433
uv sync --all-extras                                         # app + dev tools + optional extras
uv run pytest -q                                             # all tests (first run downloads a ~130 MB embedding model)
uv run python evals/run_evals.py --report                    # the release gate
uv run uvicorn agentops.api:create_app --factory --reload    # API on :8000
uv run streamlit run ui/app.py                               # UI on :8501
```

Host port **5433** is deliberate: it avoids a locally installed Postgres on 5432.

### Try it with curl

```bash
TOKEN=$(uv run python -c "from agentops.auth import dev_token; print(dev_token('officer-1', ['officer']))")
FRAUD=$(uv run python -c "from agentops.auth import dev_token; print(dev_token('fraud-1', ['officer','fraud_specialist']))")
MGR=$(uv run python -c "from agentops.auth import dev_token; print(dev_token('manager-1', ['manager']))")

# 1. Officer triages a stolen-card message: PII redacted, R1 fires, case opened, approval routed to a fraud specialist
curl -s localhost:8000/triage -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"message":"My card was stolen at the airport, call me on 0411 821 692"}'

# 2. The fraud specialist sees it and approves; the card block runs exactly once
curl -s localhost:8000/approvals/mine -H "Authorization: Bearer $FRAUD"
curl -s localhost:8000/approvals/1/decision -H "Authorization: Bearer $FRAUD" -H 'content-type: application/json' -d '{"approve":true}'

# 3. Officer asks the copilot about restricted policy: referred to the hardship queue, never shown the content
curl -s localhost:8000/copilot -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"question":"What hardship arrangement options can we offer?"}'

# 4. Only managers and compliance can read the audit trail
curl -s localhost:8000/audit -H "Authorization: Bearer $MGR"
```

## Optional services

| Profile | Service | Use |
|---|---|---|
| `tracing` | Jaeger (`:16686`) | `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` → see each request's spans |
| `auth` | Keycloak (`:8080`, realm `wattle`) | `AGENTOPS_JWKS_URL=http://localhost:8080/realms/wattle/protocol/openid-connect/certs` ([deploy/keycloak](deploy/keycloak/README.md)) |
| `temporal` | Temporal dev server (`:7233`, UI `:8233`) | `uv run python evals/temporal_restart_drill.py` |
| `live` | LiteLLM gateway (`:4000`) | `AGENTOPS_MODE=live` with provider keys in `.env` (see `.env.example`) |

`docker compose -f deploy/docker-compose.yml --profile <name> up -d`

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `AGENTOPS_MODE` | `offline` | `live` sends model calls through LiteLLM |
| `AGENTOPS_DATABASE_URL` | `postgresql://agentops:agentops@localhost:5433/agentops` | Postgres (on AWS: `AGENTOPS_DB_SECRET_ARN` + `AGENTOPS_DB_HOST` instead) |
| `AGENTOPS_JWKS_URL`, `AGENTOPS_JWT_AUDIENCE`, `AGENTOPS_JWT_ISSUER` | unset / `agentops-api` / unset | RS256 tokens from Keycloak or Cognito; unset = dev HS256 tokens |
| `AGENTOPS_CASE_SOURCE` | `static` | `mcp` = cases from MCP Case Tools (`uv pip install -e ../mcp-case-tools`) |
| `AGENTOPS_PROMPT_TRIAGE_MAJOR` | `1` | Feature flag: switch prompt version without a deploy |
| `AGENTOPS_POLICY_FILE` | `policies/rules.yaml` | Feature flag: trial a new rule set |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Export traces (Jaeger, Langfuse, ADOT) |

## Evals and reports

| Script | Writes | Question it answers |
|---|---|---|
| `evals/run_evals.py --report` | `docs/evals/<version>-<mode>.md` | Is this change safe to ship? (7 metrics) |
| `evals/baseline.py` | `docs/evals/baseline-<mode>.md` | Run-to-run spread, cost per tier, outage behaviour |
| `evals/replay.py` | stdout | Do the rules do the right thing over a customer's lifecycle? |
| `evals/rag_compare.py` | `docs/evals/rag-comparison.md` | Keyword vs vector vs hybrid; any leaks? |
| `evals/guard_metrics.py` | `docs/evals/guards.md` | Guard precision, recall, false positives, latency |
| `evals/judge_calibration.py` | `docs/evals/judge-calibration.md` | Can we trust an automated judge? |
| `evals/set_size.py` | `docs/evals/set-size.md` | How noisy is a small eval set? |
| `evals/drift_report.py` | `docs/evals/drift.md` | Has the population moved away from training? |
| `evals/shadow.py` | stdout | What would change if we switched config? |
| `evals/oversight.py` | stdout | Are approvers reviewing or rubber-stamping? |
| `benchmarks/run.py` | `docs/evals/framework-benchmark.md` | PydanticAI vs LangGraph on the same task |

## Honest scope

- **Offline by default.** A deterministic rule-based stand-in drives the real agent loop, so CI needs no keys. Offline scores prove pipeline and gating, **not model quality**. No live baseline has been recorded yet (it needs provider credentials).
- **AWS is written and validated, not deployed.** cfn-lint, Checkov, kubeconform, Trivy and shellcheck all pass; deploying needs your account and costs money ([docs/aws.md](docs/aws.md)).
- **Not wired:** the API still uses the Postgres timer worker, not Temporal; actions run against an in-repo fake ledger, not MCP's `execute_action`; Langfuse and Ragas aren't set up.
- **Synthetic everything.** Wattle Bank, its policies, customers and thresholds are invented. Verify real regulatory obligations before reusing any rule.
- Accepted risks are listed in [docs/threat-model.md](docs/threat-model.md).

## Related

[MCP Case Tools](../mcp-case-tools): an MCP server with least-privilege roles, two workflow profiles (regulator, Wattle Bank), idempotency keys and an audit trail.
