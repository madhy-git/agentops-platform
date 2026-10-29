"""Human-in-the-loop approval queue plus an append-only audit log (in memory, or SQLite if a path is given)."""
from __future__ import annotations

import itertools
import json
import sqlite3
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
    def __init__(self, db_path: str | None = None):
        self.items: dict[int, Approval] = {}
        self._mem: list[dict] = []
        self._db = None
        if db_path:
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts REAL, event TEXT, data TEXT)")

    def log(self, event: str, **data):
        ts = time.time()
        if self._db:
            # Append-only by convention: nothing in the app issues UPDATE or DELETE on this table.
            with self._db:
                self._db.execute("INSERT INTO audit (ts, event, data) VALUES (?, ?, ?)", (ts, event, json.dumps(data)))
        else:
            self._mem.append({"ts": ts, "event": event, **data})

    @property
    def audit(self) -> list[dict]:
        if not self._db:
            return self._mem
        rows = self._db.execute("SELECT ts, event, data FROM audit ORDER BY id").fetchall()
        return [{"ts": ts, "event": ev, **json.loads(d)} for ts, ev, d in rows]

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
