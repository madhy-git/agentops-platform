"""Phase 2: identity-aware retrieval on Postgres. One test per leak path built so far.

Leak paths (project.md "Entitlement leakage"): vector search, cache, citations, (reranker: none
built), memory (Phase 4: tests/integration/test_copilot.py).
"""

import pytest

from agentops.audit import AuditLog
from agentops.rag.pg import PgRetriever, ingest
from agentops.service import TriageService


@pytest.fixture
def rconn(conn):
    ingest(conn)
    return conn


def docs(passages):
    return {p.source.split("#")[0] for p in passages}


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_s3_officer_never_gets_restricted_hardship_options(rconn, mode):
    r = PgRetriever(rconn, mode=mode)
    q = "what hardship arrangement options can we offer, repayment pause or fee waiver?"
    assert "POL-HARD-01" not in docs(r.search(q, roles={"officer"}, k=10))
    assert "POL-HARD-01" in docs(r.search(q, roles={"hardship_specialist"}, k=10))


def test_filtered_retrieval_is_audited_with_counts_only(rconn):
    audit = AuditLog(rconn)
    PgRetriever(rconn, audit=audit).search("hardship repayment pause options", roles={"officer"})
    ev = [e for e in audit.events() if e["event"] == "retrieval_filtered"]
    assert ev and ev[0]["data"]["hidden_chunks"] >= 1
    assert "pause" not in str(ev[0]["data"])  # the count, never the content


def test_cache_is_keyed_by_roles(rconn):
    r = PgRetriever(rconn)
    q = "goodwill compensation team leader approval"
    assert "POL-COMP-01" in docs(r.search(q, roles={"manager"}, k=10))  # manager warms the cache...
    assert "POL-COMP-01" not in docs(r.search(q, roles={"officer"}, k=10))  # ...officer must not hit it


def test_citations_only_reference_documents_the_caller_can_see(rconn):
    svc = TriageService(rconn, retriever=PgRetriever(rconn))
    o = svc.triage("I lost my job and need a repayment pause", roles=frozenset({"officer"}))
    assert o.result.citations and not any(
        c.startswith(("POL-HARD", "POL-COMP", "POL-FRAUD-02")) for c in o.result.citations
    )


def test_vector_search_finds_paraphrase_keyword_search_misses(rconn):
    q = "a caller pretended to be from the bank"
    assert "POL-FRAUD-01" in docs(PgRetriever(rconn, mode="vector").search(q, roles={"officer"}))


def test_planted_instruction_never_reaches_the_agent_via_pg(rconn):
    svc = TriageService(rconn, retriever=PgRetriever(rconn))
    o = svc.triage("why are card refunds slow during vendor maintenance?")
    assert not any(c.startswith("POL-VEND") for c in o.result.citations)
