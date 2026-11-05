-- Phase 4: cases, approval requests with SLAs, idempotent actions, session memory.
-- Replaces the naive `approvals` table from 001 (kept for history; no longer written).

-- CASES ---------------------------------------------------------------------
-- LEARNING NOTE: the allowed transitions live in Python (workflow/cases.py) so they're unit-
-- testable, but the CHECK constraint stops any code path writing a state that doesn't exist.
CREATE TABLE cases (
    id           BIGSERIAL PRIMARY KEY,
    customer_id  TEXT,
    state        TEXT NOT NULL CHECK (state IN ('new','in_progress','pending_approval','approved','rejected',
                                                'actioned','resolved','closed','escalated','reopened')),
    queue        TEXT NOT NULL,
    priority     TEXT NOT NULL,
    summary      TEXT NOT NULL,            -- PII-redacted
    decision_id  BIGINT REFERENCES decisions,
    created_by   TEXT NOT NULL,
    assigned_to  TEXT,
    created_at   TIMESTAMPTZ NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL
);

-- APPROVAL REQUESTS -----------------------------------------------------------
CREATE TABLE approval_requests (
    id            BIGSERIAL PRIMARY KEY,
    case_id       BIGINT NOT NULL REFERENCES cases,
    decision_id   BIGINT NOT NULL REFERENCES decisions,   -- no approval without a decision record
    action        TEXT NOT NULL,
    domain        TEXT NOT NULL,                          -- fraud | hardship | disputes | complaints | general
    requested_by  TEXT NOT NULL,
    assigned_to   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at    TIMESTAMPTZ NOT NULL,
    sla_due       TIMESTAMPTZ NOT NULL,
    reminded_at   TIMESTAMPTZ,                            -- set once at 50% of SLA (idempotent timer)
    escalated_at  TIMESTAMPTZ,                            -- set once at 100% of SLA
    decided_by    TEXT,
    decided_at    TIMESTAMPTZ,
    reason        TEXT,
    seeded_bad    BOOLEAN NOT NULL DEFAULT false,         -- oversight drill: a deliberately wrong proposal
    -- Separation of duties, enforced by the database as well as by code.
    CONSTRAINT requester_cannot_approve CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE INDEX approval_requests_open ON approval_requests (status, sla_due) WHERE status = 'pending';

-- ACTIONS (idempotent execution) -----------------------------------------------
-- LEARNING NOTE: the idempotency key is the PRIMARY KEY. Retrying an action (network blip, worker
-- restart, double click) can't create a second row, so it can't run the side effect twice.
-- status 'started' with no finished_at after a crash = "unknown state", resolved by workflow.recover().
CREATE TABLE actions (
    idempotency_key TEXT PRIMARY KEY,
    case_id         BIGINT NOT NULL REFERENCES cases,
    approval_id     BIGINT REFERENCES approval_requests,
    action          TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('started','succeeded','failed')),
    result          TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ
);

-- Stand-in for the core-banking system. A real downstream API would honour the same idempotency
-- key; modelling it as a table with a UNIQUE key lets the crash test (S8) prove no duplicates.
CREATE TABLE core_banking_ledger (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    action          TEXT NOT NULL,
    customer_id     TEXT,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- SESSION MEMORY (copilot) ------------------------------------------------------
-- Each turn stores which roles may read it, derived from the chunks it used. When memory is read
-- back, turns the *current* caller can't read are skipped: memory is a leak path like any other.
CREATE TABLE chat_turns (
    id            BIGSERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    speaker       TEXT NOT NULL CHECK (speaker IN ('user', 'assistant')),
    content       TEXT NOT NULL,          -- PII-redacted
    allowed_roles TEXT[] NOT NULL,        -- who may see this turn again
    sources       TEXT[] NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX chat_turns_session ON chat_turns (session_id, id);
