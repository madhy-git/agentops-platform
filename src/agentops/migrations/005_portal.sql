-- Phase 8: self-service portal.

-- What corpus is loaded, per chunk size. ensure_ingested() re-ingests when the policy files change.
-- LEARNING NOTE: before this, ingestion ran only when policy_chunks was EMPTY, so editing a policy (say, removing
-- a role from allowed_roles) never reached a database that already had chunks. An entitlement change that
-- silently doesn't apply is a data leak waiting to happen. Found while adding the "customer" role to the FAQ.
CREATE TABLE corpus_fingerprints (
    chunk_size   INT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,          -- sha256 over every chunk's text, roles and classification
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Customers list their own cases on every portal page load.
CREATE INDEX cases_customer_idx ON cases (customer_id, id DESC);
