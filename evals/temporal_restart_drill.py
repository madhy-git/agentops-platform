"""S7 against a REAL Temporal server, with genuine downtime: kill the worker, let the SLA expire, restart.

Usage:
    docker compose -f deploy/docker-compose.yml --profile temporal up -d temporal
    uv run python evals/temporal_restart_drill.py

LEARNING NOTE: the in-process test server can't advance time while no worker is alive. A real server can:
its durable timer fires during the outage, and the new worker finds the workflow overdue and escalates
immediately. Compare with the naive worker (workflow/timers.py), which escalates on its next poll after it
comes back, and only because every step was written to be idempotent.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid

from temporalio.client import Client

from agentops import db
from agentops.config import settings
from agentops.service import Outcome, TriageService
from agentops.workflow.temporal_approval import TASK_QUEUE, ApprovalInput, ApprovalWorkflow

SLA_S = 20.0
# The worker runs as a separate OS process so it can be killed for real.
WORKER = """
import asyncio, sys
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker
from agentops.workflow.temporal_activities import ApprovalActivities
from agentops.workflow.temporal_approval import TASK_QUEUE, ApprovalWorkflow
async def run():
    c = await Client.connect(sys.argv[1]); a = ApprovalActivities(schema=sys.argv[2])
    with ThreadPoolExecutor(4) as pool:
        await Worker(c, task_queue=TASK_QUEUE, workflows=[ApprovalWorkflow], activity_executor=pool,
                     activities=[a.remind, a.escalate, a.status, a.execute]).run()
asyncio.run(run())
"""


def start_worker(schema: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", WORKER, settings().temporal_address, schema], env=os.environ.copy())


async def drill(svc: TriageService, o: Outcome, schema: str) -> None:
    assert o.approval_id is not None and o.case_id is not None
    t0 = time.monotonic()

    def log(msg: str) -> None:
        print(f"[t+{time.monotonic() - t0:5.1f}s] {msg}")

    client = await Client.connect(settings().temporal_address)
    worker = start_worker(schema)
    handle = await client.start_workflow(
        ApprovalWorkflow.run, ApprovalInput(o.approval_id, SLA_S), id=f"drill-{schema}", task_queue=TASK_QUEUE
    )
    log(f"workflow started, SLA {SLA_S:.0f}s, worker A pid {worker.pid}")
    while svc.approvals.get(o.approval_id)["reminded_at"] is None:
        await asyncio.sleep(0.5)
    log("reminder recorded at ~50% SLA")

    worker.kill()
    worker.wait()
    log("worker A KILLED. No worker running; SLA expires during the outage...")
    await asyncio.sleep(SLA_S / 2 + 3)
    down = svc.approvals.get(o.approval_id)["escalated_at"] is not None
    log(f"escalated while down? {down} (expected: False, nobody to run the activity)")

    worker = start_worker(schema)
    log(f"worker B started, pid {worker.pid}")
    while svc.approvals.get(o.approval_id)["escalated_at"] is None:
        await asyncio.sleep(0.5)
    req = svc.approvals.get(o.approval_id)
    log(
        f"escalated immediately on restart -> {req['assigned_to']}; status still {req['status']!r} (never auto-approved)"
    )

    svc.approvals.decide(o.approval_id, True, req["assigned_to"], {"manager"}, req["created_at"])
    svc.cases.transition(o.case_id, "approved", req["assigned_to"], {"manager"}, req["created_at"])
    await handle.signal(ApprovalWorkflow.decided, True)
    log(f"manager approved -> workflow result: {await handle.result()!r}")
    n = svc.conn.execute("SELECT count(*) AS n FROM core_banking_ledger").fetchone()
    log(f"ledger rows: {n['n'] if n else 0} (exactly once)")
    worker.kill()


if __name__ == "__main__":
    schema = f"drill_{uuid.uuid4().hex[:8]}"
    admin = db.connect()
    admin.execute(f'CREATE SCHEMA "{schema}"')
    conn = db.connect(schema=schema)
    db.migrate(conn)
    try:
        svc = TriageService(conn)
        # Triage is synchronous (PydanticAI run_sync), so it runs before the async drill starts.
        outcome = svc.triage("my card was stolen", actor="officer-1")
        asyncio.run(drill(svc, outcome, schema))
    finally:
        conn.close()
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
