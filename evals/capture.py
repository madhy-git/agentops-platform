"""Grow the golden set from real failures.

Usage:
    uv run python evals/capture.py candidates            # list rejected approvals (likely misjudged)
    uv run python evals/capture.py add "message text" --category fraud --needs-human
    uv run python evals/capture.py add "Ignore your rules..." --blocked

LEARNING NOTES
- The best eval cases are the ones the system got *wrong* in practice. A rejected approval means a
  human disagreed with the system's proposal; that's a labelled failure for free.
- `add` appends with a `source` tag and a date, so you can later ask "which cases came from production?"
  and check the set isn't drifting towards cases the system already handles.
- Text from production is already PII-redacted (service.triage redacts first). Never paste raw
  customer text into the golden set: it's committed to git.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from agentops import db
from agentops.guardrails import redact_pii

GOLDEN = Path(__file__).with_name("golden.jsonl")


def candidates() -> None:
    conn = db.connect()
    db.migrate(conn)
    rows = conn.execute(
        "SELECT id, case_text, proposed_action, reviewer, decided_at FROM approvals WHERE status = 'rejected' ORDER BY id DESC LIMIT 50"
    ).fetchall()
    for r in rows:
        print(f"#{r['id']} rejected by {r['reviewer']}: proposed {r['proposed_action']!r} for {r['case_text']!r}")
    print(f"{len(rows)} candidates. Label each and `add` the ones the system got wrong.")


def add(text: str, category: str | None, needs_human: bool, blocked: bool) -> None:
    text = redact_pii(text).text  # belt and braces: never commit PII
    case: dict[str, object] = {"input": text, "source": f"failure:{date.today().isoformat()}"}
    case |= {"blocked": True} if blocked else {"category": category, "needs_human": needs_human}
    with GOLDEN.open("a") as f:
        f.write(json.dumps(case) + "\n")
    print("added:", case)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("candidates")
    a = sub.add_parser("add")
    a.add_argument("text")
    a.add_argument("--category", choices=["fraud", "hardship", "dispute", "complaint", "general"])
    a.add_argument("--needs-human", action="store_true")
    a.add_argument("--blocked", action="store_true")
    args = ap.parse_args()
    if args.cmd == "candidates":
        candidates()
    else:
        if not args.blocked and not args.category:
            ap.error("--category is required unless --blocked")
        add(args.text, args.category, args.needs_human, args.blocked)
