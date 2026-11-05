# Runbook: suspected data leak (restricted policy or PII shown to the wrong person)

1. **Contain:** if retrieval is implicated, set `AGENTOPS_POLICY_FILE` / disable the copilot route at the gateway. Preserve evidence: the audit log is append-only, so don't try to "clean" it.
2. **Scope with the audit trail:**
   ```sql
   SELECT * FROM audit_events WHERE event IN ('copilot_answered', 'retrieval_filtered')
   AND ts > now() - interval '7 days' ORDER BY id;
   ```
   Join `trace_id` to traces for the exact passages served.
3. Check each leak path: SQL filter (`rag/pg.py`), cache key (must include roles), citations, session memory (`chat_turns.allowed_roles`).
4. Add the failing case to `evals/rag_questions.yaml` `leak_probes` *before* fixing, so the fix is proven by a test.
5. Escalate to privacy/compliance per policy. Customer PII exposure may be notifiable.
