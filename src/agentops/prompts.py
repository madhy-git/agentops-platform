"""Versioned prompts loaded from prompts/<id>.v<major>.md.

LEARNING NOTES
- A prompt is production behaviour, so it gets the same treatment as code: reviewed in a PR,
  versioned, and stamped on every trace and audit event (`prompt_version`). When a metric moves,
  you can ask "which prompt version was live?" and get an answer.
- Front matter (between the `---` lines) holds metadata; the body is the prompt text.
- Changing the body without bumping `version` is caught by tests/unit/test_prompts.py, which
  keeps a hash of each released version.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import yaml

from .config import REPO_ROOT

PROMPT_DIR = REPO_ROOT / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    text: str

    @property
    def sha(self) -> str:
        """Short content hash: proves which exact text ran, even if someone forgot to bump version."""
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]


def load(prompt_id: str, major: int | None = None) -> Prompt:
    # Feature flag: AGENTOPS_PROMPT_<ID>_MAJOR=2 switches to prompts/<id>.v2.md without a deploy.
    # Rollback = unset the variable. See docs/release.md.
    if major is None:
        major = int(os.getenv(f"AGENTOPS_PROMPT_{prompt_id.upper()}_MAJOR", "1"))
    raw = (PROMPT_DIR / f"{prompt_id}.v{major}.md").read_text()
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front)
    return Prompt(meta["id"], str(meta["version"]), body.strip())
