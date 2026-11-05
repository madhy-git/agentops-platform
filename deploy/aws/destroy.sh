#!/usr/bin/env bash
# Tear everything down. Run after every demo: an idle EKS cluster + NAT + endpoints still costs money.
# LEARNING NOTE: Kubernetes-created AWS resources (the ALB from the Ingress) must be deleted BEFORE the
# stack, or CloudFormation can't delete the VPC (the ALB's network interfaces still live in it).
set -euo pipefail
ENV="${1:-demo}"
STACK="agentops-${ENV}"
REGION="${AWS_REGION:?set AWS_REGION}"
CLUSTER=$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='ClusterName'].OutputValue" --output text 2>/dev/null || true)
if [[ -n "${CLUSTER}" && "${CLUSTER}" != "None" ]]; then
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
  kubectl delete namespace agentops --wait=true --timeout=10m || true   # removes the Ingress -> ALB
fi
REPO=$(aws ecr describe-repositories --repository-names "agentops-${ENV}" --query "repositories[0].repositoryName" --output text 2>/dev/null || true)
[[ -n "${REPO}" && "${REPO}" != "None" ]] && aws ecr delete-repository --repository-name "$REPO" --force
aws cloudformation delete-stack --stack-name "$STACK"
# The LBC role/policy were created by deploy.sh outside CloudFormation, so remove them here too.
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws iam detach-role-policy --role-name "agentops-${ENV}-lbc" --policy-arn "arn:aws:iam::${ACCOUNT}:policy/AgentOpsLBC-${ENV}" 2>/dev/null || true
aws iam delete-role --role-name "agentops-${ENV}-lbc" 2>/dev/null || true
aws iam delete-policy --policy-arn "arn:aws:iam::${ACCOUNT}:policy/AgentOpsLBC-${ENV}" 2>/dev/null || true
aws cloudformation wait stack-delete-complete --stack-name "$STACK"
echo "destroyed $STACK. RDS left a final snapshot (DeletionPolicy: Snapshot); delete it if not needed."
