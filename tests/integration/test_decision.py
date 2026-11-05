"""Decision service wired into triage, against Postgres."""

from datetime import UTC, datetime

import pytest

from agentops.decision.flags import FlagPermissionError
from agentops.decision.service import load_customers
from agentops.service import TriageService

CUSTOMER = {
    "customer_id": "CUS-T1", "name": "Test", "lifecycle_stage": "everyday", "vulnerable": False,
    "monthly_logins": 20, "complaints_12m": 0, "balance_trend": 0.1, "products": ["everyday"],
    "tenure_days": 900, "missed_payments_90d": 0,
}  # fmt: skip


@pytest.fixture
def svc(conn):
    load_customers(
        conn, [CUSTOMER],
        [{"txn_id": "TXN-OLD", "customer_id": "CUS-T1", "date": "2026-01-02", "merchant": "x", "amount": 900}],
    )  # fmt: skip
    return TriageService(conn)


def test_fraud_triage_sets_flag_logs_decision_and_links_approval(svc, conn):
    o = svc.triage("my card was stolen", customer_id="CUS-T1")
    assert o.decision.reason_codes[:2] == ["FRAUD_SUSPECTED", "NEEDS_APPROVAL"]
    assert svc.decisions.flags.active("CUS-T1") == ["fraud_flag"]
    appr = svc.approvals.get(o.approval_id)
    assert appr["decision_id"] == o.decision.decision_id and appr["action"] == "block_card"
    assert svc.decisions.customer("CUS-T1")["lifecycle_stage"] == "distress"
    _, effect = svc.decide(o.approval_id, True, "fraud-1", {"fraud_specialist"})
    assert effect == "card frozen"


def test_rules_force_review_even_when_model_says_no(svc, conn):
    # The offline model marks "general" as needs_human=False; an out-of-window dispute isn't regulated,
    # but an in-window refund requested by an officer is (R5), whatever the model thinks.
    o = svc.triage("please refund the wrong charge", customer_id="CUS-T1")
    assert o.status == "pending_approval"


def test_dispute_on_old_transaction_is_not_auto_progressed(svc):
    o = svc.triage("I want to dispute a wrong charge", customer_id="CUS-T1", txn_id="TXN-OLD")
    assert "DISPUTE_OUT_OF_WINDOW" in o.decision.reason_codes and "refund_review" not in o.decision.actions


def test_only_the_right_role_can_clear_a_flag(svc):
    svc.triage("my card was stolen", customer_id="CUS-T1")
    with pytest.raises(FlagPermissionError):
        svc.decisions.clear_flag("CUS-T1", "fraud_flag", "officer-1", {"officer"})
    svc.decisions.clear_flag("CUS-T1", "fraud_flag", "fs-1", {"fraud_specialist"})
    assert svc.decisions.marketing_suppressed("CUS-T1", datetime.now(UTC))  # still in cooling-off
