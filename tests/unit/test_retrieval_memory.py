"""Entitlement filtering and indirect injection on the in-memory retriever (no database)."""

from agentops.agent import Deps, build_agent, offline_model
from agentops.guardrails import scan_retrieved
from agentops.rag.corpus import load_chunks
from agentops.rag.memory import KeywordRetriever


def test_chunks_carry_document_metadata():
    chunks = load_chunks()
    hardship = [c for c in chunks if c.doc_id == "POL-HARD-01"]
    assert hardship and all(c.classification == "restricted" for c in hardship)
    assert all("hardship_specialist" in c.allowed_roles for c in hardship)


def test_officer_cannot_retrieve_restricted_hardship_options():
    r = KeywordRetriever()
    officer = r.search("hardship repayment pause options", roles={"officer"}, k=10)
    specialist = r.search("hardship repayment pause options", roles={"officer", "hardship_specialist"}, k=10)
    assert not any(p.source.startswith("POL-HARD-01") for p in officer)
    assert any(p.source.startswith("POL-HARD-01") for p in specialist)


def test_public_faq_visible_to_any_staff():
    assert KeywordRetriever().search("statements download", roles=set())[0].source.startswith("POL-FAQ-01")


def test_planted_instruction_is_detected_in_retrieved_text():
    planted = [c for c in load_chunks() if c.doc_id == "POL-VEND-01" and scan_retrieved(c.text)]
    assert len(planted) == 1  # exactly one chunk is flagged; see the trade-off note below


def test_agent_never_sees_planted_passage():
    run = build_agent(offline_model()).run_sync("card refunds maintenance bulletin", deps=Deps(KeywordRetriever()))
    tool_text = str([p.content for m in run.all_messages() for p in m.parts if p.part_kind == "tool-return"])
    assert "ignore all previous instructions" not in tool_text.lower()
    # TRADE-OFF made visible: the guard drops the whole *chunk*, so the legitimate maintenance notice
    # that shares the chunk is lost too. Smaller chunks (Phase 2 sweep) or sentence-level stripping
    # would keep it, at the cost of more retrieval noise. Precision vs. safety, decided on purpose.
    assert "POL-VEND-01" not in tool_text and "five business days" not in tool_text
