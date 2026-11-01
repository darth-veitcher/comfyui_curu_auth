# ADR-007: The OIDC login uses the exact issuer, asymmetric algorithms only, and an allowlist that fails closed

## Status

Accepted

_Date:_ 2026-11-01
_Deciders:_ James Veitch (with Claude Code)

It adds to [ADR-002](ADR-002-oidc-session-sharing-and-test-idp.md). It replaces no ADR.

---

## Context

- The OIDC login of spec 002 had tests against Authelia only. The issuer of Authelia has no `/` at the end.
- rauthy 0.37.2 gives the issuer `http://<host>/auth/v1/`, with a `/` at the end. Authentik gives `https://<host>/application/o/<slug>/`.
- On 2026-11-01, the gate built `<issuer>/.well-known/openid-configuration` and got HTTP 404 from rauthy for the issuer with `/`. Without the `/`, discovery worked, but the `iss` check then failed.
- OpenID Connect Discovery 1.0, section 4, removes the `/` at the end of the issuer before it adds the path. Section 4.3 requires that the `issuer` of the document is exactly the issuer that the client used.
- The gate accepted RS256 only. rauthy signs an ID token with the algorithm of the client, for example EdDSA.
- An Authentik provider with no signing key signs with HS256 and the client secret.
- A token that names HS256 in its header can use the public key of the provider as the HMAC secret. This is the key-confusion attack.
- The callback gave a session to each person with a valid ID token. With Google as the provider, each Google account could log in.
- `joserfc` 1.7.4 accepts an ID token with no `exp` unless the claims registry marks `exp` as essential.
- curu-memory (its ADR-015 and ADR-017) and comfy-mcp (its ADR-007) use the same issuer rule and the same key rule.
- An exception in `__init__.py` makes ComfyUI skip the node. The gate is then off, and ComfyUI is open.

## Decision

The gate keeps the exact issuer, takes an asymmetric algorithm from the key, and gives a session only to a person on an allowlist.

**The issuer.**

- The discovery URL is `issuer.rstrip("/") + "/.well-known/openid-configuration"`.
- The `issuer` of the discovery document must equal the configured issuer exactly. The `iss` of each ID token must equal the same value.
- The issuer, `authorization_endpoint`, `token_endpoint` and `jwks_uri` must use `https`. Plain `http` is allowed only on `localhost`, `127.0.0.1` and `::1`.
- The gate follows no redirect from these URLs. A redirect could move the keys to `http`, or send the client secret to another host.
- A bad discovery document stops the login at its start with HTTP 503. The gate logs the reason at ERROR, but not as an authentication failure.

**The algorithms.**

- The gate accepts RS256, RS384, RS512, PS256, ES256 and EdDSA.
- The JWK with the `kid` of the token sets the algorithm. When the JWK has no `alg`, the key type sets it: RS256 for RSA, ES256 for the P-256 curve, and EdDSA for Ed25519.
- The `alg` of the token header must equal the algorithm of the key.
- The gate refuses `none` and each HMAC algorithm before it reads the JWKS. For HMAC, the reason says that an Authentik provider with no signing key signs this way.

**The claims of an ID token.**

- `iss`, `aud`, `exp`, `iat` and `nonce` are essential.
- When `aud` has more than one value, `azp` must equal the client id. When `azp` is present, it must always equal the client id.
- The clock leeway is 60 seconds for `exp`, `iat` and `nbf`.

**The allowlist.**

- A person gets a session when one of these is true:
  - `sub` is in `ALLOWED_SUBJECTS`.
  - `email` is in `ALLOWED_EMAILS` and `email_verified` is true.
  - `hd` equals `ALLOWED_DOMAIN`.
  - `ALLOW_ANY_USER` is true.
- The comparison of emails and of the domain ignores capital letters. The comparison of subjects is exact.
- A refused person gets HTTP 401, one failure in the shared `RateLimiter`, and the failure log line.

**Fail closed at start.** When the four settings of spec 002 are set, but no allowlist is set and `ALLOW_ANY_USER` is not true, the OIDC login stays off. The gate writes an error at start and keeps the credential gate on. It does not raise an exception, because ComfyUI would then skip the node and leave ComfyUI open.

**The settings names.** Each name has the prefix `COMFYUI_CURU_AUTH_OIDC_`.

| Setting | Meaning | Default |
|---|---|---|
| `COMFYUI_CURU_AUTH_OIDC_ISSUER_URL` | The issuer, exactly as the discovery document gives it. The name is from spec 002. | none |
| `COMFYUI_CURU_AUTH_OIDC_CLIENT_ID` | The client id. From spec 002. | none |
| `COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET` | The client secret. From spec 002. | none |
| `COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI` | The callback URL. From spec 002. | none |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS` | The `sub` values that can log in, with a comma or a space between them. | empty |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_EMAILS` | The verified emails that can log in, with a comma or a space between them. | empty |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_DOMAIN` | One Google Workspace domain, compared with the `hd` claim. | empty |
| `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER` | `true` lets the provider decide who can log in. | `false` |
| `COMFYUI_CURU_AUTH_OIDC_SCOPES` | The scopes of the login, with a space or a comma between them. The gate always adds `openid`. | `openid profile email` |

The reasons are these:

- One issuer rule for the three projects lets one Authentik setup serve curu-memory, comfy-mcp and this gate.
- The key decides the algorithm, so a token cannot choose a weaker one.
- An HMAC check needs a shared secret. A gate that refuses HMAC cannot be tricked into using a public key as that secret.
- An allowlist that fails closed protects an operator who connects Google, where each account in the world is a valid person.
- A start error that raises would turn the gate off. An error line and an OIDC login that stays off keep the gate on.

## Consequences

- **Good:** the login works with rauthy, Authentik, Keycloak and each provider that follows OpenID Connect Discovery.
- **Good:** a refused person is visible to fail2ban and crowdsec with the log format they already read.
- **Cost:** this is a breaking change. An operator who used the login of spec 002 must set an allowlist or `ALLOW_ANY_USER=true` after the upgrade.
- **Cost:** a Google ID token with `iss` `accounts.google.com`, with no scheme, is refused. Google uses the `https` form in the authorization code flow.
- **Cost:** an operator must copy the issuer exactly. A wrong `/` gives HTTP 503 at the start of the login, and the log names both values.
- **Escape route:** the allowlist is one function of the claims. A later rule, for example a group claim, adds one branch.

## Considered Alternatives

### Alternative A: Remove the `/` from the configured issuer, and compare `iss` without it

**Why rejected:** Discovery, section 4.3, requires an exact comparison. Two issuers that differ only in `/` could then match.

### Alternative B: Take the algorithm from the token header, with a list of allowed values

**Why rejected:** The header is data from the attacker. A key of the wrong type could then check a token, as in the key-confusion attack.

### Alternative C: Accept HS256 with the client secret, for Authentik with no signing key

**Why rejected:** The gate would then hold a secret that also signs tokens. A signing key on the provider is the correct fix, and the error says so.

### Alternative D: No allowlist, and rely on the provider

**Why rejected:** This is safe only with a group binding at the provider. With Google, it is not safe. `ALLOW_ANY_USER=true` keeps this option as an explicit decision.

### Alternative E: Raise an exception when the allowlist is missing

**Why rejected:** ComfyUI catches the exception and skips the node, so the gate is off. Constitution article III forbids a setup that fails open.

---

## Links

- Related specs: `specs/003-oidc-provider-fixes/`, `specs/002-oidc-login/`
- Related issues: #13, #14
- curu-memory ADR-015 and ADR-017; comfy-mcp ADR-007
- OpenID Connect Discovery 1.0, sections 4 and 4.3; OpenID Connect Core 1.0, section 3.1.3.7
- RFC 8725 (JWT best current practices)
