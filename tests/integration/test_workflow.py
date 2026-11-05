"""Phase 4 workflow: state machine, approvals (domain, SoD), timers (S7), idempotent actions (S8)."""

import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta

import pytest

from agentops.service import TriageService
from agentops.workflow.approvals import ApprovalError
from agentops.workflow.cases import InvalidTransition
from agentops.workflow.timers import TimerWorker

T0 = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


@pytest.fixture
def svc(conn):
    return TriageService(conn)


def fraud_case(svc, actor="officer-1"):
    return svc.triage("my card was stolen", actor=actor, now=T0)


# -- state machine ---------------------------------------------------------------------------------


def test_invalid_transition_is_rejected_and_audited(svc):
    o = svc.triage("How do I download my statement?", now=T0)
    with pytest.raises(InvalidTransition):
        svc.cases.transition(o.case_id, "actioned", "officer-1", {"officer"}, T0)
    assert svc.audit.events()[-1]["data"]["rejected"].startswith("in_progress -> actioned")


def test_only_managers_escalate(svc):
    o = svc.triage("How do I download my statement?", now=T0)
    with pytest.raises(InvalidTransition, match="manager"):
        svc.cases.transition(o.case_id, "escalated", "officer-1", {"officer"}, T0)
    assert svc.cases.transition(o.case_id, "escalated", "manager-1", {"manager"}, T0)["state"] == "escalated"


def test_full_happy_path_states(svc):
    o = fraud_case(svc)
    svc.decide(o.approval_id, True, "fraud-1", {"fraud_specialist"}, now=T0)
    assert svc.cases.get(o.case_id)["state"] == "actioned"
    for to in ("resolved", "closed"):
        svc.cases.transition(o.case_id, to, "officer-1", {"officer"}, T0)
    assert svc.audit.events()[-1]["event"] == "case_closed"


# -- approvals --------------------------------------------------------------------------------------


def test_fraud_approval_routed_to_least_loaded_fraud_specialist(svc):
    a, b = fraud_case(svc), fraud_case(svc)
    assignees = {svc.approvals.get(x.approval_id)["assigned_to"] for x in (a, b)}
    assert assignees == {"fraud-1", "fraud-2"}  # workload spread, both in the right domain


def test_separation_of_duties(svc):
    o = fraud_case(svc, actor="fraud-1")  # a fraud specialist raised it...
    with pytest.raises(ApprovalError, match="separation of duties"):
        svc.decide(o.approval_id, True, "fraud-1", {"fraud_specialist"}, now=T0)  # ...and can't approve it


def test_wrong_domain_cannot_approve(svc):
    o = fraud_case(svc)
    with pytest.raises(ApprovalError, match="fraud"):
        svc.decide(o.approval_id, True, "hardship-1", {"hardship_specialist"}, now=T0)


def test_officer_specialist_manager_behave_differently(svc):
    o = svc.triage("I lost my job and can't pay", now=T0)
    with pytest.raises(ApprovalError):
        svc.decide(o.approval_id, True, "officer-2", {"officer"}, now=T0)
    assert svc.decide(o.approval_id, True, "hardship-1", {"hardship_specialist"}, now=T0)[1] == "hardship review opened"
    o2 = svc.triage("I lost my job and can't pay", now=T0)
    assert svc.decide(o2.approval_id, True, "manager-1", {"manager"}, now=T0)[1] == "hardship review opened"


# -- S7: timers ---------------------------------------------------------------------------------------


def test_s7_reminder_then_escalation_never_auto_approve_survives_restart(svc, conn):
    o = fraud_case(svc)  # fraud SLA = 1 hour
    assert TimerWorker(conn).tick(T0 + timedelta(minutes=10)) == {"reminded": [], "escalated": []}
    assert TimerWorker(conn).tick(T0 + timedelta(minutes=31))["reminded"] == [o.approval_id]
    assert TimerWorker(conn).tick(T0 + timedelta(minutes=40))["reminded"] == []  # idempotent: once only
    # "Restart": a brand-new worker instance, past the SLA.
    assert TimerWorker(conn).tick(T0 + timedelta(minutes=61))["escalated"] == [o.approval_id]
    req = svc.approvals.get(o.approval_id)
    assert req["status"] == "pending"  # never auto-approved
    assert req["assigned_to"].startswith("manager-")
    assert [r["id"] for r in svc.approvals.pending_for("manager-2", {"manager"})] == [o.approval_id]


# -- S8: idempotency + crash recovery ------------------------------------------------------------------


def ledger_rows(conn):
    return conn.execute("SELECT count(*) AS n FROM core_banking_ledger").fetchone()["n"]


def test_retrying_an_approved_action_does_not_repeat_the_side_effect(svc, conn):
    o = fraud_case(svc)
    req, effect = svc.decide(o.approval_id, True, "fraud-1", {"fraud_specialist"}, now=T0)
    again = svc.executor.execute(svc.approvals.get(o.approval_id), "fraud-1", T0)  # a retry / double-click
    assert effect == again == "card frozen" and ledger_rows(conn) == 1


def test_s8_kill_mid_action_then_recover_exactly_once(svc, conn):
    o = fraud_case(svc)
    approval = svc.approvals.decide(o.approval_id, True, "fraud-1", {"fraud_specialist"}, T0)
    svc.cases.transition(o.case_id, "approved", "fraud-1", {"fraud_specialist"}, T0)
    schema = conn.execute("SELECT current_schema() AS s").fetchone()["s"]
    # A separate process runs the action and dies (exit 137, like kill -9) after the side effect,
    # before it can record success.
    script = textwrap.dedent(f"""
        from datetime import datetime, UTC
        from agentops import db
        from agentops.audit import AuditLog
        from agentops.workflow.actions import ActionExecutor
        from agentops.workflow.cases import CaseStore
        c = db.connect(schema="{schema}")
        a = AuditLog(c)
        ex = ActionExecutor(c, a, CaseStore(c, a))
        ex.execute(c.execute("SELECT * FROM approval_requests WHERE id={approval["id"]}").fetchone(), "fraud-1", datetime.now(UTC))
    """)
    proc = subprocess.run([sys.executable, "-c", script], env=os.environ | {"AGENTOPS_CRASH_AFTER_SIDE_EFFECT": "1"})
    assert proc.returncode == 137
    # Unknown state: side effect applied, bookkeeping not.
    assert ledger_rows(conn) == 1
    assert conn.execute("SELECT status FROM actions").fetchone()["status"] == "started"
    # The worker starts up and recovers.
    recovered = svc.executor.recover("system", T0)
    assert recovered == ["card frozen"] and ledger_rows(conn) == 1  # finished, and still exactly once
    assert conn.execute("SELECT status FROM actions").fetchone()["status"] == "succeeded"
    assert svc.cases.get(o.case_id)["state"] == "actioned"
