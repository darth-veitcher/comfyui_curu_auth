# ADR-008: The Bearer path also accepts a short-lived OIDC access token, in an opt-in resource-server mode

## Status

Accepted

_Date:_ 2026-11-01
_Deciders:_ James Veitch (with Claude Code)

It adds to [ADR-004](ADR-004-only-offered-credentials-count-as-attempts.md) and [ADR-007](ADR-007-oidc-issuer-algorithms-and-allowlist.md). It replaces no ADR.

---

## Context

- comfy-mcp can get its own access token for each backend with the OAuth 2.0 `client_credentials` grant (comfy-mcp ADR-007). Today this gate accepts only its static credential on the Bearer path.
- comfy-mcp sends `Authorization: Bearer <token>` on each HTTP call and on the `/ws` handshake. It gets a new token 60 seconds before `exp`.
- After HTTP 401, comfy-mcp invalidates its token, gets a new one, and sends the request one more time at once (`_SourceAuth` in `comfy_mcp/comfyui.py`). On HTTP 429 it raises `BackendRateLimited`.
- The gate checks the wait of the `RateLimiter` before it checks the Bearer credential. So a request in a wait gets HTTP 429, also with a correct credential. A valid session cookie is checked before the wait and never gets 429.
- The first wait is 1 second. comfy-mcp sends its second attempt well inside that second.
- curu-memory and comfy-mcp check an access token with the same rules. The rules are about the issuer, the key, the audience, the time, the lifetime and the token type.
- ADR-007 gives the issuer rule and the key rule of the OIDC login. `oidc.py` has them as `fetch_discovery_document`, `check_token_algorithm` and `select_signing_key`.
- A login reads the JWKS at each callback. A resource server checks a token on each request, so it must keep the JWKS in memory.
- Google access tokens are opaque, and Google has no `client_credentials` grant. A `client_credentials` token of Microsoft Entra ID has `roles`, but no `scp`.

## Decision

The gate adds an opt-in resource-server mode: the Bearer path also accepts a JWT access token of the configured issuer, after the checks below.

**The settings.** Each name has the prefix `COMFYUI_CURU_AUTH_OIDC_`.

| Setting | Meaning | Default |
|---|---|---|
| `COMFYUI_CURU_AUTH_OIDC_ISSUER_URL` | The issuer, as for the login (ADR-007). The login and the mode share it. | none |
| `COMFYUI_CURU_AUTH_OIDC_AUDIENCE` | The value that `aud` must hold. It turns the mode on. | none |
| `COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES` | Scopes that each token must hold, with a space or a comma between them. | empty |

- The mode is on only when the issuer and the audience are both set.
- An audience with no issuer is a start error. Required scopes with no audience are a start error. An issuer with `http` off loopback is a start error.
- A start error writes an error line and keeps the mode off. The gate stays on, for the reason of ADR-007.
- The mode does not need the client id, the secret, the redirect URI or the allowlist of the login. The login and the mode are independent.

**The checks of a token.** The gate refuses the token at the first check that fails.

1. The token is a compact JWS.
2. The `alg` of the header is not `none` and not an HMAC algorithm (ADR-007).
3. The `typ` of the header is `at+jwt`, `application/at+jwt`, `JWT`, or absent. The comparison ignores capital letters.
4. The unverified `iss` equals the issuer.
5. The JWK with the `kid` of the token sets the algorithm (ADR-007).
6. The signature is valid.
7. `iss`, `aud`, `exp` and `iat` are present. `aud` holds the audience.
8. `exp` is in the future, with no leeway. `nbf` and `iat` are not more than 60 seconds in the future.
9. `exp` minus `iat` is 3600 seconds or less.
10. A token of the type `JWT`, or with no `typ`, has a client id (`azp`, `client_id` or `cid`) and a scope (`scope` or `scp`). This stops an ID token, which has the same `aud` but no scope.
11. The token holds each required scope, in `scope` (a string) or `scp` (a list or a string).

Checks 1 to 4 need no network. A token that fails them never causes a read of the JWKS.

**The keys.** The gate keeps the discovery document and the JWKS in memory. An unknown `kid` causes one new read, at most one time in 60 seconds. A failed read also starts the 60 seconds.

**The static credential.** The gate compares the static credential first, exactly as before (FR-004 of spec 002). Only a Bearer value that is not the static credential, and that has the shape of a JWT, goes to the token checks.

**The rate limit.**

- Each refused token is one failed attempt in the shared `RateLimiter`, as a wrong static credential is.
- A valid token passes before the wait is checked, as a valid session cookie does. It also clears the failures of that address.
- So the second attempt of comfy-mcp after a 401 passes when its new token is valid. It does not get 429 from the failure of the first token.

**The logs.**

- Each refused token writes the failure line `authentication failure from <IP> (<METHOD> <PATH>: token refused: <reason>)`. This also applies to a token in a wait, before the 429.
- The reason is a fixed text. It never holds the token, a part of it, or a claim value.
- An accepted token writes `sub` and the client id at DEBUG.

The reasons are these:

- One set of token rules for curu-memory, comfy-mcp and this gate lets one Authentik setup serve all three.
- A valid signature cannot be guessed, so a valid token is no attempt to guess. To let it pass during a wait does not weaken the bound on guesses. Each invalid token still counts.
- The checks before the key need no network, so an attacker cannot make the gate read the JWKS with junk tokens.

## Consequences

- **Good:** comfy-mcp can reach this gate with a token of 10 minutes or less, in place of a static credential that never expires.
- **Good:** the static credential and its rate limit do not change.
- **Cost:** a token cannot be revoked before its `exp`. The lifetime limit of 1 hour bounds the risk.
- **Cost:** while an address waits, the gate still checks each JWT that it gets. Checks 1 to 4 are cheap, and the read of the JWKS has its own limit.
- **Cost:** Google and Microsoft Entra ID cannot give tokens for programs that pass these checks.
- **Escape route:** the gate gets the check as one function. A later change, for example token introspection, replaces that function only.

## Considered Alternatives

### Alternative A: Count a signed but expired token once for each `jti`

**Why rejected:** the first failure still starts a wait of 1 second. The second attempt of comfy-mcp comes inside it and gets 429, whatever the count.

### Alternative B: Keep the order and rely on the short first wait

**Why rejected:** the first wait is 1 second, and comfy-mcp retries at once. The retry gets 429, and comfy-mcp raises `BackendRateLimited`.

### Alternative C: Do not count a token that has a valid signature

**Why rejected:** the requirement is that each refused token counts. Also, a token for another audience is a fault that the operator must see in the wait.

### Alternative D: A separate setting to turn the mode on

**Why rejected:** the audience is required for the mode in all cases. A second setting would add a state with no meaning: on, but with no audience.

---

## Links

- Related specs: `specs/004-oidc-access-tokens/`, `specs/003-oidc-provider-fixes/`
- Related issues: #14, #13
- curu-memory ADR-015 and ADR-017; comfy-mcp ADR-007
- RFC 9068 (JWT access tokens), RFC 8707 (resource indicators), RFC 8725 (JWT best current practices)
