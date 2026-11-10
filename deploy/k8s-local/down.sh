#!/usr/bin/env bash
# Remove the local deployment. Deleting the namespace removes everything in it, including the Secret and the
# Postgres volume (PVC), so the next up.sh starts with an empty database and fresh random credentials.
#   deploy/k8s-local/down.sh
set -euo pipefail
CTX="${KUBE_CONTEXT:-docker-desktop}"
case "$CTX" in
  *arn:aws*|*eks*|*gke*|*aks*) echo "refusing: '$CTX' looks like a cloud cluster; use deploy/aws/destroy.sh" >&2; exit 1 ;;
esac
kubectl --context "$CTX" delete namespace agentops --ignore-not-found --wait=true
echo "removed namespace agentops from '$CTX'"
