-- Phase 8b: a large knowledge base (~100k chunks) for vector search at a scale where indexes and filters matter.
-- Separate from policy_chunks: that table is the small, curated corpus the copilot answers from; this one is a
-- big synthetic corpus to search, benchmark and learn from (rag/kb.py).

CREATE TABLE kb_chunks (
    id             BIGSERIAL PRIMARY KEY,
    doc_id         TEXT NOT NULL,
    chunk_no       INT NOT NULL,
    doc_type       TEXT NOT NULL,            -- product_terms | fee_schedule | faq | procedure | case_note | ...
    product        TEXT,                     -- e.g. "Low Rate credit card"; NULL for bank-wide documents
    title          TEXT NOT NULL,
    classification TEXT NOT NULL,            -- public | internal | restricted | confidential
    allowed_roles  TEXT[] NOT NULL,          -- same entitlement model as policy_chunks
    published      DATE NOT NULL,
    content        TEXT NOT NULL,
    embedding      vector(384),
    tsv            tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED,
    UNIQUE (doc_id, chunk_no)
);

-- LEARNING NOTE: no HNSW index here. Building it AFTER the bulk load is several times faster than updating it
-- on every insert, so the loader creates it (rag/kb.py: build_index). Same reason data warehouses drop indexes
-- before a big load. The filter indexes are cheap, so they exist from the start.
CREATE INDEX kb_chunks_roles ON kb_chunks USING gin (allowed_roles);
CREATE INDEX kb_chunks_tsv ON kb_chunks USING gin (tsv);
CREATE INDEX kb_chunks_type_product ON kb_chunks (doc_type, product);
