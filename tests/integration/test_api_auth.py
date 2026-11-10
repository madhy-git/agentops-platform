"""Phase 4: identity from JWT claims; different roles get different powers through the API."""

import jwt
import pytest
from fastapi.testclient import TestClient

from agentops.api import create_app
from agentops.auth import AUDIENCE, dev_token, principal_from_claims


@pytest.fixture
def client(conn):
    return TestClient(create_app(conn))


def h(user, *roles):
    return {"Authorization": f"Bearer {dev_token(user, list(roles))}"}


def test_no_token_or_forged_token_is_rejected(client):
    assert client.post("/triage", json={"message": "hi"}).status_code == 401
    forged = jwt.encode({"sub": "x", "roles": ["manager"], "aud": AUDIENCE, "exp": 9999999999}, "wrong-secret", "HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_for_another_audience_is_rejected(client):
    from agentops.config import settings

    tok = jwt.encode(
        {"sub": "x", "roles": ["manager"], "aud": "other-app", "exp": 9999999999}, settings().jwt_secret, "HS256"
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_keycloak_claims_map_to_app_roles_only():
    p = principal_from_claims({"sub": "u1", "preferred_username": "fraud-1",
                               "realm_access": {"roles": ["fraud_specialist", "offline_access", "uma_authorization"]}})  # fmt: skip
    assert p.user == "fraud-1" and p.roles == {"fraud_specialist"}


def test_end_to_end_roles_through_the_api(client):
    r = client.post("/triage", json={"message": "My card was stolen"}, headers=h("officer-1", "officer")).json()
    aid = r["approval_id"]
    assert r["status"] == "pending_approval"
    # An officer can't approve, and can't read the audit log.
    assert (
        client.post(f"/approvals/{aid}/decision", json={"approve": True}, headers=h("officer-2", "officer")).status_code
        == 403
    )
    assert client.get("/audit", headers=h("officer-1", "officer")).status_code == 403
    # The assigned fraud specialist sees it in their queue and approves it.
    mine = client.get("/approvals/mine", headers=h("fraud-1", "officer", "fraud_specialist")).json()
    assert [m["id"] for m in mine] == [aid]
    d = client.post(
        f"/approvals/{aid}/decision", json={"approve": True}, headers=h("fraud-1", "fraud_specialist")
    ).json()
    assert d["effect"] == "card frozen"
    # A manager can read the audit trail, including the officer's denied attempt.
    events = client.get("/audit", headers=h("manager-1", "manager")).json()
    assert any(e["event"] == "action_denied" and e["reason_code"] == "APPROVAL_NOT_PERMITTED" for e in events)


def test_ready_reports_a_dead_database_connection(conn):
    # Regression: after Postgres restarted in the local cluster, /health said 200 while every real request
    # failed. /ready (used by the k8s probes) must notice, so Kubernetes restarts the pod.
    app = TestClient(create_app(conn))
    assert app.get("/ready").status_code == 200
    conn.close()  # stands in for "the database went away under us"
    assert app.get("/ready").status_code == 503
    assert app.get("/health").status_code == 200  # /health alone would have hidden it
