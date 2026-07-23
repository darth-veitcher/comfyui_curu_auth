# Research: OIDC/OAuth Login Path

## Decision: `joserfc` for JWK/JWT verification — the one new runtime dependency this spec adds

**Rationale**: OIDC's authorization-code flow itself is plain HTTP (a
discovery-document fetch, a browser redirect, a token-endpoint POST) —
nothing here needs a new dependency beyond `aiohttp`, already this
project's one runtime dependency. Verifying the identity provider's signed
ID token against its published JWKS (rotating RSA/EC keys, `kid`-based key
selection, `iss`/`aud`/`exp`/`nonce` claim checks) is different: this is
exactly the kind of cryptographic correctness Constitution Principle IV
(Test-First for Security-Critical Logic) and Principle I (Minimal Attack
Surface) both say not to hand-roll — algorithm-confusion and
signature-verification bugs are a well-known, recurring class of OIDC
relying-party vulnerability.

Compared three options (web search, 2026-07-23):
- **`joserfc`** — narrow, RFC-scoped JOSE implementation (JWS/JWE/JWK/JWA/JWT
  only), the modern successor to Authlib's own `authlib.jose` module
  (Authlib's docs point migrations at it). No OAuth client/server framework
  bundled — exactly the one piece this spec needs and nothing more.
- **`PyJWT`** — still widely used, but JWKS key-set handling and claims
  validation are more manual/piecemeal than `joserfc`'s, pushing more
  security-relevant logic into this project's own code rather than a
  vetted library's.
- **`python-jose`** — effectively superseded; current guidance points
  migrations away from it, not toward it.
- **Full `authlib`** — rejected as too broad: bundles a complete OAuth
  client/server framework this spec doesn't need, since the
  authorization-code-flow plumbing itself is deliberately hand-rolled over
  `aiohttp` (see below) — pulling in all of `authlib` to use only its JOSE
  slice would add attack surface with no corresponding benefit over
  `joserfc` alone.

**Decision**: Add `joserfc` as the one new `[project.dependencies]` entry.
Implement OIDC discovery and authorization-code token exchange directly
over `aiohttp.ClientSession` — no framework, matching Constitution
Principle V (Simplicity: prefer the plainest construct).

## Decision: Generalize `gate.py`'s single `LOGIN_PATH` bypass into a small "public paths" set

**Rationale**: `build_gate_middleware` today lets exactly one path
(`LOGIN_PATH`) through unauthenticated, for the same chicken-and-egg
reason a brand-new OIDC start/callback route needs the same treatment: a
browser arriving at `/curu-auth/oidc/callback` has no session yet by
definition. Rather than hardcoding a second special-cased path check
alongside the first, generalize `LOGIN_PATH` (a single string) into a
small, explicit set of unauthenticated-allowed paths — `{LOGIN_PATH}` when
OIDC is unconfigured (byte-for-byte the same set as today, satisfying
FR-002/FR-004), extended to include the OIDC start and callback paths only
when OIDC is actually configured.

**Rationale for the "set", not a broader rule**: Keeps Constitution
Principle II (Total Route Coverage) intact — every route not explicitly,
narrowly named in this set stays fully gated, including every OIDC-related
route except the two that must be reachable pre-session by definition.

**Alternatives considered**: A generic "startswith `/curu-auth/`" bypass
rule — rejected: would also exempt any *future* route added under that
prefix without a deliberate decision each time, quietly weakening Total
Route Coverage as a side effect of unrelated future changes. An explicit
set requires a conscious edit to widen it.

## Decision: In-memory, short-lived state for the OIDC flow (state/nonce/PKCE verifier)

**Rationale**: The authorization-code flow needs to correlate the request
that started the flow with the callback that completes it (CSRF-style
`state`, replay-resistant `nonce`, and a PKCE code verifier) — this is
transient, seconds-to-minutes-lived data, not a session. Follows
`SessionStore`'s own precedent (ADR-002): in-memory only, cleared on
restart, no durable storage (FR-008), matching this gate's fully-stateless
design elsewhere.

**Alternatives considered**: Encoding this state into a signed cookie
instead of server-side memory — rejected as unnecessary complexity for a
single-operator gate with no multi-instance/load-balancing concern this
project has today; server-side memory is simpler (Simplicity) and
sufficient.

## Decision: Live tests authenticate against Authelia (Lite bundle) in `local-test-harness`'s harness, per ADR-002

**Rationale**: Already decided at the epic level (ADR-002) — this spec's
own `tests/system/` additions extend
`local-test-harness`'s `docker-compose.yml` with the `authelia` service
ADR-002 named, rather than mocking token responses. Hermetic tests
(`tests/test_oidc.py`) still use a minimal fake/mocked provider double for
fast, offline unit coverage of the token-verification logic itself
(claims rejection, signature mismatch, expiry) — the live suite is for
proving the real end-to-end flow, not for exhaustive edge-case coverage of
`joserfc` usage.

## Decision: No `contracts/` directory

**Rationale**: Consistent with `specs/001-docker-comfyui-harness/`'s own
precedent — this is server-side gate logic with no external API surface
of its own beyond the two new HTTP routes, which are documented in
`quickstart.md` and the spec's own Functional Requirements instead.
