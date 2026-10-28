"""Human-in-the-loop approval queue plus an append-only audit log."""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

_ids = itertools.count(1)


@dataclass
class Approval:
    id: int
    case_text: str
    proposed_action: str
    status: str = "pending"  # pending | approved | rejected
    reviewer: str | None = None
    created: float = field(default_factory=time.time)


class ApprovalStore:
    def __init__(self):
        self.items: dict[int, Approval] = {}
        self.audit: list[dict] = []

    def log(self, event: str, **data):
        self.audit.append({"ts": time.time(), "event": event, **data})

    def request(self, case_text: str, action: str) -> Approval:
        a = Approval(next(_ids), case_text, action)
        self.items[a.id] = a
        self.log("approval_requested", approval_id=a.id, action=action)
        return a

    def decide(self, approval_id: int, approve: bool, reviewer: str) -> Approval:
        a = self.items[approval_id]
        if a.status != "pending":
            raise ValueError("already decided")
        a.status, a.reviewer = ("approved" if approve else "rejected"), reviewer
        self.log("approval_decided", approval_id=a.id, status=a.status, reviewer=reviewer)
        return a

    def pending(self) -> list[Approval]:
        return [a for a in self.items.values() if a.status == "pending"]
