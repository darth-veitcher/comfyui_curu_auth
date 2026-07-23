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

## Decision: Headless Authelia login — `POST /api/firstfactor` + authorization-URL `GET`, pre-configured `consent_mode: implicit`

**Rationale**: Authelia's own login portal is a React SPA — a plain HTTP
client can't "click through" it — but the API it calls is directly
scriptable: `POST /api/firstfactor` with the harness's test user's
credentials sets Authelia's own session cookie, after which a `GET` of the
authorization URL (with that cookie attached) proceeds through Authelia's
OIDC flow to the registered `redirect_uri`, no browser involved. The one
precondition: the static client Authelia is configured with must set
`consent_mode: implicit` (or otherwise pre-authorize the client) — without
it, the flow stalls on an interactive consent screen a headless client
can't drive. Validated as a throwaway spike (tasks.md's dedicated spike
task) *before* any production callback-handling code was written — found
during adversarial engineering review (2026-07-23) that this needed
confirming, not assuming, given the live-verification criterion would
otherwise silently depend on the not-yet-built `browser-e2e` epic.

**Alternatives considered**: A real browser via Playwright — rejected as
the *default* path; would pull `browser-e2e`'s dependency forward into
this epic despite ADR-002/ADR-003 explicitly scoping it out, for no
benefit over the scriptable API path Authelia already exposes.

**Revised (2026-07-23, user direction)**: if the headless spike (tasks.md
T009) fails, fall back to Playwright directly in this spec's own live
test rather than treating spike failure as a hard stop. This is narrower
than adopting `browser-e2e`'s own scope: Playwright here would only drive
Authelia's login portal (a React SPA, but standard DOM interaction — no
WebAuthn virtual-authenticator API needed), which doesn't require or
justify pulling `browser-e2e`'s own WebAuthn-ceremony tooling forward.
`browser-e2e`'s reason to exist is unchanged either way.

**SPIKE RESULT (2026-07-23): confirmed working, no Playwright needed.**
Ran the exact sequence against a standalone Authelia `latest` (v4.39.20)
container: `POST /api/firstfactor` (200, session cookie set) →
`GET /api/oidc/authorization` with that cookie (303, straight to the
registered `redirect_uri` with `code`/`state`/`iss` — no consent screen,
`consent_mode: implicit` confirmed sufficient) →
`POST /api/oidc/token` with the code (200, returns `access_token` +
`id_token`). Decoded the `id_token`: `iss` matched the configured
`authelia_url` exactly, `aud` matched `client_id`, `nonce` matched what
was sent. The entire authorization-code flow is headlessly scriptable
with nothing beyond `curl`/`aiohttp` — T028's live test can proceed
exactly as planned.

Two real findings from getting the spike running, both feeding T010:

1. **HTTPS is mandatory for Authelia itself, confirmed, not optional for
   local testing** — verified live (`session: domain config #1: option
   'authelia_url' does not have a secure scheme`). A bare `http://` config
   refuses to start at all. See the new TLS-trust decision below for how
   the harness satisfies this without weakening production `oidc.py` code.
2. **The session cookie `domain` must contain a dot or be an IP address**
   — Authelia rejects a bare `localhost` (`option 'domain' is not a valid
   cookie domain`). Not relevant to the final container-network harness
   (which uses the `authelia` service hostname, which *does* contain
   meaning as a Compose network alias — but doesn't literally contain a
   dot either, so T010 needs to verify this against the real hostname
   pattern, not assume the IP-address workaround this spike used applies
   unchanged).

## Decision: The harness trusts a fixed, repo-committed self-signed CA at the OS level — not a TLS-verification bypass in production code

**Rationale**: Since HTTPS is mandatory (confirmed above), `oidc.py`'s
discovery/token/JWKS fetches need to establish trust with Authelia's
certificate. The wrong fix would be adding a "skip TLS verification" flag
to `oidc.py` itself — that's exactly the kind of insecure default a
security-focused gate must never ship, even gated behind a flag nobody
would remember to unset. Instead: generate a self-signed CA once,
committed to the repo under `docker/authelia/` (deterministic, matching
the "fixed test credential" precedent already established in ADR-002 —
this CA is meaningless outside this disposable harness), and install it
into `docker/comfyui/Dockerfile`'s image at build time via the standard
OS trust-store mechanism (`update-ca-certificates` or equivalent). Python's
default `ssl` context (what `aiohttp` uses unless told otherwise) already
trusts the OS store, so `oidc.py` needs zero test-only code paths — the
exact same discovery/token/JWKS-fetch code that will run against a real,
publicly-trusted provider in production runs unmodified here too.

**Alternatives considered**: A TLS-verification-bypass flag in `oidc.py`
(e.g. `verify_ssl=False`) — rejected outright; Constitution Principle I
(Minimal Attack Surface) does not bend for test convenience, and the
OS-trust-store approach achieves the same test outcome with zero
production-code risk.

## Decision: Reconcile the issuer-URL duality — container-internal hostname for the gate, published host port for the test's simulated "browser"

**Rationale**: Found during adversarial engineering review (2026-07-23) —
the classic OIDC-in-Docker-Compose footgun. Two different callers reach
Authelia from two different network vantage points, and conflating them
is the actual risk, not a detail to gloss over:

- The **gate** (inside the `comfyui` container) does every OIDC
  backend-channel call — discovery-document fetch, token exchange, JWKS
  fetch, and `iss`-claim comparison — against Authelia's
  container-network hostname, `http://authelia:9091`. Authelia's own
  `identity_providers.oidc.issuer` config is set to that exact same
  value, so the `iss` claim it mints always matches what the gate
  expects, independent of anything the front-channel does.
- The **live test's simulated "browser"** (a host-side
  `aiohttp.ClientSession`, per the headless-login decision above) reaches
  Authelia's login/authorization endpoints via its **published port on
  the host**, `http://localhost:9091`. It never validates the `iss`
  claim itself, so this address never needs to match the gate's.
- The **redirect_uri** registered with Authelia points at whatever
  actually completes the front-channel redirect — the host-side test
  client, so `http://localhost:8188/curu-auth/oidc/callback` (the
  `comfyui` service's already-published port).

Three addresses for what looks like "the same provider" — reconciled by
keeping straight which is a backend-channel address (must match `iss`)
and which are front-channel addresses (never validated, just reachable by
whoever makes that particular call).

**Alternatives considered**: A single shared hostname for everything
(e.g. adding a host-side `/etc/hosts` entry so `authelia` resolves from
the host too) — rejected as an unnecessary environment-specific setup
step when the two-address reconciliation above needs no host
configuration at all and generalizes to any developer's machine
unchanged.

## Decision: No JWKS caching — fetch fresh per verification

**Rationale**: Found during adversarial engineering review (2026-07-23) —
an unstated cache is worse than no cache here. Login is a low-frequency
operation (not a hot request path), so the cost of one extra HTTP fetch
per login is negligible, while a cache that never invalidates would fail
every login after the provider rotates signing keys, silently, until a
restart. Simplicity wins over a premature optimization.

**Alternatives considered**: Cache JWKS for the process lifetime —
rejected; saves one rare HTTP call per login at the cost of a silent,
full-outage-on-key-rotation failure mode.

## Decision: Discovery document fetched fresh per login attempt, with a bounded timeout and fail-closed on error

**Rationale**: Directly required by the spec's own Edge Case ("identity
provider is unreachable or times out during the callback") — the fetch
needs an explicit `aiohttp.ClientTimeout` and must treat any failure
(timeout, connection error, malformed document) as a hard failure of that
login attempt, never a partial or cached fallback that could silently
serve a stale or attacker-influenced endpoint set. Same reasoning as the
JWKS decision above: a rare operation doesn't need a cache, and a cache
would trade rare extra latency for a correctness risk.

**Alternatives considered**: Fetch once at startup, cache for the process
lifetime — rejected for the same reason as JWKS caching.

## Decision: Promote `gate._client_key` to a public `client_key` export

**Rationale**: Found during adversarial engineering review (2026-07-23) —
`oidc.py` needs the exact same client-identity function `RateLimiter` and
the failure logger already key on (US3's rate-limit/logging parity,
FR-005/FR-006), but `_client_key` is underscore-private and absent from
`gate.py`'s `__all__`. A second module needing a name is exactly the
signal that it should no longer be private. Renamed and exported; no
behavior change to the function itself.

**Alternatives considered**: Importing the private name directly from
`oidc.py` with a justifying comment — rejected; the entire point of a
leading underscore is "nothing outside this module relies on this," and a
second real consumer means that's no longer true.

## Decision: The OIDC start route is rate-limited by the same shared `RateLimiter`, and the in-flight-request store is size-capped — both, not either

**Rationale**: Found during adversarial engineering review (2026-07-23) —
the start route must sit in the public-paths bypass (FR-010; it's
reachable pre-session by definition, like the login form already is),
which means an unauthenticated caller could otherwise hammer it to grow
the In-Flight Auth Request store without limit (`data-model.md`'s own
`created_at` field is explicitly not a security control). Two independent
bounds, both cheap:
- Reuse the *existing* shared `RateLimiter` instance (the same one
  already backing the credential and login-form paths) on this route —
  no new mechanism, matching Simplicity.
- Cap the In-Flight store's total size (oldest entries evicted first) as
  a second, independent bound — rate-limiting slows a single client
  identity; the size cap bounds the worst case if an attacker spreads
  requests across many distinct identities (e.g. rotating
  `X-Forwarded-For` values) to evade per-client throttling.

**Alternatives considered**: Rate-limiting alone — rejected; `_client_key`
(soon `client_key`) is best-effort by its own docstring, and a size cap
costs almost nothing to add as defense in depth against exactly the
identity-rotation case that already documents itself as a known
limitation.

## Discovered during the T009 spike: mount Authelia's config as a directory, not individual files

**What happened**: Bind-mounting individual files (`configuration.yml`,
`users_database.yml`) directly onto container paths that don't already
exist as files in the base image intermittently got created as
directories instead by the Docker Desktop macOS VM layer — a known class
of Docker bind-mount gotcha, worse once a path has been mounted once
(subsequent mounts of the same host path can reuse a stale
directory-typed entry from the VM's own cache, surviving across separate
`--rm` containers).

**Fix**: Mount the whole config directory as `/config` in one bind mount,
not each file individually. T010's `docker-compose.yml` entry for the
`authelia` service should do the same — a directory volume mount for
`docker/authelia/` as `/config`, not a `volumes:` entry per file.

## Decision: No `contracts/` directory

**Rationale**: Consistent with `specs/001-docker-comfyui-harness/`'s own
precedent — this is server-side gate logic with no external API surface
of its own beyond the two new HTTP routes, which are documented in
`quickstart.md` and the spec's own Functional Requirements instead.
