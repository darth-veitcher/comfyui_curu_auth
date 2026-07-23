# Implementation Plan: Docker ComfyUI Integration Harness

**Branch**: `001-docker-comfyui-harness` | **Date**: 2026-07-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-docker-comfyui-harness/spec.md`

## Summary

Bring up a real, CPU-only ComfyUI instance in Docker with comfyui_curu_auth
installed from this repo's own working tree (bind-mounted, not a published
release), and add an opt-in `system`-marked pytest suite that exercises the
live gate — unauthenticated rejection on HTTP routes and the `/ws`
handshake, correct-credential success, and rate-limit backoff — closing the
gap the README already names: `__init__.py`'s real ComfyUI-side wiring has
no automated test today. Adapted directly from the equivalent, already-
proven harness in the sibling repo `~/repos/JAMESVEITCH/curu`, swapping its
`git clone`-a-release approach for a bind mount of the local working tree
and dropping its checkpoint-generation step (out of scope — no rendering).

## Technical Context

**Language/Version**: Python 3.12 (matches `pyproject.toml` `requires-python`)

**Primary Dependencies**: `aiohttp` (already the project's only runtime
dependency — its `ClientSession`/`ws_connect` drives every live HTTP and
websocket check); `pytest` + `pytest-asyncio` (already dev dependencies);
Docker / `docker compose` CLI (new — required to run the harness at all)

**Storage**: N/A — the harness is a stateless ComfyUI process; no database
or persistent volume

**Testing**: `pytest`, new `system`-marked test module under
`tests/system/`, opt-in via `-m system` (excluded from the default
`uv run pytest` per FR-006)

**Target Platform**: Any Docker host the developer's machine already runs
(Linux container regardless of host OS) — no GPU required or used

**Project Type**: Dev/test tooling (docker-compose harness + opt-in test
suite) for an existing single-file ComfyUI custom node — not a service

**Performance Goals**: Harness reaches healthy within its health check's
startup budget; SC-001's 180-second repeat-boot budget applies once the
image is already built (first build is a separate, multi-minute one-time
cost per the Assumptions section) — 180s matches the sibling harness's own
validated cold-start time (revised from an initial 1-minute target after
adversarial engineering review found ComfyUI's own CPU boot routinely
exceeds it)

**Constraints**: CPU-only — no GPU device reservation; no model checkpoint;
no workflow execution (Epic + spec Non-Goals)

**Scale/Scope**: Single-instance, single-developer local harness — not
concurrent, not multi-tenant, not a shared environment

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Minimal Attack Surface (NON-NEGOTIABLE) | PASS. No new dependency enters `pyproject.toml`'s `[project.dependencies]` (the shipped node's own runtime deps are unchanged) — Docker and the harness's own container-internal deps (torch, ComfyUI itself) are dev/test-only and never ship with the node. The harness's fixed test credential is explicitly scoped to this disposable local context (spec Assumptions), mirroring curu's own already-documented rationale for the identical pattern. |
| II. Total Route Coverage (NON-NEGOTIABLE) | PASS — this is the principle's own enabler. FR-005 explicitly requires verifying the `/ws` handshake is gated, not just HTTP routes. |
| III. Zero-Config by Default | PASS. The harness sets `COMFYUI_CURU_AUTH_TOKEN` deliberately (FR-003) for deterministic test auth — this is test-harness configuration, not a change to the node's own zero-config default behavior, which is untouched by this feature. |
| IV. Test-First for Security-Critical Logic (NON-NEGOTIABLE) | PASS, applies to this feature's own build: `tasks.md` orders the `system`-marked test module before/alongside the harness's Docker artifacts, per the acceptance scenarios in spec.md. |
| V. Simplicity | PASS. Reuses curu's proven Dockerfile/compose/healthcheck pattern rather than designing a new one; explicitly rejects adding a `just` task runner or a container-testing library (`testcontainers`) where a thin `subprocess` wrapper over `docker compose` and `aiohttp.ClientSession` already cover everything needed (research.md). |

No violations. Complexity Tracking table below is not needed.

**Post-Phase-1 re-check**: Unchanged — Phase 1 design (below) introduced no
new dependencies or principle tensions beyond what's assessed above.

## Project Structure

### Documentation (this feature)

```text
specs/001-docker-comfyui-harness/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
└── tasks.md              # Phase 2 output (/speckit-tasks — not yet created)
```

No `contracts/` directory — see research.md's "No `contracts/` directory"
decision; this is internal dev/test tooling with no external API surface
of its own.

### Source Code (repository root)

```text
docker/
└── comfyui/
    ├── Dockerfile         # CPU-only ComfyUI image, pinned tag, bind-mount target for this node
    └── healthcheck.py     # Requires 401 specifically (200 = unhealthy/ungated) —
                            # inverted from curu's own tolerant version; see research.md

docker-compose.yml         # Single service: comfyui, bind-mounts repo root to the absolute
                            # in-container path /app/ComfyUI/custom_nodes/comfyui_curu_auth

tests/
└── system/
    ├── conftest.py         # compose() subprocess helper, wait_until_reachable/unreachable
    └── test_docker_harness.py   # system-marked: gate rejects unauthenticated (HTTP + /ws),
                                   # correct credential succeeds, rate-limit backoff,
                                   # teardown/restart leaves no stale state
```

**Structure Decision**: Mirrors curu's own layout
(`docker/comfyui/Dockerfile` + root `docker-compose.yml`) for consistency
with the sibling repo this pattern is adapted from, and extends this
repo's existing `tests/` directory (already `testpaths = ["tests"]` in
`pyproject.toml`) with a `system/` subdirectory carrying the new opt-in
marker — no change to where `tests/test_gate.py`'s existing hermetic suite
lives.

## Complexity Tracking

*Not applicable — no Constitution Check violations.*
