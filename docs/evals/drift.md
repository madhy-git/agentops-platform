# Drift report (synthetic)

Baseline = training population. Drifted = `data/generate.py --shift 0.6` (same churn formula, shifted inputs).

| Signal | PSI | Verdict |
|---|---|---|
| feature `monthly_logins` | 0.491 | investigate |
| feature `balance_trend` | 0.471 | investigate |
| feature `missed_payments_90d` | 0.062 | stable |
| feature `complaints_12m` | 0.001 | stable |
| feature `tenure_days` | 0.004 | stable |
| **risk score** | 0.201 | watch |

| Outcome check | Baseline | Drifted |
|---|---|---|
| AUC | 0.708 (held-out) | 0.716 |
| Share above R6 threshold (0.5) | 35.2% | 52.4% |

**Reading it:** inputs moved (PSI high) and many more customers now cross the R6 threshold, so the
retention queue would grow sharply overnight. AUC held, so the model still ranks customers well:
this is data drift, not concept drift. The *business* question is whether R6's fixed 0.5 threshold
is still right when the population shifts. That's a policy decision, which is why it lives in rules.yaml.
