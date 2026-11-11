"""All runtime configuration in one place.

LEARNING NOTE: reading `os.getenv` all over the codebase makes behaviour hard to reason
about ("why is it in live mode?"). One frozen settings object is easy to log, test and
override. Twelve-factor style: config comes from the environment, never from code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root: versioned prompts/ and policies/ live here, outside the Python package, because
# they are reviewed and released like code but edited by people who may not write Python.
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    # offline = deterministic rule model, no API keys (CI). live = real models via LiteLLM.
    mode: str = "offline"
    # Postgres is the single store for state, audit, flags, vectors and sessions (ADR 0002).
    database_url: str = "postgresql://agentops:agentops@localhost:5433/agentops"
    # LiteLLM gateway (OpenAI-compatible). Only used in live mode (ADR 0003).
    litellm_base_url: str = "http://localhost:4000/v1"
    litellm_api_key: str = "sk-local-dev"
    # Phase 4: JWT verification. Dev uses a shared secret; with Keycloak, set the JWKS URL.
    jwt_secret: str = "dev-only-secret-change-me-at-least-32-bytes"
    jwt_jwks_url: str | None = None
    jwt_audience: str = "agentops-api"  # Keycloak client id, or the Cognito app client id
    jwt_issuer: str | None = None  # e.g. https://cognito-idp.<region>.amazonaws.com/<pool-id>
    # Phase 6: on AWS the DB password lives in Secrets Manager (RDS-managed). Set the secret ARN and host.
    db_secret_arn: str | None = None
    db_host: str | None = None
    # Phase 5: Temporal server address.
    temporal_address: str = "localhost:7233"
    # Phase 4: where the agent's lookup_case tool reads cases from. "static" | "mcp" (mcp_tools.py).
    case_source: str = "static"
    # Self-service portal: demo sign-in (personas.py). Off unless set; refused anyway when jwt_jwks_url is set.
    dev_login: bool = False
    # The copilot's model can be switched to live on its own (AGENTOPS_COPILOT_MODE=live) while triage stays offline:
    # try a real model where it matters most to users, without changing the rules-driven pipeline or its tests.
    copilot_mode: str = "offline"

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def copilot_live(self) -> bool:
        return self.copilot_mode == "live"


def settings() -> Settings:
    """Read the environment now. Rebuilt per call so tests can monkeypatch env vars."""
    d = Settings()
    return Settings(
        mode=os.getenv("AGENTOPS_MODE", d.mode),
        database_url=os.getenv("AGENTOPS_DATABASE_URL", d.database_url),
        litellm_base_url=os.getenv("LITELLM_BASE_URL", d.litellm_base_url),
        litellm_api_key=os.getenv("LITELLM_API_KEY", d.litellm_api_key),
        jwt_secret=os.getenv("AGENTOPS_JWT_SECRET", d.jwt_secret),
        jwt_jwks_url=os.getenv("AGENTOPS_JWKS_URL"),
        jwt_audience=os.getenv("AGENTOPS_JWT_AUDIENCE", d.jwt_audience),
        jwt_issuer=os.getenv("AGENTOPS_JWT_ISSUER"),
        db_secret_arn=os.getenv("AGENTOPS_DB_SECRET_ARN"),
        db_host=os.getenv("AGENTOPS_DB_HOST"),
        temporal_address=os.getenv("TEMPORAL_ADDRESS", d.temporal_address),
        case_source=os.getenv("AGENTOPS_CASE_SOURCE", d.case_source),
        dev_login=os.getenv("AGENTOPS_DEV_LOGIN", "") == "1",
        copilot_mode=os.getenv("AGENTOPS_COPILOT_MODE", os.getenv("AGENTOPS_MODE", d.mode)),
    )


def database_url(s: Settings | None = None, fetch_secret: object = None) -> str:
    """The Postgres URL. On AWS, built from the RDS-managed secret instead of an env var with a password.

    LEARNING NOTE: the password is fetched at start-up with the pod's own IAM role (Pod Identity), so it never
    appears in a manifest, an env var, CI logs or the container image. RDS rotates it; a restart picks it up.
    """
    s = s or settings()
    if not s.db_secret_arn:
        return s.database_url
    if fetch_secret is None:
        import boto3  # only needed on AWS: `uv sync --extra aws`

        def fetch_secret(arn: str) -> str:
            return str(boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])

    import json
    from urllib.parse import quote

    secret = json.loads(fetch_secret(s.db_secret_arn))  # type: ignore[operator]
    return f"postgresql://{secret['username']}:{quote(secret['password'])}@{s.db_host}:5432/agentops?sslmode=require"
