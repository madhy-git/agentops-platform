"""Phase 7: the Rego policy and the Python rules engine must make the same decision for every context.

Runs OPA in Docker (skips if Docker isn't available). Exhaustive over the dimensions the rules read.
"""

import itertools
import json
import shutil
import subprocess

import pytest

from agentops.config import REPO_ROOT
from agentops.decision.rules import evaluate, load_policy

OPA_IMAGE = "openpolicyagent/opa:1.22.0-static"
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker for OPA")

CATEGORIES = ["fraud", "hardship", "dispute", "complaint", "general"]
RECOMMENDED = ["answer", "freeze_card", "hardship_review", "refund_review", "escalate"]
ROLES = ["officer", "manager"]
AGES = [None, 10, 120, 121, 150]  # None = unknown transaction; 120/121 = the boundary
RISKS = [0.1, 0.9]
FLAGS = [[], ["fraud_flag"], ["hardship_flag"], ["cooling_off"]]


def contexts():
    for cat, rec, role, age, risk, flags in itertools.product(CATEGORIES, RECOMMENDED, ROLES, AGES, RISKS, FLAGS):
        yield {
            "category": cat,
            "recommended_action": rec,
            "role": role,
            "txn_age_days": age,
            "risk_score": risk,
            "flags": flags,
        }


def opa_eval(ctxs):
    out = subprocess.run(
        ["docker", "run", "--rm", "-i", "-v", f"{REPO_ROOT / 'policies'}:/p:ro", OPA_IMAGE,
         "eval", "--format", "json", "-d", "/p/rules.rego", "--stdin-input", "data.wattle.decisions"],
        input=json.dumps({"contexts": ctxs}), capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)["result"][0]["expressions"][0]["value"]


def test_rego_matches_python_on_every_context():
    policy = load_policy()
    ctxs = list(contexts())
    mismatches = []
    for ctx, opa in zip(ctxs, opa_eval(ctxs), strict=True):
        py = evaluate(policy, ctx)
        mine = {"fired": py.fired, "actions": sorted(py.actions), "set_flags": sorted(py.set_flags),
                "requires_approval": py.requires_approval, "suppress_marketing": "marketing" in py.suppress_kinds}  # fmt: skip
        if mine != opa:
            mismatches.append((ctx, mine, opa))
    assert not mismatches, f"{len(mismatches)}/{len(ctxs)} differ, e.g. {mismatches[0]}"
