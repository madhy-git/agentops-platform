"""Circuit breaker for model calls.

LEARNING NOTES (found in the Phase 4 incident drill: docs/incidents/2026-11-04-tier2-outage-drill.md)
- Without a breaker, every request routed to a dead model tries it first, waits for the timeout,
  then falls back. In the drill: 12 failed attempts for 12 requests. With a real 30 s timeout that's
  30 s of extra latency for every affected customer, for the whole outage.
- A breaker counts consecutive failures per model. After `threshold` failures it *opens*: the model
  is skipped for `cooldown_s`. Then it goes *half-open*: one request is let through as a probe;
  success closes the breaker, failure opens it again.
- Breakers are per process and in memory: each API replica learns about the outage on its own after
  `threshold` failures. A shared breaker (Redis) is a later optimisation, not a correctness need.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _states: dict[str, _State] = field(default_factory=dict)

    def allow(self, name: str) -> bool:
        s = self._states.setdefault(name, _State())
        if s.opened_at is None:
            return True
        # Cooldown over = half-open: let one probe through; record_* decides what happens next.
        return self.clock() - s.opened_at >= self.cooldown_s

    def record_success(self, name: str) -> None:
        self._states[name] = _State()

    def record_failure(self, name: str) -> None:
        s = self._states.setdefault(name, _State())
        s.failures += 1
        if s.failures >= self.threshold:
            s.opened_at = self.clock()  # open (or re-open after a failed probe)

    def is_open(self, name: str) -> bool:
        s = self._states.get(name)
        return bool(s and s.opened_at is not None and self.clock() - s.opened_at < self.cooldown_s)


# Shared by all TriageService instances in this process.
BREAKER = CircuitBreaker()
