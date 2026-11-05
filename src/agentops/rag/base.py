"""The retrieval contract.

LEARNING NOTES
- The agent depends on this Protocol, never on a concrete retriever. That is what lets Phase 2
  swap the keyword retriever for pgvector hybrid search without touching agent.py.
- `roles` is part of the *interface*, not an optional extra. If a retriever can be called
  without saying who is asking, someone eventually will, and restricted text leaks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

# Every staff principal implicitly has "staff"; public documents are readable by "staff".
STAFF = "staff"


@dataclass(frozen=True)
class Passage:
    source: str  # citation id, e.g. "POL-FRAUD-01#2" (document id + chunk number)
    text: str
    score: float
    classification: str = "public"
    # Who may read this passage. Carried forward into anything derived from it (answers, memory),
    # so derived text can never be shown to someone who couldn't read the source.
    allowed_roles: tuple[str, ...] = (STAFF,)


class Retriever(Protocol):
    def search(self, query: str, roles: Iterable[str], k: int = 3) -> list[Passage]: ...


def can_read(allowed_roles: Iterable[str], roles: Iterable[str]) -> bool:
    """Entitlement check shared by every retriever: any overlap between allowed and held roles."""
    return bool(set(allowed_roles) & ({STAFF} | set(roles)))
