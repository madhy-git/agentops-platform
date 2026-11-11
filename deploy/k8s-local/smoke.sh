#!/usr/bin/env bash
# End-to-end check of the local deployment: the README demo plus the web app, run against the cluster, with assertions.
#   deploy/k8s-local/smoke.sh
#
# LEARNING NOTES
# - "Pods are Running" is not "it works". This drives a real request through every layer in the cluster:
#   JWT auth -> PII redaction -> agent -> rules -> case -> approval routing -> exactly-once action -> audit,
#   plus the negative paths (no token, wrong role), which are the ones that matter in a regulated system.
# - Tokens are minted with the cluster's own JWT secret, read from the Secret, so a token from your laptop's
#   dev setup (default secret) is rejected here. That's checked too.
set -euo pipefail
CTX="${KUBE_CONTEXT:-docker-desktop}"
NS=agentops
PORT="${PORT:-18000}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
k() { kubectl --context "$CTX" "$@"; }

k -n "$NS" port-forward svc/agentops-api "$PORT:80" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf "localhost:$PORT/health" >/dev/null && break; sleep 1; done
URL="http://localhost:$PORT"

SECRET=$(k -n "$NS" get secret agentops-secrets -o jsonpath='{.data.AGENTOPS_JWT_SECRET}' | base64 -d)
mint() { (cd "$ROOT" && AGENTOPS_JWT_SECRET="$SECRET" uv run --quiet python -c \
  "import sys; from agentops.auth import dev_token; print(dev_token(sys.argv[1], sys.argv[2].split(',')))" "$1" "$2"); }
OFFICER=$(mint officer-1 officer)
FRAUD1=$(mint fraud-1 officer,fraud_specialist)
FRAUD2=$(mint fraud-2 officer,fraud_specialist)
MGR=$(mint manager-1 manager)
WRONG=$(cd "$ROOT" && AGENTOPS_JWT_SECRET=not-the-cluster-secret-but-32-bytes-long uv run --quiet python -c \
  "from agentops.auth import dev_token; print(dev_token('officer-1', ['officer']))")

pass=0
check() {  # check <description> <expected> <actual>
  if [[ "$2" == "$3" ]]; then echo "  ok   $1"; pass=$((pass + 1)); else echo "  FAIL $1: expected '$2', got '$3'" >&2; exit 1; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post() { curl -sf "$URL$1" -H "Authorization: Bearer $2" -H 'content-type: application/json' -d "$3"; }

echo "== negative paths"
check "no token is rejected"                401 "$(code -X POST "$URL/triage" -H 'content-type: application/json' -d '{"message":"hi"}')"
check "token signed with another secret"    401 "$(code "$URL/me" -H "Authorization: Bearer $WRONG")"
check "officer cannot read the audit trail" 403 "$(code "$URL/audit" -H "Authorization: Bearer $OFFICER")"

echo "== S1 stolen card"
T=$(post /triage "$OFFICER" '{"message":"My card was stolen at the airport, call me on 0411 821 692"}')
check "phone number redacted"        1                "$(echo "$T" | json 'd["redactions"].get("PHONE")')"
check "R1 fired (FRAUD_SUSPECTED)"    True             "$(echo "$T" | json '"FRAUD_SUSPECTED" in d["decision"]["reason_codes"]')"
check "waits for a human"            pending_approval "$(echo "$T" | json 'd["status"]')"
AID=$(echo "$T" | json 'd["approval_id"]')
# Routing is least-loaded across the fraud roster, so which specialist gets it depends on who has pending work
# (e.g. cases you created in the UI). Assert it reached exactly one of them, then act as that person.
in_queue() { curl -sf "$URL/approvals/mine" -H "Authorization: Bearer $1" | json "any(a['id'] == $AID for a in d)"; }
Q1=$(in_queue "$FRAUD1"); Q2=$(in_queue "$FRAUD2")
check "routed to exactly one fraud specialist" True "$([[ "$Q1" != "$Q2" ]] && echo True || echo False)"
if [[ "$Q1" == True ]]; then FRAUD=$FRAUD1; else FRAUD=$FRAUD2; fi
check "officer cannot approve"       403 "$(code "$URL/approvals/$AID/decision" -H "Authorization: Bearer $OFFICER" -H 'content-type: application/json' -d '{"approve":true}')"
D=$(post "/approvals/$AID/decision" "$FRAUD" '{"approve":true}')
check "specialist approves"          approved "$(echo "$D" | json 'd["status"]')"
check "deciding twice is refused"    409 "$(code "$URL/approvals/$AID/decision" -H "Authorization: Bearer $FRAUD" -H 'content-type: application/json' -d '{"approve":true}')"

echo "== S3 restricted policy"
C=$(post /copilot "$OFFICER" '{"question":"What hardship arrangement options can we offer?"}')
check "officer referred, not told"   True "$(echo "$C" | json 'd["referred_to"] is not None and not d["sources"]')"

echo "== audit"
A=$(curl -sf "$URL/audit" -H "Authorization: Bearer $MGR")
check "manager reads the audit trail" True "$(echo "$A" | json 'len(d) > 0')"

echo "== web app through nginx (what a browser does)"
# Its own tunnel to the web Service (127.0.0.1 only), like the API one above: no dependency on forward.sh.
k -n "$NS" port-forward --address 127.0.0.1 svc/agentops-web 18088:80 >/dev/null 2>&1 &
WPF=$!
trap 'kill $PF $WPF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf "localhost:18088/healthz" >/dev/null && break; sleep 1; done
WEB="http://localhost:18088"
check "web app is served"                   1 "$(curl -s "$WEB/" | grep -c 'id="root"')"
check "deep links fall back to the app"     200 "$(code "$WEB/portal/requests/1")"
check "strict Content-Security-Policy set"  1 "$(curl -sI "$WEB/" | grep -ci "content-security-policy: default-src 'self'")"
check "API docs self-hosted (no CDN)"      200 "$(code "$WEB/api-docs/swagger-ui-bundle.js")"
check "/api/docs redirects to them"         /api-docs/ "$(curl -s -o /dev/null -w '%{redirect_url}' "$WEB/api/docs" | sed "s#$WEB##")"
check "/api is proxied to the API"          ready "$(curl -s "$WEB/api/ready" | json 'd["status"]')"
CTOK=$(curl -sf "$WEB/api/auth/dev-login" -H 'content-type: application/json' -d '{"username":"jordan.brown"}' | json 'd["token"]')
R=$(curl -sf "$WEB/api/portal/requests" -H "Authorization: Bearer $CTOK" -H 'content-type: application/json' \
  -d '{"message":"My card was stolen and I can see charges I did not make"}')
check "customer request reaches a specialist" "With a specialist" "$(echo "$R" | json 'd["status"]')"
check "customer is kept out of staff data"  403 "$(code "$WEB/api/cases" -H "Authorization: Bearer $CTOK")"
check "copilot streams through nginx"       True "$(curl -sN --max-time 20 "$WEB/api/portal/assistant/stream" -H "Authorization: Bearer $CTOK" \
  -H 'content-type: application/json' -d '{"question":"how much is the foreign transaction fee?"}' | grep -q 'event: done' && echo True || echo False)"

echo
echo "smoke test passed: $pass checks against context '$CTX'"
