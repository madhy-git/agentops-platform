"""Data contracts: the versioned shapes that cross a boundary.

LEARNING NOTES
- A *contract* is any structure another component, team or stored row depends on: the model's
  structured output, the decision service's result, an audit event. Changing one silently is how
  dashboards, replays and downstream consumers break.
- Each contract has a SCHEMA_VERSION. `contracts/*.schema.json` holds the committed JSON Schema;
  tests/contract/test_contracts.py fails if the code drifts from it. To change a contract you must
  regenerate the file (`uv run python -m agentops.contracts`) and bump the version on purpose.
- Rule of thumb: adding an optional field = minor bump; removing/renaming/tightening = major bump.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import REPO_ROOT

# --- Triage (LLM structured output) ------------------------------------------------------------

Category = Literal["hardship", "dispute", "fraud", "complaint", "general"]
Action = Literal["answer", "escalate", "refund_review", "freeze_card", "hardship_review"]


class TriageResult(BaseModel):
    """What the agent must return. Validation failure => PydanticAI asks the model to retry."""

    schema_version: Literal["1.1"] = "1.1"
    category: Category
    severity: Literal["low", "medium", "high"]
    summary: str = Field(max_length=300)
    recommended_action: Action
    needs_human: bool
    # Bounded: a model claiming 1.3 confidence fails validation instead of polluting metrics.
    confidence: float = Field(ge=0.0, le=1.0, description="Model's own confidence in the category, 0-1")
    citations: list[str] = Field(default_factory=list)


# --- Decision service (deterministic, Phase 1) --------------------------------------------------


class DecisionResult(BaseModel):
    """What the *rules* decided. The LLM recommends; this authorises (project.md design rationale)."""

    schema_version: Literal["1.0"] = "1.0"
    decision_id: int | None = None
    customer_id: str | None
    queue: str
    priority: Literal["low", "normal", "high", "urgent"]
    reason_codes: list[str]
    actions: list[str]  # actions the rules allow or require, e.g. ["block_card"]
    needs_approval: bool
    flags_set: list[str] = Field(default_factory=list)
    suppressed_actions: list[str] = Field(default_factory=list)  # e.g. marketing removed by R7
    candidate_actions: list[str] = Field(default_factory=list)  # ranked next-best-actions (UC7)
    policy_version: str


# --- Audit -------------------------------------------------------------------------------------

# The full event vocabulary from project.md. A typo'd event name fails validation instead of
# silently creating an event nobody queries.
AuditEventType = Literal[
    "message_received",
    "pii_redacted",
    "injection_blocked",
    "triaged",
    "model_failed",
    "decision_made",
    "flag_set",
    "flag_cleared",
    "retrieval_filtered",
    "approval_requested",
    "approval_reminder",
    "approval_escalated",
    "approval_decided",
    "action_executed",
    "action_denied",
    "case_state_changed",
    "case_closed",
    "copilot_answered",
    "dev_login",
    "misuse_refused",  # copilot declined a "how do I get around the bank's controls" question (guardrails.detect_misuse)  # demo sign-in on the web app (personas.py); never available with a real identity provider
]


class AuditEvent(BaseModel):
    # 1.1: added "dev_login". 1.2: added "misuse_refused". Both additive: older rows stay valid.
    schema_version: Literal["1.2"] = "1.2"
    event: AuditEventType
    actor: str = "system"
    ts: datetime | None = None  # set by the database on insert
    trace_id: str | None = None
    case_id: str | None = None
    reason_code: str | None = None
    policy_version: str | None = None
    prompt_version: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


CONTRACTS: dict[str, type[BaseModel]] = {
    "TriageResult": TriageResult,
    "DecisionResult": DecisionResult,
    "AuditEvent": AuditEvent,
}
SCHEMA_DIR = REPO_ROOT / "contracts"


def write_schemas() -> None:
    """Regenerate contracts/*.schema.json. Run deliberately when you change a contract."""
    SCHEMA_DIR.mkdir(exist_ok=True)
    for name, model in CONTRACTS.items():
        (SCHEMA_DIR / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")


if __name__ == "__main__":
    write_schemas()
