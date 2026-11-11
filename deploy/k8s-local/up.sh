#!/usr/bin/env bash
# Deploy AgentOps to a LOCAL Kubernetes cluster (default: Docker Desktop). Free, offline, no cloud account.
#   deploy/k8s-local/up.sh                 # build image, create Secret (first time), apply, wait
#   KUBE_CONTEXT=kind-agentops deploy/k8s-local/up.sh   # another local cluster (kind: see README)
#
# LEARNING NOTES
# - Every kubectl call passes --context explicitly, and the script refuses anything that looks like a cloud
#   cluster. "Ran the dev script against prod because that was the current context" is a classic outage.
# - The Secret is created once with random values and never regenerated: Postgres only reads POSTGRES_PASSWORD
#   when it first initialises its volume, so rotating it here would lock the app out of its own database.
# - Re-running is safe (kubectl apply is declarative). The rollout restart picks up a rebuilt image, because
#   the tag `agentops:local` doesn't change and Kubernetes only restarts pods when the pod spec changes.
set -euo pipefail
CTX="${KUBE_CONTEXT:-docker-desktop}"
NS=agentops
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
k() { kubectl --context "$CTX" "$@"; }

case "$CTX" in
  *arn:aws*|*eks*|*gke*|*aks*) echo "refusing: '$CTX' looks like a cloud cluster; use deploy/aws/deploy.sh" >&2; exit 1 ;;
esac
k get nodes >/dev/null || { echo "cluster '$CTX' not reachable (Docker Desktop: Settings > Kubernetes > Enable)" >&2; exit 1; }

echo "== 1/4 build images agentops:local (API + worker) and agentops-web:local (web app)"
docker build -t agentops:local "$ROOT"
docker build -t agentops-web:local "$ROOT/web"
if [[ "$CTX" == kind-* ]]; then
  kind load docker-image agentops:local agentops-web:local --name "${CTX#kind-}"
fi

echo "== 2/4 namespace + secret"
k apply -f "$ROOT/deploy/k8s/00-namespace.yaml" >/dev/null
if ! k -n "$NS" get secret agentops-secrets >/dev/null 2>&1; then
  PW=$(openssl rand -hex 24)
  k -n "$NS" create secret generic agentops-secrets \
    --from-literal=POSTGRES_PASSWORD="$PW" \
    --from-literal=AGENTOPS_DATABASE_URL="postgresql://agentops:${PW}@postgres.${NS}.svc.cluster.local:5432/agentops" \
    --from-literal=AGENTOPS_JWT_SECRET="$(openssl rand -hex 32)"
else
  echo "secret agentops-secrets exists; keeping it"
fi

# LiteLLM master key: random, created once (the gateway refuses to start without one).
k -n "$NS" get secret litellm-master >/dev/null 2>&1 || \
  k -n "$NS" create secret generic litellm-master --from-literal=LITELLM_MASTER_KEY="sk-$(openssl rand -hex 32)" >/dev/null

# Gemini key for the LiteLLM gateway, from the git-ignored .env (never from the command line, so it doesn't show
# up in `ps` or shell history). Re-applied every run, so editing .env and re-running picks up a new key.
if grep -q '^GEMINI_API_KEY=.' "$ROOT/.env" 2>/dev/null; then
  k -n "$NS" create secret generic gemini-api --from-env-file=<(grep '^GEMINI_API_KEY=' "$ROOT/.env") \
    --dry-run=client -o yaml | k apply -f - >/dev/null
  echo "gemini-api secret updated from .env"
else
  echo "no GEMINI_API_KEY in .env: the copilot will answer with the offline model"
fi

echo "== 3/4 apply manifests (deploy/k8s base + deploy/k8s-local overlay)"
k apply -k "$ROOT/deploy/k8s-local"
k -n "$NS" rollout restart deploy/agentops-api deploy/agentops-worker deploy/agentops-web deploy/litellm >/dev/null

echo "== 4/4 wait for rollout"
k -n "$NS" rollout status statefulset/postgres --timeout=3m
k -n "$NS" rollout status deploy/agentops-api --timeout=5m
k -n "$NS" rollout status deploy/agentops-worker --timeout=3m
k -n "$NS" rollout status deploy/agentops-web --timeout=3m
k -n "$NS" rollout status deploy/litellm --timeout=5m
k -n "$NS" get pods -o wide
echo
echo "deployed. Open http://localhost:8088 (web app). Check it: deploy/k8s-local/smoke.sh"
