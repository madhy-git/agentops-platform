# Runbook: model provider outage

<!-- LEARNING NOTE: a runbook is for 3 a.m. Short steps, real commands, clear exits. -->

**Symptoms:** `model_failed` audit events spike; `agent.run` spans show errors; p95 triage latency jumps; cost per case rises (fallback to a pricier tier).

**Automatic behaviour:** the fallback chain moves *up* a tier, and the circuit breaker (`resilience.py`) stops sending traffic to the failing tier after 3 consecutive failures, probing again every 30 s.

1. Confirm scope: which alias is failing?
   ```sql
   SELECT data->>'model' AS model, count(*) FROM audit_events
   WHERE event = 'model_failed' AND ts > now() - interval '15 minutes' GROUP BY 1;
   ```
2. Check the provider's status page, and the LiteLLM logs (`docker compose logs litellm`).
3. If one tier is down for more than 15 minutes, point its alias at another provider in `deploy/litellm/config.yaml` and restart LiteLLM. No app deploy is needed.
4. If *all* tiers are down: triage stops. Messages are not lost (the client gets a 5xx and retries). Tell contact-centre leads to triage manually. **Never** switch on automatic approvals as a workaround.
5. Watch cost: fallback to tier 3 costs about +70% (`docs/evals/baseline-offline.md`). If it's sustained, cap with `budget_tier` and accept slower handling of high-risk cases.

**Exit:** `model_failed` back to baseline for 30 minutes; the breaker is closed (no `circuit_open: true` in recent events).
