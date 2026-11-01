---
description: "Task list for 003-oidc-provider-fixes"
---

# Tasks: The OIDC login works with rauthy, Authentik and other providers

**Input**: `spec.md`, `plan.md`, `research.md` and `features/oidc_provider_fixes.feature` in `specs/003-oidc-provider-fixes/`.

**Tests**: each `-T` task is a failing test in its own commit. Its `-I` partner is the code in the next commit (constitution article IV).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: the task can run in parallel with the task before it.
- **[Story]**: the user story of the task.

---

## Phase 1: Setup

- [x] T001 Upgrade BEACON and Spec Kit, and commit the result (issue #15).
- [x] T002 Make the release re-lock `uv.lock` in `pyproject.toml` (issue #16).
- [x] T003 Write the settings names and the rules in `project-management/ADRs/ADR-007-oidc-issuer-algorithms-and-allowlist.md`.
- [ ] T004 Add the fake issuer in `tests/support/fake_issuer.py`, with RSA, EC and Ed25519 keys.

## Phase 2: User Story 1 - Log in through rauthy or Authentik (P1)

- [ ] T005-T [US1] Write failing tests in `tests/test_oidc_providers.py` for the issuer with `/`, the exact issuer of the document, and an EdDSA and ES256 ID token.
- [ ] T005-I [US1] Fix the discovery URL, the issuer check and the key choice in `oidc.py`.

## Phase 3: User Story 3 - The gate refuses an unsafe provider or token (P2)

- [ ] T006-T [US3] Write failing tests in `tests/test_oidc_providers.py` for `none`, key confusion, the HS256 reason, `http` endpoints, no `exp`, no `iat`, `azp` and the leeway.
- [ ] T006-I [US3] Add the algorithm, endpoint and claim rules to `oidc.py`.

## Phase 4: User Story 2 - Only the allowed people get a session (P1)

- [ ] T007-T [US2] Write failing tests in `tests/test_oidc_providers.py` for each allowlist, the start error and the failure log line.
- [ ] T007-I [US2] Add the allowlist to `oidc.py` and read its settings in `__init__.py`.
- [ ] T008 [US2] Pass the new settings in `docker-compose.yml`, and set `ALLOW_ANY_USER=true` in `tests/system/conftest.py`.

## Phase 5: User Story 4 - Set the scopes of the login (P3)

- [ ] T009-T [US4] Write failing tests in `tests/test_oidc_providers.py` for the default scopes and the scopes setting.
- [ ] T009-I [US4] Add the scopes setting to `oidc.py` and `__init__.py`.

## Phase 6: The live tier

- [ ] T010 Add the `rauthy` marker and the `live` dependency group with Playwright in `pyproject.toml`.
- [ ] T011 Start rauthy 0.37.2 with an EdDSA client and a test user in `tests/live/conftest.py`.
- [ ] T012 Log in through rauthy in Chromium and check the `curu_auth` cookie in `tests/live/test_rauthy_login.py`.

## Phase 7: Documentation and polish

- [ ] T013 Write the guide for each provider in `docs/oidc-providers.md`, with "tested live" or "from the provider documentation" on each line.
- [ ] T014 Rewrite `README.md` to the headings of `docs/WRITING.md`, and add `AGENTS.md` (issue #17).
- [ ] T015 Add the change to `CHANGELOG.md`, and add the spec to `project-management/Roadmap/README.md` (issue #15).
- [ ] T016 Run the quality gates, `uv run pytest` 3 times, the `rauthy` tier, and `beacon doctor --strict`.
- [ ] T017 Get a review from `beacon-reviewer` in a new context, and fix each finding.

## Dependencies

- Phase 2 comes first, because the other phases use the fake issuer and the new key code.
- Phase 3 and Phase 4 change different functions, but both change `oidc.py`, so do them in order.
- Phase 6 needs Phases 2 to 5.
