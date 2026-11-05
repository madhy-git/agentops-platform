"""Pure rules-engine tests: no database, no model."""

from agentops.decision.rules import Outcome, evaluate, load_policy, rank_offers

POLICY = load_policy()
RELEASED = {"2026.11.1"}  # add a version here when you release a rules change


def ctx(**kw):
    return {"category": "general", "role": "officer", "flags": [], "risk_score": 0.1} | kw


def test_rules_file_has_a_released_version():
    # Bump `version` in policies/rules.yaml on every change, then add it to RELEASED above.
    assert POLICY.version in RELEASED


def test_fraud_fires_r1_then_r5_then_r7_in_one_decision():
    out = evaluate(POLICY, ctx(category="fraud", recommended_action="freeze_card"))
    assert out.fired == ["R1", "R5", "R7"]
    assert out.set_flags == ["fraud_flag"] and out.requires_approval and "marketing" in out.suppress_kinds


def test_out_of_window_dispute_blocks_refund_and_needs_no_approval():
    out = evaluate(POLICY, ctx(category="dispute", recommended_action="refund_review", txn_age_days=150))
    assert "refund_review" not in out.actions and not out.requires_approval  # regression: replay J5


def test_unknown_transaction_age_fires_neither_dispute_rule():
    out = evaluate(POLICY, ctx(category="dispute", txn_age_days=None))
    assert "R3" not in out.fired and "R3b" not in out.fired


def test_manager_requests_need_no_extra_approval():
    assert not evaluate(
        POLICY, ctx(category="fraud", recommended_action="freeze_card", role="manager")
    ).requires_approval


def test_high_risk_ranks_retention_first_unless_hardship():
    high = evaluate(POLICY, ctx(risk_score=0.9))
    assert rank_offers(POLICY, high, [])[0][0] == "retention_fee_waiver"
    hardship = evaluate(POLICY, ctx(risk_score=0.9, flags=["hardship_flag"]))
    assert "R6" not in hardship.fired


def test_hardship_hides_debt_products_even_if_marketing_were_allowed():
    ranked, hidden = rank_offers(POLICY, Outcome(), ["hardship_flag"])
    assert "credit_limit_increase" in hidden and "credit_limit_increase" not in ranked
