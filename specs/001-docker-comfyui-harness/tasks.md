---
description: "Task list for 001-docker-comfyui-harness"
---

# Tasks: Docker ComfyUI Integration Harness

**Input**: Design documents from `/specs/001-docker-comfyui-harness/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md,
features/docker_comfyui_harness.feature

**Tests**: First-class, not optional — this spec carries acceptance scenarios
and success criteria (BEACON test-first discipline). `-T`/`-I` suffix pairs:
the `-T` task is committed alone (failing) before its `-I` partner makes it
pass.

**Organization**: Grouped by user story (spec.md priorities P1/P1/P2).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

Single project — `docker/`, root `docker-compose.yml`, `tests/system/` per
`plan.md`'s Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Register the `system` pytest marker and add `-m "not system"` to
      `addopts` in `pyproject.toml` (verbatim convention from
      `~/repos/JAMESVEITCH/curu`'s `pyproject.toml` — research.md), so the
      suite this feature adds is opt-in per FR-006 from the moment it exists
- [ ] T002 [P] Create `tests/system/` directory with empty `conftest.py` and
      `test_docker_harness.py` stubs

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete —
every story's tests drive the harness through these helpers.

- [ ] T003 Implement a `compose(*args, timeout=None)` subprocess helper
      (wraps `docker compose <args>`, returns a `CompletedProcess`) in
      `tests/system/conftest.py`, adapted from curu's own
      `tests/system/conftest.py` helper of the same name
- [ ] T004 Implement `wait_until_reachable(timeout)` /
      `wait_until_unreachable(timeout)` polling helpers in
      `tests/system/conftest.py` (poll `GET http://localhost:8188/` via
      `aiohttp.ClientSession`; "reachable" means *any* HTTP response,
      including 401 — the gate being active is not a failure to reach)

**Checkpoint**: Foundation ready — US1 can now be implemented.

---

## Phase 3: User Story 1 - Boot a real, gated ComfyUI instance (Priority: P1) 🎯 MVP

**Goal**: `docker compose up` brings up a real, CPU-only ComfyUI instance
with comfyui_curu_auth installed from the local working tree, enforcing the
gate.

**Independent Test**: Bring the harness up by hand; confirm an
unauthenticated request 401s and the fixed test credential succeeds.

- [ ] T005-T [US1] Write a FAILING test `test_harness_boots_and_gate_enforces`
      in `tests/system/test_docker_harness.py`: `compose("up", "-d")`
      succeeds, `wait_until_reachable` returns under its timeout, an
      unauthenticated `GET /` returns 401, and the same request with the
      fixed test credential (`COMFYUI_CURU_AUTH_TOKEN`) returns 200.
      Implements the feature file's "Boot a real, gated ComfyUI instance",
      "Unauthenticated HTTP requests are rejected", and "The fixed test
      credential succeeds" scenarios. **Fails now** — no
      `docker-compose.yml` or Dockerfile exist yet, so `compose up` errors.
- [ ] T006 [P] [US1] Implement `docker/comfyui/Dockerfile`: CPU-only ComfyUI
      at a pinned tag (same tag as curu's own harness — research.md), CPU
      torch wheels, no checkpoint generation step, `EXPOSE 8188`, `CMD`
      running the persistent server (`--cpu --listen 0.0.0.0 --port 8188`)
- [ ] T007 [P] [US1] Implement `docker/comfyui/healthcheck.py`: treats HTTP
      401 alongside 200 as healthy (adapted directly from curu's own
      `docker/comfyui/healthcheck.py` — same reasoning, gate active means
      401 on every route including `/`)
- [ ] T008-I [US1] Implement root `docker-compose.yml`: single `comfyui`
      service building T006's Dockerfile, port `8188:8188`, no GPU device
      reservation, bind-mounts this repo's root read-only to
      `custom_nodes/comfyui_curu_auth` inside the container (FR-002), sets
      `COMFYUI_CURU_AUTH_TOKEN` to a fixed test value (FR-003), wires
      T007's healthcheck. Depends on T006, T007. Makes T005-T pass.

**Checkpoint**: User Story 1 fully functional — a developer can bring up a
real, gated ComfyUI instance and verify it by hand per `quickstart.md`.

---

## Phase 4: User Story 2 - Automated integration suite proves the gate (Priority: P1)

**Goal**: `uv run pytest -m system` verifies the live harness end-to-end,
including the `/ws` handshake and rate-limit backoff, without manual
poking.

**Independent Test**: Run the suite against a harness already up from US1;
confirm it exits non-zero if the gate is temporarily broken.

- [ ] T009-T [US2] Write a FAILING test `test_websocket_handshake_is_gated`
      in `tests/system/test_docker_harness.py`: an unauthenticated
      `aiohttp.ClientSession.ws_connect("ws://localhost:8188/ws")` MUST be
      rejected. Implements the feature file's "The websocket handshake is
      gated too" scenario. **Fails now** — no ws-connect assertion exists
      yet in the suite.
- [ ] T010-I [US2] Implement the ws-connect helper/assertion (expect
      `WSServerHandshakeError` or equivalent rejection before upgrade) so
      T009-T passes
- [ ] T011-T [US2] Write a FAILING test
      `test_repeated_wrong_credentials_trigger_backoff` in
      `tests/system/test_docker_harness.py`: submitting the wrong
      credential repeatedly against the harness MUST return 429 with a
      growing `Retry-After`. Implements the feature file's "Repeated wrong
      credentials trigger backoff" scenario. **Fails now** — no
      repeated-failure helper exists yet.
- [ ] T012-I [US2] Implement the repeated-failed-login helper and backoff
      assertions so T011-T passes
- [ ] T013 [US2] One-time manual regression sanity check (not a permanent
      automated task, mirroring curu's own precedent for a
      not-worth-automating check): temporarily comment out the gate
      middleware registration in `__init__.py`, confirm T005-T/T009-T/T011-T
      all fail loudly, then revert. Record the result in this task's
      completion note — proves the suite isn't tautologically green.

**Checkpoint**: User Stories 1 AND 2 both work — the auth gate is verified
automatically against a real ComfyUI process.

---

## Phase 5: User Story 3 - Teardown and restart leave no stale state (Priority: P2)

**Goal**: Tearing the harness down and bringing it back up behaves
identically to a first-ever run.

**Independent Test**: Trigger rate-limit backoff, tear down, bring up
again, confirm the fresh instance isn't still rate-limited and issues a
fresh session.

- [ ] T014-T [US3] Write a FAILING test
      `test_teardown_and_restart_leaves_no_stale_state` in
      `tests/system/test_docker_harness.py`, adapted from curu's own
      `TestTearDownLeavesNoResidualState` and extended per FR-007: bring
      the harness up, trigger rate-limit backoff, tear down
      (`wait_until_unreachable`), bring up again, and assert the fresh
      instance is not rate-limited and issues a fresh session on login.
      Implements the feature file's "Teardown and restart leave no stale
      state" scenario. **Fails now** — no such assertion exists yet.
- [ ] T015-I [US3] Implement the teardown/restart assertions so T014-T
      passes
- [ ] T016-T [US3] Write a FAILING test
      `test_second_up_without_down_is_not_destructive` in
      `tests/system/test_docker_harness.py`, adapted from curu's own
      `TestIdempotentUp` (spec Edge Case: a second `up` without an
      intervening `down` must not fail destructively or start a duplicate
      container). **Fails now** — no such assertion exists yet.
- [ ] T017-I [US3] Implement the idempotent-up assertions so T016-T passes

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T018 [P] Update README.md's "Tests" section to mention
      `uv run pytest -m system` as the opt-in live-harness suite, linking to
      `specs/001-docker-comfyui-harness/quickstart.md`
- [ ] T019 Manually walk through `quickstart.md` end-to-end (up, run suite,
      tear down, up again) and correct any drift between it and actual
      behavior
- [ ] T020 [P] `beacon doctor --strict` clean before calling this feature's
      bullets done

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — no dependency on other
  stories
- **US2 (Phase 4)**: Depends on US1 — needs a live, healthy harness to test
  against
- **US3 (Phase 5)**: Depends on US1 (same reason as US2); independent of
  US2 in logic, but shares `tests/system/test_docker_harness.py` with it,
  so sequential for a single implementer even though nothing blocks doing
  US3 before US2
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### Within Each User Story

- `-T` task written and confirmed FAILING before its paired `-I` task
- Story complete before moving to the next priority

---

## Parallel Example: User Story 1

```bash
# T006 and T007 are different files with no dependency on each other:
Task: "Implement docker/comfyui/Dockerfile"
Task: "Implement docker/comfyui/healthcheck.py"
# T008 depends on both — not parallel with either.
```

---

## Implementation Strategy

### Suggested tracer-bullet split (2-4h each, per BEACON)

1. **Bullet 1 (MVP)**: Phase 1 + Phase 2 + Phase 3 (US1) — a developer can
   bring up a real, gated ComfyUI instance and verify it by hand. Demoable.
2. **Bullet 2**: Phase 4 (US2) — the automated live-gate suite.
3. **Bullet 3**: Phase 5 (US3) + Phase 6 (Polish) — teardown/restart
   guarantees and documentation/cleanup.

### MVP First

Complete Phases 1–3, then **STOP and VALIDATE**: run `quickstart.md`'s
manual steps and confirm US1's three acceptance scenarios hold before
starting US2.
