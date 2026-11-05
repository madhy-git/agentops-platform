"""Durable approval workflow on Temporal (Phase 5, scenario S7 after restart).

    start --(50% SLA, no decision)--> remind --(100% SLA, no decision)--> escalate --> wait for decision
      any time: signal `decided(approved)` --> approved? execute (retried, idempotent) : finish

Run a worker:  docker compose -f deploy/docker-compose.yml --profile temporal up -d temporal
               uv run python -m agentops.workflow.temporal_approval

LEARNING NOTES
- *Workflow code must be deterministic.* After a crash, Temporal rebuilds the workflow's state by
  *replaying* its event history through this code. So: no database calls, no `datetime.now()`, no
  random numbers, no network here. Use `workflow.now()`, timers and activities instead. The SDK runs
  workflows in a sandbox that blocks most non-deterministic imports to catch mistakes early.
- `wait_condition(..., timeout=...)` is a *durable timer*: it lives in the Temporal server, not in
  this process. Kill the worker, and the timer still fires; the next worker picks the workflow up
  exactly where it was. That's what the naive polling worker approximated with idempotent UPDATEs.
- A timeout never approves. After escalation the workflow waits for a human for as long as it takes.
- The database stays the source of truth for *who decided what* (SoD checks in approvals.py).
  The workflow owns *time* and *orchestration*, and is told about decisions by a signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .temporal_activities import ApprovalActivities

TASK_QUEUE = "approvals"
EXECUTE_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2.0, maximum_attempts=10)


@dataclass
class ApprovalInput:
    approval_id: int
    sla_seconds: float


@workflow.defn
class ApprovalWorkflow:
    def __init__(self) -> None:
        self.decision: bool | None = None
        self.stage = "waiting"

    @workflow.signal
    def decided(self, approved: bool) -> None:
        self.decision = approved

    @workflow.query
    def current_stage(self) -> str:
        return self.stage

    @workflow.run
    async def run(self, inp: ApprovalInput) -> str:
        half = timedelta(seconds=inp.sla_seconds / 2)
        # Activities are referenced unbound (Class.method): the workflow names *what* to run; the worker
        # supplies the instance (with its DB settings). Workflow code never touches the database.
        timeout = timedelta(seconds=30)  # each activity attempt must finish within this

        # Durable timer #1: wait for a decision for half the SLA.
        if not await self._decided_within(half):
            await workflow.execute_activity_method(
                ApprovalActivities.remind, inp.approval_id, start_to_close_timeout=timeout
            )
            self.stage = "reminded"
            # Durable timer #2: the rest of the SLA.
            if not await self._decided_within(half):
                await workflow.execute_activity_method(
                    ApprovalActivities.escalate, inp.approval_id, start_to_close_timeout=timeout
                )
                self.stage = "escalated"
                await workflow.wait_condition(lambda: self.decision is not None)  # no timeout: never auto-approve

        if not self.decision:
            self.stage = "rejected"
            return "rejected"
        self.stage = "executing"
        effect: str = await workflow.execute_activity_method(
            ApprovalActivities.execute, inp.approval_id, retry_policy=EXECUTE_RETRY, start_to_close_timeout=timeout
        )
        self.stage = "done"
        return str(effect)

    async def _decided_within(self, timeout: timedelta) -> bool:
        try:
            await workflow.wait_condition(lambda: self.decision is not None, timeout=timeout)
            return True
        except TimeoutError:
            return False


def workflow_id(approval_id: int) -> str:
    """Deterministic id: starting the same approval twice is rejected by Temporal (idempotent start)."""
    return f"approval-{approval_id}"


async def main() -> None:  # pragma: no cover - long-running worker
    from concurrent.futures import ThreadPoolExecutor

    from temporalio.client import Client
    from temporalio.worker import Worker

    from ..config import settings

    client = await Client.connect(settings().temporal_address)
    acts = ApprovalActivities()
    with ThreadPoolExecutor(max_workers=8) as pool:
        worker = Worker(client, task_queue=TASK_QUEUE, workflows=[ApprovalWorkflow],
                        activities=[acts.remind, acts.escalate, acts.status, acts.execute], activity_executor=pool)  # fmt: skip
        print(f"approval worker on {settings().temporal_address}, queue {TASK_QUEUE}")
        await worker.run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
