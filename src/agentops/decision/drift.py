"""Population Stability Index (PSI): has the input data moved away from what the model learned?

LEARNING NOTES
- *Data drift*: the inputs change (fewer app logins after a redesign) but the relationship between
  inputs and outcome is the same. PSI on features catches it.
- *Concept drift*: the relationship itself changes (a competitor's offer makes loyal customers
  leave). Features can look stable while the model gets worse; only outcome monitoring (AUC on
  fresh labels) catches it. PSI is necessary, not sufficient.
- Rule of thumb: PSI < 0.1 stable, 0.1-0.25 watch, > 0.25 investigate / retrain.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def psi(expected: Sequence[float], actual: Sequence[float], bins: int = 10) -> float:
    e, a = np.asarray(expected, float), np.asarray(actual, float)
    # Bin edges come from the *expected* (training) distribution, so both are measured on one scale.
    edges = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:  # (near-)constant or binary feature: fall back to its distinct values
        edges = np.unique(np.concatenate([e, a]))
        edges = np.append(edges, edges[-1] + 1)
    e_pct = np.histogram(e, edges)[0] / len(e)
    a_pct = np.histogram(np.clip(a, edges[0], edges[-1]), edges)[0] / len(a)
    # Small floor avoids log(0) when a bin is empty in one sample.
    e_pct, a_pct = np.clip(e_pct, 1e-4, None), np.clip(a_pct, 1e-4, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def verdict(value: float) -> str:
    return "stable" if value < 0.1 else "watch" if value < 0.25 else "investigate"
