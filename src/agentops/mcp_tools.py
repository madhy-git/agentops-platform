"""Consume MCP Case Tools (the sibling repo) as the agent's case source.

Enable with AGENTOPS_CASE_SOURCE=mcp. Install the sibling repo into this venv first:
    uv pip install -e ../mcp-case-tools

Why not a dependency in pyproject.toml? A path dependency on a *sibling repo* (`../mcp-case-tools`) gets
written into uv.lock, and then every Docker build and every CI run of this repo fails, because neither has
the sibling folder. Cross-repo dependencies need a published package or a git URL. Until the repo is
published, it's an explicit local install, and tests that need it skip cleanly.

LEARNING NOTES
- The agent's `lookup_case` tool stays the same; only `Deps.case_lookup` changes. That is the
  payoff of injecting dependencies: swap the static dict for an MCP server without touching agent.py.
- *Identity flows through*: the MCP server is built for the calling human's role, so the MCP layer
  enforces the same least privilege again. Two independent checks (agentops and MCP) must both
  allow an action. Neither trusts the model.
- Transport: in-process here (fast, testable). In production you'd connect over stdio or streamable
  HTTP (`mcp.Client("https://.../mcp")`) and pass the user's token so the server can verify it
  itself, instead of trusting a role handed over by the caller.
- The agent's tools are sync and run in a worker thread, so `anyio.run` can start a short-lived
  event loop per call. Simple, not fast. An async agent would keep one session open.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anyio

# Agentops roles -> the single role MCP Case Tools expects (it models one role per principal).
_MCP_ROLE_ORDER = ("manager", "fraud_specialist", "hardship_specialist", "officer", "viewer")


def mcp_role(roles: frozenset[str]) -> str:
    return next((r for r in _MCP_ROLE_ORDER if r in roles), "viewer")


def mcp_case_lookup(user: str, roles: frozenset[str], profile: str = "wattle") -> Callable[[str], dict[str, Any]]:
    from mcp import Client
    from mcp.types import TextContent
    from mcp_case_tools.policy import AuditLog, Principal
    from mcp_case_tools.server import build_server

    audit = AuditLog()
    server = build_server(Principal(user, mcp_role(roles)), audit=audit, profile=profile)

    async def _get(case_id: str) -> dict[str, Any]:
        async with Client(server) as c:
            r = await c.call_tool("get_case", {"case_id": case_id})
            first = r.content[0]
            # Tools may return images or resources, not only text; only text is expected from get_case.
            text = first.text if isinstance(first, TextContent) else str(first)
            return {"error": text} if r.is_error else dict(json.loads(text))

    def lookup(case_id: str) -> dict[str, Any]:
        return anyio.run(_get, case_id)

    lookup.audit = audit  # type: ignore[attr-defined]  # exposed so tests and demos can read the MCP-side audit
    return lookup
