"""Retrieval-augmented generation (RAG).

base.py    - the Retriever protocol and the Passage type every retriever returns
corpus.py  - loads synthetic policy documents (data/policies/*.md) and chunks them
memory.py  - in-memory keyword retriever: no database, used by fast unit tests
pg.py      - Phase 2: Postgres keyword (full-text), vector (pgvector) and hybrid search,
             with the entitlement filter applied *inside* the SQL query
embeddings.py - Phase 2: local embedding model (no API key needed)
"""
