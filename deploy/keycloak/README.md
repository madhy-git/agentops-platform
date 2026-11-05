# Keycloak realm `wattle` (fictional, local dev only)

Imported on start by `docker compose --profile auth up -d keycloak`.

- Users: `officer-1`, `fraud-1`, `hardship-1`, `disputes-1`, `manager-1`, `compliance-1`. Password `password` for all. Never reuse it outside local dev.
- Realm roles match `agentops.auth.APP_ROLES`.
- Client `agentops-api` has an **audience mapper**, so access tokens carry `aud: agentops-api`. The API rejects tokens without it, so a token minted for another app can't be replayed here.

```bash
# get a token (password grant: fine for local dev, never for production)
curl -s -d grant_type=password -d client_id=agentops-api -d username=fraud-1 -d password=password \
  http://localhost:8080/realms/wattle/protocol/openid-connect/token | jq -r .access_token
# run the API against Keycloak
AGENTOPS_JWKS_URL=http://localhost:8080/realms/wattle/protocol/openid-connect/certs uv run uvicorn agentops.api:create_app --factory
```
