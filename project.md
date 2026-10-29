# Projects – Mathiyazhagan Arumugam

Two small, tested repositories that demonstrate the operational layer around AI agents in a regulated setting. GitHub: https://github.com/madhy-git

---

## 1. AgentOps Platform
**Repo:** https://github.com/madhy-git/agentops-platform
**Stack:** Python, FastAPI, PydanticAI, OpenTelemetry, pytest, Docker, GitHub Actions

**Problem.** An agent that triages banking customer messages is easy to demo and hard to run safely. This project builds the controls around it: what goes in, which model runs, who approves risky actions, and how quality is gated before release.

**Flow**
```
message -> PII redaction -> prompt-injection check -> cost-aware model router
        -> PydanticAI agent (tools: lookup_case, search_policy with citations)
        -> typed TriageResult -> human-in-the-loop gate -> audit log
        (every step traced with OpenTelemetry)
```

**Key design decisions**
| Decision | Why |
|---|---|
| Model router picks the cheapest model whose capability tier covers the task, with a budget cap and fallback chain | Most messages are simple; frontier models are reserved for high-risk cases (hardship, fraud, disputes) |
| Fraud, hardship, dispute and complaint outcomes always need human approval | Regulated decisions need a person accountable; the agent only recommends |
| Read-only tools are always allowed; anything that changes state needs approval | Least privilege for agent tools |
| Retriever sits behind a protocol | Keyword retriever today; LlamaIndex/pgvector can replace it without touching the agent |
| Evals run as a CI gate (category accuracy, escalation recall, injection block rate) | A prompt or model change cannot ship if safety-critical recall drops |

**Results.** 13 tests pass. The eval gate passes on a 12-case golden set. CI runs tests plus the gate on every push.

**Limits (be upfront).**
- Default mode uses a deterministic offline model so CI needs no API keys. Its eval scores prove the pipeline and gate, not model quality. Run `AGENTOPS_MODE=live` with provider credentials for real quality numbers.
- In-memory approval and audit stores; no persistence yet.

**Next steps.** LlamaIndex + pgvector retriever; LiteLLM gateway; durable approvals on Temporal; persistent audit store; Terraform for EKS/AKS; benchmark against the OpenAI Agents SDK and Google ADK.

**Demo (60 seconds).** `uvicorn agentops.api:app`, then POST a stolen-card message: show the PII redaction, the routed model, the `pending_approval` status, then approve it via `/approvals/{id}/decision` and show `/audit`.

---

## 2. MCP Case Tools
**Repo:** https://github.com/madhy-git/mcp-case-tools
**Stack:** Python, Model Context Protocol (MCP) server, pytest, GitHub Actions

**Problem.** AI assistants need access to case and workflow data, but they must not be able to do more than the person using them. This server exposes case capabilities as MCP tools with the controls a regulator expects.

**Tools:** `get_case`, `search_cases`, `add_note`, `progress_case`; resource `audit://log`.

**Controls**
| Control | How |
|---|---|
| Least-privilege roles | `viewer` (read), `officer` (read, write), `manager` (read, write, approve) |
| Enforced workflow | `new -> assessment -> compliance_review -> enforcement -> closed`; invalid transitions rejected |
| Human approval for high impact | Moving to enforcement needs a manager with the approve scope |
| Audit trail | Every call is logged, allowed or denied, with role, tool and reason |

**Results.** 5 tests pass using an in-memory MCP client.

**Limits.** Seed data is in memory and the role comes from an environment variable. Production would use a real case store and OAuth/OIDC claims for identity.

**Tie to experience.** Mirrors how case and workflow capabilities were exposed to AI assistants on the ACRES platform at the Aged Care Quality and Safety Commission, where human approval was kept on regulatory decisions.

---

## Interview talking points
- **Why a router?** Cost and latency. Show the tier logic and the fallback chain, and say what you would measure in live mode (cost per resolved case, escalation rate).
- **How do you stop an agent doing something unsafe?** Read-only tools by default, approval for state changes, injection checks on input, and an audit log you can replay.
- **How do you know a change is safe to ship?** The eval gate. Name the three metrics and why escalation recall has a threshold of 1.0.
- **What would you do next?** Run the golden set against real models, add persistence and durable approvals, and grow the eval set from real failures.