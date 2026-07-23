---
description: "Task list for 002-oidc-login"
---

# Tasks: OIDC/OAuth Login Path

**Input**: Design documents from `/specs/002-oidc-login/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md,
features/oidc_login.feature

**Tests**: First-class, not optional — this spec carries acceptance scenarios
and success criteria (BEACON test-first discipline). `-T`/`-I` suffix pairs:
the `-T` task is committed alone (failing) before its `-I` partner makes it
pass. This spec's security-critical logic (token verification, state/nonce/
PKCE, the public-paths carve-out) is exactly what Constitution Principle IV
exists for — no exceptions to the pairing here.

**Organization**: Grouped by user story (spec.md priorities P1/P1/P2).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

Single project — `oidc.py` (new), `gate.py` (minimal change), `__init__.py`
(wiring), `docker-compose.yml` + `docker/authelia/` (new service),
`tests/test_oidc.py` (new hermetic), `tests/system/test_oidc_harness.py`
(new live) per `plan.md`'s Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Add `joserfc` to `dependencies` in `pyproject.toml` (research.md —
      the one new dependency this spec adds, scoped to ID-token JWK/JWT
      verification only)
- [ ] T002 [P] Create `tests/test_oidc.py` stub (hermetic suite, mirrors
      `tests/test_gate.py`'s existing structure and conventions)
- [ ] T003 [P] Create `tests/system/test_oidc_harness.py` stub (`system`-
      marked, mirrors `tests/system/test_docker_harness.py`'s conventions)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete —
US1 registers new routes through this mechanism; US2 verifies nothing
changes when it isn't used.

- [ ] T004-T Write a FAILING test in `tests/test_oidc.py` asserting
      `build_gate_middleware` accepts a `public_paths` iterable and lets
      *every* path in it through unauthenticated (not just a single
      `LOGIN_PATH` string) — the ADR-003 generalization. **Fails now** —
      `build_gate_middleware`'s signature has no such parameter yet.
- [ ] T005-I Generalize `gate.py`'s `LOGIN_PATH` check into a `public_paths`
      parameter (defaulting to `{LOGIN_PATH}` — byte-for-byte today's
      behavior when no extra paths are supplied) so T004-T passes. Run the
      full existing `tests/test_gate.py` suite (44 tests) unmodified
      immediately after this change — every one MUST still pass; this *is*
      the regression guard for FR-004 (default Bearer-header path
      untouched).
- [ ] T006-T Write a FAILING test in `tests/test_oidc.py` for
      `resolve_oidc_config()`: returns a populated config object when all
      four environment variables (issuer URL, client ID, client secret,
      redirect URI) are present, and `None` when any subset is missing —
      including the partial-configuration edge case (FR-009). **Fails
      now** — `oidc.py` doesn't exist yet.
- [ ] T007-I Implement `oidc.py`'s `resolve_oidc_config()` so T006-T passes
- [ ] T008 Extend `docker-compose.yml` with an `authelia` service (Lite
      bundle — file-based user, SQLite storage, no Postgres/Redis; ADR-002)
      and add `docker/authelia/` with its static configuration: one
      registered OIDC client matching this feature's redirect URI, and the
      HMAC/JWK secrets Authelia's OIDC provider role requires. No
      production code depends on this task, but every live test in US1-US3
      does.

**Checkpoint**: Foundation ready — US1 can now be implemented.

---

## Phase 3: User Story 1 - Log in through an existing identity provider (Priority: P1) 🎯 MVP

**Goal**: An operator with OIDC configured can authenticate through their
identity provider and land on ComfyUI in a session identical, mechanism-wise,
to the credential-login session.

**Independent Test**: Configure OIDC against the real Authelia instance
(T008), authenticate through it, confirm the same `curu_auth` cookie session
results.

- [ ] T009-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the authorization-URL builder: given a resolved OIDC config,
      produces a redirect URL to the provider's authorization endpoint
      carrying `state`, `nonce`, and a PKCE `code_challenge`, and records
      the matching In-Flight Auth Request (data-model.md) keyed by `state`.
      References the feature file's "Initiate login redirects to the
      identity provider" scenario. **Fails now** — the builder doesn't
      exist yet.
- [ ] T010-I [US1] Implement the authorization-URL builder and In-Flight
      Auth Request store in `oidc.py` so T009-T passes
- [ ] T011-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for ID-token verification (via `joserfc`, against a mocked
      provider's JWKS and a hand-signed test token): a token with valid
      signature, matching `iss`/`aud`/`nonce`, and unexpired `exp` is
      accepted; wrong signature, wrong audience, wrong/missing nonce, and
      expired tokens are each rejected. **Fails now** — no verification
      function exists yet.
- [ ] T012-I [US1] Implement ID-token verification in `oidc.py` using
      `joserfc` so T011-T passes
- [ ] T013-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the callback handler against a mocked provider double
      (`aiohttp.test_utils`): a valid callback (matching `state`, valid
      token) calls the *existing* `SessionStore.issue()` and sets the
      *existing* `curu_auth` cookie with the *existing* attributes — not a
      new session mechanism (ADR-002/FR-003). References the feature
      file's "Successful provider login establishes a session" scenario.
      **Fails now** — no callback handler exists yet.
- [ ] T014-I [US1] Implement the token-exchange call (POST to the
      provider's token endpoint via `aiohttp`) and callback handler in
      `oidc.py` so T013-T passes
- [ ] T015-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`:
      a callback with a mismatched `state`, or one representing a
      cancelled/failed provider login, does NOT establish a session and
      surfaces an appropriate message. References the feature file's
      "Cancelled or failed provider login does not authenticate" scenario.
      **Fails now**.
- [ ] T016-I [US1] Implement the cancelled/failed/mismatched-state paths
      in the callback handler so T015-T passes
- [ ] T017-I [US1] Wire `oidc.py`'s routes into `__init__.py`: only
      registered when `resolve_oidc_config()` returns non-`None`, using
      T005-I's `public_paths` mechanism for the start/callback routes
      (ADR-003); add the OIDC login option to the login page template only
      when configured
- [ ] T018 [US1] Write a live `system`-marked test in
      `tests/system/test_oidc_harness.py`: drive the full authorization-
      code flow against the real Authelia instance (T008) end-to-end and
      confirm the resulting session cookie authenticates subsequent
      requests exactly like a credential-login session does. Requires a
      real (scripted or Authelia-test-mode) login at the provider — note
      in the task's own completion notes how this was actually driven
      (e.g. a direct POST to Authelia's own login endpoint with its
      Lite-bundle file-based test user, not a full browser).

**Checkpoint**: User Story 1 fully functional — an operator can log in
through a real identity provider and land in an authenticated session.

---

## Phase 4: User Story 2 - Default credential path is completely unaffected when OIDC isn't configured (Priority: P1)

**Goal**: Zero behavior change for every operator who never configures OIDC.

**Independent Test**: With no OIDC configuration, confirm the existing
hermetic suite (`tests/test_gate.py`) and the existing live suite
(`tests/system/test_docker_harness.py`) both still pass completely
unmodified, and that no OIDC routes exist.

- [ ] T019-T [US2] Write a FAILING hermetic test in `tests/test_oidc.py`:
      when `resolve_oidc_config()` returns `None`, `__init__.py`'s wiring
      registers no OIDC routes on the app and the login page renders with
      no OIDC option. References the feature file's "No OIDC routes or
      behavior when unconfigured" scenario. **Fails now** — `__init__.py`
      doesn't yet check this condition (T017-I only just made it possible
      to check).
- [ ] T020-I [US2] Confirm/adjust `__init__.py`'s conditional wiring (from
      T017-I) so T019-T passes — this task is largely verification that
      T017-I's design already satisfies US2, not new code
- [ ] T021 [US2] Run the full existing `tests/test_gate.py` (44 tests) and
      `tests/system/test_docker_harness.py` (5 tests) suites, unmodified,
      with OIDC left unconfigured throughout. Both MUST pass exactly as
      before this feature existed (FR-002/FR-004; references the feature
      file's "Existing credential and login form are unaffected" scenario)
      — this is the acceptance evidence, not a new test to write.
- [ ] T022-T [US2] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the partial-configuration edge case: e.g. an issuer URL and
      client ID present but no client secret MUST resolve to the same
      "unconfigured" state as no configuration at all (FR-009) — already
      partly covered by T006-T's own assertion; this task adds the
      specific edge-case regression the spec's Edge Cases section calls
      out. **Fails now** if not already covered.
- [ ] T023-I [US2] Adjust `resolve_oidc_config()` if T022-T reveals a gap;
      otherwise confirm it already passes

**Checkpoint**: User Stories 1 AND 2 both work — OIDC login works, and its
absence changes nothing.

---

## Phase 5: User Story 3 - Failed OIDC attempts are logged and rate-limited like every other path (Priority: P2)

**Goal**: An OIDC-path attacker gets the same treatment the credential and
login-form paths already give one.

**Independent Test**: Submit repeated failed OIDC callbacks (mismatched
state, invalid token) from the same client and confirm the same backoff
and logging behavior as the existing paths.

- [ ] T024-T [US3] Write a FAILING hermetic test in `tests/test_oidc.py`:
      a rejected OIDC callback (mismatched state, invalid/expired token,
      or provider error) calls the *existing* `RateLimiter.record_failure`
      for that client, and emits a log line via the *existing* stable,
      greppable format (`comfyui_curu_auth: authentication failure from
      %s (...)`) — not a new logging/rate-limit mechanism. References the
      feature file's "Failed OIDC attempts are logged like other paths"
      scenario. **Fails now**.
- [ ] T025-I [US3] Wire the existing `RateLimiter`/logger calls into the
      callback handler's failure paths so T024-T passes
- [ ] T026-T [US3] Write a FAILING live test in
      `tests/system/test_oidc_harness.py`, paced like spec 001's own
      T011/T012 (research.md's pacing decision, `gate.py`'s
      `RateLimiter.record_failure` is skipped while already blocked):
      repeated failed OIDC callbacks against the real Authelia harness
      trigger the same growing `Retry-After` backoff the credential path
      already exhibits. **Fails now**.
- [ ] T027-I [US3] Confirm T025-I's wiring makes T026-T pass against the
      real harness (likely no new code — this validates the hermetic
      T024-T/T025-I pairing holds true end-to-end, the same "validates
      pre-existing behavior" pattern spec 001's own T011/T012 hit)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T028 [P] Update README.md: document the four `COMFYUI_CURU_AUTH_OIDC_*`
      environment variables and link to `specs/002-oidc-login/quickstart.md`
- [ ] T029 Manually walk through `quickstart.md` end-to-end (configure,
      restart, log in via Authelia, confirm session) and correct any drift
- [ ] T030 One-time manual regression sanity check (mirrors spec 001's
      T013): temporarily break the ID-token verification (e.g. accept any
      signature), confirm T011-T-derived coverage and the live T018 test
      both fail loudly, then revert. Proves the suite isn't tautologically
      green on the security-critical path this feature adds.
- [ ] T031 [P] `beacon doctor --strict` clean before calling this
      feature's bullets done

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — no dependency on other
  stories
- **US2 (Phase 4)**: Depends on Foundational and on US1's `__init__.py`
  wiring existing (T017-I) to have something to verify is conditional
- **US3 (Phase 5)**: Depends on US1's callback handler existing (T014-I,
  T016-I) — there's no failure path to harden until the callback exists
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### Within Each User Story

- `-T` task written and confirmed FAILING before its paired `-I` task
- Story complete before moving to the next priority

---

## Parallel Example: Setup

```bash
# T002 and T003 are different, independent test-file stubs:
Task: "Create tests/test_oidc.py stub"
Task: "Create tests/system/test_oidc_harness.py stub"
```

---

## Implementation Strategy

### Suggested tracer-bullet split (2-4h each, per BEACON)

This spec is materially larger than 001-docker-comfyui-harness — a new
cryptographic dependency, a new module, a new Docker service, and three
user stories each needing hermetic *and* live coverage. Expect more
bullets, not fewer:

1. **Bullet 1**: Phase 1 (Setup) + T004-T005 (gate.py generalization) +
   T006-T007 (`resolve_oidc_config`) — pure Python, hermetic, no Docker.
2. **Bullet 2**: T008 (Authelia harness extension) — Docker-iteration-cost
   bullet, like spec 001's own US1 experience.
3. **Bullet 3 (MVP core, likely 2 sessions)**: T009-T012 (auth-URL
   building + PKCE/state/nonce + ID-token verification) — the
   security-critical heart of this feature; do not compress the `-T`/`-I`
   pairing to save time here of all places.
4. **Bullet 4**: T013-T017 (callback handler, session minting,
   `__init__.py` wiring) — completes US1 hermetically.
5. **Bullet 5**: T018 (US1 live test against real Authelia).
6. **Bullet 6**: Phase 4 (US2) — the unconfigured-path regression guard.
7. **Bullet 7**: Phase 5 (US3) — rate-limit/logging parity, hermetic +
   live.
8. **Bullet 8**: Phase 6 (Polish).

### MVP First

Complete Phases 1–3, then **STOP and VALIDATE**: run `quickstart.md`'s
manual login flow against the real Authelia instance and confirm all
three of US1's acceptance scenarios hold before starting US2.
