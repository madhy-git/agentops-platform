"""Human-oversight drill: are approvers actually reviewing, or rubber-stamping?

Usage:
    uv run python evals/oversight.py seed --n 10 --bad 3    # put a mix of real and deliberately wrong proposals in the queue
    # ... approvers decide via the UI or API ...
    uv run python evals/oversight.py report                 # approval rate, decision time, override rate, bad-proposal catch rate

LEARNING NOTES (project.md "Human oversight": automation bias, approver fatigue, rubber-stamping)
- A human in the loop only helps if the human disagrees sometimes. An approval rate near 100% plus
  decision times of a few seconds is the signature of rubber-stamping.
- Seeded bad proposals (seeded_bad = true) are the only way to *measure* catch rate: you know the
  right answer is "reject". Tell approvers drills happen, not which items are drills.
- Override rate = share of proposals a human rejected. Too low: rubber-stamping. Too high: the system's
  proposals are poor and approvers are drowning. Both are findings.
"""

from __future__ import annotations

import argparse
import statistics
from typing import Any

from agentops import db
from agentops.db import Conn
from agentops.decision.service import utcnow
from agentops.service import TriageService

REAL = ["My card was stolen at the airport", "I lost my job and can't pay", "Please refund the wrong charge"]
# Plausible-looking but wrong: a card block proposed for a harmless question.
BAD = [
    "How do I download my statement?",
    "What are the fees on the everyday account?",
    "What time does the branch open?",
]


def seed(conn: Conn, n: int, bad: int) -> list[int]:
    svc = TriageService(conn)
    now, ids = utcnow(), []
    for i in range(n - bad):
        o = svc.triage(REAL[i % len(REAL)], actor="officer-1", now=now)
        if o.approval_id:
            ids.append(o.approval_id)
    for i in range(bad):
        o = svc.triage(BAD[i % len(BAD)], actor="officer-1", now=now)
        assert o.decision and o.decision.decision_id and o.case_id
        req = svc.approvals.request(o.case_id, o.decision.decision_id, "block_card", "officer-1", now, seeded_bad=True)
        # Seeds follow the same state machine as real requests (it rejected the shortcut when we skipped this).
        svc.cases.transition(o.case_id, "pending_approval", "officer-1", {"officer"}, now)
        ids.append(req["id"])
    return ids


def report(conn: Conn) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM approval_requests WHERE status <> 'pending'").fetchall()
    if not rows:
        return {"decided": 0}
    secs = [(r["decided_at"] - r["created_at"]).total_seconds() for r in rows]
    bad = [r for r in rows if r["seeded_bad"]]
    m = {
        "decided": len(rows),
        "approval_rate": sum(r["status"] == "approved" for r in rows) / len(rows),
        "override_rate": sum(r["status"] == "rejected" for r in rows) / len(rows),
        "median_decision_s": statistics.median(secs),
        "fast_decisions_under_10s": sum(s < 10 for s in secs) / len(rows),
        "seeded_bad_caught": (sum(r["status"] == "rejected" for r in bad) / len(bad)) if bad else None,
        "per_approver": {},
    }
    for r in rows:
        a = m["per_approver"].setdefault(r["decided_by"], {"n": 0, "approved": 0})
        a["n"] += 1
        a["approved"] += r["status"] == "approved"
    warnings = []
    if m["seeded_bad_caught"] is not None and m["seeded_bad_caught"] < 1.0:
        warnings.append("some deliberately wrong proposals were APPROVED: review approver training and UI")
    if m["approval_rate"] > 0.95 and m["fast_decisions_under_10s"] > 0.5:
        warnings.append("high approval rate with very fast decisions: possible rubber-stamping")
    m["warnings"] = warnings
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--n", type=int, default=10)
    s.add_argument("--bad", type=int, default=3)
    sub.add_parser("report")
    args = ap.parse_args()
    c = db.connect()
    db.migrate(c)
    if args.cmd == "seed":
        print("seeded approvals:", seed(c, args.n, args.bad))
    else:
        import json

        print(json.dumps(report(c), indent=2, default=str))
