"""In-memory keyword retriever (TF-IDF style). No database, so unit tests stay fast.

LEARNING NOTE: the entitlement filter runs *before* scoring, i.e. restricted chunks are never
candidates. Filtering after ranking ("retrieve top-k, then drop what the user can't see") is a
common mistake: it leaks through scores and counts, and returns fewer results than asked.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from .base import Passage, can_read
from .corpus import Chunk, load_chunks


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z]{3,}", s.lower())


class KeywordRetriever:
    def __init__(self, chunks: list[Chunk] | None = None):
        self.chunks = chunks if chunks is not None else load_chunks()
        self.tf = [Counter(_tok(c.title + " " + c.text)) for c in self.chunks]
        df = Counter(t for c in self.tf for t in c)
        n = len(self.chunks)
        # Smoothed inverse document frequency: rare words count more than common ones.
        self.idf = {t: math.log((n + 1) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, roles: Iterable[str], k: int = 3) -> list[Passage]:
        roles = set(roles)
        q = _tok(query)
        scored = []
        for chunk, tf in zip(self.chunks, self.tf, strict=True):
            if not can_read(chunk.allowed_roles, roles):  # filter first (see module note)
                continue
            s = sum(tf[t] * self.idf.get(t, 0.0) for t in q)
            if s > 0:
                scored.append(Passage(chunk.source, chunk.text, round(s, 3), chunk.classification, chunk.allowed_roles))
        return sorted(scored, key=lambda p: -p.score)[:k]
