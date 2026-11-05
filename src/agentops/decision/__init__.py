"""Decision service (Phase 1): deterministic rules, customer flags, lifecycle, risk score.

rules.py     - loads policies/rules.yaml and evaluates it against a context (pure, no I/O)
flags.py     - flag store in Postgres: set, clear (role-checked), active, suppression window
risk.py      - scikit-learn churn-risk model trained on synthetic data, plus its metrics
drift.py     - population stability index (PSI): is today's data still like the training data?
lifecycle.py - which lifecycle stage a customer is in after an event
service.py   - DecisionService: gathers context, runs rules, writes flags + decision log + audit

LEARNING NOTE: the LLM *recommends* (TriageResult); this package *authorises* (DecisionResult).
If the model hallucinates "issue a refund", nothing happens unless a rule allows it and, where
required, a human approves. Deterministic code is where regulated logic belongs: it is testable,
explainable with reason codes, and gives the same answer every time.
"""
