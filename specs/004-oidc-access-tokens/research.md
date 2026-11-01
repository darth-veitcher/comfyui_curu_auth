# Research: spec 004

## R-1: What comfy-mcp does after a 401

Source: comfy-mcp `src/comfy_mcp/comfyui.py` at `77aaa58`.

- `_SourceAuth.async_auth_flow` sends the token. On HTTP 401, it invalidates the token, gets a new one, and sends the request one more time at once.
- `_raise_for_status` raises `BackendRateLimited` on HTTP 429.
- The `/ws` handshake waits `Retry-After` on 429, and 30 seconds on 401 or 403.

Result: a retry inside the first wait of 1 second gets 429 if the gate checks the wait first. ADR-008 lets a valid token pass before the wait.

## R-2: rauthy 0.37.2 access tokens

Sources: comfy-mcp `tests/oidc/conftest.py`, curu-memory ADR-015.

- A `client_credentials` token has `typ` `at+jwt`, and the claims `iss`, `aud`, `azp`, `scope`, `iat`, `nbf`, `exp` and `jti`. It has no `sub`.
- With no `resource`, `aud` is the client id only. With `resource`, `aud` also holds it, when `allowed_resources` of the client holds it.
- The bootstrap file cannot set `allowed_resources`. The admin API can, with a bootstrap API key.
- rauthy 0.37.2 refuses HTTP Basic on the `client_credentials` grant. Send the secret in the form.

## R-3: The token types of other providers

| Provider | `typ` | Client id | Scope | Source |
|---|---|---|---|---|
| rauthy | `at+jwt` | `azp` | `scope` | comfy-mcp tests |
| Authentik | `JWT` | `azp` | `scope` | curu-memory ADR-017 |
| Keycloak | `JWT` | `azp` | `scope` | comfy-mcp guide |
| Okta | none | `cid` | `scp` (list) | comfy-mcp guide |
| Entra ID, user | `JWT` | `azp` | `scp` | comfy-mcp guide |
| Entra ID, program | `JWT` | `azp` | none (`roles`) | comfy-mcp guide |

## R-4: Leeway in `joserfc`

`JWTClaimsRegistry` has one `leeway` for `exp`, `nbf` and `iat`. ADR-008 wants none for `exp` and 60 seconds for the others. So the gate validates with a leeway of 60 seconds, and then compares `exp` with the time itself.
