<!--
Sync Impact Report
- Version change: (template) → 1.0.0
- Modified principles: n/a (initial ratification)
- Added sections: I. Minimal Attack Surface, II. Total Route Coverage,
  III. Zero-Config by Default, IV. Test-First for Security-Critical Logic,
  V. Simplicity (Function Before Class), Security Requirements,
  Development Workflow & Quality Gates, Governance
- Removed sections: none (first fill of the template)
- Templates requiring updates:
  ✅ .specify/templates/plan-template.md — Constitution Check section reads
     this file generically; no hardcoded principle names to sync
  ✅ .specify/templates/spec-template.md — no principle-specific references
  ✅ .specify/templates/tasks-template.md — no principle-specific references
  ✅ .specify/templates/commands/*.md — no agent-specific references found
- Follow-up TODOs: none
-->

# comfyui_curu_auth Constitution

## Core Principles

### I. Minimal Attack Surface (NON-NEGOTIABLE)
This project is a security boundary other software trusts — every dependency
and every network call is itself part of the attack surface it exists to
reduce. The default authentication path MUST require zero network egress to
issue or verify a credential, and MUST NOT depend on an external identity
provider. New runtime dependencies beyond `aiohttp` require explicit
justification in the PR description, not just a `pyproject.toml` diff.
Additive authentication methods (OIDC/OAuth, passkeys — see Roadmap vision)
are permitted only as opt-in extensions that do not weaken or bypass the
zero-dependency default.

**Rationale:** A gate that has been widened by its own dependency tree no
longer does the one job it was installed for.

### II. Total Route Coverage (NON-NEGOTIABLE)
The auth middleware MUST wrap every route ComfyUI's `aiohttp` app serves,
including the `/ws` websocket handshake. Any change to how the middleware is
attached, or any new route class ComfyUI introduces, MUST be verified as
covered — not assumed covered by inheritance from a prior version. A test
exercising an unauthenticated request against the route in question is the
only acceptable evidence of coverage.

**Rationale:** A login screen that misses one path is worse than no login
screen, because it creates false confidence in operators who never test the
gap themselves.

### III. Zero-Config by Default
Installing the node and restarting ComfyUI MUST be the entire setup for the
default credential flow: no config file, no account creation, no manual key
exchange. `COMFYUI_CURU_AUTH_TOKEN` MAY be set to pin a credential across
restarts, but its absence MUST NOT degrade the default experience. Any
feature that requires configuration before it does anything (e.g. OIDC
provider details) MUST fail safe to "gate stays on with the random
credential," never to "gate is open."

**Rationale:** The target operator is a solo/home GPU owner, not someone
standing up an identity stack — see `project-management/Background/00-problem-statement.md`.

### IV. Test-First for Security-Critical Logic (NON-NEGOTIABLE)
Credential comparison, rate-limiting/backoff, and route-coverage logic MUST
have a failing test written before the implementation that makes it pass.
`uv run pytest` MUST be green before a bullet is called done. Credential
comparison MUST use a constant-time comparison; token generation MUST use
`secrets`, never `random`.

**Rationale:** Security bugs in an auth gate are silent until exploited —
tests are the only feedback loop that exists before a real attacker provides
one.

### V. Simplicity — Function Before Class, Script Before Service
Prefer the plainest construct that solves the problem in front of you. Do
not introduce abstractions, plugin systems, or configuration layers for
authentication methods that don't exist yet. Three similar lines beat a
premature abstraction; a working middleware function beats a framework.

**Rationale:** Inherited from BEACON's pragmatic principles
(`.claude/CLAUDE.md`) — orthogonality and reversibility are cheaper to
preserve in simple code than to bolt onto complex code later.

## Security Requirements

- Credentials are generated with `secrets.token_urlsafe(32)` (256 bits of
  entropy) or read from `COMFYUI_CURU_AUTH_TOKEN`; never logged, never
  printed more than once per process start.
- Session cookies MUST be `HttpOnly`, `Secure`, and `SameSite=Strict`.
- Repeated failed credentials MUST trigger exponential backoff
  (capped at 5 minutes), applied uniformly across the login-form and
  Bearer-header paths, and MUST reset on a correct attempt.
- Every rejected request MUST emit one stable, greppable log line
  (source IP + path) so operators can wire fail2ban/crowdsec — see
  `contrib/README.md`. Log format changes are a breaking change to that
  integration and MUST be called out in the PR description.
- Never commit secrets or example tokens to the repo, including in tests or
  fixtures.

## Development Workflow & Quality Gates

Before any tracer bullet is considered done:

```bash
uv run ruff check --fix && uv run ruff format
uv run ty check
uv run pytest
beacon doctor --strict
```

This package is loaded directly by ComfyUI from `custom_nodes/` and is never
built or published as a wheel (`tool.uv.package = false` in
`pyproject.toml`) — do not add packaging/distribution steps that assume
otherwise. Then ask: *"Would I proudly sign my name to this?"* If not,
refactor before committing.

## Governance

This constitution supersedes ad-hoc practice for this project. Where an ADR
under `project-management/ADRs/` appears to conflict with a principle here,
the constitution wins unless the ADR explicitly amends it (and this file is
updated in the same change).

Amendments require: the change written into this file, a version bump per
semantic versioning (MAJOR: principle removed/redefined incompatibly; MINOR:
principle added or materially expanded; PATCH: wording/clarification only),
and the Sync Impact Report at the top of this file updated in the same
commit. `/speckit-plan`'s Constitution Check gate evaluates every plan
against the Core Principles above — a plan that violates a NON-NEGOTIABLE
principle must either change or document the violation in that plan's
Complexity Tracking section.

**Version**: 1.0.0 | **Ratified**: 2026-07-23 | **Last Amended**: 2026-07-23
