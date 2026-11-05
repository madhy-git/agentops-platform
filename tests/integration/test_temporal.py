"""Phase 5: durable approvals on Temporal (time-skipping test server; no Docker needed).

S7 after restart: the worker is stopped mid-SLA and a *new* worker finishes the workflow.
Chaos: the action fails on its first attempts; Temporal retries; idempotency keeps it exactly once.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentops.service import TriageService
from agentops.workflow import temporal_activities
from agentops.workflow.temporal_activities import ApprovalActivities
from agentops.workflow.temporal_approval import TASK_QUEUE, ApprovalInput, ApprovalWorkflow, workflow_id

SLA = 3600.0  # fraud SLA: 1 hour


def make_worker(env, schema, pool):
    acts = ApprovalActivities(schema=schema)
    # max_cached_workflows=0: no in-memory workflow cache, so every workflow task is rebuilt by *replaying*
    # history. That is exactly what happens after a crash, and it also stops the server routing tasks to a
    # dead worker's "sticky" queue (which made the restart test hang).
    return Worker(env.client, task_queue=TASK_QUEUE, workflows=[ApprovalWorkflow], max_cached_workflows=0,
                  activities=[acts.remind, acts.escalate, acts.status, acts.execute], activity_executor=pool)  # fmt: skip


@pytest.fixture
def setup(conn):
    # Sync fixture on purpose: TriageService uses PydanticAI's run_sync, which can't run inside the async
    # test's event loop. (When it was called there, the fallback chain reported it as a *model* failure.)
    schema = conn.execute("SELECT current_schema() AS s").fetchone()["s"]
    svc = TriageService(conn)
    return svc, schema, svc.triage("my card was stolen", actor="officer-1")


async def test_s7_reminder_escalation_survive_worker_restart_then_human_decides(setup, conn):
    svc, schema, o = setup
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with ThreadPoolExecutor(4) as pool:
            async with make_worker(env, schema, pool):
                handle = await env.client.start_workflow(
                    ApprovalWorkflow.run,
                    ApprovalInput(o.approval_id, SLA),
                    id=workflow_id(o.approval_id),
                    task_queue=TASK_QUEUE,
                )
                await env.sleep(timedelta(minutes=31))
                assert await handle.query(ApprovalWorkflow.current_stage) == "reminded"
            # Worker A is gone ("crash"). Note: the time-skipping test server won't advance the clock while a
            # workflow task waits for a worker, so the downtime itself isn't simulated; with a real server the
            # durable timer keeps running while no worker is alive. What we prove: a *new* worker resumes it.
            async with make_worker(env, schema, pool):  # Worker B: fresh worker, same workflow, no state handed over
                await env.sleep(timedelta(minutes=31))
                assert await handle.query(ApprovalWorkflow.current_stage) == "escalated"
                req = svc.approvals.get(o.approval_id)
                assert req["status"] == "pending" and req["assigned_to"].startswith("manager-")  # never auto-approved
                await env.sleep(timedelta(days=3))  # still waiting for a human, however long
                assert await handle.query(ApprovalWorkflow.current_stage) == "escalated"
                # A human decides (SoD checks in the DB), then tells the workflow.
                svc.approvals.decide(o.approval_id, True, req["assigned_to"], {"manager"}, req["created_at"])
                svc.cases.transition(o.case_id, "approved", req["assigned_to"], {"manager"}, req["created_at"])
                await handle.signal(ApprovalWorkflow.decided, True)
                assert await handle.result() == "card frozen"
    assert svc.cases.get(o.case_id)["state"] == "actioned"


async def test_chaos_failed_action_is_retried_and_applied_exactly_once(setup, conn):
    svc, schema, o = setup
    req = svc.approvals.decide(
        o.approval_id, True, "fraud-1", {"fraud_specialist"}, svc.approvals.get(o.approval_id)["created_at"]
    )
    svc.cases.transition(o.case_id, "approved", "fraud-1", {"fraud_specialist"}, req["decided_at"])
    temporal_activities._FAIL_FIRST["n"] = 2  # core banking times out twice
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with ThreadPoolExecutor(4) as pool:
            async with make_worker(env, schema, pool):
                handle = await env.client.start_workflow(
                    ApprovalWorkflow.run,
                    ApprovalInput(o.approval_id, SLA),
                    id=workflow_id(o.approval_id),
                    task_queue=TASK_QUEUE,
                )
                await handle.signal(ApprovalWorkflow.decided, True)
                assert await handle.result() == "card frozen"
    assert conn.execute("SELECT count(*) AS n FROM core_banking_ledger").fetchone()["n"] == 1


async def test_rejection_finishes_without_side_effect(setup, conn):
    svc, schema, o = setup
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with ThreadPoolExecutor(4) as pool:
            async with make_worker(env, schema, pool):
                handle = await env.client.start_workflow(
                    ApprovalWorkflow.run,
                    ApprovalInput(o.approval_id, SLA),
                    id=workflow_id(o.approval_id),
                    task_queue=TASK_QUEUE,
                )
                await handle.signal(ApprovalWorkflow.decided, False)
                assert await handle.result() == "rejected"
    assert conn.execute("SELECT count(*) AS n FROM core_banking_ledger").fetchone()["n"] == 0
