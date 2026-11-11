"""Self-service portal: customers see their own outcomes, nothing internal, and nothing of anyone else's.

LEARNING NOTE: most of these are *negative* tests (who must NOT be able to do what). For a customer-facing
surface those are the ones that matter: a missing feature is a bug report, a missing check is a breach.
"""

import json

import pytest
from fastapi.testclient import TestClient

from agentops.api import create_app
from agentops.auth import dev_token

JORDAN = ("jordan.brown", "CUS-00001")
PRIYA = ("priya.smith", "CUS-00002")


def cust(who: tuple[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {dev_token(who[0], ['customer'], customer_id=who[1])}"}


def staff(user: str, roles: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {dev_token(user, roles)}"}


@pytest.fixture
def client(conn):
    return TestClient(create_app(conn))


def raise_request(client, who, message):
    r = client.post("/portal/requests", json={"message": message}, headers=cust(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_customer_sees_plain_status_and_nothing_internal(client):
    case = raise_request(client, JORDAN, "My card was stolen at the airport, call me on 0411 821 692")
    assert case["reference"].startswith("WB-") and case["status"] == "With a specialist"
    assert case["topic"] == "Card security" and "[PHONE]" in case["message"]
    leaked = {"reason_codes", "queue", "priority", "decision_id", "assigned_to", "approver", "risk", "model"}
    assert not leaked & set(case), "internal fields must not reach customers"


def test_customer_cannot_see_another_customers_case(client):
    case = raise_request(client, JORDAN, "My card was stolen")
    assert client.get(f"/portal/cases/{case['id']}", headers=cust(PRIYA)).status_code == 404
    assert client.get("/portal/cases", headers=cust(PRIYA)).json() == []
    assert [c["id"] for c in client.get("/portal/cases", headers=cust(JORDAN)).json()] == [case["id"]]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/triage", {"message": "hi"}),
        ("get", "/cases", None),
        ("get", "/cases/1", None),
        ("post", "/cases/1/transition", {"to": "resolved"}),
        ("get", "/approvals/mine", None),
        ("post", "/approvals/1/decision", {"approve": True}),
        ("get", "/audit", None),
        ("post", "/copilot", {"question": "hardship options"}),
        ("get", "/stats", None),
        ("get", "/customers/CUS-00001", None),
        ("post", "/customers/CUS-00001/flags/fraud_flag/clear", None),
    ],
)
def test_customers_are_refused_on_every_staff_endpoint(client, method, path, body):
    raise_request(client, JORDAN, "My card was stolen")  # so case 1 / approval 1 exist
    r = getattr(client, method)(path, headers=cust(JORDAN), **({"json": body} if body else {}))
    assert r.status_code == 403, f"{method.upper()} {path} -> {r.status_code}"


def test_staff_cannot_use_the_customer_portal(client):
    assert client.get("/portal/cases", headers=staff("manager-1", ["manager"])).status_code == 403


def test_tokens_mixing_customer_and_staff_roles_are_rejected(client):
    mixed = {"Authorization": f"Bearer {dev_token('x', ['customer', 'manager'], customer_id='CUS-00001')}"}
    no_id = {"Authorization": f"Bearer {dev_token('y', ['customer'])}"}
    assert client.get("/me", headers=mixed).status_code == 403
    assert client.get("/me", headers=no_id).status_code == 403


def test_full_loop_customer_request_specialist_approval_customer_sees_outcome(client):
    # "stolen", not "stole": the offline stand-in triages by keyword, and "Someone stole my card" reads as a
    # general enquiry offline. Real customers paraphrase freely; that's what live mode + the paraphrase set test.
    case = raise_request(client, JORDAN, "My card was stolen and someone made purchases")
    # Staff side: the fraud specialist it was routed to sees context, approves; the card block runs once.
    for user in ("fraud-1", "fraud-2"):
        queue = client.get("/approvals/mine", headers=staff(user, ["officer", "fraud_specialist"])).json()
        mine = [a for a in queue if a["case_id"] == case["id"]]
        if mine:
            break
    assert mine and mine[0]["customer_name"] == "Jordan Brown"
    r = client.post(f"/approvals/{mine[0]['id']}/decision", json={"approve": True},
                    headers=staff(user, ["officer", "fraud_specialist"]))  # fmt: skip
    assert r.status_code == 200
    detail = client.get(f"/portal/cases/{case['id']}", headers=cust(JORDAN)).json()
    assert detail["status"] == "Action taken" and "card has been blocked" in detail["status_detail"]
    assert [t["status"] for t in detail["timeline"]] == [
        "Received",
        "Being reviewed",
        "With a specialist",
        "Approved",
        "Action taken",
    ]


def test_staff_workspace_sees_the_customer_case_with_context(client):
    case = raise_request(client, JORDAN, "My card was stolen")
    officer = staff("officer-1", ["officer"])
    listed = client.get("/cases", headers=officer).json()
    assert listed[0]["id"] == case["id"] and listed[0]["customer_name"] == "Jordan Brown"
    detail = client.get(f"/cases/{case['id']}", headers=officer).json()
    assert "FRAUD_SUSPECTED" in detail["decision"]["reason_codes"]
    assert "fraud_flag" in detail["customer"]["active_flags"] and "escalated" in detail["allowed_transitions"]
    assert client.get("/stats", headers=officer).json()["approvals"]["pending"] == 1


def test_customer_assistant_reads_only_customer_articles(client):
    def ask(q):
        r = client.post("/portal/assistant/stream", json={"question": q}, headers=cust(JORDAN))
        text, done = "", {}
        event = None
        for line in r.text.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                if event == "delta":
                    text += line[6:]
                else:
                    done = json.loads(line[6:])
        return text, done

    text, done = ask("how much is the foreign transaction fee?")
    assert "3 percent" in text and done["sources"] == ["POL-FAQ-01#1"]
    # Hardship options are staff-only. A customer gets no content AND no hint that internal guidance exists.
    text, done = ask("what hardship arrangement options can you offer?")
    assert done["sources"] == [] and "restricted" not in text.lower() and "queue" not in text.lower()


def test_dev_login_is_off_by_default_and_refused_with_a_real_identity_provider(client, monkeypatch):
    assert client.post("/auth/dev-login", json={"username": "jordan.brown"}).status_code == 404
    monkeypatch.setenv("AGENTOPS_DEV_LOGIN", "1")
    r = client.post("/auth/dev-login", json={"username": "jordan.brown"})
    assert r.status_code == 200 and r.json()["persona"]["customer_id"] == "CUS-00001"
    me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
    assert me == {"user": "jordan.brown", "roles": ["customer"], "customer_id": "CUS-00001"}
    monkeypatch.setenv("AGENTOPS_JWKS_URL", "http://idp.example/jwks")  # e.g. Cognito on AWS
    assert client.post("/auth/dev-login", json={"username": "manager-1"}).status_code == 404
