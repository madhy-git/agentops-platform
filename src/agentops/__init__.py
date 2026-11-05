"""AgentOps Platform: the operational layer around an AI agent. See docs/STRUCTURE.md for a map."""

import os

# PydanticAI prints a promotional banner on first run; it clutters eval and test output.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

__version__ = "0.4.0"
