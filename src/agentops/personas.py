"""Demo sign-in for the web app: pick a fictional person, get a signed dev token.

LEARNING NOTES
- A browser can't mint its own tokens (that would need the signing secret in JavaScript, readable by anyone).
  So the API mints them, for a fixed list of fictional people, and ONLY when two things are true:
  AGENTOPS_DEV_LOGIN=1 is set, and no real identity provider (JWKS URL) is configured. On AWS, Cognito is
  configured, so this endpoint refuses even if someone sets the flag by mistake (tests/integration/test_portal.py).
- "Log in as anyone" is exactly what an attacker wants, which is why it is opt-in, double-guarded, and
  every dev login is audited. Production sign-in is the identity provider's authorization-code flow (PKCE).
- Customers are real rows from data/generated/customers.jsonl, seeded on start-up (`seed_demo_customers`),
  so the rules engine sees their flags and history like any other customer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .config import REPO_ROOT
from .db import Conn
from .decision.service import load_customers
from .workflow.approvals import STAFF


@dataclass(frozen=True)
class Persona:
    username: str
    display_name: str
    roles: tuple[str, ...]
    kind: str  # "customer" | "staff"
    blurb: str
    customer_id: str | None = None


_STAFF_BLURBS = {
    "officer-1": ("Alex Officer", "Front-line officer: triages messages, asks the copilot"),
    "fraud-1": ("Fiona Fraud", "Fraud specialist: approves card blocks"),
    "fraud-2": ("Farid Fraud", "Fraud specialist (second on the roster)"),
    "hardship-1": ("Harper Hardship", "Hardship specialist: sees hardship options"),
    "disputes-1": ("Dana Disputes", "Disputes officer"),
    "manager-1": ("Morgan Manager", "Manager: approves anything, reads the audit trail"),
    "compliance-1": ("Casey Compliance", "Compliance: read-only, audit trail"),
}
# First three generated customers; their names come from the data file, so the two never disagree.
DEMO_CUSTOMER_IDS = ("CUS-00001", "CUS-00002", "CUS-00003")
CUSTOMERS_FILE = REPO_ROOT / "data" / "generated" / "customers.jsonl"


def _demo_customers() -> list[dict]:
    rows = []
    with CUSTOMERS_FILE.open() as f:
        for line in f:
            row = json.loads(line)
            if row["customer_id"] in DEMO_CUSTOMER_IDS:
                rows.append(row)
            if len(rows) == len(DEMO_CUSTOMER_IDS):
                break
    return rows


def personas() -> list[Persona]:
    customers = [
        Persona(
            username=c["name"].lower().replace(" ", "."),
            display_name=c["name"],
            roles=("customer",),
            kind="customer",
            blurb=f"Customer · {', '.join(p.replace('_', ' ') for p in c['products'])}",
            customer_id=c["customer_id"],
        )
        for c in _demo_customers()
    ]
    staff = [Persona(u, name, tuple(sorted(STAFF[u])), "staff", blurb) for u, (name, blurb) in _STAFF_BLURBS.items()]
    return customers + staff


def find(username: str) -> Persona | None:
    return next((p for p in personas() if p.username == username), None)


def as_dict(p: Persona) -> dict:
    return asdict(p)


def seed_demo_customers(conn: Conn) -> None:
    """Make sure the demo customers exist (idempotent: ON CONFLICT DO NOTHING)."""
    load_customers(conn, _demo_customers())
