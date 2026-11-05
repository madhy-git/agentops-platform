"""Phase 7: offline, both framework adapters must agree on every golden case (same stand-in rules).
A disagreement is an adapter bug, like the missing case-lookup node the first benchmark run exposed."""

import json

import pytest

pytest.importorskip("langgraph", reason="uv sync --extra bench")

from agentops.config import REPO_ROOT  # noqa: E402
from benchmarks.adapters import LangGraphAdapter, PydanticAIAdapter  # noqa: E402


def test_adapters_agree_on_every_golden_case():
    rows = [json.loads(line) for line in (REPO_ROOT / "evals" / "golden.jsonl").read_text().splitlines()]
    pa, lg = PydanticAIAdapter(), LangGraphAdapter()
    for r in (r for r in rows if not r.get("blocked")):
        a, b = pa.triage(r["input"]).output, lg.triage(r["input"]).output
        assert (a.category, a.needs_human, a.recommended_action) == (b.category, b.needs_human, b.recommended_action), r
