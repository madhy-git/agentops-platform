"""Local text embeddings (BAAI/bge-small-en-v1.5 via fastembed, ONNX runtime, CPU).

LEARNING NOTES
- An embedding maps text to a vector so that similar *meaning* lands close together. That's what
  lets "someone used my card without permission" match a fraud procedure with no shared keywords,
  the exact gap the keyword retriever (and the offline triage rules) can't close.
- Local model: no API key, no per-call cost, deterministic, and no customer text leaves the machine.
  The trade-off is quality: a 384-dim small model is weaker than a hosted large one. Swap behind
  `Embedder` and re-run evals/rag_compare.py to see if a bigger model earns its cost.
- bge models want a query prefix for retrieval; documents are embedded without one. Getting this
  asymmetry wrong quietly costs several points of recall.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ..config import REPO_ROOT

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# Locally: a git-ignored folder in the repo. In the container image the model is baked in at build time
# (AGENTOPS_EMBED_CACHE=/opt/models), so pods need no internet access and can run with a read-only filesystem.
CACHE = Path(os.getenv("AGENTOPS_EMBED_CACHE", str(REPO_ROOT / ".cache" / "fastembed")))


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    def __init__(self, model: str = MODEL):
        from fastembed import TextEmbedding  # imported lazily: ~1s import, only when RAG is used

        self.model = TextEmbedding(model, cache_dir=str(CACHE))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self.model.embed([QUERY_PREFIX + text]))).tolist()


@lru_cache(maxsize=1)
def default_embedder() -> LocalEmbedder:
    return LocalEmbedder()
