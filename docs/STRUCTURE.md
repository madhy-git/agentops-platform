# Project structure: a map for learning

This repo is built to *learn* AI engineering, so the layout follows the questions you'd ask about an AI system in a regulated business: *what comes in, who decides, what can it touch, how do we know it's good, and how does it run in production?*

```text
/Users/.../agentops-platform/
├── agentops-platform/     ← this repo: the operational layer around an AI agent (Phases 0–7)
├── mcp-case-tools/        ← sibling repo: an MCP server giving agents least-privilege access to cases
└── LEARNING_TRACKER.md    ← your progress, outside both repos (only you mark things [x])
```

---

## 1. One request, end to end

Follow a customer message ("my card was stolen") through the code. Each step names the file to open.

```text
HTTP POST /triage  (bearer token)                                   api.py
  │  verify JWT → Principal(user, roles)                            auth.py
  ▼
TriageService.triage                                                service.py
  ├─ 1. redact PII ("0411 821 692" → [PHONE])                       guardrails.redact_pii
  ├─ 2. block prompt injection (direct)                             guardrails.detect_injection
  ├─ 3. route: cheapest model tier that can do the job              router.route
  │     └─ run the agent, falling back UP a tier on provider errors service._run_with_fallback
  │          circuit breaker skips a dead tier                      resilience.py
  │          model = offline rules (CI) or LiteLLM → real model     llm.py
  │          agent: typed TriageResult + tools                      agent.py, contracts.py
  │            ├─ search_policy → retriever (filtered by ROLE)      rag/pg.py, rag/memory.py
  │            │    └─ drops planted instructions (indirect inj.)   guardrails.scan_retrieved
  │            └─ lookup_case → static dict or MCP Case Tools       mcp_tools.py
  ├─ 4. cost from measured tokens, on the span                      telemetry.py
  ├─ 5. DECISION: rules authorise, the model only recommends        decision/service.py, decision/rules.py
  │        R1–R7 from policies/rules.yaml → reason codes, flags,     policies/rules.yaml
  │        marketing suppression, next-best-action, risk score      decision/flags.py, decision/risk.py
  ├─ 6. open a CASE (state machine)                                 workflow/cases.py
  └─ 7. regulated? → APPROVAL request, routed by domain, with SLA   workflow/approvals.py
                         │
       timer worker: remind 50%, escalate 100%, never approve       workflow/timers.py   (or Temporal: temporal_approval.py)
                         │
HTTP POST /approvals/{id}/decision  (specialist or manager)         api.py
  └─ separation of duties + domain check → approved                workflow/approvals.py
       └─ execute EXACTLY ONCE (idempotency key, crash recovery)    workflow/actions.py
Every step: an audit event (append-only table) + an OpenTelemetry span, linked by trace_id   audit.py
```

The **copilot** (`POST /copilot/stream`) is a second, simpler path: redact → injection check → retrieve with the caller's roles → relevance threshold → stream an answer with citations → store memory with derived entitlements (`copilot.py`, `memory.py`).

---

## 2. Folder by folder

| Folder | What lives there | Phase | Start with |
|---|---|---|---|
| `src/agentops/` | The application (Python package) | 0–7 | `service.py`: the whole pipeline in one file |
| `src/agentops/decision/` | Deterministic rules, flags, lifecycle, risk model, drift | 1 | `rules.py` then `service.py` |
| `src/agentops/rag/` | Corpus loading, chunking, embeddings, keyword/vector/hybrid search | 2 | `base.py` (the contract), then `pg.py` |
| `src/agentops/workflow/` | Cases, approvals, idempotent actions, timers, Temporal | 4–5 | `cases.py`, then `actions.py` |
| `src/agentops/migrations/` | Numbered SQL files, one per phase: the schema's history | 0–4 | `001_core.sql` (the append-only trigger) |
| `policies/` | Business rules as data: `rules.yaml` (live), `rules.rego` (OPA variant) | 1, 7 | `rules.yaml` |
| `prompts/` | Versioned prompts with front matter | 0, 3 | `triage.v1.md` |
| `contracts/` | Committed JSON Schemas for data contracts | 0 | any; then `tests/contract/` |
| `data/` | Synthetic data generator + policy corpus (all fictional) | 0, 2 | `generate.py` docstring |
| `evals/` | Golden sets, red-team, journeys, and every eval script | 0–5 | `run_evals.py` (the release gate) |
| `benchmarks/` | Same task in PydanticAI and LangGraph | 7 | `adapters.py` docstring |
| `tests/unit/` | Pure logic, no database | all | `test_rules.py` |
| `tests/contract/` | Schemas match the committed contracts | 0 | `test_contracts.py` |
| `tests/integration/` | Real Postgres (scratch schema per test), API, Temporal | all | `test_pipeline.py` |
| `tests/replay/` | Lifecycle journeys (scenario S6) | 1 | `test_journeys.py` |
| `ui/` | Streamlit client (thin; the server checks everything) | 4 | `app.py` |
| `deploy/` | docker-compose, LiteLLM, Keycloak, CloudFormation, Kubernetes, AWS scripts | 0, 4, 6 | `docker-compose.yml` |
| `docs/adr/` | Why each choice was made (and two deviations from project.md) | all | `0002`, `0005`, `0009` |
| `docs/evals/` | Generated reports: baseline, gate, RAG, guards, judge, drift, benchmark | 0–7 | `0.3.0-offline.md` |
| `docs/runbooks/`, `docs/incidents/` | What to do at 3 a.m.; one drill postmortem | 4 | `incidents/...drill.md` |
| `.github/workflows/` | CI (tests + gate), security scans, manual OIDC deploy | 0, 6 | `ci.yml` |

---

## 3. The modules in `src/agentops/`, by layer

| Layer | Module | One-line purpose |
|---|---|---|
| Entry | `api.py` | HTTP endpoints; maps domain errors to 401/403/404/409 |
| Identity | `auth.py` | JWT (dev HS256, Keycloak/Cognito RS256) → `Principal`; `require(...)` dependency |
| Orchestration | `service.py` | The triage pipeline (steps 1–7 above) |
| Safety | `guardrails.py` | PII redaction, direct and indirect injection, tool policy |
| Model access | `router.py`, `llm.py`, `resilience.py` | Tier choice, fallback, LiteLLM client, circuit breaker |
| Agent | `agent.py`, `prompts.py` | PydanticAI agent, tools, offline stand-in, versioned prompt |
| Contracts | `contracts.py` | `TriageResult`, `DecisionResult`, `AuditEvent` (versioned) |
| Decisions | `decision/*` | Rules engine, flags, lifecycle, risk model, PSI drift |
| Retrieval | `rag/*` | Corpus, chunks, embeddings, Postgres search, entitlement filter |
| Copilot | `copilot.py`, `memory.py` | Streamed cited answers; role-aware session memory |
| Tools | `mcp_tools.py` | Calls MCP Case Tools as the human's role |
| Workflow | `workflow/*` | Case state machine, approvals, exactly-once actions, timers, Temporal |
| Records | `audit.py`, `db.py`, `migrations/` | Append-only audit; connections, scratch schemas, migrations |
| Ops | `telemetry.py`, `config.py` | OpenTelemetry setup; all settings from env in one place |

---

## 4. "Where is …?"

| Question | Answer |
|---|---|
| Where are permissions checked? | Three independent places: `auth.require` (API), `workflow/approvals.can_approve` + DB CHECK (SoD), and the SQL `WHERE allowed_roles && …` in `rag/pg.py`. MCP Case Tools checks again in its own `guarded()` |
| Where does the LLM stop and business logic start? | `service.py` step 5: `TriageResult` (model) goes in, `DecisionResult` (rules) comes out |
| How do I change a rule? | Edit `policies/rules.yaml`, bump `version`, add it to `RELEASED` in `tests/unit/test_rules.py`, run `evals/replay.py` |
| How do I change the prompt? | Edit `prompts/triage.v1.md`, bump `version`, update the hash in `tests/unit/test_prompts.py`, run the gate and a shadow run |
| Why did a case get escalated? | `GET /audit?case_id=…` (manager/compliance) → follow `trace_id` into Jaeger |
| What's measured before release? | `evals/run_evals.py`: 7 metrics; thresholds at the top of the file |
| What runs only with credentials? | Live mode (`AGENTOPS_MODE=live`), the LLM judge, and the AWS deploy |

---

## 5. Database tables (one Postgres, by migration)

| Migration | Tables | Notes |
|---|---|---|
| `001_core.sql` | `audit_events`, `approvals` (Phase 0, superseded) | Trigger blocks UPDATE/DELETE on audit |
| `002_decision.sql` | `customers`, `customer_flags`, `transactions`, `decisions` | Flags have a lifetime; one active flag per customer (partial unique index) |
| `003_rag.sql` | `policy_chunks` | Embedding (pgvector, HNSW) + generated `tsvector`; roles on every chunk |
| `004_workflow.sql` | `cases`, `approval_requests`, `actions`, `core_banking_ledger`, `chat_turns` | SoD CHECK; idempotency key is the primary key |

---

## 6. Suggested reading order

1. `service.py` (the whole story), then `guardrails.py` and `router.py`.
2. `agent.py` and `evals/run_evals.py`: how the model is constrained, and how it's measured.
3. `decision/rules.py` + `policies/rules.yaml` + `evals/journeys.yaml`.
4. `rag/pg.py` + `docs/evals/rag-comparison.md`.
5. `workflow/actions.py` + `tests/integration/test_workflow.py::test_s8_kill_mid_action_then_recover_exactly_once`.
6. `docs/adr/` in order. Each ADR is a design discussion you can disagree with.

Every module opens with **LEARNING NOTES**: what it does, why it's built that way, and which failure it prevents.
