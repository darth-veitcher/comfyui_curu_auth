# Research: Docker ComfyUI Integration Harness

No `[NEEDS CLARIFICATION]` markers were left in the spec, so this phase
consolidates decisions rather than resolving open questions — largely by
adapting the proven, already-running equivalent in the sibling repo
`~/repos/JAMESVEITCH/curu` (same author, same node, different purpose:
curu consumes comfyui_curu_auth as a dependency of its own live-ComfyUI
integration; this spec tests comfyui_curu_auth itself).

## Decision: Base the harness directly on curu's Dockerfile/compose pattern

**Rationale**: curu already runs a CPU-only ComfyUI container
(`docker/comfyui/Dockerfile`) at a pinned tag with CPU-only torch wheels,
comfyui_curu_auth installed as a custom node, and a healthcheck that treats
`401` as "alive and correctly gated" rather than a failure. It's a proven,
working pattern for exactly the kind of instance this spec needs — no
reason to design a different one from scratch.

**Alternatives considered**: A from-scratch minimal aiohttp stand-in
instead of real ComfyUI — rejected because it would just be a bigger
version of the existing hermetic `tests/test_gate.py` suite, not the
"real `server.PromptServer.instance`" wiring the README already flags as
untested.

## Decision: Install this node via bind mount, not `git clone` / `COPY`

**Rationale**: curu's Dockerfile does `git clone .../comfyui_curu_auth.git
custom_nodes/comfyui_curu_auth` because curu is consuming a released
version of someone else's node. This spec is the opposite case — testing
comfyui_curu_auth's own in-progress working tree (FR-002). A `COPY` at
build time would require a full image rebuild (ComfyUI re-clone + torch
reinstall, multi-minute) on every code change; a read-only bind mount of
the repo root to the **absolute** in-container path
`/app/ComfyUI/custom_nodes/comfyui_curu_auth` (where the Dockerfile clones
ComfyUI — a relative path here would silently mount nowhere ComfyUI's
loader looks) lets a plain container restart pick up local edits, which is
what SC-001's repeat-boot budget actually depends on.

**Alternatives considered**: `COPY . custom_nodes/comfyui_curu_auth` at
build time — rejected: forces a full rebuild per code change, directly
works against SC-001 and the fast dev-loop this harness exists to enable.

## Decision: Pin the same ComfyUI tag curu already validated (v0.27.0)

**Rationale**: curu's Dockerfile already proved this tag works with this
exact node installed as a custom node. Reusing it removes a variable;
diverging versions between the two repos' harnesses would be a needless
source of "works in one, not the other" confusion later.

**Alternatives considered**: Track ComfyUI `master` — rejected, trades
reproducibility for currency the harness doesn't need (Assumptions:
"pinned version acceptable, updated manually over time").

## Decision: Adapt curu's healthcheck reasoning, but tighten it — 401 required, not merely tolerated

**Rationale**: curu's `docker/comfyui/healthcheck.py` treats **both** `200`
and `401` as healthy (a `200` falls through its `try` with no exception
raised). That's safe for curu, where the node is baked into the image at
build time and is always present. It is **wrong here**: this harness's
entire premise is a bind-mounted working tree that can fail to mount or
fail to import, in which case ComfyUI comes up ungated and answers `200` —
copied verbatim, curu's healthcheck would report that as *healthy*,
directly violating FR-004 ("distinguishes 'the gate is actively enforcing'
from … 'gate isn't wired up'"). Caught by adversarial engineering review
(`/beacon.engineering`, 2026-07-23) before any code was written.

This harness's `healthcheck.py` must invert the tolerance: exit non-zero
(unhealthy) on `200`, exit 0 (healthy) only on `401`. An unmounted or
crashed node then fails the health check instead of silently passing it —
the bind-mount premise becomes self-verifying rather than a silent failure
mode only caught later by US1's own test assertion.

**Alternatives considered**: A bespoke `/ping`-style unauthenticated
health route — rejected; would require patching ComfyUI itself or carving
an exception into the gate, contradicting FR-001/Total Route Coverage
(Constitution Principle II) — the healthcheck should observe the gate
behaving normally, not require a special case in it.

## Decision: No `just` task runner — plain `docker compose` + `pytest -m system`

**Rationale**: curu uses `just` (`just up-d`, `just test-system`, ...) as
its task runner, but curu already depends on `just` project-wide for other
recipes. comfyui_curu_auth has no task runner today and no other reason to
add one. Two extra words per command (`docker compose` vs `just up-d`) is
a smaller cost than a new required tool, per the Constitution's Simplicity
principle ("prefer the plainest construct").

**Alternatives considered**: Add a `Justfile` mirroring curu's — rejected
as unjustified scope for a single feature; revisit only if a second
harness-adjacent recipe makes a task runner earn its keep.

## Decision: `system` pytest marker, opt-in via curu's exact `addopts` convention

**Rationale**: curu's `pyproject.toml` already has this precise, working
mechanism:

```toml
markers = [
    "system: needs a full docker-compose harness (opt-in, not run by default)",
]
addopts = "... -m \"not system\""
```

Copying it verbatim satisfies FR-006 (opt-in, never part of the default
`uv run pytest`) with a convention already proven in the sibling repo,
rather than inventing an equivalent.

**Alternatives considered**: A separate `tests/system/` directory excluded
from `testpaths` — rejected; markers are more explicit about *why* a test
is excluded (opt-in dependency) than a bare path-exclusion would be, and
`pytest -m system` still works as a single, memorable opt-in command
regardless of directory layout.

## Decision: Drive the harness from tests via `subprocess` + `docker compose`, assert over real HTTP/WS via `aiohttp.ClientSession`

**Rationale**: `aiohttp` is already this project's one runtime dependency
(Constitution Principle I) — its `ClientSession` (including
`ws_connect` for the `/ws` handshake check) covers every request FR-005
needs without adding a new one (`requests`/`httpx`). `subprocess` wrapping
`docker compose up -d` / `down` / `ps` mirrors curu's own
`tests/system/conftest.py` `compose()` helper's *shape*.

**Important divergence from curu, not a verbatim port**: curu's own
`conftest.py` polling helpers (`wait_until_reachable` / equivalent) are
built on `httpx` (sync). That contradicts this spec's own "no new
dependency" decision above — this project has no `httpx`. `conftest.py`'s
`compose()` subprocess wrapper can follow curu's shape closely, but the
HTTP-polling helpers must be written fresh, async, against
`aiohttp.ClientSession` — not copied. Caught by adversarial engineering
review (2026-07-23): the tasks describing this as "adapted from curu's
helper" understated that this part is a rewrite, not a port.

**Alternatives considered**: `testcontainers-python`'s generic container
API — rejected; it's a real dependency addition for a project whose
Constitution treats every dependency as attack-surface-relevant, when a
thin `subprocess` wrapper over `docker compose` (already required by FR-001
regardless) does the same job with nothing new to justify.

## Decision: Pace the rate-limit backoff assertion across block expiries, not a tight failure loop

**Rationale**: `gate.py`'s `RateLimiter` only calls `record_failure` when
the client is **not currently blocked** — a client already inside a block
window gets `429` immediately, without incrementing further. Hammering the
wrong credential in a tight loop therefore observes a constant ~1s
`Retry-After`, never growth — the opposite of what FR-005's "repeated wrong
credentials trigger increasing backoff" requires the test to witness.
Caught by adversarial engineering review (2026-07-23) before T011/T012 were
implemented.

The test must instead: fail once, read `Retry-After`, **sleep past** that
window, fail again, confirm the next `Retry-After` is larger, and repeat
for at least two growth steps (1s → 2s → 4s) — a real, budgeted sleep cost
of roughly 7+ seconds for this one test, not a tight loop. Assertions on
the growth sequence should use loose (`>=` / ratio) comparisons, not exact
second values, since scheduling jitter under Docker is expected.

Also worth recording here: through Docker's published port
(`localhost:8188` → container), `request.remote` on the ComfyUI side
resolves to Docker's bridge gateway address, which is stable across
requests from the same test run — so `_client_key`-based backoff keys
consistently in this harness. No `X-Forwarded-For` handling is needed for
this feature.

**Alternatives considered**: Asserting only that a `429` eventually
appears, without checking growth — rejected; that's a materially weaker
witness of FR-005 than what the spec's Acceptance Scenario actually
claims ("increasing backoff").

## Decision: No `contracts/` directory

**Rationale**: The Phase 1 template skips `contracts/` for "purely
internal (build scripts, one-off tools, etc.)" projects. This harness is
exactly that — dev/test tooling with no external API surface of its own
(the docker-compose commands and pytest invocation *are* the interface,
documented in `quickstart.md` instead).
