# ADR-005: Expire a stale session cookie, rather than exempt it from the limiter

## Status

Accepted

_Date:_ 2026-09-04
_Deciders:_ James Veitch (with Claude Code)

Follows [ADR-004](ADR-004-only-offered-credentials-count-as-attempts.md),
and deliberately leaves its rule unchanged — see Considered Alternatives.

---

## Context

`SessionStore` is in-memory. It starts empty on every ComfyUI restart, and
curu restarts ComfyUI routinely (`comfy-restarting` is a normal cold-start
phase; the upgrade path restarts too). The browser's `curu_auth` cookie
does *not* start empty: it was issued with a 30-day `max_age`
(`COOKIE_MAX_AGE_SECONDS`) and nothing has told the browser otherwise. So
after a restart, an already-open ComfyUI tab holds a cookie that can never
validate again, and replays it on every request it makes.

Under [ADR-004](ADR-004-only-offered-credentials-count-as-attempts.md)
each of those replays is an **offered** credential, and rightly so: a
cookie value the store does not hold is a *wrong* credential, and
exempting it wholesale would remove any bound on guessing `SessionStore`
tokens. So each replay that lands after the previous block lapses records
another failure and doubles the backoff.

PR #9's own author flagged this as a plausible fourth instance of the
lockout class ADR-004 addressed, on a path that PR did not change, and
deliberately did not fix it. It is genuinely reachable. Measured live
against this repo's own docker harness (real ComfyUI v0.27.0, real
Chromium):

- A logged-in ComfyUI page load fires **253 HTTP requests in 3.5 s**.
- The shipped frontend bundle re-opens `/ws` every **300 ms**
  indefinitely once the socket drops
  (`setTimeout(() => createSocket(true), 300)`), each handshake carrying
  the cookie.
- An untouched post-restart tab made an unauthenticated readiness poll
  from the same host answer `429`.

The escalation is driven by *elapsed time*, not request count, because the
block gates its own accounting: a burst of N simultaneous requests records
exactly **one** failure (verified for N = 10, 30, 60, 120, 253) — the rest
return `429` ahead of the credential check. Replayed at the frontend's own
300 ms cadence, the backoff reaches the 300 s cap after ~8.5 minutes
(failure #10, t ≈ 512 s) and is then **renewed indefinitely**, one failure
per 300 s window, by a tab nobody realises is doing it.

That client key is then locked out of everything: `__init__.py` hands one
`RateLimiter` to the gate middleware, the login form and the OIDC routes
alike, so the human is locked out of the very form they would use to
recover, and a correctly-credentialled API client on that key gets `429`
too. Only an already-*valid* cookie escapes (it returns before the limiter
is consulted).

## Decision

Expire the cookie instead of exempting it. A rejected request that
presented a `curu_auth` value the store does not recognise gets that
cookie set to `""` with `max_age=0` on the rejecting response, carrying
the same `HttpOnly` / `Secure` / `SameSite=Strict` / `Path=/` attributes it
was issued with.

Applied on **all four** branches such a request can leave by — the `401`,
the already-blocked `429`, and each one's `Accept: text/html` redirect to
`LOGIN_PATH`. The `429` branch is the one that actually stops the storm:
after the first rejection starts a block, every later request returns
there ahead of the credential check, so expiring only on the `401` would
leave the client replaying for the whole block and re-arming the backoff
the instant it lapsed.

Deliberately narrow:

| Presented | Expired? | Why |
|---|---|---|
| A `curu_auth` value the store does not recognise | **Yes** | It can never validate; the client should stop sending it. |
| A `curu_auth` value the store *does* recognise | No | Returns before every rejection branch; a live session is never touched. |
| No cookie at all | No | Nothing to expire. A `Set-Cookie` on every anonymous `401` would be noise on the most common rejected request there is. |
| Any cookie, with `sessions=None` | No | Cookie auth is disabled; the gate neither reads nor owns a cookie of that name. |

**ADR-004's rule is untouched.** The first request bearing an unrecognised
cookie is still an offered-and-wrong credential and still consumes the
backoff budget. What changes is only that a client which honours the
expiry has no *second* request to charge — the storm ends at its source
rather than being exempted from counting. Net effect on the measured
incident: an indefinitely-renewed 300 s lockout becomes a single
`base_delay` (1 s) backoff, self-healing.

Verified that this actually works on the path the storm lives on: a real
Chromium honours a `Set-Cookie` expiry carrying exactly these attributes
even on the `401` that rejects a **WebSocket handshake** (checked directly,
because if it did not, expiring the cookie could not stop a `/ws`
reconnect loop and this decision would be worthless).

## Consequences

**Easier**: A ComfyUI restart no longer strands an open tab in a
self-renewing lockout. The human's next navigation lands on the login form
with the dead cookie already gone, rather than holding one that keeps
charging failures against the shared limiter they are about to POST to.
Nothing about the limiter's semantics has to be reasoned about differently.

**Harder / accepted**: One stale-cookie request still costs its client key
one `base_delay` (1 s) of backoff, during which a correct credential from
that key gets `429`. That is the limiter doing exactly its job — a cookie
the store does not hold *is* a wrong credential — and it is bounded, self-
healing, and identical to what a single wrong Bearer token has always
cost. Removing even that would require narrowing what counts as an
attempt; see Alternative A.

**Risk retained**: A client that ignores `Set-Cookie` (a script with a
hard-coded cookie value, say) keeps replaying and keeps being charged.
That is correct — such a client is indistinguishable from, and behaves
exactly like, a session-token guesser.

## Considered Alternatives

### Alternative A: Exempt a cookie from counting while `SessionStore` is empty

The remedy the defect report proposed. The security reasoning checks out,
and was verified rather than assumed: `SessionStore.is_valid` is
`any(...)` over the issued set, so with an empty store **no** cookie value
can validate, and a request presenting one has tested nothing and cannot
be a successful guess — the same argument ADR-004 accepted for a missing
`Authorization` header. "Empty" is also the right boundary, not a wider
one: a store holding one live session and a request bearing a *different*
value is a real guess and must stay counted.

An attacker cannot manufacture the empty state to farm free attempts.
Emptying the store requires restarting the ComfyUI process, and every
restart path (ComfyUI Manager's reboot endpoint included) is itself behind
this gate. They can *wait* for a restart, and can detect the state by
observing that they are never blocked — a minor information leak ("nobody
is logged in right now") — but the free guesses are worthless while it
lasts, and counting resumes the instant a session exists, with no
accumulated advantage. It does not interact with the OIDC start route
(which charges per hit regardless, ADR-004) or with the login form (which
keys on the submitted token, not on cookies).

Rejected anyway, because it is not needed. It buys ~1 second of recovery
latency over this ADR's decision, and pays for it with a state-dependent
security rule — "does this count? depends whether anyone is logged in" —
plus a new `SessionStore` API to expose that state. Expiring the cookie
solves the reachable problem without touching a security control's
semantics at all, which makes it strictly the better trade. If a future
change makes the residual 1 s matter, this alternative is still available
and its reasoning still holds.

### Alternative B: Shorten the cookie's `max_age`

Does not help. The cookie's lifetime is irrelevant — the store empties on
a restart that has nothing to do with the cookie's own expiry, and any
`max_age` short enough to bound the problem would log real users out
constantly.

### Alternative C: Persist `SessionStore` across restarts

Would make the cookie keep working, removing the storm entirely. Rejected
as a much larger change with its own security surface (durable session
tokens on disk), against a gate whose whole design is deliberately
in-memory and stateless — `RateLimiter` and, until recently, the
credential itself all reset on restart by design.

### Alternative D: Do nothing

The status quo PR #9 left deliberately. Rejected: the same defect class has
now been hit four times, and the standing instruction is that a recurring
edge case is fixed properly and durably rather than re-learned.

## Links

- Follows [ADR-004](ADR-004-only-offered-credentials-count-as-attempts.md).
  Its rule and its "offered" table are unchanged by this ADR.
- `gate.py` — `_expire_session_cookie`, `build_gate_middleware`.
- `darth-veitcher/curu#216`.
