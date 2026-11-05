"""Load the synthetic policy corpus and split it into chunks.

LEARNING NOTES
- Each document's front matter carries its *classification* and *allowed_roles*. That metadata
  is copied onto every chunk, because retrieval returns chunks, not documents. Lose the metadata
  at chunking time and no later filter can recover it ("missing metadata" failure mode).
- Chunking: split on paragraphs, then pack paragraphs up to `max_chars`. Chunk size is a real
  tuning knob; evals/rag_compare.py sweeps it. Too small loses context; too large dilutes the
  match and wastes prompt tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..config import REPO_ROOT

POLICY_DIR = REPO_ROOT / "data" / "policies"


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_no: int
    title: str
    classification: str
    allowed_roles: tuple[str, ...]
    text: str

    @property
    def source(self) -> str:
        return f"{self.doc_id}#{self.chunk_no}"


def load_documents(directory: Path = POLICY_DIR) -> list[dict]:
    docs = []
    for path in sorted(directory.glob("*.md")):
        _, front, body = path.read_text().split("---", 2)
        meta = yaml.safe_load(front)
        docs.append({**meta, "body": body.strip()})
    return docs


def chunk_document(doc: dict, max_chars: int = 600) -> list[Chunk]:
    paragraphs = [p.strip() for p in doc["body"].split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        # Start a new chunk when adding this paragraph would overflow (but never emit an empty one).
        if buf and len(buf) + len(p) + 2 > max_chars:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return [
        Chunk(doc["id"], i, doc["title"], doc["classification"], tuple(doc["allowed_roles"]), text)
        for i, text in enumerate(chunks, 1)
    ]


def load_chunks(max_chars: int = 600, directory: Path = POLICY_DIR) -> list[Chunk]:
    return [c for d in load_documents(directory) for c in chunk_document(d, max_chars)]
