# ADR-006: The session cookie is `Secure` exactly when the browser used HTTPS

## Status

Accepted

_Date:_ 2026-10-16
_Deciders:_ James Veitch (with Claude Code)

Amends [ADR-002](ADR-002-oidc-session-sharing-and-test-idp.md) and
[ADR-005](ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md),
which both list `Secure` among the cookie's fixed attributes.

---

## Context

The `curu_auth` session cookie was set with `secure=True` unconditionally,
at all three places that write it: the login form, the OIDC callback, and
the expiry of an unrecognised session (ADR-005). That was correct for as
long as the gate was reached only through RunPod's proxy, which terminates
TLS: the browser was always on HTTPS.

curu-infra now also installs this node on operator-owned hosts reached at
plain `http://<lan-address>:8188` (curu-infra ADR-050: a host is on the LAN
by default, behind `comfyui_curu_auth`). Browsers refuse to store a
`Secure` cookie set by a plain-HTTP response on any origin except
localhost. So on such a host a **correct** credential at
`/curu-auth/login` got `302 → /`, no cookie was stored, and the gate sent
the browser back to the login page. To the operator, the right credential
looked "not accepted". Confirmed live with curl:

```
HTTP/1.1 302 Found
Location: /
Set-Cookie: curu_auth=…; HttpOnly; Max-Age=2592000; Path=/; SameSite=Strict; Secure
```

The `Authorization: Bearer` path was never affected.

This repo's docker harness could not have caught it. It is reached at
`http://localhost:8188`, and localhost is the one plain-HTTP origin that
browsers treat as secure.

## Decision

Every `Set-Cookie` for `curu_auth` goes through one function,
`gate.set_session_cookie`. It sets `Secure` exactly when
`gate.browser_used_https(request)` is true:

- the connection itself is TLS (`request.secure`; ComfyUI started with
  `--tls-keyfile`/`--tls-certfile`), **or**
- a proxy in front reports that the browser's own hop was HTTPS, in either
  standard form: the de facto `X-Forwarded-Proto: https`, or RFC 7239's
  `Forwarded: proto=https`. Each is read at its left-most entry, the hop
  the browser itself made. `client_key` already reads `X-Forwarded-For`
  the same way.

`HttpOnly`, `SameSite=Strict`, `Path=/` and the 30-day `Max-Age` stay
fixed, on every scheme.

The expiry goes through the same function with the same request, so it
always carries the attributes the cookie was issued with over that scheme.
That matters for more than tidiness. A browser will not let a plain-HTTP
response overwrite a `Secure` cookie ("Leave Secure Cookies Alone"), so an
expiry whose flags drift from the issue's can fail to delete it.

### Why trusting a forwarded header is safe here

`client_key` already trusts `X-Forwarded-For` on a best-effort basis. This
decision needs less than that, because of the direction a header can move
the answer:

- A browser never sends `X-Forwarded-Proto` or `Forwarded` itself. Only
  something in front of the gate adds one.
- A forged `https` can only **add** `Secure`. A client that sends one over
  plain HTTP gets a cookie its own browser refuses to store, so the only
  person it locks out is itself.
- Weakening an HTTPS deployment would take the opposite: a proxy that
  terminates TLS but **doesn't report** https. No client can cause that.
  It is a property of the proxy.

## Consequences

**Easier**: browser login works on a host reached over plain HTTP. On
every HTTPS path the cookie is still `Secure`, so a cookie issued over
HTTPS is still never sent back over plain HTTP.

**Accepted**: over plain HTTP the session cookie travels in clear on the
network. So does the credential typed into the login form on the same
connection, and so does the `Authorization` header on every request there.
Choosing plain HTTP is the operator's decision (curu-infra ADR-050). This
ADR only stops that choice from also breaking browser login. It does not
make plain HTTP any safer, and the README says so.

**Dependency retained**: an HTTPS deployment behind a TLS-terminating
proxy depends on that proxy reporting `https`. RunPod's own documentation
doesn't say which forwarded headers its proxy sends. The way to verify a
deployment is a real login's `Set-Cookie`: over HTTPS it must end in
`; Secure`.

## Considered Alternatives

### Alternative A: Drop `Secure` entirely

This would have fixed the LAN host. It would also weaken every HTTPS
deployment for no gain, letting a cookie issued over HTTPS be sent over
plain HTTP to the same host. Rejected.

### Alternative B: An operator setting (`COMFYUI_CURU_AUTH_COOKIE_SECURE`)

Rejected, because the request already contains the answer. A setting
would be a second record of "which scheme is this deployment on", able to
disagree with the first, and this project's zero-config default would
then have to pick a wrong value for somebody. It is still available if a
proxy is ever found that terminates TLS without reporting it.

### Alternative C: `X-Forwarded-Proto` only

This would cover RunPod-style proxies. It would miss a proxy that speaks
only the RFC 7239 form, which is the actual standard. Reading both costs
one branch, and in this direction neither can do harm.

### Alternative D: Recognise the deployment by its `Host` (e.g. `*.proxy.runpod.net`)

Rejected. It hard-codes a vendor's hostname into a security attribute,
and it would be wrong for every other TLS-terminating proxy.

## Links

- Amends [ADR-002](ADR-002-oidc-session-sharing-and-test-idp.md) (the OIDC
  callback's cookie attributes) and
  [ADR-005](ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md)
  (the expiry's attributes).
- `gate.py`: `browser_used_https`, `set_session_cookie`,
  `_expire_session_cookie`, `build_login_routes`. `oidc.py`: the
  callback in `build_oidc_routes`.
- curu-infra ADR-050: a host is on the LAN by default, behind
  `comfyui_curu_auth`.
- [RFC 7239](https://www.rfc-editor.org/rfc/rfc7239) `Forwarded`;
  [RFC 6265bis](https://datatracker.ietf.org/doc/draft-ietf-httpbis-rfc6265bis/)
  "Leave Secure Cookies Alone".
