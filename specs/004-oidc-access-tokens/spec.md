# Feature Specification: The Bearer path accepts OIDC access tokens

**Feature Branch**: `004-oidc-access-tokens`

**Created**: 2026-11-01

**Status**: Draft

**Input**: Issue #14, which is item 6 of issue #13 (OIDC access tokens for programs). It uses the issuer code and the key code of spec 003.

**Epic**: [oidc-auth](../../project-management/Roadmap/epics/oidc-auth.md)

## Context

comfy-mcp can get its own access token for each backend with the `client_credentials` grant. The gate accepts only its static credential on the Bearer path. So a comfy-mcp backend behind this gate must use a static credential that never expires.

An access token is a short-lived JWT that the identity provider gives to a program. A resource server is a service that checks such a token on each request.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A program calls ComfyUI with an access token (Priority: P1)

An operator sets the issuer and the audience. A program, for example comfy-mcp, sends an access token of that issuer and gets the normal answer of ComfyUI.

**Why this priority**: This is the value of the feature: a credential that expires, in place of one that never expires.

**Independent Test**: Start rauthy 0.37.2, get a `client_credentials` token for the audience, and send it to `GET /queue`.

**Acceptance Scenarios**:

1. **Given** the mode is on, **When** a program sends a valid access token, **Then** the gate gives the answer of ComfyUI.
2. **Given** a real rauthy, **When** a program sends a `client_credentials` token for the audience, **Then** `GET /queue` gives HTTP 200.
3. **Given** a real rauthy, **When** a program sends a token for another resource, **Then** `GET /queue` gives HTTP 401.
4. **Given** the mode is on, **When** a program opens `/ws` with a valid access token, **Then** the gate lets the handshake through.
5. **Given** the mode is on, **When** a program opens `/ws` with a refused token, **Then** the gate gives HTTP 401 before the upgrade.

---

### User Story 2 - The static credential does not change (Priority: P1)

An operator who does not set the audience sees no change. An operator who sets it can still use the static credential.

**Why this priority**: The constitution forbids a change that weakens the default path.

**Independent Test**: Run the tests of `tests/test_gate.py` with no change, with the mode off and with the mode on.

**Acceptance Scenarios**:

1. **Given** no audience, **When** ComfyUI starts, **Then** the mode is off.
2. **Given** the mode is on, **When** a program sends the static credential, **Then** the gate gives the answer of ComfyUI.
3. **Given** an audience with no issuer, **When** ComfyUI starts, **Then** the gate writes a start error.
4. **Given** an audience with no issuer, **When** ComfyUI starts, **Then** the credential gate stays on.

---

### User Story 3 - The gate refuses a bad token (Priority: P1)

The gate refuses each token that it cannot trust. The refusal counts in the rate limit and writes a log line.

**Why this priority**: A token check that a forged token can pass is worse than no check.

**Independent Test**: Send each bad token from a fake issuer, and check HTTP 401, the log line and the wait.

**Acceptance Scenarios**:

1. **Given** an HS256 token signed with the public key, **When** the gate checks it, **Then** the gate gives HTTP 401.
2. **Given** a token with `alg` `none`, **When** the gate checks it, **Then** the gate gives HTTP 401.
3. **Given** an ID token with `typ` `JWT` and no scope, **When** the gate checks it, **Then** the gate gives HTTP 401.
4. **Given** a token that lives 2 hours, **When** the gate checks it, **Then** the gate gives HTTP 401.
5. **Given** a token that expired 1 second ago, **When** the gate checks it, **Then** the gate gives HTTP 401.
6. **Given** a token for another audience, **When** the gate checks it, **Then** the gate gives HTTP 401.
7. **Given** a token with no required scope, **When** the gate checks it, **Then** the gate gives HTTP 401.
8. **Given** a refused token, **When** the gate refuses it, **Then** the log line names the reason and holds no part of the token.
9. **Given** a refused token, **When** the gate refuses it, **Then** the address gets one failure in the rate limit.

---

### User Story 4 - The gate reads the keys rarely (Priority: P2)

The gate keeps the keys in memory, and reads them again only for a new key.

**Why this priority**: A read for each request would make the identity provider a point of failure, and an attacker could cause many reads.

**Independent Test**: Count the reads of the JWKS of a fake issuer across many requests and a key rotation.

**Acceptance Scenarios**:

1. **Given** ten valid tokens, **When** the gate checks them, **Then** the gate reads the JWKS one time.
2. **Given** a new key at the issuer, **When** a token with its `kid` comes, **Then** the gate reads the JWKS again and accepts the token.
3. **Given** a read less than 60 seconds ago, **When** a token with an unknown `kid` comes, **Then** the gate does not read the JWKS.
4. **Given** a bad shape, another issuer or a refused `alg`, **When** the gate checks the token, **Then** the gate does not read the JWKS.

---

### User Story 5 - comfy-mcp recovers after a 401 (Priority: P2)

comfy-mcp gets a new token after a 401 and tries again at once. That second attempt must pass when its token is valid.

**Why this priority**: Without it, one expired token makes a failed tool call.

**Independent Test**: Send an expired token, then a valid token from the same address within one second.

**Acceptance Scenarios**:

1. **Given** a refused token, **When** a valid token comes from the same address within one second, **Then** the gate gives the answer of ComfyUI.
2. **Given** a refused token, **When** a second refused token comes within one second, **Then** the gate gives HTTP 429.

---

### Edge Cases

- The static credential contains two dots. The gate compares it first, so it never goes to the token checks.
- The identity provider is down at the first token. The gate refuses the token, and reads again after 60 seconds at the earliest.
- A token has no `kid`, and the JWKS has one key. The gate uses that key.
- `scp` is a list (Okta), or a string with spaces.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The mode MUST be on only when the issuer and the audience are both set.
- **FR-002**: An audience with no issuer MUST be a start error.
- **FR-003**: Required scopes with no audience MUST be a start error.
- **FR-004**: A start error MUST keep the credential gate on.
- **FR-005**: The gate MUST compare the static credential first, with no change to its behaviour.
- **FR-006**: The gate MUST use the issuer code and the key code of spec 003.
- **FR-007**: The gate MUST keep the discovery document and the JWKS in memory.
- **FR-008**: The gate MUST read the JWKS again for an unknown `kid` at most one time in 60 seconds.
- **FR-009**: The gate MUST NOT read the JWKS for a token with a bad shape, another issuer or a refused `alg`.
- **FR-010**: The gate MUST accept the `typ` values `at+jwt` and `application/at+jwt`.
- **FR-011**: A token of the type `JWT`, or with no `typ`, MUST have a client id and a scope.
- **FR-012**: The gate MUST refuse a token whose `exp` is more than 3600 seconds after its `iat`.
- **FR-013**: The gate MUST give `exp` no leeway.
- **FR-014**: `aud` MUST hold the configured audience.
- **FR-015**: The token MUST hold each required scope.
- **FR-016**: The gate MUST check the `/ws` handshake with the same code.
- **FR-017**: Each refused token MUST count as one failed Bearer attempt in the shared `RateLimiter`.
- **FR-018**: A valid token MUST pass before the gate checks the wait.
- **FR-019**: Each refused token MUST write the failure log line with its reason.
- **FR-020**: No log line MUST hold a token or a part of a token.

### Key Entities

- **Issuer keys**: the discovery document and the JWKS of the issuer in memory, with the time of the last read.
- **Access token**: a JWT that the identity provider gives to a program for the audience of this gate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A live test gets HTTP 200 on `GET /queue` with a rauthy 0.37.2 `client_credentials` token.
- **SC-002**: A live test gets HTTP 401 on `GET /queue` with a rauthy token for another resource.
- **SC-003**: The hermetic tests refuse 100% of 9 bad tokens, with key confusion, `none`, an ID token and a token of 2 hours among them.
- **SC-004**: Ten requests with valid tokens cause 1 read of the JWKS.
- **SC-005**: Each test of `tests/test_gate.py` passes with no change.
- **SC-006**: The full test suite passes 3 times in a row.

## Non-Goals

*(The first three come from the parent epic.)*

- This spec does not replace the static credential. It is additive only.
- This spec gives no roles. A valid token opens the whole backend.
- This spec does not build an identity provider.
- This spec does not exchange an app password in a Basic header for a token, as curu-memory does.
- This spec does not support token introspection or opaque tokens.
- This spec does not change comfy-mcp or ansible-ubuntu-server.

## Assumptions

- The identity provider of the program is the identity provider of the login, when both are on.
- comfy-mcp gets a new token 60 seconds before `exp`, so an expired token is rare.
- rauthy 0.37.2 puts the `resource` of the request in `aud` when the `allowed_resources` of the client holds it.
