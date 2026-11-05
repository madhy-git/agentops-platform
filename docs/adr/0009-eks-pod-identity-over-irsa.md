# ADR 0009: EKS Pod Identity instead of IRSA

- **Status:** accepted (deviation from project.md, review)
- **Date:** 2026-11-04
- **Phase:** 6

## Context
project.md asks for "IRSA, one least-privilege role per service". IRSA trust policies need a condition keyed by the cluster's OIDC issuer (`oidc.eks.<region>.amazonaws.com/id/<ID>:sub`). That key is only known after the cluster exists, and CloudFormation can't build a JSON *key* from `!GetAtt`. The usual workarounds are a Lambda custom resource or a second deployment pass.

## Options considered
| Option | For | Against |
|---|---|---|
| IRSA via custom resource | Matches project.md; works on older clusters | Extra Lambda to write, secure and maintain; more moving parts |
| IRSA via eksctl | Simple CLI | Second tool, outside CloudFormation's change sets |
| **EKS Pod Identity** | Native CloudFormation (`AWS::EKS::PodIdentityAssociation`); simpler trust policy (`pods.eks.amazonaws.com`); no OIDC provider to manage | Needs the Pod Identity agent add-on; newer, so some third-party charts still document IRSA only |

## Decision
Use EKS Pod Identity. Same outcome as IRSA (one role per service account, no node credentials used by pods), with less machinery.

## Consequences
- `tests/unit/test_iam_least_privilege.py` checks each role's actions and its binding to exactly one service account.
- The AWS Load Balancer Controller's role is created by `deploy.sh` (its upstream policy is pinned at a version), outside CloudFormation, and removed by `destroy.sh`.
- Revisit if a required add-on supports only IRSA.
