# Implementation Plan: OIDC/OAuth Login Path

**Branch**: `002-oidc-login` | **Date**: 2026-07-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-oidc-login/spec.md`

## Summary

Add an optional OIDC/OAuth authorization-code login path that mints a
session through the exact same `SessionStore`/`curu_auth` cookie mechanism
the existing login form already uses (ADR-002), entirely opt-in via
environment variables and fully inert when unconfigured. The
authorization-code-flow plumbing (discovery, redirect, token exchange) is
hand-rolled over the existing `aiohttp` dependency; ID-token signature and
claims verification uses one new, narrowly-scoped dependency (`joserfc`)
rather than hand-rolled cryptography. Live verification runs against a
real Authelia (Lite bundle) instance added to `local-test-harness`'s
Docker harness, per ADR-002 — not a mocked provider.

## Technical Context

**Language/Version**: Python 3.12 (matches `pyproject.toml`
`requires-python`)

**Primary Dependencies**: `aiohttp` (existing — discovery fetch, token
exchange, and the two new route handlers all use it, no new HTTP
dependency); `joserfc` (**new** — ID-token JWK/JWT signature and claims
verification only; see research.md for why this over PyJWT/python-jose/
full Authlib)

**Storage**: N/A for durable storage. New in-memory, short-lived state for
in-flight OIDC flows (`state`/`nonce`/PKCE verifier), analogous to and
alongside `SessionStore` — cleared on restart, never persisted (FR-008)

**Testing**: `tests/test_oidc.py` (new hermetic suite, mocked provider
double via `aiohttp.test_utils`, following `tests/test_gate.py`'s existing
pattern) + `tests/system/` extended to exercise the real flow against a
real Authelia instance (ADR-002)

**Target Platform**: Same as the existing node — wherever ComfyUI + this
custom node runs

**Project Type**: Extension to an existing single-file-ish gate — a new
`oidc.py` module alongside `gate.py`, wired from `__init__.py`

**Performance Goals**: No hard target; a full login round-trip (redirect →
provider auth → callback → token exchange → session established)
completing within a few seconds under normal network conditions is the
sanity bound

**Constraints**: MUST NOT alter the default Bearer-header credential path
in any way (FR-004); MUST fail safe to "OIDC unconfigured" behavior on
partial configuration (FR-009); no durable token storage (FR-008); one
configured provider at a time (epic Non-Goals)

**Scale/Scope**: Single-operator gate, additive second login path — not
multi-tenant, not multiple simultaneous providers

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Minimal Attack Surface (NON-NEGOTIABLE) | PASS, with one justified addition. `joserfc` is the sole new dependency — narrowly scoped to JOSE/JWT verification (research.md), chosen specifically because hand-rolling signature verification is a worse attack-surface outcome than a vetted, narrow library. Discovery/token-exchange reuse the existing `aiohttp`. OIDC is entirely opt-in (FR-001/FR-002) — the zero-dependency default path is untouched when unconfigured. |
| II. Total Route Coverage (NON-NEGOTIABLE) | PASS, revised after adversarial engineering review (2026-07-23). The OIDC start/callback routes are the *only* new unauthenticated-reachable paths, and only when OIDC is configured — generalizing `LOGIN_PATH`'s existing single-path carve-out into a small, explicit set (research.md), not a broad prefix rule. Every other route stays fully gated exactly as today. The initial assessment reasoned only about the *bypass* itself; it's now extended to what the bypass *exposes*: the start route being unauthenticated-reachable means it must not become an unthrottled resource-exhaustion path (FR-010) — closed by reusing the existing shared `RateLimiter` on that route plus an independent size cap on the in-flight-request store (research.md), not a new gate mechanism. |
| III. Zero-Config by Default | PASS. FR-002/FR-009: no OIDC route or behavior exists unless fully configured; partial configuration fails safe to unconfigured, never to a half-working state. |
| IV. Test-First for Security-Critical Logic (NON-NEGOTIABLE) | Applies most sharply here of any feature so far: token signature verification, `state`/`nonce`/PKCE validation, single-use replay rejection (FR-011), and the public-paths carve-out are exactly the logic this principle exists for. `tasks.md` sequences tests before implementation for each, with no compression of the pairing on this spec's crypto-heavy core. |
| V. Simplicity | PASS. Authorization-code flow hand-rolled over existing `aiohttp` rather than adopting a full OAuth client framework; only the genuinely hard cryptographic part gets a dedicated library. Start-route protection reuses the existing `RateLimiter` rather than inventing a second throttling mechanism. |

No violations. Complexity Tracking table below is not needed — the one
new dependency is a justified addition under Principle I, not an
exception to it.

**Post-adversarial-review re-check (2026-07-23)**: Principle II's
assessment above was strengthened per the review's finding (start-route
exposure was previously unaddressed). No other principle's assessment
changed — the review's remaining findings (issuer-URL duality, headless
login feasibility, discovery-fetch/JWKS caching, `_client_key` promotion,
replay rejection) are implementation-correctness and scope findings, not
Constitution-level concerns, and are resolved in research.md and
tasks.md.

**Post-Phase-1 re-check**: Unchanged — Phase 1 design (below) introduced
no dependencies or principle tensions beyond what's assessed above.

## Project Structure

### Documentation (this feature)

```text
specs/002-oidc-login/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
└── tasks.md              # Phase 2 output (/speckit-tasks — not yet created)
```

No `contracts/` directory — see research.md; this is server-side gate
logic, not a public API.

### Source Code (repository root)

```text
oidc.py                    # New module, parallel to gate.py:
                            #   - resolve_oidc_config() from env vars (None if
                            #     unconfigured/partial -- FR-009)
                            #   - discovery-document fetch (aiohttp, fresh per
                            #     attempt, bounded timeout, fail-closed)
                            #   - authorization URL builder (state/nonce/PKCE,
                            #     with a size-capped in-flight store -- FR-010)
                            #   - token exchange (aiohttp POST to token endpoint)
                            #   - ID token verification (joserfc: JWKS fetch --
                            #     fresh per attempt, no cache -- signature,
                            #     iss/aud/exp/nonce claims)
                            #   - build_oidc_routes() -- (start, callback) handlers,
                            #     mirroring gate.py's build_login_routes() shape;
                            #     start route rate-limited via the existing
                            #     shared RateLimiter (FR-010); callback enforces
                            #     single-use state consumption (FR-011)
                            #   - in-memory, short-lived state store for
                            #     in-flight state/nonce/PKCE (FR-008)

gate.py                    # Two changes, both minimal: (1) LOGIN_PATH's
                            # single-path unauthenticated bypass generalized
                            # to a small public-paths set (research.md); (2)
                            # `_client_key` promoted to a public `client_key`
                            # export (oidc.py needs it too -- research.md).
                            # The Bearer-header/default-credential path itself
                            # is otherwise untouched (FR-004)

__init__.py                # Wires oidc.py's routes onto the same app,
                            # only when resolve_oidc_config() returns non-None

docker-compose.yml          # Extended: new `authelia` service (Lite bundle),
docker/authelia/            # its static config (registered OIDC client,
                            # file-based user, HMAC/JWK secrets) -- per
                            # ADR-002

tests/
├── test_oidc.py            # New hermetic suite: mocked provider double,
│                            # state/nonce/PKCE generation+validation,
│                            # token verification (valid, wrong signature,
│                            # expired, wrong audience, replayed nonce)
└── system/
    └── test_oidc_harness.py   # New: live flow against the real Authelia
                                # instance -- login, default-path-unaffected
                                # regression check, rate-limit/logging parity
```

**Structure Decision**: New logic lives in its own `oidc.py` module rather
than growing `gate.py` directly — keeps `gate.py`'s existing, already-
tested surface (credential generation, rate limiter, session store, login
form) undisturbed, and makes FR-004's "MUST NOT alter the default
Bearer-header path" easy to verify by inspection: `gate.py`'s diff for
this feature is limited to the single public-paths generalization.

## Complexity Tracking

*Not applicable — no Constitution Check violations. The one new
dependency (`joserfc`) is assessed as a justified addition under
Principle I, not an exception requiring justification here.*
