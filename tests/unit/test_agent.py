from agentops.agent import Deps, build_agent, offline_model
from agentops.rag import KeywordRetriever


def run(text: str):
    return build_agent(offline_model()).run_sync(text, deps=Deps(KeywordRetriever()))


def test_confidence_is_bounded_and_higher_when_a_rule_matches():
    fraud, general = run("my card was stolen").output, run("what are your fees?").output
    assert 0 <= general.confidence < fraud.confidence <= 1


def test_case_lookup_flags_vulnerable_customer():
    r = run("Question about case C-1002: how do I download my statement?")
    called = [p.tool_name for m in r.all_messages() for p in m.parts if getattr(p, "part_kind", "") == "tool-call"]
    assert "lookup_case" in called
    assert r.output.category == "general" and r.output.needs_human and r.output.recommended_action == "escalate"


def test_non_vulnerable_case_does_not_escalate():
    assert not run("Question about case C-1001: how do I download my statement?").output.needs_human
