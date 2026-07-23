# Data Model: Docker ComfyUI Integration Harness

This feature has no persistent storage and no domain entities in the usual
sense — it is dev/test infrastructure around an existing node. The
"entities" below are runtime/process concepts the tests and harness
configuration reason about, documented here because `plan.md` references
this file, not because they warrant a schema.

## Harness Instance

Represents one running (or torn-down) instance of the docker-compose
service defined for this feature.

- **State**: `stopped` | `starting` | `healthy` | `unhealthy`
- Transitions: `stopped → starting` (on `docker compose up -d`),
  `starting → healthy` (once the healthcheck first passes),
  `starting/healthy → stopped` (on `docker compose down`)
- Invariant (spec FR-007 / SC-004): re-entering `starting → healthy` after
  a `stopped` state MUST NOT be observably different from a first-ever run
  — no field on this entity persists across that transition.

## Test Credential

The fixed, known bearer credential the harness configures via
`COMFYUI_CURU_AUTH_TOKEN` (spec FR-003), as opposed to comfyui_curu_auth's
own default of a fresh random credential per restart.

- **Value**: a constant string, scoped to this harness only
- **Scope**: valid only for the lifetime of a given Harness Instance's
  container process — never meaningful outside this local, disposable
  context (spec Assumptions)

## Rate-Limit Counter (observed, not owned)

The per-client backoff state comfyui_curu_auth's own gate already
maintains internally (existing behavior, not introduced by this feature).
This feature only *observes* it from the outside, via HTTP response codes
and `Retry-After` headers, to verify FR-005's rate-limit acceptance
scenario — it does not read or manipulate the gate's internal state
directly.

- **Observed via**: HTTP status (`429` after repeated failures) and the
  `Retry-After` header's value
- Invariant under test (spec FR-007): this counter MUST NOT survive a
  Harness Instance's `stopped → starting` transition.
