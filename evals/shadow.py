"""Shadow run: compare the current configuration with a candidate on the golden set, case by case.

Usage:
    uv run python evals/shadow.py --candidate-budget-tier 2
    AGENTOPS_MODE=live uv run python evals/shadow.py --candidate-budget-tier 2

LEARNING NOTES
- Before switching a model, prompt or budget, run the candidate *alongside* the current setup on the
  same inputs and diff the outputs. Aggregate metrics can stay flat while individual cases flip, and
  a flipped fraud case matters more than the average.
- Typical candidates: a cheaper tier (cost cap), a new model behind a tier alias (deprecations), a new
  prompt major version. The report lists every disagreement for a human to review before rollout.
- Offline, the rule model behaves identically on every tier, so you'll see 0 disagreements and only
  the cost delta. The live run is where shadowing earns its keep.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_evals import load  # noqa: E402

from agentops import db  # noqa: E402
from agentops.service import TriageService  # noqa: E402


def run_config(budget_tier: int) -> list[dict[str, object]]:
    out = []
    with db.scratch_schema("shadow") as conn:
        svc = TriageService(conn, budget_tier=budget_tier)
        for c in load():
            o = svc.triage(c["input"])
            out.append({"input": c["input"], "status": o.status,
                        "category": o.result.category if o.result else None, "cost": o.cost_usd,
                        "model": o.model_used.name if o.model_used else None})  # fmt: skip
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-budget-tier", type=int, default=2)
    args = ap.parse_args()
    current, candidate = run_config(3), run_config(args.candidate_budget_tier)
    diffs = [
        (a, b)
        for a, b in zip(current, candidate, strict=True)
        if (a["status"], a["category"]) != (b["status"], b["category"])
    ]
    cost_a = sum(float(r["cost"]) for r in current)  # type: ignore[arg-type]
    cost_b = sum(float(r["cost"]) for r in candidate)  # type: ignore[arg-type]
    print(f"Candidate: budget_tier={args.candidate_budget_tier}")
    print(f"Disagreements: {len(diffs)}/{len(current)}")
    for a, b in diffs:
        print(f"  {a['input'][:60]!r}: {a['status']}/{a['category']} -> {b['status']}/{b['category']}")
    print(f"Cost: {cost_a:.4f} -> {cost_b:.4f} USD ({(cost_b / cost_a - 1) * 100:+.0f}%)")


if __name__ == "__main__":
    main()
