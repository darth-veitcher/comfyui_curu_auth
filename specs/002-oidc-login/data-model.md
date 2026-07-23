# Data Model: OIDC/OAuth Login Path

## OIDC Configuration

Resolved once at startup from environment variables (FR-001); either
fully present or treated as absent (FR-009 — no partial state).

- **issuer_url**: the identity provider's base URL (discovery document at
  `{issuer_url}/.well-known/openid-configuration`)
- **client_id** / **client_secret**: this node's registered credentials
  with the provider
- **redirect_uri**: the callback URL registered with the provider,
  matching the OIDC callback route this feature adds
- Resolved via a function analogous to `gate.py`'s `resolve_credential` —
  returns a populated config object or `None` (never a partially-filled
  one)

## In-Flight Auth Request

Transient, short-lived, in-memory only (FR-008) — correlates the request
that started an OIDC login with the callback that completes it.

- **state**: opaque, unguessable value (CSRF protection) — round-tripped
  through the provider and checked for an exact match on callback
- **nonce**: opaque, unguessable value bound into the authorization
  request and required to reappear in the returned ID token's `nonce`
  claim (replay protection)
- **pkce_verifier**: the PKCE code verifier generated at request start;
  its derived challenge is sent to the provider, and the verifier itself
  is presented at token exchange
- **created_at**: used to expire entries that are never completed
    (bounds memory growth from abandoned flows — not itself a security
    control, since `state`/`nonce` already prevent misuse of a stale
    entry)
- **Lifecycle**: created when the OIDC start route is hit; consumed
  (single use — deleted whether the callback succeeds or fails) when the
  callback route processes it — a second submission of the same
  state/code pair finds no matching entry and is rejected (FR-011,
  Edge Cases: verbatim replay), not merely re-validated and accepted
  again. Never durably stored; cleared entirely on restart, exactly like
  `SessionStore` and `RateLimiter` (FR-008).
- **Bounded creation** (FR-010, found during adversarial engineering
  review): the login-initiation route that creates these entries is
  reachable pre-session by definition (like the login form already is),
  so it MUST be subject to the *existing* shared `RateLimiter` — the same
  instance already backing the credential and login-form paths, not a
  new mechanism — and the store's total size MUST be capped (oldest
  entries evicted first) as a second, independent bound: rate-limiting
  slows a single client; the size cap bounds the worst case if many
  distinct client identities are used to spread the load.

## ID Token Claims (verified, not stored)

The claims `joserfc` yields after successfully verifying the identity
provider's signed ID token. Read once, at callback time, to decide whether
to mint a session — never persisted beyond that decision (FR-008).

- **iss**: MUST exactly match the configured `issuer_url`
- **aud**: MUST include the configured `client_id`
- **exp** / **iat**: MUST place the token within its valid time window
- **nonce**: MUST exactly match the In-Flight Auth Request's `nonce`
- **sub**: the provider's stable subject identifier — logged (as the
  client key an operator's fail2ban/crowdsec setup already keys on,
  alongside IP) but not stored, since this gate has no user-account
  concept of its own to attach it to (epic Non-Goals: not multi-tenant)

Both the discovery document and the provider's JWKS are fetched fresh on
every login attempt, not cached — see research.md's "No JWKS caching" and
"Discovery document fetched fresh" decisions. Login is infrequent enough
that the extra HTTP round-trip is negligible, and an unstated cache would
otherwise fail closed-but-silent after the provider rotates signing keys.

## Session (existing entity, reused — not redefined here)

On successful verification, an OIDC login mints a session by calling the
*existing* `SessionStore.issue()` and setting the *existing* `curu_auth`
cookie with the *existing* attributes — see ADR-002. This feature adds no
new session entity or cookie; it is a second issuer of the same one.
