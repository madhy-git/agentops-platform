"""Drift report: baseline vs drifted synthetic population. Writes docs/evals/drift.md.

Usage:
    uv run python data/generate.py --shift 0.6 --suffix _drifted --seed 8
    uv run python evals/drift_report.py

LEARNING NOTE: the drifted file was generated with the *same* hidden churn formula but shifted
inputs, i.e. pure data drift. Expect: feature PSI and score PSI jump, yet AUC on the drifted data
stays close, because the input->outcome relationship didn't change. If AUC fell while PSI stayed
flat, that would point to concept drift. Both signals are needed.
"""

from __future__ import annotations

from sklearn.metrics import roc_auc_score

from agentops.config import REPO_ROOT
from agentops.decision import drift, risk

GEN = REPO_ROOT / "data" / "generated"


def main() -> None:
    base, shifted = risk.load(GEN / "customers.jsonl"), risk.load(GEN / "customers_drifted.jsonl")
    model = risk.default_model()
    lines = [
        "# Drift report (synthetic)",
        "",
        "Baseline = training population. Drifted = `data/generate.py --shift 0.6` (same churn formula, shifted inputs).",
        "",
        "| Signal | PSI | Verdict |",
        "|---|---|---|",
    ]
    raw_features = ["monthly_logins", "balance_trend", "missed_payments_90d", "complaints_12m", "tenure_days"]
    for f in raw_features:
        v = drift.psi([c[f] for c in base], [c[f] for c in shifted])
        lines.append(f"| feature `{f}` | {v:.3f} | {drift.verdict(v)} |")
    sb, ss = [model.score(c) for c in base], [model.score(c) for c in shifted]
    v = drift.psi(sb, ss)
    lines.append(f"| **risk score** | {v:.3f} | {drift.verdict(v)} |")

    auc_shift = roc_auc_score([c["churned"] for c in shifted], ss)
    high_b = sum(s > 0.5 for s in sb) / len(sb)
    high_s = sum(s > 0.5 for s in ss) / len(ss)
    lines += [
        "",
        "| Outcome check | Baseline | Drifted |",
        "|---|---|---|",
        f"| AUC | {model.auc:.3f} (held-out) | {auc_shift:.3f} |",
        f"| Share above R6 threshold (0.5) | {high_b:.1%} | {high_s:.1%} |",
        "",
        "**Reading it:** inputs moved (PSI high) and many more customers now cross the R6 threshold, so the",
        "retention queue would grow sharply overnight. AUC held, so the model still ranks customers well:",
        "this is data drift, not concept drift. The *business* question is whether R6's fixed 0.5 threshold",
        "is still right when the population shifts. That's a policy decision, which is why it lives in rules.yaml.",
        "",
    ]
    out = REPO_ROOT / "docs" / "evals" / "drift.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
