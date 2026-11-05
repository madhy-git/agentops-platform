"""Churn-risk model (scikit-learn logistic regression) on synthetic customers.

LEARNING NOTES
- Why a *classical* model next to an LLM? Risk scores need to be cheap, fast, stable and
  explainable (coefficients), and to come with measured accuracy. An LLM is none of those for
  tabular data. Use the right tool per job.
- The model is trained from data/generated/customers.jsonl at first use (seeded, ~50 ms) instead of
  loading a committed pickle. Pickles execute code when loaded, so never load one you didn't build.
  In production you'd use a model registry (MLflow, Phase 7) with signed artefacts.
- The score feeds rule R6 ("risk_score > 0.5"). The threshold is a business choice, so it lives
  in rules.yaml, not here. See docs/model-cards/risk-model.md for data, metrics and limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from ..config import REPO_ROOT

DATA = REPO_ROOT / "data" / "generated" / "customers.jsonl"
FEATURES = ["low_logins", "complaints_12m", "falling_balance", "many_products", "tenure_years", "missed_payments_90d"]
MODEL_VERSION = "risk-v1"


def features(c: dict[str, Any]) -> list[float]:
    """Feature engineering. Kept explicit and small so the model card can explain every input."""
    return [
        float(c["monthly_logins"] < 4),
        float(c["complaints_12m"]),
        float(c["balance_trend"] < -0.3),
        float(len(c["products"]) >= 3),
        c["tenure_days"] / 365,
        float(c["missed_payments_90d"]),
    ]


def load(path: Path = DATA) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@dataclass
class RiskModel:
    model: LogisticRegression
    auc: float
    n_train: int
    version: str = MODEL_VERSION

    def score(self, customer: dict[str, Any]) -> float:
        return float(self.model.predict_proba(np.array([features(customer)]))[0, 1])

    def coefficients(self) -> dict[str, float]:
        return {f: round(float(w), 3) for f, w in zip(FEATURES, self.model.coef_[0], strict=True)}


def train(rows: list[dict[str, Any]], seed: int = 7) -> RiskModel:
    X = np.array([features(r) for r in rows])
    y = np.array([r["churned"] for r in rows])
    # Hold out 25% so the AUC on the model card is measured on data the model never saw.
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=seed, stratify=y)
    m = LogisticRegression(max_iter=1000, class_weight="balanced").fit(Xtr, ytr)
    auc = float(roc_auc_score(yte, m.predict_proba(Xte)[:, 1]))
    return RiskModel(m, round(auc, 3), len(Xtr))


@lru_cache(maxsize=1)
def default_model() -> RiskModel:
    return train(load())
