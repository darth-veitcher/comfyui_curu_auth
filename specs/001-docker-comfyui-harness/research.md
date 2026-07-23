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
the repo root to `custom_nodes/comfyui_curu_auth` lets a plain container
restart pick up local edits, which is what SC-001's "under 1 minute" repeat
boot actually depends on.

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

## Decision: Reuse curu's `401`-tolerant healthcheck approach

**Rationale**: `docker/comfyui/healthcheck.py` in curu already encodes the
right reasoning: once comfyui_curu_auth is active, every route including a
plain `GET /` requires a credential, so a `401` means "up and correctly
gated," not "crashed." Same logic applies here unchanged.

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
`tests/system/conftest.py` `compose()` helper almost exactly.

**Alternatives considered**: `testcontainers-python`'s generic container
API — rejected; it's a real dependency addition for a project whose
Constitution treats every dependency as attack-surface-relevant, when a
thin `subprocess` wrapper over `docker compose` (already required by FR-001
regardless) does the same job with nothing new to justify.

## Decision: No `contracts/` directory

**Rationale**: The Phase 1 template skips `contracts/` for "purely
internal (build scripts, one-off tools, etc.)" projects. This harness is
exactly that — dev/test tooling with no external API surface of its own
(the docker-compose commands and pytest invocation *are* the interface,
documented in `quickstart.md` instead).
