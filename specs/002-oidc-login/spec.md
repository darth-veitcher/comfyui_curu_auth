# Feature Specification: OIDC/OAuth Login Path

**Feature Branch**: `002-oidc-login`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "Optional OIDC/OAuth login path that lets an operator with an existing identity provider log in through it, sharing the same session-cookie mechanism the default credential path already uses"

**Epic**: [oidc-auth](../../project-management/Roadmap/epics/oidc-auth.md)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Log in through an existing identity provider (Priority: P1)

An operator who already runs an OIDC identity provider (for their team, or
for other self-hosted services) configures it once, then logs into
ComfyUI by authenticating with that provider instead of pasting the
gate's own printed credential.

**Why this priority**: This is the entire value of the feature — one
fewer credential for an operator who already has an identity provider to
manage separately.

**Independent Test**: Configure OIDC provider details, visit the login
page, choose the OIDC option, authenticate at the identity provider, and
confirm landing back on ComfyUI's UI in an authenticated session.

**Acceptance Scenarios**:

1. **Given** OIDC is configured, **When** the operator initiates login via the OIDC option, **Then** they are redirected to their identity provider to authenticate.
2. **Given** the operator successfully authenticates at the identity provider, **When** they are redirected back, **Then** they land on ComfyUI's UI in an authenticated session — indistinguishable, session-wise, from a form login with the default credential.
3. **Given** the operator cancels or fails authentication at the identity provider, **When** they are redirected back (or return to ComfyUI directly), **Then** they are not authenticated and see an appropriate message.
4. **Given** a state/code pair that already completed a login once, **When** it is submitted again verbatim, **Then** the second attempt is rejected, not accepted (found during adversarial engineering review, 2026-07-23; FR-011).
5. **Given** the OIDC login-initiation route is reachable without a session, **When** it is hit repeatedly by an unauthenticated caller, **Then** the same rate-limiting already applied to other unauthenticated paths applies here too, and in-flight state does not grow without bound (found during adversarial engineering review, 2026-07-23; FR-010).

---

### User Story 2 - Default credential path is completely unaffected when OIDC isn't configured (Priority: P1)

An operator who never configures OIDC sees zero difference in behavior —
no new routes, no new required environment variables, no change to
startup or to the existing credential/login-form/Bearer-header paths.

**Why this priority**: This is the epic's own non-negotiable — the
zero-config default must never regress because an optional feature was
added alongside it (Constitution Principle I; epic Non-Goals).

**Independent Test**: With no OIDC configuration present, confirm
ComfyUI's existing behavior (credential generation or pinning, login
form, Bearer-header auth) is unchanged from before this feature existed.

**Acceptance Scenarios**:

1. **Given** no OIDC configuration is present, **When** ComfyUI starts, **Then** no OIDC-related routes or behavior are exposed, and startup succeeds exactly as it does today.
2. **Given** OIDC is unconfigured, **When** an operator uses the existing credential or login form, **Then** behavior is unchanged from before this feature existed.

---

### User Story 3 - Failed OIDC attempts are logged and rate-limited like every other path (Priority: P2)

Someone probing or abusing the OIDC login path gets the same treatment an
attacker probing the existing credential or login-form paths already
gets: escalating backoff and a greppable log line an operator's
fail2ban/crowdsec setup can act on.

**Why this priority**: Security parity — a new auth path must not be a
softer target than the ones this gate already hardens. Lower priority
than US1/US2 because the feature has no value at all without them first;
this closes a gap in an already-working path.

**Independent Test**: Submit repeated failed OIDC callback attempts from
the same client and confirm the same backoff and logging behavior the
existing paths already exhibit.

**Acceptance Scenarios**:

1. **Given** repeated failed OIDC authentication attempts from the same client, **When** they occur, **Then** the same rate-limit backoff already applied to the credential and login-form paths also applies here.
2. **Given** a failed OIDC attempt is rejected, **When** it happens, **Then** a stable, greppable log line is emitted matching the existing fail2ban/crowdsec-compatible format.

---

### Edge Cases

- What happens if the identity provider is unreachable or times out during
  the callback? The operator MUST see a clear failure, not a silent hang
  or an accidental authenticated session.
- What happens if the identity provider's response is missing an expected
  claim (e.g., no stable subject identifier)? The attempt MUST be
  rejected, not accepted with a degraded/partial identity.
- What happens if OIDC configuration is only partially supplied (e.g., a
  client ID but no client secret, or no redirect URI)? The system MUST
  fail safe — treat OIDC as unconfigured (User Story 2's behavior) rather
  than starting in a half-configured, insecure state.
- What happens if someone replays or forges an OIDC callback (a
  captured/guessed redirect URL, without ever having authenticated)? It
  MUST be rejected — see FR-007.
- A verbatim replay of a *previously-completed* callback, and repeated
  hits on the login-initiation route by an unauthenticated caller, are
  both promoted to full Acceptance Scenarios under User Story 1 above
  (Scenarios 4 and 5) rather than left as edge-case prose only — found
  during adversarial engineering review, 2026-07-23 (FR-010, FR-011).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow an operator to configure OIDC
  provider details (issuer URL, client ID, client secret, redirect URI)
  via environment variables, following this project's existing
  zero-file-config convention.
- **FR-002**: The system MUST NOT expose any OIDC-related route or
  behavior when OIDC is not configured — the app must start and behave
  exactly as it does today.
- **FR-003**: On successful OIDC authentication, the system MUST
  establish a session using the exact same session mechanism (cookie
  name, attributes, in-memory storage) the existing login form already
  uses (ADR-002) — not a second, parallel session mechanism.
- **FR-004**: The system MUST NOT alter the default Bearer-header
  credential path in any way — its behavior is fully independent of
  whether OIDC is configured.
- **FR-005**: Repeated failed OIDC authentication attempts from the same
  client MUST receive the same rate-limit backoff treatment as the
  existing login-form and Bearer-header paths.
- **FR-006**: Every rejected or failed OIDC attempt MUST emit a log line
  in the same stable, greppable format the existing paths already use.
- **FR-007**: The system MUST validate the identity provider's response
  (state/nonce match, token signature and expiry) before establishing a
  session — a forged or replayed callback MUST NOT succeed.
- **FR-008**: The system MUST NOT persist OIDC tokens beyond what's
  needed to establish the session — no durable token storage, matching
  the existing in-memory-only session design.
- **FR-009**: If OIDC configuration is only partially supplied, the
  system MUST fail safe to "OIDC is unconfigured" (User Story 2's
  behavior), never to a half-configured state that starts anyway.
- **FR-010**: The OIDC login-initiation route MUST be subject to the same
  rate-limiting as every other unauthenticated path, and the amount of
  in-flight-authorization-request state an unauthenticated caller can
  cause the system to hold MUST be bounded — this route is necessarily
  reachable pre-session (like the login form already is), and that MUST
  NOT become an unthrottled resource-exhaustion path (found during
  adversarial engineering review, 2026-07-23).
- **FR-011**: A completed authorization attempt (a state/code pair that
  already succeeded once) MUST be single-use — resubmitting it verbatim
  MUST be rejected, not accepted a second time (found during adversarial
  engineering review, 2026-07-23).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with an existing OIDC identity provider goes
  from setting configuration to a working authenticated ComfyUI session
  without writing or editing any code.
- **SC-002**: 100% of ComfyUI's existing zero-config behavior (credential
  generation, login form, Bearer-header auth) is unchanged when OIDC is
  not configured — verified by the existing hermetic and live test suites
  continuing to pass unmodified.
- **SC-003**: 100% of forged or replayed OIDC callback attempts are
  rejected.
- **SC-004**: Repeated failed OIDC attempts trigger the same escalating
  backoff, within the same timing envelope, as the existing credential
  and login-form paths.

## Non-Goals

*(Carried from the parent epic — see
[oidc-auth.md](../../project-management/Roadmap/epics/oidc-auth.md#non-goals).)*

- Not a replacement for the default shared-credential model — additive
  only (Constitution Principle I: the zero-dependency default must stay
  intact).
- Not multi-tenant / per-user roles — still gates the whole backend as
  one boundary, just with a second way through the door.
- Not building a full identity provider — integrates with one the
  operator already runs.
- Not supporting multiple simultaneous OIDC providers in this first
  version — one configured provider at a time.

## Assumptions

- The identity provider is one the operator already operates and trusts
  (e.g., Authelia, Okta, Auth0, Keycloak) — this feature is a relying
  party / OIDC client, not an identity provider itself.
- Authorization Code flow (with PKCE where the provider supports it) is
  the standard, secure default for this kind of client — no need to
  support legacy flows (implicit, resource-owner-password) in this first
  version.
- The redirect/callback route follows the same `/curu-auth/...` namespace
  the existing login route already uses.
- `local-test-harness`'s Authelia (Lite bundle) service — added per
  ADR-002 — is the real identity provider this feature's live tests
  authenticate against; no mocked token responses.
