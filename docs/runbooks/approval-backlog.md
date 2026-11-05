# Runbook: approval backlog

**Symptoms:** many `approval_reminder` / `approval_escalated` events; pending approvals past `sla_due`.

1. Size it:
   ```sql
   SELECT domain, assigned_to, count(*), min(sla_due) FROM approval_requests
   WHERE status = 'pending' GROUP BY 1, 2 ORDER BY 3 DESC;
   ```
2. Is the timer worker running? (`python -m agentops.workflow.timers`). No reminders at all usually means it's stopped. Restart it; it's idempotent and resumes where it left off.
3. Reassign by domain to available specialists (managers can approve any domain).
4. **Never** bulk-approve to clear the queue. A timeout escalates; it never approves. That is a regulatory control, not a performance problem.
5. Afterwards, check the oversight report (`evals/oversight.py report`) for rubber-stamping during the catch-up.
