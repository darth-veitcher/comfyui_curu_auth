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

- [x] T001 Register the `system` pytest marker and add `-m "not system"` to
      `addopts` in `pyproject.toml` (verbatim convention from
      `~/repos/JAMESVEITCH/curu`'s `pyproject.toml` — research.md), so the
      suite this feature adds is opt-in per FR-006 from the moment it exists
- [x] T002 [P] Create `tests/system/` directory with empty `conftest.py` and
      `test_docker_harness.py` stubs

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete —
every story's tests drive the harness through these helpers.

- [x] T003 Implement a `compose(*args, timeout=None)` subprocess helper
      (wraps `docker compose <args>`, returns a `CompletedProcess`) in
      `tests/system/conftest.py` — this one can follow the *shape* of
      curu's own `conftest.py` helper of the same name closely, since
      subprocess wrapping has no dependency conflict
- [x] T004 Implement `wait_until_reachable(timeout=180)` /
      `wait_until_unreachable(timeout)` polling helpers in
      `tests/system/conftest.py`, written **fresh against
      `aiohttp.ClientSession`** — NOT ported from curu's own equivalent,
      which is built on `httpx` (a dependency this project deliberately
      doesn't have; research.md). "Reachable" means *any* HTTP response,
      including 401 — the gate being active is not a failure to reach.
      Default timeout of 180s matches SC-001's revised, realistic budget.

**Checkpoint**: Foundation ready — US1 can now be implemented.

---

## Phase 3: User Story 1 - Boot a real, gated ComfyUI instance (Priority: P1) 🎯 MVP

**Goal**: `docker compose up` brings up a real, CPU-only ComfyUI instance
with comfyui_curu_auth installed from the local working tree, enforcing the
gate.

**Independent Test**: Bring the harness up by hand; confirm an
unauthenticated request 401s and the fixed test credential succeeds.

- [x] T005-T [US1] Write a FAILING test `test_harness_boots_and_gate_enforces`
      in `tests/system/test_docker_harness.py`: `compose("up", "-d")`
      succeeds, `wait_until_reachable` returns under a 180s timeout (SC-001 —
      see research.md's "Pace the rate-limit..." sibling note on realistic
      ComfyUI CPU boot time), an unauthenticated `GET /` returns 401, and the
      same request with the fixed test credential (`COMFYUI_CURU_AUTH_TOKEN`)
      returns 200. Implements the feature file's "Boot a real, gated ComfyUI
      instance", "Unauthenticated HTTP requests are rejected", and "The
      fixed test credential succeeds" scenarios. **Fails now** — no
      `docker-compose.yml` or Dockerfile exist yet, so `compose up` errors.
- [x] T006 [P] [US1] Implement `docker/comfyui/Dockerfile`: CPU-only ComfyUI
      at a pinned tag (same tag as curu's own harness — research.md), CPU
      torch wheels, no checkpoint generation step, `EXPOSE 8188`, `CMD`
      running the persistent server (`--cpu --listen 0.0.0.0 --port 8188`).
      Note the ComfyUI dependency footgun curu's own Dockerfile already
      documents at this tag (a `pip install requests` needed beyond
      `requirements.txt`) — expect similar iteration here.
- [x] T007 [P] [US1] Implement `docker/comfyui/healthcheck.py`: **NOT** a
      verbatim copy of curu's own (which treats 200 as healthy too — wrong
      here, see research.md's healthcheck decision). This version exits
      non-zero (unhealthy) on 200 and exit 0 (healthy) on 401 **or 429**, so
      a failed/unmounted bind mount (FR-002) reports unhealthy instead of
      silently passing as an ungated instance (FR-004). 429 was added after
      discovering live that this check's own repeated unauthenticated
      probing eventually rate-limits itself too — still proof the gate is
      enforcing, not evidence it's missing (research.md).
- [x] T008-I [US1] Implement root `docker-compose.yml`: single `comfyui`
      service building T006's Dockerfile, port `8188:8188`, no GPU device
      reservation, bind-mounts this repo's root read-only to the **absolute**
      in-container path `/app/ComfyUI/custom_nodes/comfyui_curu_auth` (FR-002
      — a relative path here mounts nowhere ComfyUI's loader looks), sets
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

- [x] T009-T [US2] Write a FAILING test `test_websocket_handshake_is_gated`
      in `tests/system/test_docker_harness.py`: an unauthenticated
      `aiohttp.ClientSession.ws_connect("ws://localhost:8188/ws")` MUST be
      rejected. Implements the feature file's "The websocket handshake is
      gated too" scenario. **Fails now** — no ws-connect assertion exists
      yet in the suite.
- [x] T010-I [US2] Implement the ws-connect helper/assertion (expect
      `WSServerHandshakeError` or equivalent rejection before upgrade) so
      T009-T passes
- [x] T011-T [US2] Write a FAILING test
      `test_repeated_wrong_credentials_trigger_backoff` in
      `tests/system/test_docker_harness.py`. **Must NOT hammer the wrong
      credential in a tight loop** — `gate.py`'s `RateLimiter` only calls
      `record_failure` when the client isn't already blocked, so a tight
      loop observes a constant ~1s `Retry-After`, never growth (caught by
      adversarial engineering review, 2026-07-23; see research.md's pacing
      decision). Instead: fail once, read `Retry-After`, sleep past that
      window, fail again, and assert the next `Retry-After` is larger —
      repeat for at least two growth steps (1s → 2s → 4s). Budget ~7+
      real seconds of sleep for this test; use loose (`>=`/ratio)
      comparisons, not exact second values. Implements the feature file's
      "Repeated wrong credentials trigger backoff" scenario. **Fails now**
      — no repeated-failure helper exists yet.
- [x] T012-I [US2] Implement the paced, block-expiry-aware repeated-failed-
      login helper and backoff-growth assertions so T011-T passes
- [x] T013 [US2] One-time manual regression sanity check (not a permanent
      automated task, mirroring curu's own precedent for a
      not-worth-automating check): temporarily comment out the gate
      middleware registration in `__init__.py`, confirm T005-T/T009-T/T011-T
      all fail loudly, then revert. Record the result in this task's
      completion note — proves the suite isn't tautologically green.
      **Done (2026-07-23)**: all three tests failed as expected with the
      middleware disabled (401→200 assertion failures, WS handshake
      succeeded instead of raising). `__init__.py` reverted; `git diff`
      confirmed clean; all 3 system tests + 44 hermetic tests pass again.

**Checkpoint**: User Stories 1 AND 2 both work — the auth gate is verified
automatically against a real ComfyUI process.

---

## Phase 5: User Story 3 - Teardown and restart leave no stale state (Priority: P2)

**Goal**: Tearing the harness down and bringing it back up behaves
identically to a first-ever run.

**Independent Test**: Trigger rate-limit backoff, tear down, bring up
again, confirm the fresh instance isn't still rate-limited and issues a
fresh session.

- [x] T014-T [US3] Write a FAILING test
      `test_teardown_and_restart_leaves_no_stale_state` in
      `tests/system/test_docker_harness.py`, adapted from curu's own
      `TestTearDownLeavesNoResidualState` and extended per FR-007: bring
      the harness up, trigger rate-limit backoff, tear down
      (`wait_until_unreachable`), bring up again, and assert the fresh
      instance is not rate-limited and issues a fresh session on login.
      Implements the feature file's "Teardown and restart leave no stale
      state" scenario. **Fails now** — no such assertion exists yet.
- [x] T015-I [US3] Implement the teardown/restart assertions so T014-T
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

Revised after adversarial engineering review (2026-07-23): US1 gets its own
bullet, separate from Setup/Foundational, because its budget is dominated
by Docker image build iteration (CPU torch wheels + ComfyUI clone,
multi-minute per rebuild, plus a known dependency footgun at this ComfyUI
tag — research.md) rather than by code volume. Bundling it with the quick,
deterministic Setup/Foundational work risked blowing a single 4h ceiling.

1. **Bullet 1**: Phase 1 (Setup) + Phase 2 (Foundational) — quick,
   deterministic, no Docker builds yet.
2. **Bullet 2 (MVP)**: Phase 3 (US1) — a developer can bring up a real,
   gated ComfyUI instance and verify it by hand. Demoable. Budget extra
   time/sessions for Docker build iteration specifically, not just the
   code in T005–T008.
3. **Bullet 3**: Phase 4 (US2) — the automated live-gate suite. Includes
   the rate-limit test's own ~7+ second real sleep budget (T011/T012) —
   not just implementation time.
4. **Bullet 4**: Phase 5 (US3) + Phase 6 (Polish) — teardown/restart
   guarantees and documentation/cleanup.

### MVP First

Complete Phases 1–3, then **STOP and VALIDATE**: run `quickstart.md`'s
manual steps and confirm US1's three acceptance scenarios hold before
starting US2.
