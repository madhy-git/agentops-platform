-- Phase 0: audit log and (naive) approvals.

-- AUDIT LOG ---------------------------------------------------------------
-- LEARNING NOTE: an audit log you can edit is not an audit log. The trigger below makes the
-- table append-only *in the database*, so even a bug or a careless admin script cannot UPDATE
-- or DELETE history. (Earlier, with SQLite, "append-only" was only a convention.)
CREATE TABLE audit_events (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    event          TEXT NOT NULL,          -- one of contracts.AuditEventType
    schema_version TEXT NOT NULL,          -- version of the AuditEvent contract that wrote it
    trace_id       TEXT,                   -- joins the audit row to its OpenTelemetry trace
    case_id        TEXT,
    actor          TEXT NOT NULL,          -- user id, or "system" / "agent"
    reason_code    TEXT,                   -- e.g. FRAUD_SUSPECTED (Phase 1 rules)
    policy_version TEXT,                   -- which rules.yaml version made the decision
    prompt_version TEXT,                   -- which prompt version the model saw
    data           JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_events_case_idx ON audit_events (case_id, id);

CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

-- APPROVALS (naive, Phase 0) ----------------------------------------------
-- Phase 4 replaces this with a full case state machine (migration 004). Kept simple here so the
-- jump from "status column" to "state machine with timers" is visible in the history.
CREATE TABLE approvals (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    case_text       TEXT NOT NULL,          -- already PII-redacted
    proposed_action TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewer        TEXT,
    decided_at      TIMESTAMPTZ
);
