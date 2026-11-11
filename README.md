# AgentOps Platform

A tested reference implementation of the **operational layer around an AI agent** in a regulated setting: triaging customer messages and assisting staff at **Wattle Bank**, a fictional Australian bank.

The agent is the easy part. This repo is about running it safely:

- **What goes in:** PII redaction, plus direct and indirect prompt-injection guards.
- **Which model runs:** a cost-aware router, fallback to a higher tier, a circuit breaker.
- **What the rules allow:** deterministic rules decide; the model only recommends.
- **Who approves:** domain-routed approvals with SLAs and separation of duties.
- **What the agent can touch:** role-filtered retrieval, and MCP tools that run as the human's role.
- **How quality is gated:** a 7-metric release gate, a red-team set, judge calibration.
- **How it runs in production:** tracing, audit, Temporal, CloudFormation and EKS.

It is also a **learning project**. Every module opens with *LEARNING NOTES* (what it does, why it's built that way, which failure it prevents), and progress is tracked outside the repo in [`../LEARNING_TRACKER.md`](../LEARNING_TRACKER.md). All data is synthetic.

| If you want… | Read |
|---|---|
| A map of the code, and one request traced end to end | [docs/STRUCTURE.md](docs/STRUCTURE.md) |
| The plan (business, rules, scenarios, Phases 0–7) | [project.md](project.md) |
| Why each choice was made | [docs/adr/](docs/adr/) |
| What changed, release by release | [CHANGELOG.md](CHANGELOG.md) |

---

## The workspace

```text
agentops-platform/            (workspace folder, not a repo)
├── agentops-platform/        ← this repo: guardrails, routing, decisions, RAG, evals, workflow, deploy
├── mcp-case-tools/           ← sibling repo: MCP server with least-privilege case tools
└── LEARNING_TRACKER.md       ← exercises and progress; only you mark items [x]
```

## Architecture

### System components

Solid arrows are the default path. Dotted arrows are optional; each is switched on by a compose profile or an env var.

```mermaid
flowchart LR
    subgraph Clients
        UI["Streamlit UI<br/>ui/app.py"]
        CLI["curl / API clients"]
    end

    IDP["Identity provider<br/>dev HS256 · Keycloak · Cognito"]

    subgraph App["agentops-platform (FastAPI)"]
        API["api.py + auth.py<br/>JWT → Principal(user, roles)"]
        subgraph Pipeline["service.py: triage pipeline"]
            GR["guardrails.py<br/>PII redaction · injection"]
            RT["router.py + resilience.py<br/>tier choice · fallback · breaker"]
            AG["agent.py (PydanticAI)<br/>typed TriageResult + tools"]
            DS["decision/<br/>rules R1–R7 · flags · risk"]
            WF["workflow/<br/>cases · approvals · actions"]
        end
        CP["copilot.py + memory.py<br/>cited, streamed answers"]
        RAG["rag/<br/>keyword · vector · hybrid<br/>role filter in SQL"]
    end

    WK["Timer worker<br/>workflow/timers.py"]
    TMP["Temporal<br/>temporal_approval.py"]
    LLM["LiteLLM gateway<br/>tier1 · tier2 · tier3"]
    OFF["Offline model<br/>(default, CI)"]
    PROV["Model providers<br/>Anthropic (Bedrock on AWS)"]
    MCP["MCP Case Tools<br/>../mcp-case-tools"]
    PG[("Postgres 17 + pgvector<br/>audit · cases · approvals · flags<br/>policy_chunks · chat_turns · ledger")]
    OTEL["OpenTelemetry → Jaeger<br/>(ADOT/X-Ray on AWS)"]

    UI --> API
    CLI --> API
    IDP -. "JWKS / tokens" .-> API
    API --> GR --> RT --> AG --> DS --> WF
    API --> CP
    AG -- "search_policy" --> RAG
    CP --> RAG
    AG -- "lookup_case" --> MCP
    RT --> OFF
    RT -. "AGENTOPS_MODE=live" .-> LLM --> PROV
    RAG --> PG
    DS --> PG
    WF --> PG
    CP --> PG
    WK -- "remind · escalate<br/>never approve" --> PG
    WF -. "durable variant" .-> TMP
    App -. "spans + trace_id" .-> OTEL
```

**How to read it:**

- **The model never authorises anything.** The agent returns a `TriageResult`, and `decision/` turns it into actions, flags and a decision on whether approval is needed.
- **Permissions are checked in several independent places:**
  - the API (`auth.require`)
  - the approval workflow: separation of duties, checked in code and by a database CHECK constraint
  - the retrieval SQL `WHERE` clause
  - MCP Case Tools, separately
- **One Postgres holds all state** (ADR 0002). Audit rows can only be added; a trigger blocks updates and deletes.

### On AWS (Phase 6, written and validated, not deployed)

```mermaid
flowchart LR
    GH["GitHub Actions"] -- "OIDC, short-lived creds" --> ROLE["Deploy role"]
    GH --> ECR["ECR<br/>immutable tags · scan on push"]
    USER["Staff"] -- "sign in" --> COG["Cognito<br/>groups = app roles"]
    USER -- "HTTPS (TLS 1.3)" --> ALB["ALB"]

    subgraph VPC["VPC: private subnets"]
        subgraph EKS["EKS (restricted pods, default-deny NetworkPolicy)"]
            APIP["agentops-api"]
            WKP["agentops-worker<br/>(timer loop)"]
            LLMP["litellm"]
            ADOT["adot-collector"]
        end
        RDS[("RDS Postgres 17 + pgvector<br/>KMS · managed password")]
        VPCE["VPC endpoints<br/>Bedrock · ECR · Secrets Manager · S3"]
    end

    ALB --> APIP
    APIP --> LLMP
    APIP --> RDS
    WKP --> RDS
    LLMP -- "Pod Identity" --> VPCE --> BR["Bedrock<br/>exact model ARNs"]
    APIP -- "Pod Identity" --> SM["Secrets Manager"]
    WKP -- "Pod Identity" --> SM
    ADOT -- "Pod Identity" --> XR["X-Ray / CloudWatch"]
    COG -. "JWKS" .-> APIP
```

The stacks are nested CloudFormation, in `deploy/cloudformation/`: `root.yaml`, which nests `network`, `data`, `identity` and `app`. The manifests are in `deploy/k8s/`. Costs and teardown are in [docs/aws.md](docs/aws.md).

## How a request flows

```text
POST /triage (JWT) ─► redact PII ─► injection check ─► route to the cheapest model tier that can do the job
                                                     │   (falls back to a higher tier on provider errors; circuit breaker)
                                                     ▼
                     PydanticAI agent ─► typed TriageResult   tools: search_policy (role-filtered RAG),
                                                     │               lookup_case (static or MCP Case Tools)
                                                     ▼
                     decision service: rules R1–R7 ─► reason codes, flags, marketing suppression, next-best-action, risk
                                                     ▼
                     case opened ─► regulated? ─► approval routed by domain, with an SLA (remind, escalate, never auto-approve)
                                                     ▼
                     specialist approves ─► action executes exactly once (idempotency key, crash recovery)

Every step writes an append-only audit event and an OpenTelemetry span, linked by trace_id.
```

The copilot (`POST /copilot/stream`) is a second path: redact, check for injection, retrieve with the caller's roles, apply a relevance threshold, then stream a cited answer. A question about content the caller can't see is referred to the right specialist queue instead of being answered.

---

## What's built

All eight phases of [project.md](project.md) have a minimal working version.

| Phase | Area | Built | Checked by running it |
|---|---|---|---|
| 0 | Foundation | Postgres, LiteLLM tier aliases, data contracts, versioned prompts, synthetic data generator, offline baseline | Audit table rejects UPDATE/DELETE (trigger); baseline report committed |
| 1 | Decisioning | YAML rules R1–R7, flags with lifetimes, lifecycle stages, next-best-action, scikit-learn risk model with model card, PSI drift | Lifecycle replay: 17/17 journey steps correct |
| 2 | Identity-aware RAG | pgvector, full-text and hybrid (RRF) search; entitlement filter inside the SQL; citations | 0 leaks across 9 configurations; comparison table committed |
| 3 | Evals and observability | 7-metric release gate, red-team set (including indirect injection), judge calibration, set-size experiment, shadow runs, failure capture; OpenTelemetry to Jaeger | A harmful prompt change fails the gate; real traces in Jaeger |
| 4 | Copilot, auth, workflow | FastAPI with SSE, Streamlit UI, JWT roles (Keycloak and Cognito), session memory, case state machine, approvals with SLAs, exactly-once actions, MCP integration, runbooks, an incident drill | Real Keycloak tokens; a process killed mid-action recovers and applies the action exactly once |
| 5 | Durable workflows | Temporal approvals and case clocks | Real server: worker killed, SLA expired while it was down, escalated 1 s after restart |
| 6 | AWS | Nested CloudFormation (network, data, identity, app), EKS with Pod Identity, RDS, Cognito, Bedrock, hardened Kubernetes manifests, deploy/destroy/smoke scripts, OIDC deploy workflow | cfn-lint, Checkov, kubeconform, Trivy, shellcheck all pass. **Not deployed** |
| 7 | Variants | Same task in PydanticAI and LangGraph; rules in OPA/Rego | Rego and Python agree on all 2,000 test inputs |

**Status:** 159 tests (unit, contract, integration, replay, Temporal); ruff and mypy clean; eval gate passing offline. MCP Case Tools: 8 tests.

### Scenarios from project.md

| Scenario | What it proves | Where |
|---|---|---|
| S1 Stolen card | PII redacted, R1 fires, case opened, approval routed to a fraud specialist | `tests/integration/test_pipeline.py`, curl demo below |
| S2 Hardship | R2, specialist routing, marketing suppressed | `tests/integration/test_decision.py` |
| S3 Officer asks restricted policy | Restricted chunks never returned; referred to the specialist queue | `test_rag_pg.py`, `test_copilot.py` |
| S4 Prompt injection | Direct and planted (indirect) injection blocked and logged, no tool call | `tests/unit/test_guardrails.py`, `evals/redteam.yaml` |
| S5 Release gate | A prompt change that drops escalation recall fails CI | `test_eval_gate.py::test_s5_harmful_change_fails_the_gate` |
| S6 Lifecycle replay | Flags set and cleared, marketing suppressed and restored | `tests/replay/`, `evals/replay.py` |
| S7 Approval timeout | Reminder, escalation, never auto-approved, survives restart | `test_workflow.py`, `test_temporal.py`, `evals/temporal_restart_drill.py` |
| S8 Mid-action crash | No duplicate side effect after a real process kill | `test_workflow.py::test_s8_kill_mid_action_then_recover_exactly_once` |
| S9 Model outage | Fallback engages; cost impact recorded | `tests/unit/test_resilience.py`, `evals/baseline.py` |

---

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

Host port **5433** is deliberate: it avoids a locally installed Postgres on 5432. Everything runs **offline** by default; no API keys needed.

To use MCP Case Tools as the case source: `uv pip install -e ../mcp-case-tools`, then set `AGENTOPS_CASE_SOURCE=mcp`.

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

### API endpoints

"Staff" means officer, manager, fraud/hardship specialist or disputes officer. Endpoints marked *service-checked* accept any valid token and let the workflow decide (domain routing, separation of duties), so a refusal is an audited 403, not a missing route.

| Method and path | Who | What |
|---|---|---|
| `GET /health`, `GET /ready`, `GET /me` | anyone / anyone / any token | Process up; can serve (DB reachable, used by k8s probes); who the token says you are |
| `POST /triage` | staff | Run the full pipeline on a customer message |
| `GET /approvals/mine` | service-checked | Approvals routed to the caller's domain |
| `POST /approvals/{id}/decision` | service-checked | Approve or reject (domain and separation of duties enforced) |
| `GET /cases/{id}` | staff, compliance | One case and its state |
| `POST /cases/{id}/transition` | service-checked | Move a case through the state machine |
| `POST /customers/{id}/flags/{flag}/clear` | service-checked | Clear a protective flag (only the matching specialist) |
| `POST /copilot`, `POST /copilot/stream` | staff | Cited answer; the stream variant uses SSE |
| `GET /audit` | manager, compliance | Append-only audit trail, filterable by `case_id` |

---

## Optional services

`docker compose -f deploy/docker-compose.yml --profile <name> up -d`

| Profile | Service | Use |
|---|---|---|
| `tracing` | Jaeger (`:16686`) | `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` → see each request's spans |
| `auth` | Keycloak (`:8080`, realm `wattle`) | `AGENTOPS_JWKS_URL=http://localhost:8080/realms/wattle/protocol/openid-connect/certs` ([deploy/keycloak](deploy/keycloak/README.md)) |
| `temporal` | Temporal dev server (`:7233`, UI `:8233`) | `uv run python evals/temporal_restart_drill.py` |
| `live` | LiteLLM gateway (`:4000`) | `AGENTOPS_MODE=live` with provider keys in `.env` (see `.env.example`) |

## Configuration

All settings are read from the environment in one place: `src/agentops/config.py`.

| Variable | Default | Effect |
|---|---|---|
| `AGENTOPS_MODE` | `offline` | `live` sends model calls through LiteLLM |
| `AGENTOPS_DATABASE_URL` | `postgresql://agentops:agentops@localhost:5433/agentops` | Postgres (on AWS: `AGENTOPS_DB_SECRET_ARN` + `AGENTOPS_DB_HOST` instead) |
| `AGENTOPS_JWKS_URL`, `AGENTOPS_JWT_AUDIENCE`, `AGENTOPS_JWT_ISSUER` | unset / `agentops-api` / unset | RS256 tokens from Keycloak or Cognito; unset = dev HS256 tokens |
| `AGENTOPS_CASE_SOURCE` | `static` | `mcp` = cases from MCP Case Tools |
| `AGENTOPS_PROMPT_TRIAGE_MAJOR` | `1` | Feature flag: switch prompt version without a deploy |
| `AGENTOPS_POLICY_FILE` | `policies/rules.yaml` | Feature flag: trial a new rule set |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Export traces (Jaeger, Langfuse, ADOT) |

---

## Quality checks

```bash
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run mypy                                           # types
uv run pytest -q                                      # tests (needs Postgres; Temporal tests use a time-skipping server)
uv run python evals/run_evals.py                      # release gate: exits non-zero if quality drops
pre-commit run --all-files                            # the same hooks that run on commit
```

| Workflow | Runs |
|---|---|
| [ci.yml](.github/workflows/ci.yml) | Lint, types, tests, eval gate (on every push and PR) |
| [security.yml](.github/workflows/security.yml) | cfn-lint, Checkov, kubeconform, Docker build, Trivy, CycloneDX SBOM |
| [deploy.yml](.github/workflows/deploy.yml) | Manual: deploy or destroy on AWS via OIDC, then smoke test |

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
| `evals/capture.py` | golden-set candidates | Turn production failures into new eval cases |
| `evals/oversight.py` | stdout | Are approvers reviewing or rubber-stamping? |
| `evals/temporal_restart_drill.py` | stdout | Does an SLA survive real worker downtime? |
| `benchmarks/run.py` | `docs/evals/framework-benchmark.md` | PydanticAI vs LangGraph on the same task |

## Web app: customer portal + staff workspace

A React + TypeScript + Tailwind app in [web/](web/src/App.tsx). There's no sign-in screen: open it and choose a side.

| Side | Who | What they can do |
|---|---|---|
| **Customer portal** (`/portal`) | Wattle Bank customers (Jordan, Priya, Noah) | Raise a request (lost card, dispute, hardship, complaint), track it step by step, ask the help assistant (customer articles only) |
| **Staff workspace** (`/staff`) | Officer, fraud/hardship specialists, disputes, manager, compliance | Live dashboard, case queue and detail (rules decision, flags), **My approvals** with SLA countdowns, policy copilot, audit trail |

"Viewing as" in the header switches person. Behind the scenes each person gets a signed token, and the API enforces their role, so switching from the officer to the fraud specialist changes what you can approve. Customers only ever see their own requests, in plain language: no reason codes, risk scores or internal queues (`tests/integration/test_portal.py`).

**Try the full loop:**
1. In the customer portal, report a stolen card.
2. In the staff workspace, switch to the fraud specialist and approve it.
3. Back in the portal, the request shows "Action taken: your card has been blocked".

```bash
# in the cluster: http://localhost:8088 (deploy/k8s-local/up.sh builds and deploys it)
# or locally, against a local API with demo access on:
AGENTOPS_DEV_LOGIN=1 uv run uvicorn agentops.api:create_app --factory   # API on :8000
cd web && npm ci && npm run dev                                         # app on :5173, /api proxied to :8000
```

`npm run typecheck`, `npm test` and `npm run build` check the app. The Streamlit UI (`ui/app.py`) still works as a minimal client.

### Copilot on Gemini

In the local cluster the copilot and help assistant answer with **Google Gemini** (`gemini-3.5-flash`, minimal thinking: about 1–2 s to first word), through the LiteLLM gateway. Triage stays on the offline model, so the rules pipeline stays deterministic.
- **Turning it on:** put `GEMINI_API_KEY=...` in the git-ignored `.env` and run `deploy/k8s-local/up.sh`. It copies the key into a Kubernetes Secret that only LiteLLM reads.
- **If Gemini is down or rate-limited:** the answer falls back to the offline one and says so. The chat shows which model answered.
- **Free tier:** prompts and answers may be used by Google, so use synthetic data only. Pro models are quota-blocked on the free tier.

## Running on Kubernetes (local)

Runs the same hardened manifests as EKS on Docker Desktop's built-in cluster (Settings → Kubernetes → Enable). [deploy/k8s-local/](deploy/k8s-local/kustomization.yaml) is a Kustomize overlay on the `deploy/k8s` base:
- **Database:** an in-cluster Postgres StatefulSet instead of RDS.
- **Models:** Gemini via LiteLLM for the copilot, and the offline model for triage, instead of Bedrock.
- **Telemetry:** an OpenTelemetry Collector, Jaeger, Prometheus and Grafana instead of ADOT and X-Ray.
- **Sign-in:** dev tokens signed with a random per-cluster secret, instead of Cognito.

```bash
deploy/k8s-local/up.sh        # build images, create secrets once, apply, wait for rollout
deploy/k8s-local/forward.sh   # open the UIs on 127.0.0.1 only (self-healing tunnels; Ctrl+C closes them)
deploy/k8s-local/smoke.sh     # 19 checks: auth, S1 stolen card, S3 referral, audit, web app through nginx
deploy/k8s-local/down.sh      # delete the namespace (data and secrets included)
```

| URL (after `forward.sh`) | What |
|---|---|
| http://localhost:8088 | Web app: customer portal + staff workspace |
| http://localhost:8088/api/docs | **API docs** (Swagger UI, self-hosted: the strict CSP blocks FastAPI's CDN version). Get a token with `POST /auth/dev-login`, then **Authorize** |
| http://localhost:3000 | **Grafana**: requests, p95 latency, errors, triage by category, copilot sources and time to first token, tokens and spend, guardrail blocks, approvals and escalations |
| http://localhost:16686 | **Jaeger**: one trace per request (HTTP → retrieval → model call → SQL) |
| 127.0.0.1:5434 | Postgres + pgvector, for a GUI or `psql` (user `agentops`) |

**Nothing is published to your network.** The tunnels bind 127.0.0.1, and docker-compose ports are bound the same way. An earlier version used a LoadBalancer Service, which Docker Desktop exposes on every interface: the demo sign-in was reachable from the whole Wi-Fi.

```text
namespace agentops (Pod Security: restricted, default-deny NetworkPolicy)
├── agentops-web     Deployment ×1   nginx + React app, proxies /api
├── agentops-api     Deployment ×2   /ready probes (checks the DB), read-only root FS, uid 10001
├── agentops-worker  Deployment ×1   SLA timers + crash recovery
├── litellm          Deployment ×1   gateway to Gemini (with model fallbacks); holds the provider key + a random master key
├── postgres         StatefulSet ×1  pgvector, 2 Gi PersistentVolume, reachable only from api + worker
└── otel-collector → jaeger (traces), prometheus → grafana (metrics)
```

**What observability caught on day one:** the Gemini free tier allows about **20 requests per day per model**. A Jaeger trace showed the copilot's model call failing (HTTP 429), followed by the offline fallback, and the dashboard's "Copilot fallback rate" shows the same thing over time. The fix was a gateway-level fallback across three models, each with its own quota.

The scripts refuse cloud contexts (`*eks*`, `arn:aws*`, …); set `KUBE_CONTEXT` to use another local cluster (kind is supported). Docker Desktop doesn't enforce NetworkPolicy, so the policies are applied but not tested locally.

## Deploying to AWS

The AWS stack is written and validated, but **not deployed**: deploying needs your account and costs money. Read [docs/aws.md](docs/aws.md) first (architecture, cost note, teardown).

```bash
deploy/aws/deploy.sh dev    # build and push the image, deploy nested CloudFormation, apply k8s manifests
deploy/aws/smoke.sh dev     # /health answers, and /triage without a token is rejected with 401
deploy/aws/destroy.sh dev   # tear everything down
```

---

## Repo layout

```text
src/agentops/          the application: api, auth, service (pipeline), guardrails, router, agent, copilot, …
  decision/            rules engine, flags, lifecycle, risk model, drift              (Phase 1)
  rag/                 corpus, chunking, embeddings, keyword/vector/hybrid search     (Phase 2)
  workflow/            cases, approvals, exactly-once actions, timers, Temporal        (Phases 4–5)
  migrations/          numbered SQL, 001–004: the schema's history
policies/              rules.yaml (live) and rules.rego (OPA variant)
prompts/               versioned prompts with front matter
contracts/             committed JSON Schemas for data contracts
data/                  synthetic data generator and policy corpus
evals/                 golden sets, red-team, journeys, and every eval script
benchmarks/            the same task in PydanticAI and LangGraph
tests/                 unit, contract, integration, replay
web/                   React web app: customer portal + staff workspace (nginx in the cluster)
ui/                    Streamlit client (minimal)
deploy/                docker-compose, LiteLLM, Keycloak, CloudFormation, k8s (EKS base), k8s-local (overlay), AWS scripts
docs/                  structure, ADRs, threat model, SLOs, release, observability, runbooks, eval reports
```

The full folder-by-folder and module-by-module guide is [docs/STRUCTURE.md](docs/STRUCTURE.md).

## Documentation

| Doc | Contents |
|---|---|
| [docs/STRUCTURE.md](docs/STRUCTURE.md) | Code map, request trace, "where is…?", database tables, reading order |
| [docs/adr/](docs/adr/) | ADRs 0001–0010. Two record deviations from project.md: [0005](docs/adr/0005-protective-flags-set-immediately.md) (flags set immediately) and [0009](docs/adr/0009-eks-pod-identity-over-irsa.md) (Pod Identity, not IRSA) |
| [docs/threat-model.md](docs/threat-model.md) | Threats, controls and accepted risks |
| [docs/slo.md](docs/slo.md), [docs/observability.md](docs/observability.md) | What's measured, and how to see it |
| [docs/release.md](docs/release.md) | Versioning, the gate, shadow runs, rollback |
| [docs/runbooks/](docs/runbooks/) | Model outage, approval backlog, failing eval gate, suspected data leak |
| [docs/incidents/](docs/incidents/) | Postmortem of the tier-2 outage drill |
| [docs/model-cards/risk-model.md](docs/model-cards/risk-model.md) | Risk model: data, metrics, limits |
| [docs/evals/](docs/evals/) | Generated reports (gate, baseline, RAG, guards, judge, drift, set size, benchmark) |

## Learning with this repo

1. Read [docs/STRUCTURE.md](docs/STRUCTURE.md), then follow its reading order.
2. Open [`../LEARNING_TRACKER.md`](../LEARNING_TRACKER.md). Every item is `[b]` (built by Claude). For each one: read the code, run it, break it, then change it without help. Only then mark it `[x]`.
3. The tracker's findings sections list the bugs that were found by *running* things (rolled-back audit rows, a fallback hiding a programming error, Rego's `null < 121`). Try to reproduce them.

## Honest scope

- **Offline by default.** A deterministic rule-based stand-in drives the real agent loop, so CI needs no keys. Offline scores prove the pipeline and gating, **not model quality**. No live baseline has been recorded yet (it needs provider credentials).
- **AWS is written and validated, not deployed.**
- **Built but not wired in:** the API still uses the Postgres timer worker, not Temporal; actions run against an in-repo fake ledger, not MCP's `execute_action`. Langfuse, Ragas and MLflow aren't set up.
- **Placeholder labels:** the judge-calibration labels were written by Claude, not by a human reviewer.
- **Synthetic everything.** Wattle Bank, its policies, customers and thresholds are invented. Verify real regulatory obligations before reusing any rule.
- Accepted risks are listed in [docs/threat-model.md](docs/threat-model.md).

## Related

[MCP Case Tools](../mcp-case-tools): an MCP server with least-privilege roles, two workflow profiles (regulator, Wattle Bank), idempotency keys and an audit trail. This repo calls it as the human's role, so the agent can never do more than the person using it.
