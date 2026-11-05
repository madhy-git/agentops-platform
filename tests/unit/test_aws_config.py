"""Phase 6 config: Cognito claims, audience handling and the Secrets Manager DB URL (no AWS calls)."""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from agentops import auth
from agentops.config import Settings, database_url


def test_cognito_groups_map_to_app_roles():
    p = auth.principal_from_claims(
        {"sub": "abc", "username": "fraud-1", "cognito:groups": ["fraud_specialist", "admins"]}
    )
    assert p.user == "fraud-1" and p.roles == {"fraud_specialist"}


def test_db_url_from_rds_managed_secret_without_touching_aws():
    s = Settings(db_secret_arn="arn:aws:secretsmanager:x:1:secret:rds", db_host="db.internal")
    url = database_url(s, fetch_secret=lambda arn: json.dumps({"username": "agentops", "password": "p@ss/word"}))
    assert url == "postgresql://agentops:p%40ss/word@db.internal:5432/agentops?sslmode=require"


@pytest.fixture
def rsa_jwks(monkeypatch):
    """A fake identity provider: our own RSA key served as if it were Cognito's JWKS."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setenv("AGENTOPS_JWKS_URL", "https://cognito.example/jwks.json")
    monkeypatch.setenv("AGENTOPS_JWT_AUDIENCE", "client-123")
    monkeypatch.setenv("AGENTOPS_JWT_ISSUER", "https://cognito.example/pool")
    monkeypatch.setattr(auth, "_jwks", lambda url: FakeJwks())
    return lambda claims: jwt.encode(claims, key, algorithm="RS256")


def base(**kw):
    return {"sub": "u", "username": "manager-1", "cognito:groups": ["manager"], "exp": int(time.time()) + 60,
            "iss": "https://cognito.example/pool"} | kw  # fmt: skip


def test_cognito_access_token_accepted_via_client_id(rsa_jwks):
    assert auth.verify(rsa_jwks(base(client_id="client-123", token_use="access"))).roles == {"manager"}


def test_token_for_another_client_or_issuer_rejected(rsa_jwks):
    for bad in (base(client_id="other-client"), base(client_id="client-123", iss="https://evil.example")):
        with pytest.raises(HTTPException) as e:
            auth.verify(rsa_jwks(bad))
        assert e.value.status_code == 401
