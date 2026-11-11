# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Two ComfyUI instances on one host now keep their own browser logins. The
  session cookie is now `curu_auth_<port>`, for example `curu_auth_8188`. The
  port is the port that ComfyUI listens on. Before, each instance set the same
  cookie, `curu_auth`, and a browser sends the cookies of a host to each port.
  So a login to one instance logged out the other instances. The credential
  form, the OIDC login and the expiry of an unknown cookie all use the new name.
  Each gate reads and expires only its own cookie (#30).

### Changed

- The gate does not read a cookie with the old name `curu_auth`. After the
  upgrade, each browser logs in again one time. A program that reads the
  session cookie by its name must read `curu_auth_<port>`. In `gate.py`,
  `COOKIE_NAME_PREFIX` and `session_cookie_name(request)` replace `COOKIE_NAME`.

<!-- version list -->

## v2.3.1 (2026-11-03)

### Fixed

- A `COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI` that holds only separators, for
  example `,` or a space, no longer turns the gate off. Before, the setting
  raised an error that ComfyUI caught, so ComfyUI skipped the node and served
  every request with no authentication. Now the OIDC login stays off with a
  message, and the gate stays on (#28).

### Bug Fixes

- **oidc**: A redirect URI setting with no entries keeps the gate on
  ([`585eaf2`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/585eaf2ab2b1e32d624cdbcb9feced99844d29d4))

### Chores

- Clean up after the v2.3.0 release
  ([#27](https://github.com/darth-veitcher/comfyui_curu_auth/pull/27),
  [`bd31097`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bd31097549934c7389389b3abda0e126a5d62c25))


## v2.3.0 (2026-11-02)

### Fixed

- An open ComfyUI tab now goes to the login page by itself when its session
  is lost, for example after a restart of ComfyUI. Before, the tab polled
  `/api/jobs` and opened `/ws` again and again, and each request wrote one
  `authentication failure` line. The node now gives ComfyUI one script,
  `web/session_loss.js`. The gate marks each of its HTTP 401 and HTTP 429
  answers with `X-Curu-Auth: login-required`; the status, the body and the log
  line do not change. A tab stays on its page while ComfyUI is down, and on an
  HTTP 401 of ComfyUI or another node.

### Added

- A `browser` test tier runs `web/session_loss.js` in Chromium against the real
  gate. The `system` tier now needs the `live` group.

### Chores

- Archive the browser-session epic and accept ADR-009
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- Close the tasks of spec 005 (T015, T022, T023)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- Record the clear beacon-reviewer result (T025)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

### Documentation

- An open tab goes to the login page after a restart (T018-T021)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- Fix the review findings for the session-loss notes
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- Fix the second review findings for the session-loss notes
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- Spec, plan and tasks for the tab that goes to the login page when its session is lost
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

### Features

- An open tab goes to the login page when its session is lost
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **gate**: Mark each 401 and 429 of the middleware with X-Curu-Auth (T005-I)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: A rejected ws handshake moves the tab, through one probe (T007-I)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: One move for each page load, and none within 5 seconds (T008-I)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: Web/session_loss.js sends the tab to the login page on a gate rejection (T006-I)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

### Testing

- Add the browser tier with a double of the ComfyUI page (T001-T004)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- Convergence tests for HTTP 429, two tabs and the WebSocket wrapper (T026-T028)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **system**: Clear the cookie jar before the wrong-credential step
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: A real ComfyUI restart sends the open tab to the login page (T016-T, T017-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: An OIDC session that is lost moves the tab (T010-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: Failing browser tests for a rejected poll (T006-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: Failing browser tests for a rejected ws handshake (T007-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: Failing browser tests for the move limits (T008-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US1**: The user logs in again after the move (T009-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US2**: A server that cannot be reached keeps the tab (T012-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US2**: A socket that closes for another reason keeps the tab (T013-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US2**: Another node's HTTP 401 keeps the tab (T011-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US3**: Failing tests for the gate rejection mark (T005-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))

- **US3**: The contrib patterns match each rejection line (T014-T)
  ([#24](https://github.com/darth-veitcher/comfyui_curu_auth/pull/24),
  [`2efd47f`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/2efd47f40c8fc115cb132a8927216aece00ababd))


## v2.2.0 (2026-11-02)

### Added

- The OIDC login works at more than one address of the same ComfyUI, for
  example a LAN address and a name behind a reverse proxy.
  `COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI` accepts a list with a comma or a space
  between the URIs. Each login uses the URI whose origin is the origin of the
  request, and the first URI when none matches. The token exchange sends the
  same URI again. One URI works as before.

### Changed

- The OIDC login stays off, with a message, when a redirect URI is not an
  `http` or `https` URL that ends in `/curu-auth/oidc/callback`. Before, such
  a login started, and then failed when the identity provider sent the
  browser back.

### Documentation

- **oidc**: Log in through the identity provider at more than one address
  ([#26](https://github.com/darth-veitcher/comfyui_curu_auth/pull/26),
  [`bad989a`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bad989a4596ded1e9679b1426410ed79ada6a9b6))

- **oidc**: The proxy must send the scheme and the host (review fixes)
  ([#26](https://github.com/darth-veitcher/comfyui_curu_auth/pull/26),
  [`bad989a`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bad989a4596ded1e9679b1426410ed79ada6a9b6))

### Features

- **oidc**: Accept more than one redirect URI and choose one by the request origin
  ([#26](https://github.com/darth-veitcher/comfyui_curu_auth/pull/26),
  [`bad989a`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bad989a4596ded1e9679b1426410ed79ada6a9b6))

### Testing

- **oidc**: Failing tests for more than one redirect URI, chosen by origin
  ([#26](https://github.com/darth-veitcher/comfyui_curu_auth/pull/26),
  [`bad989a`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bad989a4596ded1e9679b1426410ed79ada6a9b6))

- **oidc**: Give the init tests a redirect URI that ends in the callback path
  ([#26](https://github.com/darth-veitcher/comfyui_curu_auth/pull/26),
  [`bad989a`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bad989a4596ded1e9679b1426410ed79ada6a9b6))


## v2.1.1 (2026-11-02)

### Fixed

- A login through an identity provider on another site, for example Authentik on
  its own domain, no longer returns the person to the login page. The callback
  answered with a redirect to `/`, and a browser does not send a
  `SameSite=Strict` cookie after a redirect chain that starts on another site.
  The callback now answers a short page that opens ComfyUI. The cookie stays
  `SameSite=Strict`.

### Bug Fixes

- **oidc**: A login through a provider on another site no longer returns to the login page
  ([#23](https://github.com/darth-veitcher/comfyui_curu_auth/pull/23),
  [`746721e`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/746721ec58d902a5ccacadf5bf48402d0fdd1626))

### Chores

- Finish the bullet ([#22](https://github.com/darth-veitcher/comfyui_curu_auth/pull/22),
  [`8113b16`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/8113b160881713f6ea5948c1d06af7c628451d66))

- Finish the bullet ([#21](https://github.com/darth-veitcher/comfyui_curu_auth/pull/21),
  [`bbfdbc1`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bbfdbc18f3056ab31b1338acc9a07b309d58dafe))

- Start the bullet for the Authentik scope note
  ([#22](https://github.com/darth-veitcher/comfyui_curu_auth/pull/22),
  [`8113b16`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/8113b160881713f6ea5948c1d06af7c628451d66))

- Start the bullet for the comfy-mcp end-to-end test
  ([#21](https://github.com/darth-veitcher/comfyui_curu_auth/pull/21),
  [`bbfdbc1`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bbfdbc18f3056ab31b1338acc9a07b309d58dafe))

### Documentation

- An Authentik program token passes only when its request asks for a scope
  ([#22](https://github.com/darth-veitcher/comfyui_curu_auth/pull/22),
  [`8113b16`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/8113b160881713f6ea5948c1d06af7c628451d66))

- Connect comfy-mcp to the gate, and run the comfy_mcp tier
  ([#21](https://github.com/darth-veitcher/comfyui_curu_auth/pull/21),
  [`bbfdbc1`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bbfdbc18f3056ab31b1338acc9a07b309d58dafe))

- Say only what the comfy-mcp end-to-end test proves
  ([#21](https://github.com/darth-veitcher/comfyui_curu_auth/pull/21),
  [`bbfdbc1`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bbfdbc18f3056ab31b1338acc9a07b309d58dafe))

- **readme**: Say which redirect loses the Strict cookie after a login on another site
  ([#23](https://github.com/darth-veitcher/comfyui_curu_auth/pull/23),
  [`746721e`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/746721ec58d902a5ccacadf5bf48402d0fdd1626))

### Testing

- Comfy-mcp reaches the gate with its own rauthy token, end to end
  ([#21](https://github.com/darth-veitcher/comfyui_curu_auth/pull/21),
  [`bbfdbc1`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bbfdbc18f3056ab31b1338acc9a07b309d58dafe))

- Prove the refusal reason, the retry and the /ws token end to end
  ([#21](https://github.com/darth-veitcher/comfyui_curu_auth/pull/21),
  [`bbfdbc1`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/bbfdbc18f3056ab31b1338acc9a07b309d58dafe))

- **oidc**: A login from another site's provider lands on ComfyUI, not the login page
  ([#23](https://github.com/darth-veitcher/comfyui_curu_auth/pull/23),
  [`746721e`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/746721ec58d902a5ccacadf5bf48402d0fdd1626))

- **oidc**: Each good callback answers 200 and a replay is refused with 401
  ([#23](https://github.com/darth-veitcher/comfyui_curu_auth/pull/23),
  [`746721e`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/746721ec58d902a5ccacadf5bf48402d0fdd1626))


## v2.1.0 (2026-11-01)

### Added

- Resource-server mode: the Bearer path also accepts a short-lived OIDC access
  token of the configured issuer. Set `COMFYUI_CURU_AUTH_OIDC_AUDIENCE` (with the
  issuer) to turn it on, and `COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES` to require
  scopes. Off by default; the static credential does not change.
- A token must be signed by a key of the issuer (RS256, RS384, RS512, PS256,
  ES256 or EdDSA), hold the audience, live 1 hour or less, and not be expired
  (no leeway). A `JWT` token or a token with no `typ` also needs a client id and
  a scope, so an ID token is refused. The `/ws` handshake gets the same check.
- The keys of the issuer stay in memory. An unknown `kid` causes one new read, at
  most once in 60 seconds. A token with a bad shape, another issuer or a refused
  `alg` causes no read.
- A refused token counts as one failed attempt and logs
  `authentication failure from <IP> (<METHOD> <PATH>: token refused: <reason>)`.
  A valid token passes also during a wait, so the immediate retry of comfy-mcp
  after a 401 is not a 429.
- The `rauthy` test tier gets a `client_credentials` token and calls `GET /queue`.

### Features

- **oidc**: Accept OIDC access tokens on the Bearer path, in an opt-in resource-server mode
  ([#20](https://github.com/darth-veitcher/comfyui_curu_auth/pull/20),
  [`fc6f9e8`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/fc6f9e804294231ab21f75c84c2d8265c4260477))


## v2.0.0 (2026-11-01)

### Features

- **oidc**: Make the OIDC login work with rauthy, Authentik and other providers
  ([#18](https://github.com/darth-veitcher/comfyui_curu_auth/pull/18),
  [`5136021`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/5136021ed03c00dc18e044c4d87915bd072e31d6))

### Breaking Changes

- **oidc**: The OIDC login now needs COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS, _ALLOWED_EMAILS,
  _ALLOWED_DOMAIN or _ALLOW_ANY_USER=true. Without one, the OIDC login stays off and only the
  credential works.

### Details

#### Breaking changes

- The OIDC login now needs an allowlist. Set `COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS`,
  `_ALLOWED_EMAILS` or `_ALLOWED_DOMAIN`, or `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true`.
  Without one, the OIDC login stays off and the console says so; the credential
  gate stays on.

#### Added

- `COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS`, `_ALLOWED_EMAILS` (verified emails
  only), `_ALLOWED_DOMAIN` (the Google Workspace `hd` claim) and `_ALLOW_ANY_USER`.
- `COMFYUI_CURU_AUTH_OIDC_SCOPES`, with `openid` always included.
- `docs/oidc-providers.md`: a guide for rauthy, Authentik, Keycloak, Auth0, Okta,
  Microsoft Entra ID, Google and Authelia.
- A live test tier with rauthy 0.37.2 and a browser (`uv run --group live pytest -m rauthy`).

#### Fixed

- The OIDC login works with an issuer that ends in `/`, as rauthy and Authentik
  give it. The discovery URL no longer has `//`, and the issuer of the discovery
  document must equal the configured issuer exactly.
- ID tokens signed with RS384, RS512, PS256, ES256 and EdDSA are accepted. The
  key with the `kid` of the token sets the algorithm.
- `alg: none` and each HMAC algorithm are refused before the keys are read. An
  HS256 refusal tells the operator to select a signing key on the Authentik provider.
- Each endpoint of the discovery document must use `https`, or `http` on loopback.
- An ID token must have `exp` and `iat`, and `azp` must be the client id when the
  token has more than one audience. The clock leeway is 60 seconds.
- A refused OIDC login names its reason in the log line, after `oidc callback:`.
- The issuer itself must use `https`, or `http` on loopback; else the OIDC login
  stays off with a start error.
- The gate follows no redirect from the discovery URL, the JWKS URL or the token
  endpoint, so a redirect cannot move the keys to `http` or send the secret on.
- A malformed JWKS is a refused login (401, log line, wait), not an HTTP 500.
- A bad discovery document at the start of a login logs
  `OIDC login unavailable: <reason>` with both issuer values.
- A release now re-locks `uv.lock`, so it no longer falls one version behind.


## v1.0.1 (2026-10-16)

### Bug Fixes

- Set the session cookie's Secure from the scheme the browser used
  ([#12](https://github.com/darth-veitcher/comfyui_curu_auth/pull/12),
  [`5ae05a7`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/5ae05a7f6a1bdc6e53b63eef00374cb4e879c80c))

### Documentation

- ADR-006 -- the session cookie is Secure exactly when the browser used HTTPS
  ([#12](https://github.com/darth-veitcher/comfyui_curu_auth/pull/12),
  [`5ae05a7`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/5ae05a7f6a1bdc6e53b63eef00374cb4e879c80c))

### Testing

- A correct login over plain HTTP must leave the browser logged in
  ([#12](https://github.com/darth-veitcher/comfyui_curu_auth/pull/12),
  [`5ae05a7`](https://github.com/darth-veitcher/comfyui_curu_auth/commit/5ae05a7f6a1bdc6e53b63eef00374cb4e879c80c))


## v1.0.0 (2026-09-04)

- Initial Release

## Notes from before v1.0.0

### Added

- Bearer-token gate covering every ComfyUI route, including the `/ws`
  websocket handshake, via a single `aiohttp` middleware attached at import
  time.
- Browser login flow at `/curu-auth/login` with `HttpOnly` / `Secure` /
  `SameSite=Strict` session cookies (30-day session).
- `COMFYUI_CURU_AUTH_TOKEN` environment variable to pin a credential across
  restarts, instead of generating a fresh one every time.
- Exponential backoff (1s → 2s → 4s → … capped at 5 minutes) on repeated
  failed credentials, applied uniformly to both the login form and the
  Bearer-header path, with a live client-side countdown on the login page.
- Per-failure logging (source IP + path) for fail2ban/crowdsec integration,
  plus ready-to-install configs and setup instructions in `contrib/`.
- MIT license.
- The active credential (pinned via `COMFYUI_CURU_AUTH_TOKEN` or
  auto-generated) is now persisted to a file under ComfyUI's own `user/`
  directory and reused on every subsequent restart — including a
  Manager-triggered `os.execv` reboot, which reuses the process's existing
  environment and can never pick up an externally-set env var after the
  fact. Previously an auto-generated credential changed on every restart,
  and any operator-supplied env var set *after* the pod/container was first
  created never reached this module at all.

### Fixed

- A `curu_auth` session cookie stranded by a ComfyUI restart no longer
  locks its own client out. Sessions are in-memory and start empty on every
  restart (which curu performs routinely); the browser's cookie is not, so
  an already-open ComfyUI tab replayed a cookie that could never validate
  again — 253 requests per page load, and a `/ws` handshake every 300ms
  indefinitely. Each replay is an offered-and-wrong credential, so the
  backoff escalated to its 5-minute cap after ~8.5 minutes and was then
  renewed forever, locking that address out of the login form needed to
  recover (one `RateLimiter` is shared by the middleware, the form and the
  OIDC routes). The rejecting response now expires that cookie — on the
  `401`, on an already-blocked `429`, and on each one's `Accept: text/html`
  redirect — so the client stops replaying it and there is no second
  request to charge. What counts as an authentication attempt is
  deliberately unchanged: the first such request still consumes the backoff
  budget, which is what keeps session-token guessing bounded. A *valid*
  session cookie is never touched, and neither is a cookie of that name
  when cookie auth is disabled.
- A request offering **no** credential at all is no longer recorded as a
  failed authentication attempt. Previously a missing `Authorization`
  header produced `b""`, failed the constant-time comparison, and was
  counted identically to a *wrong* credential — so a few dozen
  credential-less requests (a health check, a readiness poll, a browser
  page load before login) locked out any legitimate client sharing that
  client key, via the escalating backoff. It caused the same incident at
  least three times and was worked around twice: `docker/comfyui/`
  `healthcheck.py` had to accept `429` as proof-of-gate, and ~30
  unauthenticated readiness polls turned `curu`'s own system-test suite's
  first real `POST /prompt` into a `429`. The rejection itself is
  unchanged — same `401`, same body, same `Accept: text/html` redirect to
  the login page, same fail2ban/crowdsec log line — only the failure
  accounting changed. `build_login_routes` had the identical defect for a
  POST with a blank or absent `token` field, fixed the same way. Anything
  non-blank still counts, however malformed (a `Basic` scheme, a bare
  `Bearer`, a never-issued session cookie, a token that encodes to `b""`),
  so a brute-forcer gains nothing: testing a credential requires sending
  one.
- `docker/comfyui/healthcheck.py` now requires `401` exactly, no longer
  accepting `429`. That acceptance existed only to tolerate the defect
  above (its own unauthenticated probe rate-limiting itself); with the
  cause gone, a `429` there would mean a real lockout of some other
  client on `127.0.0.1` and must not be reported as healthy.
- The credential-announcement `print()` calls in `__init__.py` (the
  active-credential line and, when OIDC is configured, the OIDC-login-URL
  line) now pass `flush=True`. Real ComfyUI replaces `sys.stdout` with its
  own `LogInterceptor` (`app/logger.py`), a plain, block-buffered
  `io.TextIOWrapper` that does **not** preserve `PYTHONUNBUFFERED=1`'s
  unbuffered/write-through behavior — a bare `print()` after that swap
  could sit in that wrapper's internal buffer indefinitely and never reach
  captured process/container logs, confirmed live (never appeared even
  after 30+ real requests and a full graceful shutdown). Any external tool
  that reads the credential back out of process logs — an operator running
  `docker logs`, or `curu`'s own SSH-based credential-scraping provisioning
  step (`darth-veitcher/curu#216`) — could race this and see nothing, or
  see a stale line from an earlier run.
- Login page countdown now anchors to a real deadline instead of
  decrementing per tick, so it stays accurate regardless of tab throttling.
- `pytest`'s own `Package.setup()` unconditionally imports every
  `__init__.py` it finds as soon as *any* test in this repo runs — including
  this one, whose relative imports only resolve under the real parent-package
  context ComfyUI's custom-node loader provides. Previously this crashed the
  entire test suite outside of the one deliberate, hand-built import in
  `tests/test_oidc.py::TestInitPyWiringIsOidcAware`; `__init__.py` now
  degrades to its documented no-op instead.

[Unreleased]: https://github.com/darth-veitcher/comfyui_curu_auth/commits/main
