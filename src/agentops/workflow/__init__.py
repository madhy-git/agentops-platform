"""Workflow (Phase 4): cases, approvals with SLAs, idempotent actions, and the timer worker.

cases.py     - case state machine (project.md "Case workflow and state machine")
approvals.py - approval requests: domain routing, separation of duties, decisions
actions.py   - idempotent execution against the (fake) core-banking ledger + crash recovery
timers.py    - the timer worker: reminder at 50% of SLA, escalate and reassign at 100%

LEARNING NOTE: this is the *naive* durable version: Postgres rows plus a polling worker. It
survives restarts because all state is in the database and every timer step is idempotent. Phase 5
rebuilds approvals on Temporal; comparing the two is the point (docs/adr/0008).
"""
