# Model card: churn-risk model `risk-v1`

<!-- LEARNING NOTE: a model card answers "can I trust this score, for what, and when not?" before
anyone wires it into a decision. Fill it in from measured numbers only. -->

| | |
|---|---|
| **Owner** | ai-platform (fictional Wattle Bank) |
| **Code** | `src/agentops/decision/risk.py` |
| **Used by** | Rule R6 (`risk_score > 0.5` ranks retention and support offers first) |
| **Type** | Logistic regression (scikit-learn), `class_weight="balanced"` |
| **Training data** | `data/generated/customers.jsonl`: 3,000 synthetic customers, seed 7; 2,250 train / 750 held-out |
| **Label** | `churned`, drawn from a hidden formula plus noise (`data/generate.py: churn_probability`) |

## Inputs
| Feature | Meaning | Learned weight |
|---|---|---|
| `low_logins` | fewer than 4 app logins a month | +1.42 |
| `complaints_12m` | complaints in the last 12 months | +0.71 |
| `falling_balance` | balance trend below −0.3 | +0.75 |
| `many_products` | holds 3+ products | −0.55 |
| `tenure_years` | tenure in years | −0.09 |
| `missed_payments_90d` | missed repayments in 90 days (not in the true formula) | +0.01 |

The weights match the direction and rough size of the hidden formula, and the model correctly gives near-zero weight to `missed_payments_90d`, which the formula doesn't use.

## Performance
| Metric | Value |
|---|---|
| AUC, held-out | **0.708** |
| AUC, drifted population (`--shift 0.6`) | 0.716 (see `docs/evals/drift.md`) |
| Base churn rate | ~13% |
| Share scored above 0.5 | ~35% |

## Limits and known issues
- **Not calibrated.** Balanced class weights push scores up: about 35% of customers score above 0.5 while about 13% churn. Treat the score as a *ranking*, not a probability. Calibrating it (e.g. `CalibratedClassifierCV`) or setting R6's threshold from a target queue size would fix the mismatch.
- **Sample size matters.** With 600 customers the model learned a complaints weight of −0.005 (the true value is +0.8), because complaints are rare. The default was raised to 3,000.
- Synthetic data only. Nothing here says anything about real customers.
- No fairness analysis: the synthetic data has no protected attributes. A real model would need one before use.

## Monitoring
- Feature and score PSI against the training population (`decision/drift.py`); investigate above 0.25.
- AUC on fresh labels, to catch concept drift that PSI can't see.
