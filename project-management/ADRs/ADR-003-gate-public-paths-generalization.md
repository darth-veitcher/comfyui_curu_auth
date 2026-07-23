# ADR-003: Generalize `gate.py`'s single-path bypass into a "public paths" set

## Status

Accepted

_Date:_ 2026-07-23
_Deciders:_ James Veitch (with Claude Code)

---

## Context

`build_gate_middleware` has always let exactly one path (`LOGIN_PATH`)
through unauthenticated — a browser with no session yet has no other way
to reach the form that would let it get one. `oidc-auth`'s callback route
needs the identical treatment, for the identical reason: a browser
arriving at `/curu-auth/oidc/callback` has no session yet by definition.

This isn't a one-off: `passkey-auth` (still in Planning, depends on
`browser-e2e`) will need the same treatment for its own WebAuthn ceremony
routes (registration/assertion challenges) once it's specced. Deciding how
the *second* additive auth method plugs into this bypass, without
deciding anything about how a *third* one will, would leave that same
question re-litigated per spec — worth fixing the mechanism once.

## Decision

Generalize `LOGIN_PATH` (a single string `build_gate_middleware` compares
against) into a small, explicit set of unauthenticated-allowed paths —
`{LOGIN_PATH}` by default (byte-for-byte the same behavior as today when
no additive auth method is configured), extended with a login method's
own bootstrap routes only when that method is actually configured (e.g.
OIDC's start/callback pair, added only when `resolve_oidc_config()`
returns non-`None`).

## Consequences

**Easier**: Every future additive auth method (`passkey-auth` included)
has one, already-decided place to register its own unauthenticated
bootstrap routes, rather than re-deciding "how does a new pre-session
route get through the gate" per spec.

**Harder / constrained**: The set must stay explicit and narrow by
construction — anyone adding a new bypass path is making a conscious,
reviewable edit, not relying on a pattern-match rule that could silently
widen over time (see Alternative A).

**Debt**: None — this is a mechanism, not a feature; it does nothing on
its own until `oidc-auth` (and later `passkey-auth`) actually populate it.

## Considered Alternatives

### Alternative A: A prefix rule (e.g., anything under `/curu-auth/`) instead of an explicit set

**Why rejected:** Would exempt any *future* route added under that prefix
from Total Route Coverage (Constitution Principle II) without a
deliberate decision each time — quietly weakening the gate as a side
effect of unrelated future changes, rather than requiring a conscious
edit to widen it.

### Alternative B: Duplicate the single-path check per auth method (one `if` per method in the middleware)

**Why rejected:** Works today for two methods, but the branching grows
linearly with every additive auth method this project adds, spreading the
same concept across multiple near-identical checks instead of one shared
mechanism.

---

## Links

- Related epics: [oidc-auth](../Roadmap/epics/oidc-auth.md), [passkey-auth](../Roadmap/epics/passkey-auth.md)
- Related spec: `specs/002-oidc-login/`
- Related ADR: [ADR-002](ADR-002-oidc-session-sharing-and-test-idp.md) — the session mechanism this same gate serves
