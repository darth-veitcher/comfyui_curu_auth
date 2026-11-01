---
description: "Task list for 004-oidc-access-tokens"
---

# Tasks: The Bearer path accepts OIDC access tokens

**Input**: `spec.md`, `plan.md`, `research.md` and `features/oidc_access_tokens.feature` in `specs/004-oidc-access-tokens/`.

**Tests**: each `-T` task is a failing test in its own commit. Its `-I` partner is the code in the next commit (constitution article IV).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: the task can run in parallel with the task before it.
- **[Story]**: the user story of the task.

---

## Phase 1: Setup

- [x] T001 Write the settings names, the checks and the rate-limit rule in `project-management/ADRs/ADR-008-oidc-access-tokens-on-the-bearer-path.md`.
- [x] T002 Add an access-token helper to `tests/support/fake_issuer.py`.

## Phase 2: User Story 3 and User Story 4 - The token check and the key cache (P1, P2)

- [x] T003-T [US3, US4] Write failing tests for each check of ADR-008 and for the key cache in `tests/test_oidc_access_tokens.py`.
- [x] T003-I [US3, US4] Add `IssuerKeys` and `verify_access_token` to `oidc.py`. The check needs the cache, so the two are one pair.

## Phase 3: User Story 1, User Story 3 and User Story 5 - The gate (P1, P2)

- [x] T005-T [US1] Write failing tests for the Bearer path, `/ws`, the log line and the rate limit in `tests/test_oidc_access_tokens.py`.
- [x] T005-I [US1] Add the `token_check` parameter to `build_gate_middleware` in `gate.py`.

## Phase 4: User Story 2 - The settings (P1)

- [x] T006-T [US2] Write failing tests for the settings and the start errors in `tests/test_oidc_access_tokens.py`.
- [x] T006-I [US2] Read the settings in `oidc.py` and `__init__.py`, and pass them in `docker-compose.yml`.

## Phase 5: The live tier

- [x] T007 Add a `client_credentials` client and `allowed_resources` to `tests/live/conftest.py`.
- [x] T008 Get a rauthy token and call `GET /queue` in `tests/live/test_rauthy_access_token.py`.

## Phase 6: Documentation and polish

- [x] T009 Add the mode and a section for programs of each provider to `README.md` and `docs/oidc-providers.md`.
- [x] T010 Add the change to `CHANGELOG.md` and `AGENTS.md`.
- [x] T011 Run the quality gates, `uv run pytest` 3 times, the `rauthy` tier, and `beacon doctor --strict`.
- [x] T012 Get a review from `beacon-reviewer` in a new context, and fix each finding.
- [x] T013 Add failing tests and fixes for the review findings in `tests/test_oidc_access_tokens.py`, `tests/test_gate_with_token_check.py`, `gate.py` and `oidc.py`.

## Dependencies

- Phase 2 comes first, because the gate and the settings use the token check.
- Phase 5 needs Phases 2 to 4.
