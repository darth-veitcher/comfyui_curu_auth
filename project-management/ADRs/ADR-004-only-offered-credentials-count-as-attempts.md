# ADR-004: Only an *offered* credential counts as an authentication attempt

## Status

Accepted

_Date:_ 2026-09-04
_Deciders:_ James Veitch (with Claude Code)

Amends the two "corrections to curu's own pattern" recorded in
[ADR-001](ADR-001-docker-comfyui-test-harness.md) — see Links.

---

## Context

`gate.py`'s middleware read the `Authorization` header, compared it to the
expected `Bearer <credential>`, and on any mismatch called
`RateLimiter.record_failure`. A request with **no** header at all yields
`b""`, fails that comparison, and was therefore recorded as an
authentication *failure* — indistinguishable from a request supplying a
*wrong* credential. With the shipped backoff (`base_delay=1.0`,
`max_delay=300.0`, doubling per consecutive failure), a few dozen
credential-less requests put a client key into a five-minute block, and
the next request from that key — including a perfectly correct,
credentialled one — got `429`.

`build_login_routes` had the same shape: a POST whose `token` field was
blank or absent recorded a failure too.

This is not theoretical. It produced the same incident at least three
times, and was worked around twice rather than fixed:

1. `docker/comfyui/healthcheck.py` accepted `429` alongside `401` as
   proof-of-gate, because its own unauthenticated probe — repeated every
   `interval` — rate-limited itself.
2. `curu`'s system-test harness polled ComfyUI readiness unauthenticated.
   ~30 failed polls during a ~60s boot meant that session's first real
   `POST /prompt` returned `429`, surfacing as a bogus `FAILED` in tests
   asserting `RESUMABLE`. Fixed there by authenticating the poll.
3. Recorded against `darth-veitcher/curu#216` as a recurring,
   fast-escalating lockout.

It bites harder than the middleware alone suggests, because `__init__.py`
hands **one** `RateLimiter` instance to the gate middleware, the login
form, and the OIDC routes. A lockout accrued by anonymous probe traffic is
a lockout on the login form a human would use to recover.

## Decision

Record a failure only when a credential was actually **offered** and was
wrong. A request that offered nothing still gets its `401` — unchanged
body, unchanged `Accept: text/html` redirect to `LOGIN_PATH`, unchanged
fail2ban/crowdsec log line — it simply does not consume the backoff
budget.

"Offered" is defined as widely as possible short of that:

| Presented | Offered? | Why |
|---|---|---|
| No `Authorization` header, no `curu_auth` cookie | No | Nothing was tested. |
| `Authorization:` blank / whitespace only | No | Cannot ever equal `Bearer <credential>`; identical in effect to sending no header. |
| Any non-blank `Authorization` value | **Yes** | Including `Basic …`, a bare `Bearer`, or plain garbage. |
| Any non-blank `curu_auth` cookie, when `sessions` is enabled | **Yes** | A session token is the gate's *other* accepted credential; exempting it would hand an attacker unlimited free guesses at `SessionStore` tokens. |
| A `curu_auth` cookie when `sessions is None` | No | Cookie auth is disabled; the gate would not accept that cookie under any value, so presenting one tests nothing. |
| Login POST with blank/absent `token` | No | Nothing was tested. |
| Login POST with a non-blank `token` | **Yes** | Keyed on the *submitted* string, not on the `latin-1`-encoded bytes: `errors="ignore"` collapses an all-non-`latin-1` token to `b""`, which must stay an attempt rather than become a loophole. |

This does not weaken the control. A brute-forcer must *supply* a candidate
credential in order to test it, so counting only supplied-and-wrong
attempts still bounds exactly the attempts that could ever succeed.
Offering nothing tests nothing. Crucially, "offered" is not "well-formed":
if malformed values were exempt, a client could obtain unlimited free
attempts simply by malforming them, and the distinction would become the
bypass.

The OIDC **start** route (`oidc.py`) keeps charging a failure for *every*
hit and is deliberately excluded from this rule. It is different in kind:
public by necessity, with no credential to be wrong about, and each hit
makes this process perform an outbound discovery fetch against the
identity provider. What is throttled there is that fetch, not a guess —
and the matching relaxation already exists one step later, where a `state`
the callback recognises bypasses the check entirely, so a real login never
pays for it.

## Consequences

**Easier**: Health checks, readiness probes, and browser page-loads before
login stop poisoning the shared limiter. Test harnesses and tooling no
longer need to authenticate *in order to avoid a lockout* (authenticating
remains the right default for other reasons). `healthcheck.py` no longer
needs to accept `429`.

**Harder / accepted**: The limiter now bounds credential *guessing*, not
raw unauthenticated request volume. A scanner sending credential-less
requests is answered `401` indefinitely rather than being backed off after
a few. Three things make that acceptable:

- A backed-off client was never actually shed load — it still got a fully
  served `429` response, so the limiter was never a DoS defence in the
  first place. The real defence against a flood is the fail2ban/crowdsec
  integration keying off the log line, at the network level.
- Those requests still emit that log line, on *every* one. Under the old
  behaviour they went silent as soon as the client was blocked (the
  `429` branch returns before logging), so fail2ban actually saw *less*
  of a flood than it does now.
- Log volume from a sustained anonymous flood is therefore higher than
  before. That is the honest cost, and it is the visible-and-actionable
  direction to err in.

**Risk retained**: `client_key` is best-effort (`X-Forwarded-For` is
forgeable by anything that can reach the origin directly), and the OIDC
start route can still lock out a shared key on its own. Neither is changed
here.

## Considered Alternatives

### Alternative A: Key the exemption on the `Authorization` header alone

Simpler, and the obvious reading of the defect report. Rejected: a request
presenting a never-issued `curu_auth` cookie and no header *has* offered a
credential and been wrong. Exempting it would silently remove any bound on
guessing `SessionStore` tokens — a real weakening of the control,
introduced while claiming to fix a bug.

### Alternative B: Exempt malformed `Authorization` headers too

Attractive because a `Basic` header is obviously not a guess at this
gate's credential. Rejected: any parse-based exemption is something a
client can produce on demand, so it converts "unlimited free
non-attempts" into "unlimited free attempts that happen to look
malformed". Non-blank is the only line that cannot be gamed.

### Alternative C: Leave the gate alone; keep authenticating every probe

The status quo, twice over. Rejected: it puts the burden on every current
and future caller to know an undocumented rule, and it has already been
re-learned from scratch three times by three different pieces of tooling.
Once is bad luck; three times is a defect in the gate.

## Links

- Amends [ADR-001](ADR-001-docker-comfyui-test-harness.md): its
  "Unauthenticated polling self-rate-limits" correction no longer holds,
  and the `429`-alongside-`401` half of its healthcheck correction is
  withdrawn. Its core decision (require `401`, never tolerate `200`) is
  unaffected and now applies exactly.
- Followed by
  [ADR-005](ADR-005-expire-a-stale-session-cookie-rather-than-exempt-it.md),
  which addresses a fourth instance of this lockout class — a session
  cookie stranded by a restart — *without* changing this ADR's rule or its
  "offered" table. The row for a non-blank `curu_auth` cookie still holds
  exactly as written; that request is simply also told to stop sending it.
- `gate.py` — `build_gate_middleware`, `build_login_routes`,
  `RateLimiter`.
- `docker/comfyui/healthcheck.py`, `tests/system/conftest.py` — the two
  workarounds this retires.
- `darth-veitcher/curu#216`.
