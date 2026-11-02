---
description: "Task list for 005-session-loss-reload"
---

# Tasks: An open tab goes to the login page when its session is lost

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/` and `features/` in `specs/005-session-loss-reload/`.

**Tests**: each `-T` task is a failing test in its own commit. Its `-I` partner is the code in the next commit (constitution article IV). A test names its scenario from `features/` in its docstring, for example `"""Scenario: The gate rejects a poll."""`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: the task can run in parallel with the task before it.
- **[Story]**: the user story of the task.

---

## Phase 1: Setup

- [x] T001 Register the `browser` marker, and exclude it from the default run, in `pyproject.toml`.
- [x] T002 Create `tests/browser/conftest.py` with the real gate middleware on a free port, a `SessionStore` that a test can clear, and a Chromium page from Playwright.
- [x] T003 Add a double of ComfyUI to `tests/browser/conftest.py`. Its page at `/` imports `web/session_loss.js`, polls `/api/jobs` each second, and opens `/ws` again after each close.
- [x] T004 Make `tests/browser/conftest.py` fail, and not skip, when Playwright or Chromium is not installed.

**Checkpoint**: `uv run --group live pytest -m browser` starts Chromium and loads the double page.

---

## Phase 2: Foundational - The gate rejection mark (contract G1 to G9)

This phase blocks User Story 1, because the module acts on the mark. It also serves User Story 3.

- [x] T005-T [US3] Write failing tests for rules G1 to G9 of `contracts/gate-rejection.md` in `tests/test_gate.py`. Cover the header on each HTTP 401 and HTTP 429 of the middleware. Cover the same status, body and log line. Cover no header on an accepted request, a handler 401 and the HTTP 503.
- [x] T005-I [US3] Add the header `X-Curu-Auth: login-required` to the HTTP 401 and the HTTP 429 of the middleware in `gate.py`, as one module constant.

**Checkpoint**: `uv run pytest` passes. Each existing test passes with no change to its assertions.

---

## Phase 3: User Story 1 - The tab goes to the login page after a restart (P1) 🎯 MVP

**Goal**: an open tab shows the login page within 5 seconds after a session loss, and then sends no more requests.

**Independent Test**: log in with Chromium, clear the `SessionStore`, and measure the time until the tab shows the login page. Count the log lines.

- [x] T006-T [US1] Write failing tests for "The session store loses the session" and "The gate rejects a poll" in `tests/browser/test_session_loss.py` (rules T1, T2).
- [x] T006-I [US1] Create `web/session_loss.js` with the wrapper of `window.fetch` and the move with `location.assign("/curu-auth/login")`, and set `WEB_DIRECTORY = "./web"` in `__init__.py`.
- [x] T007-T [US1] Write failing tests in `tests/browser/test_session_loss.py` for "The gate rejects the ws handshake" (rule T5), and for one probe in 2 seconds (rule T9).
- [x] T007-I [US1] Add the wrapper of `window.WebSocket` and the probe with the original `fetch` to `web/session_loss.js`. Keep the prototype and the static constants of `WebSocket`.
- [x] T008-T [US1] Write failing tests for "No new log line after the move" in `tests/browser/test_session_loss.py`, with `caplog`. Also test the 5-second limit (rule T10) and one move only (rule T11).
- [x] T008-I [US1] Add the `leaving` flag and the `curu-auth:left-at` limit to `web/session_loss.js`.
- [x] T009-T [US1] Write a failing test for "The user logs in again" in `tests/browser/test_session_loss.py`. The login form sends the tab to `/`, and the double page loads.
- [x] T009-I [US1] Fix `web/session_loss.js` until T009-T passes. If T009-T passes at once, record that in the commit message of T009-T.
- [x] T010-T [US1] Write a failing test for "An OIDC session is lost" in `tests/browser/test_session_loss.py`. Log in through `tests/support/fake_issuer.py`, put the cookie into Chromium, and clear the store.
- [x] T010-I [US1] Fix `web/session_loss.js` or `tests/browser/conftest.py` until T010-T passes. If T010-T passes at once, record that in the commit message of T010-T.

**Checkpoint**: User Story 1 works in the `browser` tier. This is the MVP.

---

## Phase 4: User Story 2 - A tab with a valid session stays on its page (P1)

**Goal**: the tab never goes to the login page by mistake.

**Independent Test**: use the double page with a valid session. Stop the server for 30 seconds, and make a handler give HTTP 401 twenty times. Count the moves to the login page.

- [x] T011-T [US2] Write failing tests for "Another node gives HTTP 401" in `tests/browser/test_session_loss.py`. A handler gives HTTP 401 with no mark 20 times, and the tab stays (rule T3, SC-005).
- [ ] T011-I [US2] Fix `web/session_loss.js` until T011-T passes. The wrapper returns the same answer to the page.
- [x] T012-T [US2] Write failing tests for "The server cannot be reached" and "The server comes back with the session" in `tests/browser/test_session_loss.py`. Stop the site for 30 seconds, and start it again with the same store (rules T4, T6, SC-004).
- [ ] T012-I [US2] Fix `web/session_loss.js` until T012-T passes. A network error on a fetch or on a probe never causes a move.
- [ ] T013-T [US2] Write failing tests for "The socket closes for another reason" in `tests/browser/test_session_loss.py`. The double closes an open socket, and a probe gets an answer with no mark (rules T7, T8).
- [ ] T013-I [US2] Fix `web/session_loss.js` until T013-T passes. A socket that opened causes no probe.

**Checkpoint**: User Stories 1 and 2 pass in the `browser` tier.

---

## Phase 5: User Story 3 - Programs and log tools see no change (P2)

**Goal**: curu, comfy-mcp, fail2ban and crowdsec see no change.

**Independent Test**: run the default, `system` and `comfy_mcp` tiers. Compare the log lines with the patterns in `contrib/`.

- [ ] T014-T [US3] Write a failing test for "The log line" in `tests/test_gate.py`. The `failregex` of `contrib/fail2ban/comfyui-curu-auth.conf` must match each "authentication failure" line of the tests.
- [ ] T014-I [US3] Fix `gate.py` until T014-T passes. If T014-T passes at once, record that in the commit message of T014-T.
- [ ] T015 [US3] Run `uv run pytest`, `uv run --group live pytest -m system` and `uv run --group live pytest -m comfy_mcp` with no change to existing assertions, for "A wrong Bearer header" and "The static credential" (SC-006).

---

## Phase 6: The real ComfyUI frontend (rule T12)

- [ ] T016-T [US1] Write a failing test in `tests/system/test_session_loss.py`. Log in with Chromium, and run `docker compose restart comfyui`. Expect the login page within 5 seconds after the health check passes (SC-001). Expect no more than 10 "authentication failure" lines (SC-002).
- [ ] T016-I [US1] Fix `web/session_loss.js` until T016-T passes against ComfyUI v0.27.0.
- [ ] T017-T [US1] Write a failing test in `tests/system/test_session_loss.py`: an unauthenticated `GET /extensions/comfyui_curu_auth/session_loss.js` gets HTTP 401 (article II, FR-011).
- [ ] T017-I [US1] Fix `__init__.py` until T017-T passes. If T017-T passes at once, record that in the commit message of T017-T.

---

## Phase 7: Documentation and polish

- [ ] T018 [P] Add what a user sees after a session loss to the section "Log in from a browser" of `README.md`. Add the header `X-Curu-Auth` to "Technical notes".
- [ ] T019 [P] Add the `browser` tier command, the `--group live` flag for the `system` tier, and the `web/` folder to `AGENTS.md`.
- [ ] T020 [P] Add the change under "Unreleased" in `CHANGELOG.md`.
- [ ] T021 [P] Replace the comment "no JS of its own" next to `WEB_DIRECTORY` in `__init__.py`, and update the module docstring.
- [ ] T022 Run `beacon docs check` and the `beacon-docs-reviewer` agent on `README.md` and `AGENTS.md`, and fix each finding.
- [ ] T023 Run the quality gates, `uv run pytest` 3 times, the `browser` tier 3 times, the `system` tier and `beacon doctor --strict`.
- [ ] T024 Do steps 1 to 7 of section 4 of `specs/005-session-loss-reload/quickstart.md` by hand.
- [ ] T025 Get a review from `beacon-reviewer` in a new context. For each finding, add a failing test in `tests/` and a fix in `web/session_loss.js` or `gate.py`.

---

## Dependencies

- Phase 1 comes first, because each browser test needs the harness.
- Phase 2 comes before Phase 3, because the module acts on the mark.
- Phase 4 needs Phase 3, because it tests the module of Phase 3.
- Phase 5 needs Phase 2 only. It can run in parallel with Phases 3 and 4.
- Phase 6 needs Phases 3 and 4.
- Phase 7 needs all other phases.

## Parallel work

- T001 and T005-T change different files, so they can run in parallel.
- Phase 5 (`tests/test_gate.py`, `gate.py`) can run in parallel with Phases 3 and 4 (`tests/browser/`, `web/`).
- T018 to T021 change different files, so they can run in parallel.
- Each `-I` task waits for its own `-T` task.

## Implementation strategy

1. Do Phases 1 and 2. The gate now marks its rejections, and programs see no change.
2. Do Phase 3. This is the MVP: the tab goes to the login page. Stop and check it in the `browser` tier.
3. Do Phase 4, to remove false moves to the login page.
4. Do Phases 5 and 6, to prove the effect on programs, log tools and the real ComfyUI frontend.
5. Do Phase 7, and open the pull request. Say in the pull request that the log line does not change.
