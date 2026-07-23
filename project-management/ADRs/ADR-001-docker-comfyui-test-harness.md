# ADR-001: Docker-based local ComfyUI test harness, adapted from curu's own

## Status

Accepted

_Date:_ 2026-07-23
_Deciders:_ James Veitch (with Claude Code)

---

## Context

`__init__.py` (this node's real ComfyUI-side wiring — reaching into
`server.PromptServer.instance.app` at import time) had no automated test:
the existing hermetic suite (`tests/test_gate.py`) deliberately only
imports `gate.py` against a mocked `aiohttp` app, never a real ComfyUI
process, so `__init__.py` itself was verified by installing the node for
real and checking by hand.

A sibling repo, `~/repos/JAMESVEITCH/curu` (same author), already runs an
almost-identical CPU-only Docker ComfyUI harness for its own purposes
(proving its capability-discovery code against a real backend) —
`docker-compose.yml` + `docker/comfyui/{Dockerfile,healthcheck.py}` +
`tests/system/`. The question was whether to adapt that pattern here or
design a fresh one, and — since two other planned epics (`oidc-auth`'s
Authelia extension, `browser-e2e`'s Playwright layer) already intend to
build directly on top of whatever harness this epic produces — whether
that choice deserves recording as more than a single spec's internal
implementation detail.

## Decision

Adapt curu's Dockerfile/compose/healthcheck pattern directly (CPU-only,
pinned ComfyUI tag `v0.27.0`, no model checkpoint or workflow execution),
with the one difference the two repos' purposes actually require: this
harness bind-mounts the repo's own working tree read-only into
`custom_nodes/comfyui_curu_auth` (curu instead `git clone`s a published
release), so in-progress, uncommitted changes to the gate are what get
exercised — the entire reason this harness exists.

Two corrections to curu's own pattern, found running the harness live
(not assumed by analogy) — recorded here because both future epics
extending this harness need to know them, not just this spec:

- **Healthcheck must require 401 (or 429), not tolerate 200.** curu's own
  healthcheck treats 200 and 401 as equally healthy, which is safe there
  (its node is baked into the image, always present) but wrong here: an
  unmounted/broken bind mount leaves ComfyUI ungated, answering 200 — and
  curu's version would report that as "healthy." 429 was added alongside
  401 after discovering that the healthcheck's own repeated unauthenticated
  probing eventually rate-limits itself too.
- **Unauthenticated polling self-rate-limits.** `gate.py`'s `RateLimiter`
  counts *any* unauthenticated request as a failure, including routine
  health/reachability polling — not just deliberate test failures. Any
  future test or tooling that probes this harness unauthenticated in a
  loop will eventually block itself; authenticate polling traffic instead
  (see `specs/001-docker-comfyui-harness/research.md`).

Full design detail and the decisions specific to spec 001 alone (no `just`
task runner, `system` pytest marker convention, no `contracts/` directory)
live in `specs/001-docker-comfyui-harness/research.md` — this ADR exists
for the parts that outlive that one spec.

## Consequences

**Easier**: Any future change to the gate can be verified against a real
ComfyUI process with `uv run pytest -m system`, not just by hand. `oidc-auth`
can extend this same `docker-compose.yml` with an Authelia container for
OIDC-flow testing without redesigning the harness. `browser-e2e` inherits
a known-working CPU-only ComfyUI target to add browser automation against.

**Harder / constrained**: This harness cannot verify anything requiring a
real browser (WebAuthn ceremonies) — `browser-e2e` exists as a separate
epic specifically because of this constraint, not as an oversight.
First-time image builds cost several minutes (ComfyUI clone + CPU torch
install); iterating on the Dockerfile itself is slower than iterating on
Python code.

**Debt**: None identified yet. The healthcheck/rate-limiter interaction
above is now documented, not deferred.

## Considered Alternatives

### Alternative A: From-scratch minimal `aiohttp` stand-in instead of real ComfyUI

**Why rejected:** Would just be a bigger version of the existing hermetic
`tests/test_gate.py` suite — doesn't touch the real
`server.PromptServer.instance` wiring that's actually untested today.

### Alternative B: `COPY . custom_nodes/comfyui_curu_auth` at build time (curu's approach, adapted naively)

**Why rejected:** Forces a full image rebuild (multi-minute) on every
code change under test — directly works against the fast dev-loop this
harness exists to enable. A bind mount lets a plain restart pick up edits.

### Alternative C: Track ComfyUI `master` instead of a pinned tag

**Why rejected:** Trades reproducibility for currency this harness
doesn't need; a pinned tag matching curu's own removes a variable rather
than introducing a second "which ComfyUI version" axis between the two
repos' harnesses.

---

## Links

- Related spec: `specs/001-docker-comfyui-harness/`
- Related epics: [local-test-harness](../Roadmap/epics/local-test-harness.md),
  [oidc-auth](../Roadmap/epics/oidc-auth.md),
  [browser-e2e](../Roadmap/epics/browser-e2e.md)
- External reference: `~/repos/JAMESVEITCH/curu`'s
  `docker-compose.yml` / `docker/comfyui/` (sibling repo, same author)
