"""Lifecycle replay harness (scenario S6): run journeys, check every expectation.

Usage: uv run python evals/replay.py      -> prints per-journey results; exits 1 below 100%.

LEARNING NOTES
- This tests the *decision layer* without any model: categories are given, not predicted. That
  isolates the question "given a correct triage, do the rules do the right thing over time?"
  from "is the triage correct?" (that's the golden set). Mixing them hides which layer failed.
- Time is simulated (`day: 40`), so cooling-off windows and clocks are tested in milliseconds.
- "Marketing suppression correctness" (project.md metric) = share of expectations about
  marketing_suppressed that held. Target: 100%.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from agentops import db
from agentops.decision.flags import FlagPermissionError
from agentops.decision.service import DecisionService, load_customers

JOURNEYS = Path(__file__).with_name("journeys.yaml")
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def check(expect: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    """Compare one step's expectations with what happened. Returns human-readable failures."""
    fails = []
    for key, want in expect.items():
        got = observed.get(key.removesuffix("_include").removesuffix("_exclude"))
        if key.endswith("_include") or key == "reason_codes":
            missing = [w for w in want if w not in (got or [])]
            ok = not missing
        elif key.endswith("_exclude"):
            ok = not [w for w in want if w in (got or [])]
        elif key == "flags":
            ok = sorted(got or []) == sorted(want)
        else:
            ok = got == want
        if not ok:
            fails.append(f"{key}: expected {want!r}, got {got!r}")
    return fails


def run_journey(svc: DecisionService, j: dict[str, Any], profiles: dict[str, Any]) -> list[dict[str, Any]]:
    cid = f"JRN-{j['id'].split('-')[0]}"
    cust = {"customer_id": cid, "name": j["id"], "lifecycle_stage": j["customer"]["stage"], "vulnerable": False}
    load_customers(svc.conn, [cust | profiles[j["customer"]["profile"]]])
    results = []
    for i, step in enumerate(j["steps"]):
        now = T0 + timedelta(days=step["day"])
        observed: dict[str, Any] = {}
        try:
            if step["event"] == "message":
                d = svc.decide(
                    cid, step["category"], step.get("recommended_action", "answer"), role=step.get("role", "officer"),
                    now=now, txn_age_days=step.get("txn_age_days"),
                )  # fmt: skip
                observed |= {
                    "needs_approval": d.needs_approval,
                    "reason_codes": d.reason_codes,
                    "actions": d.actions,
                    "candidates": d.candidate_actions,
                    "top_candidate": d.candidate_actions[0] if d.candidate_actions else None,
                }
            elif step["event"] == "clear_flag":
                svc.clear_flag(cid, step["flag"], actor=f"{step['roles'][0]}-1", roles=set(step["roles"]), now=now)
            elif step["event"] == "tick":
                svc.refresh_stage(cid, now)
        except FlagPermissionError as e:
            observed["error"] = type(e).__name__
        observed |= {
            "flags": svc.flags.active(cid),
            "marketing_suppressed": svc.marketing_suppressed(cid, now),
            "stage": svc.customer(cid)["lifecycle_stage"],  # type: ignore[index]
        }
        results.append(
            {"journey": j["id"], "step": i, "fails": check(step["expect"], observed), "expect": step["expect"]}
        )
    return results


def run() -> dict[str, Any]:
    spec = yaml.safe_load(JOURNEYS.read_text())
    with db.scratch_schema("replay") as conn:
        svc = DecisionService(conn)
        steps = [r for j in spec["journeys"] for r in run_journey(svc, j, spec["profiles"])]
    supp = [s for s in steps if "marketing_suppressed" in s["expect"]]
    return {
        "journeys": len(spec["journeys"]),
        "steps": len(steps),
        "step_correctness": sum(not s["fails"] for s in steps) / len(steps),
        "marketing_suppression_correctness": sum(not any("marketing" in f for f in s["fails"]) for s in supp)
        / len(supp),
        "failures": [f"{s['journey']} step {s['step']}: {f}" for s in steps for f in s["fails"]],
    }


if __name__ == "__main__":
    m = run()
    print(json.dumps(m, indent=2))
    sys.exit(0 if m["step_correctness"] == 1.0 else 1)
