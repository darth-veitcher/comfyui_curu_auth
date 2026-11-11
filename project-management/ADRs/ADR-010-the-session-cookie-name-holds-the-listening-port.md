# ADR-010: The name of the session cookie holds the port that the gate listens on

## Status

Accepted

_Date:_ 2026-11-11
_Deciders:_ James Veitch (with Claude Code)

Amends [ADR-002](ADR-002-oidc-session-sharing-and-test-idp.md),
[ADR-005](ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md) and
[ADR-006](ADR-006-session-cookie-secure-follows-the-browsers-scheme.md), which
name the session cookie `curu_auth`.

---

## Context

The gate gave its session cookie one fixed name, `curu_auth`, with no `Domain`
and with `Path=/`. A browser keys cookies by host name, not by port (RFC 6265,
section 8.5). So two ComfyUI instances on one host share one cookie, for
example `http://192.168.1.117:8188` and `http://192.168.1.117:8189`.

Each gate keeps its sessions in memory (`SessionStore`). A login to the second
instance wrote over the cookie of the first instance. The first gate did not
know that session, so it sent the browser to the login page again. The operator
could stay logged in to only one instance at a time. The OIDC callback sets the
same cookie, so the OIDC login had the same problem.

This occurred on 2026-11-11 on orange-box. That host has three instances, on
ports 8188, 8189 and 8190, which curu-infra installs (issue #30). Different
host names do not show the problem, because each host name has its own cookies.

## Decision

The name of the session cookie is `curu_auth_<port>`, for example
`curu_auth_8188`. The port is the local port of the accepted connection: the
port that this gate listens on. `gate.session_cookie_name(request)` makes the
name from the `sockname` of the transport.

- The login form, the OIDC callback, the check in the middleware and the
  expiry of an unknown cookie all use this one function. So a gate reads,
  issues and expires only its own cookie.
- A gate does not read the cookie of another gate. That cookie is not an
  offered credential there, and the gate does not expire it.
- When the connection has no port to read, the port part is `0`. A Unix
  socket and a closed connection have no port. Port 0 is the socket convention
  for "no port".
- A cookie with the old name `curu_auth` is not read. Each browser logs in
  again one time after the upgrade. There is no alias.
- `HttpOnly`, `SameSite=Strict`, `Path=/`, the 30-day `Max-Age` and the
  scheme-dependent `Secure` of ADR-006 do not change.

Jupyter Server does the same thing for the same reason: its cookie name holds
the host and the port of the server.

## Consequences

- Each instance on one host keeps its own login in one browser. No setting is
  necessary.
- Behind a reverse proxy, the name holds the port of the ComfyUI process, not
  the public port. Each instance then has its own host name, so the name has no
  effect on the problem there.
- A program that reads the cookie by its name must read `curu_auth_<port>`.
  The tests of the `system` and `rauthy` tiers do this.

## Considered Alternatives

### Alternative A: The port of the `Host` header

This is the port that the browser used. **Why rejected:** the client writes
`Host`, and `X-Forwarded-Host` too. Behind a reverse proxy, `Host` holds 443 or
80 for each instance. The listening port is a fact of the server, and it is the
same on each request to one gate.

### Alternative B: A setting for the cookie name

An operator sets `COMFYUI_CURU_AUTH_COOKIE_NAME` for each instance. **Why
rejected:** each installer must then set a different value. A missing value
gives the problem again, with no error. The listening port is already different
for each instance.

### Alternative C: A `Path` or a `Domain` for each instance

**Why rejected:** ComfyUI serves each instance at `/`, so a `Path` cannot
separate them. A `Domain` cannot hold a port.

### Alternative D: Keep `curu_auth` as an alias that the gate also reads

**Why rejected:** an alias keeps the shared cookie alive, and so it keeps the
defect. A gate restart ends each session anyway, so the old cookie has no
value after the upgrade.

## Links

- Issue [#30](https://github.com/darth-veitcher/comfyui_curu_auth/issues/30)
- RFC 6265, section 8.5, "Weak Confidentiality"
- `gate.session_cookie_name`, `gate.set_session_cookie`
- `tests/test_gate.py`: `TestTheSessionCookieNameHoldsTheListeningPort` and
  `TestTwoGatesOnOneHostKeepTheirOwnLogins`
