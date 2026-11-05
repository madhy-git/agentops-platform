"""Phase 4: the agent consumes MCP Case Tools; identity flows through to the MCP layer."""

import pytest

pytest.importorskip("mcp_case_tools", reason="sibling repo not installed (uv pip install -e ../mcp-case-tools)")

from agentops.agent import Deps, build_agent, offline_model  # noqa: E402
from agentops.mcp_tools import mcp_case_lookup, mcp_role  # noqa: E402
from agentops.rag.memory import KeywordRetriever  # noqa: E402
from agentops.service import TriageService  # noqa: E402


def test_role_mapping_picks_the_strongest_known_role():
    assert mcp_role(frozenset({"officer", "fraud_specialist"})) == "fraud_specialist"
    assert mcp_role(frozenset({"compliance"})) == "viewer"


def test_agent_lookup_case_goes_through_mcp_as_the_user():
    lookup = mcp_case_lookup("officer-1", frozenset({"officer"}))
    run = build_agent(offline_model()).run_sync(
        "Question about WB-1001 please", deps=Deps(KeywordRetriever(), case_lookup=lookup)
    )
    tool_returns = [
        p.content
        for m in run.all_messages()
        for p in m.parts
        if p.part_kind == "tool-return" and p.tool_name == "lookup_case"
    ]
    assert any(isinstance(r, dict) and r.get("summary", "").startswith("Card reported stolen") for r in tool_returns)
    ev = lookup.audit.events[-1]
    assert ev["tool"] == "get_case" and ev["user"] == "officer-1" and ev["role"] == "officer" and ev["allowed"]


def test_triage_uses_mcp_when_configured(conn, monkeypatch):
    monkeypatch.setenv("AGENTOPS_CASE_SOURCE", "mcp")
    o = TriageService(conn).triage("update on WB-1003 please", actor="officer-1")
    assert o.status in {"completed", "pending_approval"}  # pipeline ran end to end with the MCP case source
