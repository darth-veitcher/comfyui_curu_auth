# comfyui_curu_auth

## What is this

comfyui_curu_auth is a ComfyUI custom node that puts a credential in front of your whole ComfyUI server. It covers each route, also the `/ws` connection that progress updates use. It needs no accounts, no configuration file and no external service. Install it and restart ComfyUI, and it prints a new credential to the console. It is for a person who runs ComfyUI on a home computer or on a rented GPU.

<img src="docs/screenshots/login.png" width="480" alt="Login screen">

## What you can do

| Task | Command or setting | Section |
|---|---|---|
| Call ComfyUI from a program | `Authorization: Bearer <credential>` | [Call ComfyUI from a program](#call-comfyui-from-a-program) |
| Log in from a browser | Open `/curu-auth/login` | [Log in from a browser](#log-in-from-a-browser) |
| Keep the same credential | `COMFYUI_CURU_AUTH_TOKEN` | [Keep the same credential after a restart](#keep-the-same-credential-after-a-restart) |
| Log in with your identity provider | `COMFYUI_CURU_AUTH_OIDC_ISSUER_URL` and 4 more | [Log in through your identity provider](#log-in-through-your-identity-provider) |
| Choose HTTPS or plain HTTP | `X-Forwarded-Proto: https` at your proxy | [Use HTTPS or plain HTTP](#use-https-or-plain-http) |
| Understand a 429 | Wait for `Retry-After` | [Recover from repeated failures](#recover-from-repeated-failures) |
| Block attackers at the firewall | `contrib/fail2ban`, `contrib/crowdsec` | [Block repeat offenders at the firewall](#block-repeat-offenders-at-the-firewall) |

## Install

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/darth-veitcher/comfyui_curu_auth
```

## Quickstart

1. Restart ComfyUI. The console shows the credential:

   ```text
   comfyui-curu-auth gate active. Credential:
     Yx3fQvR8...
   ```

2. Open ComfyUI in your browser. The gate sends you to its login page.
3. Paste the credential, and select "Log in". ComfyUI opens.

You cannot get the credential over the network. It goes only to the console. This is deliberate: an exchange of credentials over the network would be a new point of attack.

## Call ComfyUI from a program

Send the credential in the `Authorization` header of each request, also on the `/ws` handshake:

```bash
curl -H "Authorization: Bearer $COMFYUI_CURU_AUTH_TOKEN" http://127.0.0.1:8188/queue
```

A correct credential gives the normal answer of ComfyUI. A missing or wrong credential gives HTTP 401 with `{"detail": "missing or invalid credential"}`.

## Log in from a browser

Open `/curu-auth/login`, or any page of ComfyUI, and paste the credential. The gate then sets a session cookie, `curu_auth`, for 30 days. The cookie is `HttpOnly` and `SameSite=Strict`. It holds a separate session token, so the browser never sends the credential again.

The session lives in memory. A restart of ComfyUI ends each session, and the browser shows the login page again.

## Keep the same credential after a restart

The gate keeps the active credential in `user/default/comfyui_curu_auth/credential` under ComfyUI. It uses that file at each restart. So the credential stays the same, also after a reboot from ComfyUI-Manager.

To choose the credential yourself, set `COMFYUI_CURU_AUTH_TOKEN`:

```bash
export COMFYUI_CURU_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Set it where you start ComfyUI: a shell `export`, the `Environment=` of a systemd unit, or the `environment:` of a `docker-compose.yml`. The variable always wins over the file, and the gate writes its value to the file.

A reboot from ComfyUI-Manager keeps the old environment of the process. A variable that you set after the first start reaches the gate only through the file.

## Log in through your identity provider

An identity provider is a service that logs people in, for example rauthy, Authentik, Keycloak or Google. The gate can use one with OpenID Connect (OIDC). The credential and the Bearer header keep working.

1. Register a confidential client at the provider. Use PKCE `S256` and an asymmetric signing key, for example RS256 or EdDSA.
2. Register the redirect URI `https://<your ComfyUI host>/curu-auth/oidc/callback`.
3. Copy the issuer exactly from `<issuer>/.well-known/openid-configuration`, with or without its `/` at the end.
4. Set the four settings of the client:

   ```bash
   export COMFYUI_CURU_AUTH_OIDC_ISSUER_URL="https://idp.example.com/application/o/comfyui/"
   export COMFYUI_CURU_AUTH_OIDC_CLIENT_ID="comfyui-curu-auth"
   export COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET="<client secret>"
   export COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI="https://comfyui.example.com/curu-auth/oidc/callback"
   ```

5. Set who can log in, for example:

   ```bash
   export COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS="<sub of each person>"
   ```

6. Restart ComfyUI. The login page now has "Log in with your identity provider".

A successful login gives the same `curu_auth` cookie as the credential form. [Connect an OIDC provider](docs/oidc-providers.md) gives the steps for rauthy, Authentik, Keycloak, Auth0, Okta, Microsoft Entra ID, Google and Authelia.

| Setting | Meaning | Default |
|---|---|---|
| `COMFYUI_CURU_AUTH_OIDC_ISSUER_URL` | The issuer, exactly as the discovery document gives it. | none |
| `COMFYUI_CURU_AUTH_OIDC_CLIENT_ID` | The client id at the provider. | none |
| `COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET` | The client secret at the provider. | none |
| `COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI` | The callback URL that the provider sends the browser to. | none |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS` | The `sub` values that can log in, with a comma between them. | empty |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_EMAILS` | The emails that can log in. An email matches only when `email_verified` is true. | empty |
| `COMFYUI_CURU_AUTH_OIDC_ALLOWED_DOMAIN` | One Google Workspace domain, compared with the `hd` claim. | empty |
| `COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER` | `true` lets each person that the provider accepts log in. | `false` |
| `COMFYUI_CURU_AUTH_OIDC_SCOPES` | The scopes of the login, with a space or a comma between them. The gate always adds `openid`. | `openid profile email` |

The OIDC login is off until the four client settings are set. If one of them is missing, the gate starts as if none were set.

With the four client settings but no allowlist, the OIDC login also stays off. The console then shows `OIDC login is off: set ...`. Set an allowlist, or `ALLOW_ANY_USER=true` when the provider already limits who can log in. Never set `ALLOW_ANY_USER=true` for Google, because each Google account can log in there.

The gate refuses a login when one of these is true:

- The discovery document names another issuer, or an endpoint uses plain `http` on a host that is not loopback.
- The ID token uses `none` or an HMAC algorithm such as HS256.
- The ID token has no `exp` or no `iat`, or it expired more than 60 seconds ago.
- The person is not on the allowlist.

A refused login gives HTTP 401 and counts as a failed attempt.

## Use HTTPS or plain HTTP

The session cookie is `Secure` when your browser reached ComfyUI over HTTPS. The gate knows this in two cases:

- ComfyUI serves TLS itself, with `--tls-keyfile` and `--tls-certfile`.
- A reverse proxy ends TLS and sends `X-Forwarded-Proto: https` or `Forwarded: proto=https`. The proxy of RunPod does this.

On plain HTTP, for example `http://<lan-address>:8188`, the cookie has no `Secure`. A browser does not keep a `Secure` cookie from a plain HTTP page, except on localhost. `HttpOnly`, `SameSite=Strict` and the 30 days do not change.

Plain HTTP has a cost. The session cookie, the credential in the form and each `Authorization` header cross the network with no encryption. A person who can watch that network can use them again. Use HTTPS on each network that you do not trust.

To check your proxy, log in through it and read the `Set-Cookie` of the response. It must end in `; Secure`. If it does not, configure your proxy to send `X-Forwarded-Proto` or `Forwarded`.

## Recover from repeated failures

<img src="docs/screenshots/rate-limited.png" width="480" alt="Rate-limited login screen with a live countdown">

After a wrong credential, the gate makes that client wait before its next try. The wait doubles after each failure: 1 s, 2 s, 4 s, and up to 5 minutes. During the wait, each request gets HTTP 429 with `Retry-After`. A correct attempt sets the wait to zero again. The login page shows a countdown, so you do not need to reload it.

The same wait applies to the login form, the Bearer header and the OIDC login. A session that is already open is never blocked.

Only a request that **offered** a credential counts as a failure. A request with no `Authorization` header, no session cookie and no form token gets HTTP 401, but it does not start a wait. So a health check that has no credential cannot lock out a real client at the same address. Each value that is not blank counts, also a malformed one.

A session cookie from before a restart is a wrong credential, and it counts. The gate then expires that cookie in its answer, so the browser stops sending it. Without this, an open ComfyUI tab would renew the 5-minute wait forever.

The credential has 256 bits of entropy, so a guess cannot succeed. The wait limits the number of guesses and log lines that a scanner can make.

## Block repeat offenders at the firewall

The gate writes one line for each refused request:

```text
comfyui_curu_auth: authentication failure from 203.0.113.7 (GET /object_info)
comfyui_curu_auth: authentication failure from 203.0.113.7 (login form)
comfyui_curu_auth: authentication failure from 203.0.113.7 (oidc callback: the person is not on the allowlist)
```

The text after `from` is the address of the client. The text in parentheses is the path or the reason, and it never holds a credential or a token. [`contrib/`](contrib/README.md) has configurations for fail2ban and crowdsec, with the steps to install them.

## Limits

- The gate has one credential for all people. It gives no roles and no separate accounts. The OIDC allowlist decides who logs in, not what they can do.
- The gate accepts one OIDC provider at a time.
- A multi-tenant Microsoft Entra ID app is not supported. Use the issuer of one tenant.
- Sessions live in memory. A restart of ComfyUI ends each session.
- The address of a client comes from `X-Forwarded-For` when a proxy sends it. A client that can reach ComfyUI without the proxy can change that header, and so avoid the wait.

## Technical notes

The node adds one `aiohttp` middleware to `server.PromptServer.instance.app` when ComfyUI imports it. ComfyUI registers each route on that app, so the middleware covers each route, also the `/ws` handshake. The node has no node classes, and it serves no JavaScript except the countdown on the login page.

The credential comes from `secrets.token_urlsafe(32)`. The gate compares it with `secrets.compare_digest`, in constant time.

An error in the OIDC settings never stops the node. ComfyUI skips a node whose import fails, so the gate would be off. The gate writes the error and keeps only the OIDC login off.

Decisions:

- [ADR-002](project-management/ADRs/ADR-002-oidc-session-sharing-and-test-idp.md): the OIDC login uses the same session cookie.
- [ADR-003](project-management/ADRs/ADR-003-gate-public-paths-generalization.md): the public paths of the gate.
- [ADR-004](project-management/ADRs/ADR-004-only-offered-credentials-count-as-attempts.md): only an offered credential counts as an attempt.
- [ADR-005](project-management/ADRs/ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md): the gate expires a stale session cookie.
- [ADR-006](project-management/ADRs/ADR-006-session-cookie-secure-follows-the-browsers-scheme.md): `Secure` follows the scheme of the browser.
- [ADR-007](project-management/ADRs/ADR-007-oidc-issuer-algorithms-and-allowlist.md): the issuer, the algorithms and the allowlist of the OIDC login.

The credential scheme comes from [curu](https://github.com/darth-veitcher/curu). The licence is MIT, see [LICENSE](LICENSE).

## Develop

```bash
uv sync
uv run pytest
```

The default tests need no ComfyUI and no network. They run the gate against a small `aiohttp` application, and the OIDC login against a fake provider with RSA, EC and Ed25519 keys.

Two test tiers do not run by default:

| Tier | Command | What it needs and checks |
|---|---|---|
| `system` | `uv run pytest -m system` | Docker. It starts a CPU-only ComfyUI with this node, and Authelia as the OIDC provider. It checks the routes, the `/ws` handshake, the wait and the OIDC login. |
| `rauthy` | `uv run --group live pytest -m rauthy` | Docker and Chromium. It starts rauthy 0.37.2 and logs in through it in a browser, with an EdDSA ID token. |

To install Chromium for the `rauthy` tier, run `uv run --group live playwright install chromium`.

The quality gates are `uv run ruff check`, `uv run ruff format`, `uv run ty check` and `beacon doctor --strict`. `AGENTS.md` gives the rules for a change.

## Glossary

| Term | Meaning |
|---|---|
| Allowlist | The list of people who can get a session through the OIDC login. |
| Bearer header | The header `Authorization: Bearer <credential>` that a program sends. |
| Credential | The secret that the gate prints at start. It opens ComfyUI. |
| Discovery document | The JSON document at `<issuer>/.well-known/openid-configuration`. It names the endpoints and the keys of a provider. |
| ID token | The signed token that the provider gives after a login. It names the person. |
| Identity provider | A service that logs people in, for example rauthy or Authentik. Also "provider". |
| Issuer | The URL that names a provider in its tokens. |
| OIDC | OpenID Connect, the standard that the gate uses to talk to a provider. |
| PKCE | Proof Key for Code Exchange. It stops a stolen login code from being used. |
| Session cookie | The `curu_auth` cookie that keeps a browser logged in for 30 days. |
| `sub` | The subject claim: a fixed id of the person at the provider. |
| Wait | The time a client must wait after a failure before it can try again (backoff). |
