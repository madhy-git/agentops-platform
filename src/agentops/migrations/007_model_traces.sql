-- Phase 8c: the AI decision trail. One row per triage: exactly what was sent to the model and what came back,
-- next to what the rules then decided. Staff-only (API: GET /cases/{id}/ai-trail).
--
-- LEARNING NOTES
-- - "What did the model see?" is the first question in any AI incident review, and the hardest to answer later:
--   prompts change (versioned), retrieval results change (the corpus changes), models change (the gateway).
--   So the trail stores the conversation AS SENT (after PII redaction), not a reconstruction.
-- - Append-only, like audit_events, for the same reason: it is evidence.
-- - Data minimisation: only the redacted text is stored. The raw message (with the phone number) never is.

CREATE TABLE model_traces (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    case_id         BIGINT REFERENCES cases,
    actor           TEXT NOT NULL,
    trace_id        TEXT,                    -- joins to the OpenTelemetry trace (and audit_events.trace_id)
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,           -- tier alias that answered, e.g. agentops-tier3 or offline-rules
    route_reason    TEXT,
    failed_models   JSONB NOT NULL DEFAULT '[]',
    redacted_input  TEXT NOT NULL,           -- the message as the model received it
    redactions      JSONB NOT NULL DEFAULT '{}',
    messages        JSONB NOT NULL,          -- full PydanticAI conversation: instructions, tool calls, tool results
    output          JSONB NOT NULL,          -- the validated TriageResult, including the model's rationale
    decision        JSONB,                   -- what the rules decided on top (reason codes, actions, approval)
    input_tokens    INT,
    output_tokens   INT,
    cost_usd        NUMERIC(12, 6),
    latency_ms      NUMERIC(10, 1)
);
CREATE INDEX model_traces_case_idx ON model_traces (case_id, id);

CREATE FUNCTION model_traces_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'model_traces is append-only (% blocked)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER model_traces_no_update_delete
    BEFORE UPDATE OR DELETE ON model_traces
    FOR EACH ROW EXECUTE FUNCTION model_traces_append_only();
