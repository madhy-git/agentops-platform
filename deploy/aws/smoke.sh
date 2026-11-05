#!/usr/bin/env bash
# Post-deploy smoke test: health, then an authenticated call must be rejected without a token.
set -euo pipefail
HOST=$(kubectl -n agentops get ingress agentops-api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
for _ in $(seq 1 30); do curl -sfk "https://$HOST/health" && break; sleep 10; done
code=$(curl -sk -o /dev/null -w '%{http_code}' -X POST "https://$HOST/triage" -H 'content-type: application/json' -d '{"message":"hi"}')
[[ "$code" == "401" ]] || { echo "expected 401 without a token, got $code"; exit 1; }
echo "smoke test passed: $HOST"
