"""Postgres retrieval: keyword (full-text), vector (pgvector) and hybrid (reciprocal rank fusion).

LEARNING NOTES
- Entitlements are enforced INSIDE each SQL query (`allowed_roles && %(roles)s`): Postgres never
  ranks a chunk the caller can't read. Filtering after retrieval would return fewer than k results
  and can leak through scores, counts and caches.
- *Keyword* (ts_rank) is precise on exact terms ("BSB", "chargeback") and blind to synonyms.
  *Vector* (cosine distance) matches meaning but can drift to vaguely related text.
  *Hybrid* runs both and fuses ranks with RRF: score = sum(1 / (60 + rank)). RRF uses ranks, not
  raw scores, so it doesn't need the two scales (ts_rank vs cosine) to be comparable.
- The cache is keyed by (query, roles). Keying by query alone is the classic cache leak: a manager's
  cached answer served to an officer. tests/integration/test_rag_pg.py has a test for exactly that.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

from pgvector.psycopg import register_vector

from ..audit import AuditLog
from ..db import Conn
from .base import STAFF, Passage
from .corpus import Chunk, load_chunks
from .embeddings import Embedder, default_embedder

Mode = Literal["keyword", "vector", "hybrid"]
RRF_K = 60  # standard constant from the RRF paper; dampens the advantage of rank 1 vs rank 2


def ensure_ingested(conn: Conn, chunk_size: int = 600) -> int:
    """Ingest the corpus if this chunk size isn't loaded yet. Returns the number of chunks present."""
    row = conn.execute("SELECT count(*) AS n FROM policy_chunks WHERE chunk_size = %s", (chunk_size,)).fetchone()
    return int(row["n"]) if row and row["n"] else ingest(conn, chunk_size=chunk_size)


def ingest(
    conn: Conn, chunks: list[Chunk] | None = None, chunk_size: int = 600, embedder: Embedder | None = None
) -> int:
    """(Re)load the corpus at one chunk size. Embeds every chunk once; idempotent per (size, doc, chunk)."""
    register_vector(conn)
    chunks = chunks if chunks is not None else load_chunks(max_chars=chunk_size)
    vectors = (embedder or default_embedder()).embed_documents([f"{c.title}\n{c.text}" for c in chunks])
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM policy_chunks WHERE chunk_size = %s", (chunk_size,))
        cur.executemany(
            "INSERT INTO policy_chunks (doc_id, chunk_no, title, classification, allowed_roles, chunk_size, content, embedding) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)",
            [
                (c.doc_id, c.chunk_no, c.title, c.classification, list(c.allowed_roles), chunk_size, c.text, v)
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )
    return len(chunks)


_ENTITLED = "chunk_size = %(size)s AND allowed_roles && %(roles)s"

_KEYWORD_SQL = f"""
    SELECT doc_id, chunk_no, classification, allowed_roles, content, ts_rank(tsv, q) AS score
    FROM policy_chunks, websearch_to_tsquery('english', %(query)s) q
    WHERE {_ENTITLED} AND tsv @@ q
    ORDER BY score DESC LIMIT %(k)s
"""
# `<=>` is cosine distance (0 = identical). 1 - distance gives a similarity for display.
_VECTOR_SQL = f"""
    SELECT doc_id, chunk_no, classification, allowed_roles, content, 1 - (embedding <=> %(vec)s::vector) AS score
    FROM policy_chunks
    WHERE {_ENTITLED}
    ORDER BY embedding <=> %(vec)s::vector LIMIT %(k)s
"""


class PgRetriever:
    def __init__(
        self, conn: Conn, mode: Mode = "vector", chunk_size: int = 600,  # default from evals (ADR 0006)
        embedder: Embedder | None = None, audit: AuditLog | None = None,
    ):  # fmt: skip
        register_vector(conn)
        self.conn, self.mode, self.chunk_size = conn, mode, chunk_size
        self.embedder = embedder or default_embedder()
        self.audit = audit
        self._cache: dict[tuple[str, frozenset[str], str, int], list[Passage]] = {}

    def _params(self, query: str, roles: frozenset[str], k: int) -> dict[str, Any]:
        # websearch_to_tsquery ANDs every word by default, so "how do I get a refund for a double
        # charge" would only match chunks containing *all* those words. OR the terms instead and let
        # ts_rank reward chunks that match more of them. (Stop words are dropped by Postgres.)
        terms = re.findall(r"[A-Za-z0-9]{3,}", query)
        return {"query": " or ".join(terms) or query, "roles": sorted(roles | {STAFF}), "k": k, "size": self.chunk_size}

    def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.conn.execute(sql, params).fetchall()

    def search(self, query: str, roles: Iterable[str], k: int = 3) -> list[Passage]:
        roles = frozenset(roles)
        key = (query, roles, self.mode, k)  # roles in the key: see module note on cache leaks
        if key in self._cache:
            return self._cache[key]
        params = self._params(query, roles, k)
        if self.mode != "keyword":
            params["vec"] = self.embedder.embed_query(query)

        if self.mode == "keyword":
            rows = self._rows(_KEYWORD_SQL, params)
        elif self.mode == "vector":
            rows = self._rows(_VECTOR_SQL, params)
        else:
            rows = self._hybrid(params, k)
        hits = [
            Passage(f"{r['doc_id']}#{r['chunk_no']}", r["content"], round(float(r["score"]), 4), r["classification"],
                    tuple(r["allowed_roles"]))
            for r in rows
        ]  # fmt: skip
        self._audit_filtered(query, params, hits)
        self._cache[key] = hits
        return hits

    def _hybrid(self, params: dict[str, Any], k: int) -> list[dict[str, Any]]:
        # Over-fetch from each retriever, then fuse. A chunk ranked well by both wins.
        wide = params | {"k": k * 4}
        fused: dict[tuple[str, int], dict[str, Any]] = {}
        for rows in (self._rows(_KEYWORD_SQL, wide), self._rows(_VECTOR_SQL, wide)):
            for rank, r in enumerate(rows, 1):
                entry = fused.setdefault((r["doc_id"], r["chunk_no"]), dict(r, score=0.0))
                entry["score"] += 1.0 / (RRF_K + rank)
        return sorted(fused.values(), key=lambda r: -r["score"])[:k]

    def _audit_filtered(self, query: str, params: dict[str, Any], hits: list[Passage]) -> None:
        """Record how many *relevant* chunks the caller was NOT allowed to see (count only, never content).

        This is how the copilot can say "a specialist has more on this" without leaking what.
        """
        if not self.audit:
            return
        n = len(self._hidden_rows(query, params["roles"]))
        if n:
            self.audit.record("retrieval_filtered", hidden_chunks=n, roles=params["roles"], returned=len(hits))

    # Relevance for "hidden" checks uses the vector score, not keyword overlap. ORed keywords made
    # "foreign transaction fee" look related to the hardship doc's "fee waiver" and triggered a false
    # referral (found by tests/integration/test_copilot.py). Same threshold as the copilot uses to answer.
    HIDDEN_MIN_SCORE = 0.60

    def _hidden_rows(self, query: str, held: list[str]) -> list[dict[str, Any]]:
        vec = self.embedder.embed_query(query)
        return self._rows(
            "SELECT doc_id, allowed_roles FROM policy_chunks WHERE chunk_size = %(size)s AND NOT (allowed_roles && %(roles)s) "
            "AND 1 - (embedding <=> %(vec)s::vector) >= %(min)s",
            {"size": self.chunk_size, "roles": held, "vec": vec, "min": self.HIDDEN_MIN_SCORE},
        )

    def hidden_roles(self, query: str, roles: Iterable[str]) -> set[str]:
        """Which roles could see relevant matches the caller can't. Metadata only: used to pick a queue."""
        held = sorted(set(roles) | {STAFF})
        return {r for row in self._hidden_rows(query, held) for r in row["allowed_roles"]}

    def hidden_count(self, query: str, roles: Iterable[str]) -> int:
        return len(self._hidden_rows(query, sorted(set(roles) | {STAFF})))
