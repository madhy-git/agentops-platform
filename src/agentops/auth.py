"""Authentication: turn a signed JWT into a Principal (user + roles).

LEARNING NOTES
- The API never trusts a role the caller *claims* in a request body. Roles come only from a token
  signed by the identity provider. Forging one needs the provider's private key.
- Dev mode: HS256 with a shared secret (`dev_token()` mints tokens for tests and curl).
  Keycloak mode: RS256, verified against Keycloak's public keys (JWKS), fetched and cached.
- Keycloak puts realm roles in `realm_access.roles`. Mapping claims to app roles lives in ONE place
  (`principal_from_claims`), so swapping Keycloak for Cognito (Phase 6) touches only this function.
- Always verify `exp` (expiry) and the audience (the token was issued *for this API*). A valid
  token for a different app must be rejected. Keycloak puts the audience in `aud`; Cognito access tokens
  have no `aud` and use `client_id` instead, so both are accepted, but one of them must match.
- Cognito puts groups in `cognito:groups`; the Cognito user pool's groups are named after APP_ROLES.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

AUDIENCE = "agentops-api"  # dev tokens; with a JWKS provider, settings().jwt_audience (Cognito: the app client id)
APP_ROLES = {
    "viewer", "officer", "manager", "compliance",
    "fraud_specialist", "hardship_specialist", "disputes_officer",
}  # fmt: skip


@dataclass(frozen=True)
class Principal:
    user: str
    roles: frozenset[str]

    def has_any(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    user = claims.get("preferred_username") or claims.get("username") or claims["sub"]
    raw = (
        set(claims.get("realm_access", {}).get("roles", []))  # Keycloak
        | set(claims.get("cognito:groups", []))  # Cognito
        | set(claims.get("roles", []))  # dev tokens
    )
    # Drop provider-internal roles (e.g. Keycloak's "offline_access"): only known app roles count.
    return Principal(user, frozenset(raw & APP_ROLES))


def dev_token(user: str, roles: list[str], ttl_s: int = 3600) -> str:
    """Mint an HS256 token for local dev and tests. Never enabled when a JWKS URL is configured."""
    now = int(time.time())
    claims = {"sub": user, "preferred_username": user, "roles": roles, "aud": AUDIENCE, "iat": now, "exp": now + ttl_s}
    return jwt.encode(claims, settings().jwt_secret, algorithm="HS256")


@lru_cache(maxsize=4)
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def verify(token: str) -> Principal:
    s = settings()
    try:
        if s.jwt_jwks_url:
            key = _jwks(s.jwt_jwks_url).get_signing_key_from_jwt(token).key
            # Audience is checked by hand below because Cognito access tokens carry `client_id`, not `aud`.
            claims = jwt.decode(token, key, algorithms=["RS256"], options={"verify_aud": False, "require": ["exp"]})
            aud = claims.get("aud")
            audiences = set(aud if isinstance(aud, list) else [aud]) | {claims.get("client_id")}
            if s.jwt_audience not in audiences:
                raise jwt.InvalidAudienceError("token not issued for this API")
            if s.jwt_issuer and claims.get("iss") != s.jwt_issuer:
                raise jwt.InvalidIssuerError("unexpected issuer")
        else:
            claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], audience=AUDIENCE)
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {type(e).__name__}") from e
    p = principal_from_claims(claims)
    if not p.roles:
        raise HTTPException(403, "no application roles in token")
    return p


_bearer = HTTPBearer(auto_error=False)


def current_principal(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None:
        raise HTTPException(401, "missing bearer token")
    return verify(creds.credentials)


def require(*roles: str) -> Any:
    """FastAPI dependency: the caller must hold at least one of `roles`."""

    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.has_any(*roles):
            raise HTTPException(403, f"requires one of {sorted(roles)}")
        return p

    return dep
