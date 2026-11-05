# ADR 0007: Identity from signed JWT claims (Keycloak locally, Cognito on AWS)

- **Status:** accepted
- **Date:** 2026-11-04
- **Phase:** 4

## Context
Officers, specialists and managers must get different powers. Until Phase 4 the role was a function argument (or an environment variable in MCP Case Tools), so any caller could claim to be a manager.

## Decision
- The API accepts only bearer tokens. Roles come from verified claims (`realm_access.roles` in Keycloak, `cognito:groups` on AWS), mapped to app roles in one function (`auth.principal_from_claims`).
- Tokens must have `aud: agentops-api` and an unexpired `exp`. RS256 via JWKS in Keycloak and Cognito; HS256 dev tokens only when no JWKS URL is configured.
- Identity flows on to MCP Case Tools: the MCP server is built for the caller's role, so the MCP layer enforces least privilege independently.

## Consequences
- Verified locally against a real Keycloak (`deploy/keycloak/`): an RS256 token for `fraud-1` maps to `{officer, fraud_specialist}`.
- The UI's role picker is for demos only; the server checks every call.
- Open: MCP Case Tools should verify the token itself over HTTP transport instead of trusting the role agentops passes in-process.
