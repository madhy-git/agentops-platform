"""Minimal retrieval with citations. Retriever is a protocol so a LlamaIndex/pgvector
implementation can replace this keyword retriever without touching the agent."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Passage:
    source: str
    text: str
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 3) -> list[Passage]: ...


POLICIES = {
    "POL-001 Hardship": "Customers in financial hardship must be offered a hardship review. Escalate to a human officer before any fee waiver or repayment variation.",
    "POL-002 Disputes": "Card disputes must be logged within 24 hours. Refunds above 500 dollars require human approval.",
    "POL-003 Fraud": "Suspected fraud or scams: freeze the card, escalate to the fraud team immediately, never ask the customer for full card numbers.",
    "POL-004 Complaints": "Complaints must be acknowledged within 24 hours and resolved or escalated within 30 days. Record every decision in the audit log.",
    "POL-005 General": "General enquiries about fees, statements and account features can be answered from the product guide without escalation.",
}


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z]{3,}", s.lower())


class KeywordRetriever:
    def __init__(self, docs: dict[str, str] | None = None):
        self.docs = docs or POLICIES
        self.tf = {k: Counter(_tok(v)) for k, v in self.docs.items()}
        df = Counter(t for c in self.tf.values() for t in c)
        n = len(self.docs)
        self.idf = {t: math.log((n + 1) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 3) -> list[Passage]:
        q = _tok(query)
        scored = []
        for src, tf in self.tf.items():
            s = sum(tf[t] * self.idf.get(t, 0.0) for t in q)
            if s > 0:
                scored.append(Passage(src, self.docs[src], round(s, 3)))
        return sorted(scored, key=lambda p: -p.score)[:k]
