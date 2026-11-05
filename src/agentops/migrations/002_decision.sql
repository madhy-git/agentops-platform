-- Phase 1: customers, flags, transactions and the decision log.

CREATE TABLE customers (
    customer_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    vulnerable      BOOLEAN NOT NULL DEFAULT false,
    features        JSONB NOT NULL DEFAULT '{}'   -- inputs to the risk model (decision/risk.py)
);

-- FLAGS ---------------------------------------------------------------------
-- LEARNING NOTE: flags are *rows with a lifetime*, never a boolean column that gets overwritten.
-- Setting inserts a row; clearing stamps cleared_at/cleared_by. History is kept, so you can answer
-- "was marketing suppressed for this customer on 3 March, and who lifted it?".
CREATE TABLE customer_flags (
    id             BIGSERIAL PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers,
    flag           TEXT NOT NULL,
    set_at         TIMESTAMPTZ NOT NULL,
    set_by         TEXT NOT NULL,
    reason_code    TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    cleared_at     TIMESTAMPTZ,
    cleared_by     TEXT
);
-- At most one *active* instance of a flag per customer (partial unique index).
CREATE UNIQUE INDEX one_active_flag ON customer_flags (customer_id, flag) WHERE cleared_at IS NULL;

CREATE TABLE transactions (
    txn_id      TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers,
    txn_date    DATE NOT NULL,
    merchant    TEXT NOT NULL,
    amount      NUMERIC(12, 2) NOT NULL
);

-- DECISION LOG ---------------------------------------------------------------
-- Every rules evaluation, with its full input context and result. "No action can run without
-- a decision record" (Phase 1 done-when) is enforced by foreign keys from approvals/actions.
CREATE TABLE decisions (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL,
    customer_id    TEXT REFERENCES customers,
    context        JSONB NOT NULL,
    result         JSONB NOT NULL,
    policy_version TEXT NOT NULL
);

ALTER TABLE approvals ADD COLUMN decision_id BIGINT REFERENCES decisions;
