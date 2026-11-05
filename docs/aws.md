# AWS deployment (Phase 6)

> **Status: written and validated, not deployed.** Deploying needs your AWS account and costs money. Everything below was checked locally: cfn-lint (no errors), Checkov (78 passed, 0 failed, 1 documented skip), kubeconform (20/20 resources valid), image build + Trivy (0 fixable HIGH/CRITICAL), shellcheck (clean), and IAM least-privilege unit tests.

## Architecture
```text
GitHub Actions --OIDC--> AWS (deploy role, short-lived creds)
                     \--> ECR (immutable tags, scan on push)
Internet -> ALB (TLS 1.3) -> EKS (private subnets)
                               ├─ agentops-api   --Pod Identity--> Bedrock (via LiteLLM), Secrets Manager
                               ├─ litellm        --Pod Identity--> Bedrock (exact model ARNs)
                               ├─ agentops-worker --Pod Identity--> Secrets Manager
                               └─ adot-collector --Pod Identity--> X-Ray / CloudWatch
                             RDS Postgres 17 + pgvector (private, KMS, managed password)
VPC endpoints: Bedrock runtime, ECR, Secrets Manager, S3 (model and image traffic stays on the AWS network)
Cognito user pool: staff sign-in; groups = app roles (cognito:groups)
```

| Piece | File |
|---|---|
| Nested stacks | `deploy/cloudformation/root.yaml` → `network.yaml`, `app.yaml`, `data.yaml`, `identity.yaml` |
| Kubernetes | `deploy/k8s/*.yaml` (restricted Pod Security, read-only root FS, default-deny NetworkPolicy) |
| Scripts | `deploy/aws/deploy.sh`, `destroy.sh`, `smoke.sh` |
| CI | `.github/workflows/security.yml` (every push), `deploy.yml` (manual, OIDC) |

## Deploy (when you choose to)
1. **One-time:** create a GitHub OIDC provider and a deploy role in your account; restrict its trust to `repo:<you>/agentops-platform:environment:production`. Request an ACM certificate.
2. **Pick Bedrock models** available in your region (or inference profiles), enable model access in the Bedrock console, and set `BEDROCK_MODEL_ARNS` and `BEDROCK_TIER1..3`.
3. Set repo variables: `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `BEDROCK_*`, `CERT_ARN`. Run the **deploy** workflow (or `deploy/aws/deploy.sh demo` locally).
4. Create Cognito users and add them to groups (`officer`, `fraud_specialist`, …).
5. **Run `destroy` after every demo.** Save screenshots or a video first, as project.md suggests.

## Cost note (rough; verify with the AWS Pricing Calculator for your region)
The big hourly items are the ones that run whether or not anyone uses the app:

| Item | Why it costs | Notes |
|---|---|---|
| EKS control plane | per cluster-hour | The largest fixed cost. ECS Fargate (6a) avoids it |
| 2 × t3.large nodes | per instance-hour | Could drop to 1 node for a demo |
| NAT gateway | per hour + per GB | One NAT, not one per AZ (accepted risk for a demo) |
| 4 interface VPC endpoints × 2 AZs | per endpoint-hour | The price of keeping model traffic private; drop them to save money in a demo |
| RDS db.t4g.micro + 20 GB gp3 | per hour + storage | Single-AZ by default (Checkov skip CKV_AWS_157, documented) |
| Bedrock | per token | Usually the smallest line in a demo; the router keeps most traffic on tier 1/2 |

A demo that's deployed, recorded and destroyed within a few hours costs a few dollars. **Left running, it adds up to hundreds of dollars a month.** Hence `destroy.sh` and a budget alert (set one in AWS Budgets before the first deploy).

## Deviations from project.md
- **Pod Identity instead of IRSA** (ADR 0009).
- ADOT runs as a plain Deployment exporting to X-Ray, not the EKS add-on (which also needs cert-manager).
- Phase 6a (ECS Fargate rehearsal) not built.
