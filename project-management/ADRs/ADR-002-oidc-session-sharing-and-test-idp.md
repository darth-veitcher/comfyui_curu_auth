# ADR-002: OIDC shares the existing session mechanism; Authelia (Lite) as the local test IdP

## Status

Accepted

_Date:_ 2026-07-23
_Deciders:_ James Veitch (with Claude Code)

---

## Context

`oidc-auth`'s Success Criteria commit to "landing on the same session-cookie
mechanism the default credential path uses" — but `gate.py` today has
exactly one session primitive (`SessionStore`, a set of opaque tokens
minted by `build_login_routes`'s login form) and no OIDC client code at
all. Before speccing this epic, two things needed deciding: how a second,
OIDC-based login path plugs into that existing mechanism without doubling
the surface area `build_gate_middleware` has to trust, and — since
`local-test-harness` (ADR-001) already established this project's "real
dependency, not a mock" testing standard — what real OIDC provider the
harness should test against.

## Decision

**Session sharing**: an OIDC callback route mints a session exactly the
way `build_login_routes`'s `login_post` already does on success — call the
same `SessionStore.issue()`, set the same `curu_auth` cookie with the same
attributes (`HttpOnly`/`Secure`/`SameSite=Strict`). `build_gate_middleware`
needs zero changes: it already accepts any token `SessionStore` recognizes,
regardless of which login path minted it. The Bearer-header / default
zero-config credential path is untouched and unaware OIDC exists.

**Test IdP**: extend `local-test-harness`'s `docker-compose.yml` (ADR-001)
with an `authelia` service using Authelia's **Lite** bundle — file-based
user config, SQLite-backed storage, no Postgres/Redis. Authelia is OpenID
Certified as a Provider (not just an SSO reverse-proxy — it can issue
tokens to a relying party the way this epic needs), and the Lite bundle
keeps the harness within the "lightweight, CPU-only" constraint the
Roadmap already commits to, rather than pulling in a heavier IdP stack for
a single-operator test scenario.

## Consequences

**Easier**: `oidc-auth`'s spec can write real, live integration tests
against a genuine OIDC provider — not mocked token responses — matching
the standard this project already holds the ComfyUI harness itself to.
`build_gate_middleware` and `SessionStore` need no new code paths to
support a second login origin; only a new route (the OIDC callback) and
new client code (token exchange, ID-token validation) are additive.

**Harder / constrained**: the harness gains a second service
(`comfyui` + `authelia`) instead of one — startup/teardown sequencing in
`tests/system/` must account for both being healthy before OIDC-flow tests
run. Authelia's own static configuration (registered OIDC client, HMAC/JWK
secrets) needs to be checked into the repo alongside `docker/comfyui/`,
analogous in shape but a genuinely new piece of harness surface.

**Debt**: Authelia's version pin and the exact static-client configuration
are deferred to when `oidc-auth` is actually specced — this ADR fixes the
*choice*, not the configuration detail.

## Considered Alternatives

### Alternative A: A separate OIDC-specific session store/cookie

**Why rejected:** Would double the surface area `build_gate_middleware`
has to trust (two session mechanisms instead of one) for no benefit —
`SessionStore`'s existing semantics (opaque token, constant-time compare,
in-memory, cleared on restart) already fit an OIDC-originated session
identically to a form-originated one.

### Alternative B: Store the OIDC ID token/JWT directly as the session cookie (stateless)

**Why rejected:** Would require the middleware to verify JWT signatures on
every request — a new dependency (a JWT/crypto library) in the hot path,
directly against Constitution Principle I (Minimal Attack Surface). The
existing opaque-token-plus-in-memory-set pattern is simpler and already
sufficient for a single-operator gate.

### Alternative C: Keycloak as the test IdP

**Why rejected:** JVM-based, materially heavier resource footprint and
slower cold start than this harness's CPU-only, fast-dev-loop goals — the
same startup-time concern ADR-001 already flagged for the ComfyUI side
would reappear on the IdP side too.

### Alternative D: Dex as the test IdP

**Why rejected:** A plausible lightweight alternative (Go-based, minimal
footprint) — but Authelia was the option raised during epic planning
(2026-07-23) and is already independently validated as OpenID Certified;
no concrete downside to Authelia surfaced that would justify diverging
from that direction.

### Alternative E: ORY Hydra as the test IdP

**Why rejected:** Headless-only — no built-in login UI, so it would need
pairing with a separate login-provider application, adding more moving
parts than this harness's scope warrants.

---

## Links

- Related epic: [oidc-auth](../Roadmap/epics/oidc-auth.md)
- Related ADR: [ADR-001](ADR-001-docker-comfyui-test-harness.md) — the harness this epic's Authelia service extends
- External reference: [Authelia OpenID Connect 1.0 Provider docs](https://www.authelia.com/configuration/identity-providers/openid-connect/provider/)
