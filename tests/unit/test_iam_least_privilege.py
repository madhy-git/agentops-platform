"""Phase 6: prove the IAM roles are least-privilege by reading the CloudFormation itself.

LEARNING NOTE: "one role per service" is only true if nobody later adds `Action: "*"` to make an error go
away. This test turns the design rule into a check that runs on every PR.
"""

from pathlib import Path

import yaml

CFN = Path(__file__).parents[2] / "deploy" / "cloudformation"


class CfnLoader(yaml.SafeLoader):
    """Understands CloudFormation short tags (!Ref, !Sub, !GetAtt...) as plain {tag: value} dicts."""


def _tag(loader, suffix, node):
    value = loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node) \
        if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)  # fmt: skip
    return {suffix: value}


CfnLoader.add_multi_constructor("!", _tag)


def resources(name):
    return yaml.load((CFN / name).read_text(), Loader=CfnLoader)["Resources"]


def actions(role):
    out = set()
    for pol in role["Properties"].get("Policies", []):
        for st in pol["PolicyDocument"]["Statement"]:
            a = st["Action"]
            out |= set(a if isinstance(a, list) else [a])
    return out


ROLES = resources("identity.yaml")


def test_no_wildcard_actions_or_resources_in_workload_roles():
    for name in ("ApiRole", "WorkerRole", "LitellmRole"):
        for pol in ROLES[name]["Properties"]["Policies"]:
            for st in pol["PolicyDocument"]["Statement"]:
                assert "*" not in str(st["Action"]), (name, st)
                assert st["Resource"] != "*", (name, st)


def test_each_service_gets_only_what_it_needs():
    assert actions(ROLES["ApiRole"]) == {
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "secretsmanager:GetSecretValue",
    }
    assert actions(ROLES["WorkerRole"]) == {"secretsmanager:GetSecretValue"}  # the worker never calls a model
    assert actions(ROLES["LitellmRole"]) == {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"}  # no DB


def test_roles_are_assumable_only_by_eks_pods():
    for name in ("ApiRole", "WorkerRole", "LitellmRole", "AdotRole"):
        (st,) = ROLES[name]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        assert st["Principal"] == {"Service": "pods.eks.amazonaws.com"}


def test_every_workload_role_is_bound_to_exactly_one_service_account():
    bindings = {r["Properties"]["ServiceAccount"]: r["Properties"]["RoleArn"]["GetAtt"].split(".")[0]
                for r in ROLES.values() if r["Type"] == "AWS::EKS::PodIdentityAssociation"}  # fmt: skip
    assert bindings == {"agentops-api": "ApiRole", "agentops-worker": "WorkerRole",
                        "agentops-litellm": "LitellmRole", "adot-collector": "AdotRole"}  # fmt: skip


def test_nodes_have_no_workload_permissions():
    node = resources("app.yaml")["NodeRole"]["Properties"]
    assert "Policies" not in node  # only AWS-managed node policies; workloads use Pod Identity
