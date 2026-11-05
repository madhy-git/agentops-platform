#!/usr/bin/env bash
# Deploy AgentOps to AWS: build + push image, deploy nested CloudFormation, install the ALB controller,
# apply Kubernetes manifests. NOT run by Claude: needs your AWS account and costs money (docs/aws.md).
#
# LEARNING NOTE: every step is idempotent (CloudFormation diffs, `kubectl apply`, `helm upgrade --install`),
# so re-running after a failure continues instead of duplicating resources.
set -euo pipefail
ENV="${1:-demo}"
STACK="agentops-${ENV}"
REGION="${AWS_REGION:?set AWS_REGION}"
: "${DEPLOYER_ROLE_ARN:?}" "${BEDROCK_MODEL_ARNS:?}" "${CERT_ARN:?}" "${BEDROCK_TIER1:?}" "${BEDROCK_TIER2:?}" "${BEDROCK_TIER3:?}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ARTIFACTS="agentops-cfn-${ACCOUNT}-${REGION}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(python3 -c "import tomllib;print(tomllib.load(open('$HERE/../pyproject.toml','rb'))['project']['version'])")

echo "== 1/5 artifact bucket for nested templates"
aws s3api head-bucket --bucket "$ARTIFACTS" 2>/dev/null || aws s3 mb "s3://$ARTIFACTS" --region "$REGION"

echo "== 2/5 package + deploy CloudFormation (network -> app -> data -> identity)"
aws cloudformation package --template-file "$HERE/cloudformation/root.yaml" --s3-bucket "$ARTIFACTS" \
  --output-template-file /tmp/agentops-packaged.yaml
aws cloudformation deploy --stack-name "$STACK" --template-file /tmp/agentops-packaged.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --no-fail-on-empty-changeset \
  --parameter-overrides Env="$ENV" DeployerRoleArn="$DEPLOYER_ROLE_ARN" BedrockModelArns="$BEDROCK_MODEL_ARNS"
out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
# Assign, THEN export: `export X=$(cmd)` hides a failing cmd even under `set -e` (shellcheck SC2155), which
# would apply manifests with an empty DB host. Found by shellcheck.
CLUSTER=$(out ClusterName); REPO=$(out RepositoryUri); DB_HOST=$(out DbEndpoint); DB_SECRET_ARN=$(out DbSecretArn)
JWKS_URL=$(out JwksUrl); APP_CLIENT_ID=$(out AppClientId)
JWT_ISSUER="${JWKS_URL%/.well-known/jwks.json}"; AWS_REGION="$REGION"
export CLUSTER REPO DB_HOST DB_SECRET_ARN JWKS_URL APP_CLIENT_ID JWT_ISSUER AWS_REGION CERT_ARN BEDROCK_TIER1 BEDROCK_TIER2 BEDROCK_TIER3

echo "== 3/5 build + push image (immutable tag = version + git sha)"
TAG="${VERSION}-$(git -C "$HERE/.." rev-parse --short HEAD)"
IMAGE="${REPO}:${TAG}"
export IMAGE
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build -t "$IMAGE" "$HERE/.."
docker push "$IMAGE"

echo "== 4/5 kubeconfig + AWS Load Balancer Controller (own IAM role via Pod Identity)"
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
# AWS publishes no managed policy for the controller; use the upstream one at a PINNED version (review it).
LBC_VERSION="v2.11.0"
LBC_POLICY="AgentOpsLBC-${ENV}"
LBC_ROLE="agentops-${ENV}-lbc"
POLICY_ARN="arn:aws:iam::${ACCOUNT}:policy/${LBC_POLICY}"
if ! aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  curl -fsSL "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/${LBC_VERSION}/docs/install/iam_policy.json" \
    -o /tmp/lbc-policy.json
  aws iam create-policy --policy-name "$LBC_POLICY" --policy-document file:///tmp/lbc-policy.json >/dev/null
fi
if ! aws iam get-role --role-name "$LBC_ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$LBC_ROLE" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"]}]}' >/dev/null
  aws iam attach-role-policy --role-name "$LBC_ROLE" --policy-arn "$POLICY_ARN"
fi
aws eks create-pod-identity-association --cluster-name "$CLUSTER" --namespace kube-system \
  --service-account aws-load-balancer-controller --role-arn "arn:aws:iam::${ACCOUNT}:role/${LBC_ROLE}" >/dev/null 2>&1 || true
helm repo add eks https://aws.github.io/eks-charts >/dev/null && helm repo update >/dev/null
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system \
  --set clusterName="$CLUSTER" --set serviceAccount.name=aws-load-balancer-controller

echo "== 5/5 apply manifests"
for f in "$HERE"/k8s/*.yaml; do envsubst < "$f" | kubectl apply -f -; done
kubectl -n agentops rollout status deploy/agentops-api --timeout=10m
echo "deployed $IMAGE to $CLUSTER"
