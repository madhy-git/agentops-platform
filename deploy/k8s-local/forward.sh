#!/usr/bin/env bash
# Open the local cluster's UIs on THIS Mac only (127.0.0.1), and keep them open.
#   deploy/k8s-local/forward.sh            # runs until Ctrl+C; each tunnel reconnects by itself
#
#   http://localhost:8088    web app (customer portal + staff workspace)
#   http://localhost:3000    Grafana (dashboards: requests, latency, LLM tokens/cost, guardrails)
#   http://localhost:16686   Jaeger (one trace per request, step by step)
#   127.0.0.1:5434           Postgres + pgvector (GUI / psql)
#
# LEARNING NOTES
# - Why not a LoadBalancer Service? On Docker Desktop it publishes on EVERY network interface: the web app
#   (whose demo sign-in lets anyone act as a manager) was reachable from the whole Wi-Fi. Found by curling the
#   Mac's LAN address. `port-forward --address 127.0.0.1` reaches the same Service but only from this machine.
# - A port-forward is a tunnel to one pod; it ends when that pod restarts (e.g. every redeploy). Each tunnel
#   runs in its own retry loop, so a redeploy is a 2-second blip instead of "connection refused" forever.
set -uo pipefail
CTX="${KUBE_CONTEXT:-docker-desktop}"
NS=agentops
case "$CTX" in
  *arn:aws*|*eks*|*gke*|*aks*) echo "refusing: '$CTX' looks like a cloud cluster" >&2; exit 1 ;;
esac

TUNNELS=(
  "agentops-web 8088 80"
  "grafana 3000 3000"
  "jaeger 16686 16686"
  "postgres 5434 5432"
)

keep_open() {  # keep_open <service> <local port> <service port>
  while true; do
    kubectl --context "$CTX" -n "$NS" port-forward --address 127.0.0.1 "svc/$1" "$2:$3" >/dev/null 2>&1
    sleep 2
  done
}

pids=()
for t in "${TUNNELS[@]}"; do
  read -r svc lport rport <<<"$t"
  if lsof -nP -iTCP:"$lport" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $lport already in use (another forward running?), skipping $svc"
    continue
  fi
  keep_open "$svc" "$lport" "$rport" &
  pids+=($!)
done
trap 'kill "${pids[@]}" 2>/dev/null; pkill -P $$ 2>/dev/null; echo; echo stopped; exit 0' INT TERM

echo "web app   http://localhost:8088"
echo "grafana   http://localhost:3000   (anonymous read-only; admin password: kubectl -n $NS get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d)"
echo "jaeger    http://localhost:16686"
echo "postgres  127.0.0.1:5434  db=agentops user=agentops"
echo "Ctrl+C to close all tunnels"
wait
