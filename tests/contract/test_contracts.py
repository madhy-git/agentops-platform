"""Contract tests: the code's schemas must match the committed contracts/*.schema.json.

If this fails you changed a contract. Decide whether the change is compatible, bump the model's
schema_version, then regenerate: `uv run python -m agentops.contracts`. The diff in your PR is
the reviewable record of the contract change.
"""

import json

import pytest

from agentops.contracts import CONTRACTS, SCHEMA_DIR, AuditEvent, TriageResult


@pytest.mark.parametrize("name", CONTRACTS)
def test_schema_matches_committed_contract(name):
    committed = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    assert CONTRACTS[name].model_json_schema() == committed


def test_triage_result_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        TriageResult(
            category="general",
            severity="low",
            summary="x",
            recommended_action="answer",
            needs_human=False,
            confidence=1.3,
        )


def test_audit_event_rejects_unknown_event_type():
    with pytest.raises(ValueError):
        AuditEvent(event="approval_aproved")  # typo: would silently create an event nobody queries
