# Feature Specification: The OIDC login works with rauthy, Authentik and other providers

**Feature Branch**: `003-oidc-provider-fixes`

**Created**: 2026-11-01

**Status**: Draft

**Input**: Issue #13, items 1 to 5 and item 7. Item 6 is spec 004 (issue #14).

**Epic**: [oidc-auth](../../project-management/Roadmap/epics/oidc-auth.md)

## Context

Spec 002 built the OIDC login, and its tests used Authelia only. The issuer of Authelia has no `/` at the end. On 2026-11-01, the login failed against rauthy 0.37.2 for two reasons:

- The issuer of rauthy ends in `/`. The gate added a second `/` to the discovery URL and got HTTP 404.
- The gate accepted only RS256 ID tokens. rauthy can sign with EdDSA.

The issuer of Authentik also ends in `/`. The review of issue #13 also found four security gaps:

- Each account at the provider got a session.
- The gate trusted the discovery document with no checks.
- An ID token with no `exp` could pass.
- The gate did not check `azp`.

An OIDC provider is the identity provider (IdP) that logs the person in. The issuer is the URL that names the provider in its tokens.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Log in through rauthy or Authentik (Priority: P1)

An operator sets the issuer exactly as the discovery document of the provider gives it, with or without a `/` at the end. The login then works.

**Why this priority**: Without this story, the login fails against rauthy and Authentik. The other stories have no value until the login works.

**Independent Test**: Start rauthy 0.37.2 in Docker with an EdDSA client, log in through the gate in a browser, and look for the `curu_auth` cookie.

**Acceptance Scenarios**:

1. **Given** an issuer that ends in `/`, **When** the gate reads the discovery document, **Then** the discovery URL has no `//`.
2. **Given** a document that names the configured issuer, **When** a person logs in, **Then** the gate accepts an `iss` of that issuer.
3. **Given** a discovery document that names another issuer, **When** a person starts a login, **Then** the gate refuses the login.
4. **Given** an ID token signed with EdDSA, **When** the gate checks it, **Then** the gate accepts the token.
5. **Given** a real rauthy with an EdDSA client, **When** a person logs in through a browser, **Then** the browser gets the `curu_auth` cookie.

---

### User Story 2 - Only the allowed people get a session (Priority: P1)

An operator lists the people who can log in. A person who is not on the list gets no session, also after a correct login at the provider.

**Why this priority**: With Google as the provider, each Google account in the world could otherwise log in.

**Independent Test**: Set an allowlist of one subject, and log in with a different subject through a fake issuer. The callback gives HTTP 401.

**Acceptance Scenarios**:

1. **Given** an allowlist of subjects, **When** a person with a listed `sub` logs in, **Then** the gate gives a session.
2. **Given** an allowlist of subjects, **When** a person with another `sub` logs in, **Then** the gate gives HTTP 401 and writes the failure log line.
3. **Given** an allowlist of emails, **When** the ID token has a listed email but `email_verified` is not true, **Then** the gate refuses the login.
4. **Given** an allowed domain, **When** the `hd` claim of the ID token is that domain, **Then** the gate gives a session.
5. **Given** a full OIDC setup with no allowlist, **When** ComfyUI starts, **Then** no OIDC route exists and the credential gate stays on.
6. **Given** `ALLOW_ANY_USER=true`, **When** any person logs in at the provider, **Then** the gate gives a session.

---

### User Story 3 - The gate refuses an unsafe provider or token (Priority: P2)

The gate refuses a token that it cannot check safely. It also refuses a provider that sends a person or a key over plain HTTP to another computer.

**Why this priority**: These gaps let an attacker forge a token or change a key. The login works without these checks, so this story comes after stories 1 and 2.

**Independent Test**: Give the callback each bad token or bad discovery document from a fake issuer. Each one gives HTTP 401 or HTTP 503, and no session.

**Acceptance Scenarios**:

1. **Given** an ID token with `alg` `none`, **When** the gate checks it, **Then** the gate refuses the token.
2. **Given** an HS256 ID token signed with the public key as the HMAC secret, **When** the gate checks it, **Then** the gate refuses the token.
3. **Given** an HS256 ID token, **When** the gate refuses it, **Then** the reason says that the Authentik provider has no signing key.
4. **Given** an `http` endpoint on a host that is not loopback, **When** a person starts a login, **Then** the gate refuses the login.
5. **Given** an ID token with no `exp` or no `iat`, **When** the gate checks it, **Then** the gate refuses the token.
6. **Given** two audiences and an `azp` that is not the client id, **When** the gate checks the ID token, **Then** the gate refuses it.
7. **Given** an ID token that expired 30 seconds ago, **When** the gate checks it, **Then** the gate accepts the token because of the clock leeway.

---

### User Story 4 - Set the scopes of the login (Priority: P3)

An operator sets the scopes that the gate asks for. Some providers refuse a scope that the client does not have.

**Why this priority**: The default scopes work with most providers, so few operators need this setting.

**Independent Test**: Set the scopes to `profile`, and read the `scope` of the authorization URL.

**Acceptance Scenarios**:

1. **Given** no scopes setting, **When** the gate builds the authorization URL, **Then** the scope is `openid profile email`.
2. **Given** the scopes setting `profile`, **When** the gate builds the authorization URL, **Then** the scope is `openid profile`.

---

### Edge Cases

- The provider does not give `alg` in a JWK. The gate then takes the algorithm from the key type: RS256 for RSA, ES256 for P-256 and EdDSA for Ed25519.
- The `kid` of the token is not in the JWKS. The gate refuses the token.
- The `alg` of the token header is not the algorithm of the key. The gate refuses the token.
- The provider is Google, and an ID token has `iss` `accounts.google.com` with no scheme. The gate refuses the token, because `iss` must equal the issuer exactly.
- The allowlist of emails has capital letters. The gate compares emails with no difference between capital and small letters.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The gate MUST remove each `/` at the end of the issuer before it adds `/.well-known/openid-configuration`.
- **FR-002**: The gate MUST keep the configured issuer exactly as the operator writes it.
- **FR-003**: The gate MUST refuse a discovery document whose `issuer` is not exactly the configured issuer.
- **FR-004**: The gate MUST refuse an ID token whose `iss` is not exactly the configured issuer.
- **FR-005**: The gate MUST accept only RS256, RS384, RS512, PS256, ES256 and EdDSA, and MUST take the algorithm from the matching JWK.
- **FR-006**: The gate MUST refuse `none` and each HMAC algorithm before it reads the JWKS.
- **FR-007**: The reason for an HS256 refusal MUST say that the Authentik provider has no signing key.
- **FR-008**: The gate MUST refuse a discovery document whose `authorization_endpoint`, `token_endpoint` or `jwks_uri` uses `http` on a host that is not loopback.
- **FR-009**: The gate MUST refuse an ID token with no `exp` or no `iat`.
- **FR-010**: When `aud` has more than one value, the gate MUST refuse an ID token whose `azp` is not the client id.
- **FR-011**: The gate MUST allow 60 seconds of clock leeway for `exp`, `iat` and `nbf` of an ID token.
- **FR-012**: The gate MUST give a session only to a person that an allowlist names, or to each person when `ALLOW_ANY_USER` is true.
- **FR-013**: An email in the allowlist MUST match only when the ID token has `email_verified` true.
- **FR-014**: The OIDC login MUST stay off, with an error at start, when no allowlist is set and `ALLOW_ANY_USER` is not true.
- **FR-015**: A refused person MUST get the same failure log line and the same rate limit as each other failed login.
- **FR-016**: The gate MUST ask for the configured scopes, and MUST always include `openid`.
- **FR-017**: The changes MUST NOT change the static credential path.

### Key Entities

- **Allowlist**: the subjects, the emails and the domain that can log in, or the decision to let the provider decide.
- **Discovery document**: the JSON document at `<issuer>/.well-known/openid-configuration` that names the endpoints of the provider.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A live test logs in through rauthy 0.37.2 with an EdDSA ID token, and the browser gets the `curu_auth` cookie.
- **SC-002**: The hermetic tests refuse 100% of 7 bad cases. These are `alg` `none`, key confusion, another issuer, an `http` endpoint, no `exp`, no `iat` and a wrong `azp`.
- **SC-003**: With a full OIDC setup and no allowlist, 0 OIDC routes exist after start.
- **SC-004**: Each test of `tests/test_gate.py` passes with no change.
- **SC-005**: The full test suite passes 3 times in a row.

## Non-Goals

*(The first three come from the parent epic.)*

- This spec does not replace the default shared credential. It is additive only.
- This spec gives no roles. The backend stays one boundary.
- This spec does not build an identity provider.
- This spec does not accept access tokens on the Bearer path. Spec 004 does that.
- This spec does not test Authentik live. The guide uses the Authentik documentation.
- This spec does not fix the install of `joserfc` (issue #3).

## Assumptions

- rauthy 0.37.2 in Docker is the live provider of the tests. It gives an issuer with a `/` at the end, and it signs ID tokens with EdDSA.
- The Authelia system test of spec 002 stays. It sets `ALLOW_ANY_USER=true`, because its provider has one test user.
- The operator copies the issuer from the discovery document of the provider.
