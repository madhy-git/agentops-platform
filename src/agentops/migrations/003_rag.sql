-- Phase 2: policy chunks for keyword, vector and hybrid retrieval.

-- LEARNING NOTES
-- - classification and allowed_roles live ON EACH CHUNK. The entitlement filter is a WHERE clause
--   in the same query that ranks, so restricted rows are never candidates (see rag/pg.py).
-- - `tsv` is a *generated* column: Postgres keeps the full-text index in sync with content, so
--   keyword search can never drift from what's stored.
-- - HNSW is an approximate nearest-neighbour index: much faster than scanning every vector, at the
--   cost of occasionally missing the true nearest one. Irrelevant at 30 chunks; essential at 3M.
CREATE TABLE policy_chunks (
    id             BIGSERIAL PRIMARY KEY,
    doc_id         TEXT NOT NULL,
    chunk_no       INT NOT NULL,
    title          TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('public', 'internal', 'restricted', 'confidential')),
    allowed_roles  TEXT[] NOT NULL,
    doc_version    TEXT,
    chunk_size     INT NOT NULL,          -- the max_chars this chunking used (for the size sweep)
    content        TEXT NOT NULL,
    embedding      vector(384),
    tsv            tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED,
    UNIQUE (chunk_size, doc_id, chunk_no)
);
CREATE INDEX policy_chunks_tsv ON policy_chunks USING gin (tsv);
CREATE INDEX policy_chunks_embedding ON policy_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX policy_chunks_roles ON policy_chunks USING gin (allowed_roles);
