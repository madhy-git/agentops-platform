# AgentOps Platform

A tested reference implementation of the **operational layer around an AI agent** in a regulated setting: customer self-service, message triage and a staff policy copilot for **Wattle Bank**, a fictional Australian bank.

The agent is the easy part. This repo is about running it safely:

- **What goes in:** PII masking, prompt-injection guards (direct and hidden in documents), and a misuse guard.
- **Which model runs:** a cost-aware router, fallback chains in the app *and* in the gateway, a circuit breaker.
- **What the rules allow:** deterministic, versioned rules decide; the model only recommends.
- **Who approves:** domain-routed approvals with SLAs and separation of duties; nothing is ever auto-approved.
- **What anyone can see:** role filters inside every retrieval query; customers see only their own requests.
- **Why it decided:** an append-only **AI decision trail** per case: what the model received, its tool calls, its answer and justification, and the rules that fired.
- **How it's watched:** OpenTelemetry traces and metrics into Jaeger, Prometheus and Grafana; an append-only audit trail.
- **How quality is gated:** a 7-metric release gate, a red-team set, judge calibration.

It is also a **learning project**. Every module opens with *LEARNING NOTES* (what it does, why it's built that way, which failure it prevents), and progress is tracked outside the repo in [`../LEARNING_TRACKER.md`](../LEARNING_TRACKER.md). All data is synthetic.

| If you want… | Go to |
|---|---|
| To run it and click around | [Run it](#run-it) |
| A map of the code, with one request traced end to end | [docs/STRUCTURE.md](docs/STRUCTURE.md) |
| The plan (business, rules, scenarios, phases) | [project.md](project.md) |
| Why each choice was made | [docs/adr/](docs/adr/) |
| What's honestly *not* done | [Honest scope](#honest-scope) |

**Contents:** [Run it](#run-it) · [What you can do](#what-you-can-do) · [Architecture](#architecture) · [What's built](#whats-built) · [API](#api) · [Database](#database) · [Observability](#observability) · [Configuration](#configuration) · [Security](#security) · [Quality checks](#quality-checks) · [Evals](#evals-and-reports) · [AWS](#deploying-to-aws) · [Repo layout](#repo-layout) · [Docs](#documentation) · [Honest scope](#honest-scope)

---

## The workspace

```text
agentops-platform/            (workspace folder, not a repo)
├── agentops-platform/        ← this repo
├── mcp-case-tools/           ← sibling repo: MCP server with least-privilege case tools
└── LEARNING_TRACKER.md       ← exercises, findings and progress; only you mark items [x]
```

---

## Run it

### Option A: the full platform on local Kubernetes (recommended)

Requires Docker Desktop with Kubernetes enabled (Settings → Kubernetes), plus `kubectl`, [uv](https://docs.astral.sh/uv/) and Node 22+. It runs the same hardened manifests as the AWS (EKS) target, with local stand-ins for the cloud parts.

```bash
cp .env.example .env                 # optional: add GEMINI_API_KEY=... so the copilot uses Gemini
deploy/k8s-local/up.sh               # build images, create secrets once, deploy, wait (first run ~5 min)
deploy/k8s-local/forward.sh          # open everything on 127.0.0.1 only; leave it running (Ctrl+C closes)
deploy/k8s-local/smoke.sh            # 21 end-to-end checks against the cluster
```

| Open | What |
|---|---|
| **<http://localhost:8088>** | **Web app:** customer portal and staff workspace |
| <http://localhost:8088/api/docs> | **API docs** (Swagger UI, self-hosted) |
| <http://localhost:3000> | **Grafana** dashboard |
| <http://localhost:16686> | **Jaeger** traces |
| `127.0.0.1:5434` | **Postgres + pgvector** for a database GUI ([connection details](#database)) |

`deploy/k8s-local/down.sh` deletes everything, including data and secrets. `forward.sh` stops when your Mac restarts; run it again.

### Option B: on your laptop, without Kubernetes

Requires Docker, [uv](https://docs.astral.sh/uv/) and Python 3.12 (uv installs it). Runs **offline**: no API keys needed.

```bash
docker compose -f deploy/docker-compose.yml up -d postgres          # Postgres + pgvector on 127.0.0.1:5433
uv sync --all-extras                                                # app + dev tools + optional extras
uv run pytest -q                                                    # tests (first run downloads a ~130 MB embedding model)
uv run python evals/run_evals.py --report                           # the release gate
AGENTOPS_DEV_LOGIN=1 uv run uvicorn agentops.api:create_app --factory --reload   # API on :8000
cd web && npm ci && npm run dev                                     # web app on :5173 (/api proxied to :8000)
```

Port 5433 is deliberate: it avoids a locally installed Postgres on 5432. To use MCP Case Tools as the case source, run `uv pip install -e ../mcp-case-tools` and set `AGENTOPS_CASE_SOURCE=mcp`.

---

## What you can do

### Customer portal and staff workspace

There's no sign-in screen. Open the app, pick a side, and use **"Viewing as"** in the header to switch person. Each person gets a real signed token behind the scenes, and the API enforces their role.

| Side | People | What they can do |
|---|---|---|
| **Customer portal** (`/portal`) | Jordan, Priya, Noah (customers) | Raise a request (lost card, dispute, hardship, complaint), track it step by step, ask the help assistant (customer articles only) |
| **Staff workspace** (`/staff`) | Officer, fraud and hardship specialists, disputes, manager, compliance | Dashboard; case queue; case detail with the rules decision, customer flags and the **AI decision trail**; **My approvals** with SLA countdowns; policy copilot; audit trail (managers and compliance) |

Customers only ever see their own requests, in plain language: no reason codes, risk scores or internal queues.

**Try the full loop:**

1. In the **customer portal**, as Jordan, report a stolen card. Status: *With a specialist*.
2. In the **staff workspace**, switch to the fraud specialist and approve it in *My approvals*. The card block runs exactly once.
3. Back in the portal, the request shows *Action taken: your card has been blocked*.
4. In the staff workspace, open the case and expand **How the AI triaged this case**.

### Copilot (staff) and help assistant (customers)

Both answer only from the policies the asker may read, cite their sources, and stream the answer as it's written. In the local cluster they use **Google Gemini** through the LiteLLM gateway.

- **As Alex Officer**, ask "What hardship arrangement options can we offer?". You get no content, only a banner referring you to the hardship specialist queue.
- **As Harper Hardship**, ask the same question. You get the actual options, cited.
- **Misuse** ("how can I cheat the bank to get a refund?") is refused by a deterministic guard before anything is retrieved or sent to a model.
- **Every answer says who produced it:** Gemini, the offline fallback (Gemini unavailable), a safety check, a role restriction, or no matching policy.

Turning Gemini on: put `GEMINI_API_KEY=...` in the git-ignored `.env` and run `up.sh`. Only LiteLLM ever sees the key, through a Kubernetes Secret. **Free tier:** about 20 requests per model per day, so the gateway falls back across three models, and after that the app falls back to an offline answer. Google may use free-tier prompts, so use synthetic data only.

### AI decision trail (staff only)

Every triage stores what the model actually saw and did, next to what the rules then decided. It's append-only, holds masked text only, and customers get 403.

| Step | Shows |
|---|---|
| 1. What the AI received | The message after PII masking, what was masked, the injection-check result |
| 2. Which model, and why | Model tier, routing reason, fallbacks, prompt version |
| 3. What it looked up | Each tool call, plus the **exact conversation**: system instructions, tool calls and results, the final structured answer |
| 4. What it recommended | Category, severity, confidence, action, and the model's **justification**, shown as a claim to check against the evidence |
| 5. What the rules decided | The rules that fired (e.g. R1 FRAUD_SUSPECTED → block card, R5 NEEDS_APPROVAL), the queue, the actions, whether approval is needed |
| 6. Audit trail for the case | Every event, with tokens, latency and the trace ID |

---

## Architecture

```mermaid
flowchart LR
    subgraph Browser
        WEB["Web app (React)<br/>portal · staff workspace"]
    end

    subgraph Cluster["Kubernetes namespace agentops (restricted pods, default-deny network)"]
        NGX["nginx<br/>static app · /api proxy · strict CSP"]
        API["API (FastAPI) ×2<br/>auth · triage · copilot · portal"]
        WK["Worker<br/>SLA timers · crash recovery"]
        LLM["LiteLLM gateway<br/>tier aliases · model fallbacks"]
        PG[("Postgres 17 + pgvector<br/>cases · approvals · flags · audit<br/>policy vectors · AI trail · memory")]
        COL["OpenTelemetry Collector"]
        JAE["Jaeger<br/>traces"]
        PRO["Prometheus<br/>metrics"]
        GRA["Grafana<br/>dashboard"]
    end

    GEM["Google Gemini<br/>(free tier)"]
    MCP["MCP Case Tools<br/>../mcp-case-tools"]

    WEB --> NGX --> API
    API --> PG
    WK --> PG
    API -- "copilot (live)" --> LLM --> GEM
    API -. "AGENTOPS_CASE_SOURCE=mcp" .-> MCP
    API -- "OTLP" --> COL
    WK -- "OTLP" --> COL
    COL --> JAE
    COL --> PRO --> GRA
```

**Three ideas carry the whole design:**

1. **The model recommends, the rules decide, a human approves** anything regulated. The model returns a typed `TriageResult`, and the rules engine (`decision/`) turns it into actions, flags and an approval requirement.
2. **Permissions are checked in several independent places:**
   - the API (`auth.require`);
   - the approval logic: separation of duties, checked in code *and* by a database CHECK constraint;
   - the retrieval SQL `WHERE` clause;
   - MCP Case Tools, separately.
   The UI only reflects these checks.

3. **Everything leaves evidence.** The audit trail and the AI trail are append-only: database triggers refuse updates and deletes. Traces link to both through `trace_id`.

### How a triage request flows

```text
message ─► mask PII ─► injection guard ─► route to the cheapest capable model tier
                                           │  (fallback to a higher tier on provider errors; circuit breaker)
                                           ▼
           PydanticAI agent ─► typed TriageResult (category, severity, action, confidence, rationale)
                                           │  tools: search_policy (role-filtered pgvector), lookup_case (static or MCP)
                                           ▼
           rules R1–R7 (policies/rules.yaml) ─► reason codes, flags, marketing suppression, next-best-action
                                           ▼
           case opened ─► regulated? ─► approval routed by domain, with an SLA (remind 50%, escalate 100%, never auto-approve)
                                           ▼
           specialist approves ─► action runs exactly once (idempotency key, crash recovery)

Every step: an audit event, an OpenTelemetry span and metrics. The whole model conversation goes into the AI trail.
```

The **copilot** is a second path: mask the question → injection and misuse guards → retrieve with the caller's roles (a relevance band relative to the best match) → stream a cited answer from Gemini, or the offline fallback → store it in role-aware session memory.

### On AWS (written and validated, not deployed)

```mermaid
flowchart LR
    GH["GitHub Actions"] -- "OIDC, short-lived creds" --> ROLE["Deploy role"]
    GH --> ECR["ECR<br/>immutable tags · scan on push"]
    USER["Staff"] -- "sign in" --> COG["Cognito<br/>groups = app roles"]
    USER -- "HTTPS (TLS 1.3)" --> ALB["ALB"]

    subgraph VPC["VPC: private subnets"]
        subgraph EKS["EKS (restricted pods, default-deny NetworkPolicy)"]
            APIP["agentops-api"]
            WKP["agentops-worker"]
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
    ADOT -- "Pod Identity" --> XR["X-Ray / CloudWatch"]
    COG -. "JWKS" .-> APIP
```

**The local cluster swaps in stand-ins for the cloud parts:**

| AWS | Local cluster |
|---|---|
| RDS + Secrets Manager | an in-cluster Postgres StatefulSet + Kubernetes Secrets |
| Bedrock | Gemini via LiteLLM (copilot); offline model (triage) |
| ADOT → X-Ray | Collector → Jaeger, Prometheus, Grafana |
| ALB Ingress | `forward.sh` on 127.0.0.1 |
| Cognito | dev tokens signed with a random per-cluster secret |

Both are Kustomize builds over the same base: `deploy/k8s` (base) and `deploy/k8s-local` (overlay).

---

## What's built

| Phase | Area | Built | Checked by running it |
|---|---|---|---|
| 0 | Foundation | Postgres, LiteLLM tier aliases, data contracts, versioned prompts, synthetic data, offline baseline | The audit table refuses UPDATE and DELETE |
| 1 | Decisioning | YAML rules R1–R7, flags with lifetimes, lifecycle, next-best-action, scikit-learn risk model with model card, PSI drift | Lifecycle replay: 17/17 journey steps correct |
| 2 | Identity-aware RAG | pgvector, full-text and hybrid search; role filter inside the SQL; citations | 0 leaks across 9 configurations |
| 3 | Evals | 7-metric release gate, red-team set, judge calibration, set-size experiment, shadow runs, failure capture | A harmful prompt change fails the gate |
| 4 | Copilot, auth, workflow | SSE streaming, JWT roles (Keycloak, Cognito), session memory, case state machine, approvals with SLAs, exactly-once actions, MCP | A process killed mid-action recovers and applies the action exactly once |
| 5 | Durable workflows | Temporal approvals (built; not wired in, see ADR 0008) | Real server: worker killed, SLA expired while down, escalated 1 s after restart |
| 6 | AWS | Nested CloudFormation, EKS + Pod Identity, RDS, Cognito, Bedrock, hardened manifests, deploy scripts, OIDC workflow | cfn-lint, Checkov, kubeconform, Trivy, shellcheck pass. **Not deployed** |
| 7 | Variants | Same task in PydanticAI and LangGraph; rules in OPA/Rego | Rego and Python agree on 2,000 inputs |
| 8 | Self-service platform | Local Kubernetes deployment; React portal and staff workspace; customer identity; Gemini copilot with fallbacks; misuse guard; AI decision trail; OpenTelemetry → Jaeger, Prometheus, Grafana | Smoke test 21/21 on the cluster; trail and dashboard queries verified on live data |

**Status:** 159 Python tests (unit, contract, integration, replay, Temporal) · 13 web tests · release gate passing offline · ruff, mypy and pre-commit clean · MCP Case Tools: 8 tests.

### Scenarios from project.md

| Scenario | What it proves | Where |
|---|---|---|
| S1 Stolen card | PII masked, R1 fires, case opened, approval routed to a fraud specialist | `tests/integration/test_pipeline.py`, `smoke.sh` |
| S2 Hardship | R2, specialist routing, marketing suppressed | `tests/integration/test_decision.py` |
| S3 Officer asks restricted policy | Restricted chunks never returned; referred instead | `test_rag_pg.py`, `test_copilot.py` |
| S4 Prompt injection | Direct and planted (indirect) injection blocked and logged | `tests/unit/test_guardrails.py`, `evals/redteam.yaml` |
| S5 Release gate | A prompt change that drops escalation recall fails CI | `test_eval_gate.py` |
| S6 Lifecycle replay | Flags set and cleared, marketing suppressed and restored | `tests/replay/`, `evals/replay.py` |
| S7 Approval timeout | Reminder, escalation, never auto-approved, survives restart | `test_workflow.py`, `test_temporal.py` |
| S8 Mid-action crash | No duplicate side effect after a real process kill | `test_workflow.py` |
| S9 Model outage | Fallback engages; cost impact recorded | `tests/unit/test_resilience.py`, `evals/baseline.py` |

---

## API

FastAPI, in [src/agentops/api.py](src/agentops/api.py) (staff), [portal.py](src/agentops/portal.py) (customers) and [auth.py](src/agentops/auth.py) (tokens and role guards). The web app reaches it at `/api`.

**Interactive docs:** <http://localhost:8088/api/docs>.

1. Run `POST /auth/dev-login` with `{"username": "officer-1"}`.
2. Copy the `token` from the response.
3. Click **Authorize** and paste it.

| Method and path | Who | What |
|---|---|---|
| `GET /health`, `GET /ready` | anyone | Process up; can serve (checks the DB; used by the Kubernetes probes) |
| `GET /me` | any token | Who the token says you are |
| `GET /auth/personas`, `POST /auth/dev-login` | anyone, only when enabled | Demo sign-in: needs `AGENTOPS_DEV_LOGIN=1` **and** no identity provider; otherwise 404 |
| `POST /triage` | staff | Run the full pipeline on a message |
| `GET /cases`, `GET /cases/{id}` | staff, compliance | Case queue; one case with its decision, approvals and customer flags |
| `GET /cases/{id}/ai-trail` | staff, compliance | The AI decision trail for a case |
| `POST /cases/{id}/transition` | staff | Move a case through the state machine (manager-only moves enforced) |
| `GET /approvals/mine`, `POST /approvals/{id}/decision` | staff | Your approval queue; approve or reject (domain and separation of duties enforced) |
| `GET /customers/{id}`, `POST /customers/{id}/flags/{flag}/clear` | staff | Customer and flags; only the matching specialist can clear a flag |
| `GET /stats` | staff, compliance | Dashboard counts |
| `POST /copilot`, `POST /copilot/stream` | staff | Cited policy answers (SSE streaming) |
| `GET /audit` | manager, compliance | The append-only audit trail, filterable by `case_id` |
| `GET /portal/me`, `GET /portal/cases`, `GET /portal/cases/{id}` | customer | Your own requests and timeline (someone else's case returns 404) |
| `POST /portal/requests` | customer | Raise a request (same pipeline as triage) |
| `POST /portal/assistant/stream` | customer | Help assistant over customer articles only |

"Staff" means officer, manager, fraud or hardship specialist, or disputes officer. Customers get 403 on every staff endpoint; a test covers each one.

**With curl against the cluster:**

```bash
API=http://localhost:8088/api
tok() { curl -s $API/auth/dev-login -H 'content-type: application/json' -d "{\"username\":\"$1\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])'; }
OFFICER=$(tok officer-1); MGR=$(tok manager-1)

curl -s $API/triage -H "Authorization: Bearer $OFFICER" -H 'content-type: application/json' \
  -d '{"message":"My card was stolen at the airport, call me on 0411 821 692"}'
curl -s "$API/cases?limit=1" -H "Authorization: Bearer $OFFICER"
curl -s $API/audit -H "Authorization: Bearer $MGR"
```

---

## Database

One Postgres 17 with pgvector holds all state (ADR 0002). The schema history is the numbered migrations `001`–`007` in [src/agentops/migrations/](src/agentops/migrations/).

**Connecting with a GUI** (VS Code's PostgreSQL or Database Client extension, DBeaver, TablePlus) while `forward.sh` is running:

| Setting | Cluster database (the running app) | docker-compose database (tests) |
|---|---|---|
| Host / port | `127.0.0.1` / `5434` | `127.0.0.1` / `5433` |
| Database / user | `agentops` / `agentops` | `agentops` / `agentops` |
| Password | `kubectl -n agentops get secret agentops-secrets -o jsonpath='{.data.POSTGRES_PASSWORD}' \| base64 -d` | `agentops` (local default) |

Without a GUI: `kubectl -n agentops exec -it postgres-0 -- psql -U agentops -d agentops`.

| Table | Holds |
|---|---|
| `policy_chunks` | Policy text from [data/policies/](data/policies/), chunked, with 384-dim embeddings (HNSW index) and `allowed_roles` |
| `cases`, `approval_requests`, `actions`, `core_banking_ledger` | Workflow state; the ledger is a stand-in for a core-banking system |
| `customers`, `customer_flags`, `transactions`, `decisions` | Rules-engine inputs and outputs |
| `audit_events` | Append-only audit trail |
| `model_traces` | Append-only AI decision trail |
| `chat_turns` | Copilot session memory, role-aware |
| `kb_chunks` | Large knowledge-base table (schema only so far; see [Honest scope](#honest-scope)) |

The **policy files** in `data/policies/` are the source of truth: the vectors are derived from them, and a fingerprint check re-embeds automatically when a file changes. The **rules** in `policies/rules.yaml` are never embedded; the rules engine reads them directly.

Try a vector similarity query (`<=>` is pgvector's cosine distance):

```sql
SELECT b.doc_id, round((1 - (a.embedding <=> b.embedding))::numeric, 3) AS similarity
FROM policy_chunks a JOIN policy_chunks b ON a.chunk_size = b.chunk_size
WHERE a.doc_id = 'POL-DISP-01' AND a.chunk_size = 600
ORDER BY a.embedding <=> b.embedding LIMIT 5;
```

---

## Observability

```text
API, worker ──OTLP──► OpenTelemetry Collector ──traces──► Jaeger      http://localhost:16686
                                               └─metrics─► Prometheus ──► Grafana   http://localhost:3000
```

- **Traces (Jaeger):** one trace per request: the HTTP route, then copilot retrieval (hits, passages used, best score), the agent run, the model call and every SQL query. Prompts and answers are deliberately **not** in traces. They live in the access-controlled AI trail, because telemetry systems usually have wider access.
- **Metrics (Grafana, "AgentOps" dashboard):**
  - *health:* requests, 5xx errors, p95 latency per endpoint;
  - *AI:* triage by category and outcome, copilot answers by source, time to first token, **fallback rate**, tokens and estimated spend;
  - *oversight:* guardrail blocks, approval decisions, SLA escalations.

  Metric labels are a small fixed vocabulary, never IDs or text; a test enforces this.

- **Dashboard as code:** [deploy/k8s-local/dashboards/agentops.json](deploy/k8s-local/dashboards/agentops.json). Every panel query was verified against live data.
- **Logs:** `kubectl -n agentops logs deploy/<name>`.

On AWS the same app sends OTLP to ADOT, which feeds X-Ray and CloudWatch. Only the collector's configuration differs.

---

## Configuration

All app settings are read from the environment in one place: [src/agentops/config.py](src/agentops/config.py).

| Variable | Default | Effect |
|---|---|---|
| `AGENTOPS_MODE` | `offline` | `live` sends **triage** model calls through LiteLLM |
| `AGENTOPS_COPILOT_MODE` | same as `AGENTOPS_MODE` | `live` switches only the **copilot** to a real model (the local cluster does this) |
| `AGENTOPS_DATABASE_URL` | `postgresql://agentops:agentops@localhost:5433/agentops` | Postgres. On AWS: `AGENTOPS_DB_SECRET_ARN` + `AGENTOPS_DB_HOST` instead |
| `AGENTOPS_JWT_SECRET` | dev default | Signs dev tokens. The cluster uses a random per-cluster value |
| `AGENTOPS_JWKS_URL`, `AGENTOPS_JWT_AUDIENCE`, `AGENTOPS_JWT_ISSUER` | unset / `agentops-api` / unset | Real identity provider (Keycloak, Cognito); disables demo sign-in |
| `AGENTOPS_DEV_LOGIN` | off | `1` enables the demo sign-in, only while no identity provider is set |
| `AGENTOPS_CASE_SOURCE` | `static` | `mcp` = cases from MCP Case Tools |
| `AGENTOPS_PROMPT_TRIAGE_MAJOR` | `1` | Feature flag: switch prompt version without a deploy |
| `AGENTOPS_POLICY_FILE` | `policies/rules.yaml` | Feature flag: trial a new rule set |
| `LITELLM_BASE_URL`, `LITELLM_API_KEY` | `http://localhost:4000/v1`, dev key | The model gateway; in the cluster the key is LiteLLM's random master key |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` | unset / `agentops-platform` | Turn on traces and metrics; name the service |
| `GEMINI_API_KEY` | in `.env` only | **Read by LiteLLM only.** `up.sh` copies it into a Kubernetes Secret |
| `KUBE_CONTEXT` | `docker-desktop` | Which local cluster the `k8s-local` scripts use. They refuse cloud contexts |

Optional docker-compose services (`docker compose -f deploy/docker-compose.yml --profile <name> up -d`), all bound to 127.0.0.1:

| Profile | Service |
|---|---|
| `tracing` | Jaeger (`:16686`, OTLP `:4318`) |
| `auth` | Keycloak (`:8080`, realm `wattle`; see [deploy/keycloak](deploy/keycloak/README.md)) |
| `temporal` | Temporal dev server (`:7233`, UI `:8233`); try `uv run python evals/temporal_restart_drill.py` |
| `live` | LiteLLM gateway (`:4000`) |

---

## Security

- **Nothing listens on your network.** Every UI and the database are reached through `forward.sh` on 127.0.0.1, and docker-compose ports bind 127.0.0.1. (An earlier version used a LoadBalancer Service, which Docker Desktop publishes on every interface: the demo sign-in was reachable from the whole Wi-Fi.)
- **No secrets in git or manifests.** Database password, JWT secret, LiteLLM master key and Grafana admin password are random per cluster, in Kubernetes Secrets. The Gemini key goes from the git-ignored `.env` to a Secret that only LiteLLM reads.
- **Who you are comes only from the signed token.** Customers' data scope comes from the token's `customer_id` claim, never from a URL or request body. Tokens mixing customer and staff roles are rejected.
- **Strict Content-Security-Policy:** scripts only from this site, which is why the API docs are self-hosted. Model output is rendered as text, never as HTML.
- **Guards before the model:** PII masking, injection detection (in the message *and* in retrieved documents), and a misuse guard. Their blocks are counted, audited and visible in Grafana.
- **Pods:** non-root, read-only filesystems, no Linux capabilities, restricted Pod Security, default-deny NetworkPolicy. (Docker Desktop doesn't enforce NetworkPolicy, so the policies are applied but untested locally.)
- Threats and accepted risks: [docs/threat-model.md](docs/threat-model.md).

---

## Quality checks

```bash
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run mypy                                           # types
uv run pytest -q                                      # 159 tests (needs Postgres on 5433)
uv run python evals/run_evals.py                      # release gate: exits non-zero if quality drops
(cd web && npm run typecheck && npm test && npm run build)   # web app: types, 13 tests, production build
uv run pre-commit run --all-files                     # the hooks that run on commit (incl. gitleaks)
deploy/k8s-local/smoke.sh                             # 21 end-to-end checks against the running cluster
```

| Workflow | Runs |
|---|---|
| [ci.yml](.github/workflows/ci.yml) | Lint, types, tests, eval gate (every push and PR) |
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

## Deploying to AWS

The AWS stack is written and validated, but **not deployed**: deploying needs your account and costs money. Read [docs/aws.md](docs/aws.md) first (architecture, cost note, teardown).

```bash
deploy/aws/deploy.sh dev    # build and push the image, deploy nested CloudFormation, apply the k8s base
deploy/aws/smoke.sh dev     # /health answers; /triage without a token is rejected with 401
deploy/aws/destroy.sh dev   # tear everything down
```

---

## Repo layout

```text
src/agentops/          the application: api, portal, auth, service (pipeline), guardrails, router, agent, copilot,
                       llm, telemetry, personas, …
  decision/            rules engine, flags, lifecycle, risk model, drift
  rag/                 corpus, chunking, embeddings, keyword/vector/hybrid search, role filter
  workflow/            cases, approvals, exactly-once actions, SLA timers, Temporal
  migrations/          numbered SQL 001–007: the schema's history
policies/              rules.yaml (live) and rules.rego (OPA variant)
prompts/               versioned prompts with front matter (triage 1.1.0)
contracts/             committed JSON Schemas for data contracts
data/                  synthetic data generator and the policy corpus (data/policies/)
evals/                 golden sets, red-team, journeys, and every eval script
benchmarks/            the same task in PydanticAI and LangGraph
tests/                 unit, contract, integration, replay
web/                   React web app (portal + staff workspace), nginx config, self-hosted API docs
ui/                    Streamlit client (minimal, older)
deploy/
  docker-compose.yml   laptop services (Postgres, LiteLLM, Keycloak, Jaeger, Temporal), all on 127.0.0.1
  k8s/                 Kubernetes base (EKS)
  k8s-local/           local overlay: Postgres, web, Gemini via LiteLLM, observability, up/forward/smoke/down scripts
  cloudformation/      nested AWS stacks
  aws/                 deploy, destroy, smoke scripts
docs/                  structure, ADRs, threat model, SLOs, release, observability, runbooks, eval reports
```

Folder-by-folder and module-by-module guide: [docs/STRUCTURE.md](docs/STRUCTURE.md).

## Documentation

| Doc | Contents |
|---|---|
| [docs/STRUCTURE.md](docs/STRUCTURE.md) | Code map, request trace, "where is…?", database tables, reading order |
| [docs/adr/](docs/adr/) | ADRs 0001–0010, e.g. [0005](docs/adr/0005-protective-flags-set-immediately.md) (flags set immediately), [0008](docs/adr/0008-temporal-vs-postgres-timers.md) (when Temporal is worth it), [0009](docs/adr/0009-eks-pod-identity-over-irsa.md) (Pod Identity, not IRSA) |
| [docs/threat-model.md](docs/threat-model.md) | Threats, controls and accepted risks |
| [docs/slo.md](docs/slo.md), [docs/observability.md](docs/observability.md) | What's measured, and how to see it |
| [docs/release.md](docs/release.md) | Versioning, the gate, shadow runs, rollback |
| [docs/runbooks/](docs/runbooks/) | Model outage, approval backlog, failing eval gate, suspected data leak |
| [docs/incidents/](docs/incidents/) | Postmortem of the tier-2 outage drill |
| [docs/model-cards/risk-model.md](docs/model-cards/risk-model.md) | Risk model: data, metrics, limits |
| [docs/evals/](docs/evals/) | Generated reports (gate, baseline, RAG, guards, judge, drift, set size, benchmark) |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Learning with this repo

1. Read [docs/STRUCTURE.md](docs/STRUCTURE.md), then follow its reading order.
2. Open [`../LEARNING_TRACKER.md`](../LEARNING_TRACKER.md). Every item is `[b]` (built by Claude). For each one: read the code, run it, break it, then change it without help. Only then mark it `[x]`.
3. The tracker's findings list the bugs found by *running* things, not by reading code. For example:
   - audit rows that rolled back with the error they recorded;
   - a startup race between replicas;
   - a health check that lied about a dead database;
   - a copilot crash only in newer Chrome;
   - security headers silently dropped by nginx;
   - a demo login exposed to the Wi-Fi;
   - the Gemini free-tier quota.

   Try to reproduce them.

## Honest scope

- **Triage runs on the offline model** (deterministic keyword rules driving the real agent loop), so its scores prove the pipeline and gating, **not model quality**. It misses paraphrases like "someone stole my card". No live-model baseline has been recorded yet. The **copilot** does use Gemini, on the free tier, so it's subject to daily quotas.
- **AWS is written and validated, not deployed.**
- **Temporal is built but not wired in**, deliberately: one approval type with hour-scale SLAs doesn't need it ([ADR 0008](docs/adr/0008-temporal-vs-postgres-timers.md)).
- **No real core-banking integration.** Approved actions write to a stand-in table (`core_banking_ledger`), not an external REST API; the idempotency and exactly-once patterns are real. Actions don't go through MCP's `execute_action` either.
- **The large knowledge base is not loaded yet.** The `kb_chunks` table exists (migration 006); the synthetic corpus generator, loader and benchmark are still to be built.
- **Not set up:** Langfuse, Ragas, MLflow. The judge-calibration labels are placeholders written by Claude, not by a human reviewer.
- **Synthetic everything.** Wattle Bank, its policies, customers and thresholds are invented. Verify real regulatory obligations before reusing any rule.

## Related

[MCP Case Tools](../mcp-case-tools): an MCP server with least-privilege roles, two workflow profiles (regulator, Wattle Bank), idempotency keys and an audit trail. This repo calls it as the human's role, so the agent can never do more than the person using it.
