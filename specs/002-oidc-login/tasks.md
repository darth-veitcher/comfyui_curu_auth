---
description: "Task list for 002-oidc-login"
---

# Tasks: OIDC/OAuth Login Path

**Input**: Design documents from `/specs/002-oidc-login/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md,
features/oidc_login.feature

**Revised (2026-07-23)** after adversarial engineering review — see each
task's own note for what changed. Net additions: a throwaway spike ahead of
the Authelia service task, a discovery-fetch pair, a strengthened PKCE
assertion, a replay-rejection pair, a start-route rate-limit/cap pair, a
`_client_key` promotion task, and a split + positive-assertion fix for the
callback/wiring/template slice.

**Tests**: First-class, not optional — this spec carries acceptance scenarios
and success criteria (BEACON test-first discipline). `-T`/`-I` suffix pairs:
the `-T` task is committed alone (failing) before its `-I` partner makes it
pass. This spec's security-critical logic (token verification, state/nonce/
PKCE, replay rejection, the public-paths carve-out) is exactly what
Constitution Principle IV exists for — no exceptions to the pairing here.

**Organization**: Grouped by user story (spec.md priorities P1/P1/P2).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

Single project — `oidc.py` (new), `gate.py` (two changes), `__init__.py`
(wiring), `docker-compose.yml` + `docker/authelia/` (new service),
`tests/test_oidc.py` (new hermetic), `tests/system/test_oidc_harness.py`
(new live) per `plan.md`'s Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Add `joserfc` to `dependencies` in `pyproject.toml` (research.md —
      the one new dependency this spec adds, scoped to ID-token JWK/JWT
      verification only)
- [x] T002 [P] Create `tests/test_oidc.py` stub (hermetic suite, mirrors
      `tests/test_gate.py`'s existing structure and conventions)
- [x] T003 [P] Create `tests/system/test_oidc_harness.py` stub (`system`-
      marked, mirrors `tests/system/test_docker_harness.py`'s conventions)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete —
US1 registers new routes and reuses `client_key` through this phase's
changes; US2 verifies nothing changes when they aren't used.

- [x] T004-T Write a FAILING test in `tests/test_oidc.py` asserting
      `build_gate_middleware` accepts a `public_paths` iterable and lets
      *every* path in it through unauthenticated (not just a single
      `LOGIN_PATH` string) — the ADR-003 generalization. **Fails now** —
      `build_gate_middleware`'s signature has no such parameter yet.
- [x] T005-I Generalize `gate.py`'s `LOGIN_PATH` check into a `public_paths`
      parameter (defaulting to `{LOGIN_PATH}` — byte-for-byte today's
      behavior when no extra paths are supplied) so T004-T passes. Run the
      full existing `tests/test_gate.py` suite (44 tests) unmodified
      immediately after this change — every one MUST still pass; this *is*
      the regression guard for FR-004 (default Bearer-header path
      untouched).
- [x] T006 Promote `gate._client_key` to a public `client_key` export (add
      to `__all__`); no behavior change. **Added after adversarial
      engineering review** — `oidc.py`'s US3 work needs the identical
      client-identity function `RateLimiter`/logging already key on, and a
      second real consumer means the leading underscore no longer
      describes reality (research.md). Confirm the existing 44 hermetic
      tests still pass unchanged.
- [x] T007-T Write a FAILING test in `tests/test_oidc.py` for
      `resolve_oidc_config()`: returns a populated config object when all
      four environment variables (issuer URL, client ID, client secret,
      redirect URI) are present, and `None` when any subset is missing —
      including the partial-configuration edge case (FR-009). **Fails
      now** — `oidc.py` doesn't exist yet.
- [x] T008-I Implement `oidc.py`'s `resolve_oidc_config()` so T007-T passes
- [x] T009 **SPIKE (throwaway — not production code)**. **Added after
      adversarial engineering review**, which flagged this as an
      unvalidated unknown, not a detail to assume away: bring up Authelia
      (Lite bundle) alone and prove, end to end, that
      `POST /api/firstfactor` (test user's credentials) followed by a
      `GET` of the authorization URL completes without a browser and
      without stalling on a consent screen — requires `consent_mode:
      implicit` (or equivalent pre-authorization) on the registered
      client. Also pin down and record the issuer-URL reconciliation
      (research.md): `http://authelia:9091` for the gate's own
      backend-channel calls vs `http://localhost:9091` for this spike's
      (and later T028's) host-side test client, vs
      `http://localhost:8188/curu-auth/oidc/callback` as the registered
      `redirect_uri`. **If this spike fails** (headless login proves
      infeasible against Authelia as configured), fall back to driving
      the live test with Playwright directly in this spec's own
      `tests/system/test_oidc_harness.py` — added as a dev dependency
      scoped to that one test file — rather than stopping to reconsider
      `browser-e2e` (user direction, 2026-07-23: "use Playwright if
      needed"). This does not change `browser-e2e`'s own scope or
      justification — WebAuthn ceremonies still need a real browser's
      credential-management APIs, which is a different requirement than
      "Authelia's login portal happens to be a React SPA." Findings
      either way become T010's acceptance notes.
      **Done (2026-07-23): SPIKE SUCCEEDED, no Playwright needed.** Ran
      the full sequence against a standalone Authelia v4.39.20 container:
      `POST /api/firstfactor` → 200 + session cookie;
      `GET /api/oidc/authorization` with that cookie → 303 straight to
      `redirect_uri` with `code`/`state`, no consent screen;
      `POST /api/oidc/token` → 200 with `access_token`/`id_token`; decoded
      `id_token` claims (`iss`/`aud`/`nonce`) all matched. Two findings
      feed T010, both recorded in research.md: (1) HTTPS is mandatory for
      Authelia, confirmed live — the harness will trust a fixed,
      repo-committed self-signed CA at the OS level, not a TLS-bypass flag
      in production code; (2) mount Authelia's config as a directory, not
      individual files (a Docker Desktop bind-mount gotcha hit during the
      spike). Spike container and all throwaway files cleaned up
      afterward — nothing from this task persists except these notes.
- [x] T010 Extend `docker-compose.yml` with an `authelia` service (Lite
      bundle — file-based user, SQLite storage, no Postgres/Redis;
      ADR-002) and add `docker/authelia/` with its static configuration: a
      registered confidential OIDC client (matching this feature's
      `redirect_uri` and hand-rolled token exchange's
      `token_endpoint_auth_method`), a file-based test user, HMAC/JWK
      secrets, and the `consent_mode`/issuer settings T009's spike
      validated. **Budget as its own bullet (2 sessions), not folded into
      Bullet 1** — adversarial engineering review flagged this as
      repeating spec 001's Docker-iteration-cost underestimate if sized as
      one.
      **Done (2026-07-24)**: pinned `authelia/authelia:4.39.20` (the
      spike-validated version); `docker/authelia/{configuration.yml,
      users_database.yml,ca.crt,ca.key,server.crt,server.key}` committed
      (fixed, deterministic secrets, meaningless outside this harness —
      same precedent as `COMFYUI_CURU_AUTH_TOKEN`). `docker/comfyui/
      Dockerfile` now trusts the committed CA at the OS level (not a
      TLS-bypass in `oidc.py`) and installs `joserfc`. `docker-compose.yml`
      gives `authelia` a second network alias, `authelia.internal`
      (Authelia's own cookie-domain validation rejects a bare `authelia`).
      comfyui's four `COMFYUI_CURU_AUTH_OIDC_*` env vars default to empty
      (unconfigured) via `${VAR:-}` substitution, so every existing test
      and US2's own tests keep working against this same compose file
      unmodified. Validated the **entire** authorization-code flow
      end-to-end against this real config (not just the T009 spike's
      simplified one) — firstfactor → authorization → token exchange,
      correct `iss`/`aud`/`nonce` — surfacing one more real finding:
      `aiohttp`'s cookie jar matches against the actual request URL, not
      a spoofed `Host` header, so the session cookie must be extracted
      and passed explicitly (research.md). Also fixed a pre-existing
      spec-001 test (`test_second_up_without_down_is_not_destructive`)
      that hardcoded "exactly one container" — now checks for no
      duplicates, since there are legitimately two services now. All 5
      existing system tests + 51 hermetic tests pass together.

**Checkpoint**: Foundation ready — US1 can now be implemented.

---

## Phase 3: User Story 1 - Log in through an existing identity provider (Priority: P1) 🎯 MVP

**Goal**: An operator with OIDC configured can authenticate through their
identity provider and land on ComfyUI in a session identical, mechanism-wise,
to the credential-login session.

**Independent Test**: Configure OIDC against the real Authelia instance
(T010), authenticate through it (per T009's proven headless sequence),
confirm the same `curu_auth` cookie session results.

- [x] T011-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the discovery-document fetch: given a resolved OIDC config,
      fetches `{issuer_url}/.well-known/openid-configuration` via
      `aiohttp` with a bounded `ClientTimeout`, and treats any fetch
      failure (timeout, connection error, malformed JSON) as a hard
      failure of the attempt — no cached fallback (research.md). **Added
      after adversarial engineering review** — this task had no home
      before; it's required for the "identity provider is unreachable or
      times out" Edge Case. **Fails now** — the fetch function doesn't
      exist yet.
- [x] T012-I [US1] Implement the discovery-document fetch in `oidc.py` so
      T011-T passes
- [x] T013-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the authorization-URL builder: given a resolved OIDC config,
      produces a redirect URL to the provider's authorization endpoint
      carrying `state`, `nonce`, and a PKCE `code_challenge`, and records
      the matching In-Flight Auth Request (data-model.md) keyed by
      `state`. **Strengthened after adversarial engineering review**:
      assert the `code_challenge` actually equals
      `base64url(sha256(code_verifier))` — not merely that a challenge is
      present — since a wrong derivation would otherwise only surface at
      live token exchange. References the feature file's "Initiate login
      redirects to the identity provider" scenario. **Fails now** — the
      builder doesn't exist yet.
- [x] T014-I [US1] Implement the authorization-URL builder and In-Flight
      Auth Request store in `oidc.py` so T013-T passes
- [x] T015-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for ID-token verification (via `joserfc`, against a mocked
      provider's JWKS and a hand-signed test token): a token with valid
      signature, matching `iss`/`aud`/`nonce`, and unexpired `exp` is
      accepted; wrong signature, wrong audience, wrong/missing nonce, and
      expired tokens are each rejected. **Fails now** — no verification
      function exists yet.
- [x] T016-I [US1] Implement ID-token verification in `oidc.py` using
      `joserfc`, fetching JWKS fresh on every call (no cache —
      research.md), so T015-T passes
- [x] T017-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the callback handler against a mocked provider double
      (`aiohttp.test_utils`): a valid callback (matching `state`, valid
      token) calls the *existing* `SessionStore.issue()` and sets the
      *existing* `curu_auth` cookie with the *existing* attributes — not a
      new session mechanism (ADR-002/FR-003). References the feature
      file's "Successful provider login establishes a session" scenario.
      **Fails now** — no callback handler exists yet.
- [x] T018-I [US1] Implement the token-exchange call (POST to the
      provider's token endpoint via `aiohttp`) and callback handler in
      `oidc.py` so T017-T passes
- [x] T019-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`:
      a callback with a mismatched `state`, or one representing a
      cancelled/failed provider login, does NOT establish a session and
      surfaces an appropriate message. References the feature file's
      "Cancelled or failed provider login does not authenticate" scenario.
      **Fails now**.
- [x] T020-I [US1] Implement the cancelled/failed/mismatched-state paths
      in the callback handler so T019-T passes
- [x] T021-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`:
      submitting a verbatim replay of a *previously-completed* (already
      succeeded) state/code pair a second time is rejected, not accepted
      again — the In-Flight Auth Request entry is consumed (deleted) on
      first use, whether that use succeeded or failed (FR-011).
      **Added after adversarial engineering review** — closes the actual
      Edge Case the spec names; previously only mismatched-state and
      replayed-nonce were covered, not a verbatim replay of a *successful*
      attempt. References the feature file's "A completed authorization
      attempt cannot be replayed" scenario. **Fails now**.
- [x] T022-I [US1] Ensure the callback handler deletes the In-Flight Auth
      Request entry on every path (success and failure) before it
      returns, so T021-T passes
- [x] T023-I [US1] Wire `oidc.py`'s routes into `__init__.py`: only
      registered when `resolve_oidc_config()` returns non-`None`, using
      T005-I's `public_paths` mechanism for the start/callback routes
      (ADR-003). **Split from the template change below** — adversarial
      engineering review found the original single task bundled route
      wiring with a login-page template change with asymmetric test
      coverage; kept as separate, focused tasks here.
- [x] T024-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`:
      the rendered login page includes the OIDC login option when
      `resolve_oidc_config()` returns non-`None`. **Added after
      adversarial engineering review** — the original task only tested
      the option's *absence* when unconfigured (now T031-T in US2); this
      is the missing positive counterpart. **Fails now**.
- [x] T025-I [US1] Add the OIDC login option to `_LOGIN_PAGE_TEMPLATE`
      (or an equivalent conditional render) so T024-T passes
- [x] T026-T [US1] Write a FAILING hermetic test in `tests/test_oidc.py`:
      the OIDC start route, hit repeatedly by the same client identity,
      is subject to the *existing* shared `RateLimiter` exactly like the
      login form and Bearer-header paths, and the In-Flight Auth Request
      store's size is capped (oldest entries evicted first) independent
      of rate-limiting (FR-010). **Added after adversarial engineering
      review** — the start route sitting in the public-paths bypass was
      previously unauthenticated *and* unthrottled, an unbounded
      resource-exhaustion path. References the feature file's "The
      login-initiation route is rate-limited and bounded" scenario.
      **Fails now**.
- [x] T027-I [US1] Wire the shared `RateLimiter` onto the start route and
      add the In-Flight store's size cap so T026-T passes
- [x] T028 [US1] Write a live `system`-marked test in
      `tests/system/test_oidc_harness.py`: drive the full authorization-
      code flow against the real Authelia instance (T010) end-to-end,
      using T009's spike-proven headless sequence
      (`POST /api/firstfactor` → authorization-URL `GET`), and confirm
      the resulting session cookie authenticates subsequent requests
      exactly like a credential-login session does.

**Checkpoint**: User Story 1 fully functional — an operator can log in
through a real identity provider and land in an authenticated session, with
the start route protected and replay rejected.

---

## Phase 4: User Story 2 - Default credential path is completely unaffected when OIDC isn't configured (Priority: P1)

**Goal**: Zero behavior change for every operator who never configures OIDC.

**Independent Test**: With no OIDC configuration, confirm the existing
hermetic suite (`tests/test_gate.py`) and the existing live suite
(`tests/system/test_docker_harness.py`) both still pass completely
unmodified, and that no OIDC routes exist.

- [ ] T029-T [US2] Write a FAILING hermetic test in `tests/test_oidc.py`:
      when `resolve_oidc_config()` returns `None`, `__init__.py`'s wiring
      registers no OIDC routes on the app. References the feature file's
      "No OIDC routes or behavior when unconfigured" scenario. **Fails
      now** — `__init__.py` doesn't yet check this condition (T023-I only
      just made it possible to check).
- [ ] T030-I [US2] Confirm/adjust `__init__.py`'s conditional wiring (from
      T023-I) so T029-T passes — this task is largely verification that
      T023-I's design already satisfies US2, not new code
- [ ] T031-T [US2] Write a FAILING hermetic test in `tests/test_oidc.py`:
      the rendered login page does NOT include the OIDC login option when
      `resolve_oidc_config()` returns `None`. **Fails now** until T025-I's
      conditional render is confirmed to also handle the negative case
      correctly.
- [ ] T032-I [US2] Confirm/adjust the template conditional so T031-T passes
- [ ] T033 [US2] Run the full existing `tests/test_gate.py` (44 tests) and
      `tests/system/test_docker_harness.py` (5 tests) suites, unmodified,
      with OIDC left unconfigured throughout. Both MUST pass exactly as
      before this feature existed (FR-002/FR-004; references the feature
      file's "Existing credential and login form are unaffected" scenario)
      — this is the acceptance evidence, not a new test to write.
- [ ] T034-T [US2] Write a FAILING hermetic test in `tests/test_oidc.py`
      for the partial-configuration edge case: e.g. an issuer URL and
      client ID present but no client secret MUST resolve to the same
      "unconfigured" state as no configuration at all (FR-009) — already
      partly covered by T007-T's own assertion; this task adds the
      specific edge-case regression the spec's Edge Cases section calls
      out. **Fails now** if not already covered.
- [ ] T035-I [US2] Adjust `resolve_oidc_config()` if T034-T reveals a gap;
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

- [ ] T036-T [US3] Write a FAILING hermetic test in `tests/test_oidc.py`:
      a rejected OIDC callback (mismatched state, invalid/expired token,
      or provider error) calls the *existing* `RateLimiter.record_failure`
      for that client (via T006's now-public `client_key`) and emits a log
      line via the *existing* stable, greppable format (`comfyui_curu_auth:
      authentication failure from %s (...)`) — not a new logging/rate-limit
      mechanism. References the feature file's "Failed OIDC attempts are
      logged like other paths" scenario. **Fails now**.
- [ ] T037-I [US3] Wire the existing `RateLimiter`/logger calls into the
      callback handler's failure paths so T036-T passes
- [ ] T038-T [US3] Write a FAILING live test in
      `tests/system/test_oidc_harness.py`, paced like spec 001's own
      T011/T012 (research.md's pacing decision, `gate.py`'s
      `RateLimiter.record_failure` is skipped while already blocked):
      repeated failed OIDC callbacks against the real Authelia harness
      trigger the same growing `Retry-After` backoff the credential path
      already exhibits. **Fails now**.
- [ ] T039-I [US3] Confirm T037-I's wiring makes T038-T pass against the
      real harness (likely no new code — this validates the hermetic
      T036-T/T037-I pairing holds true end-to-end, the same "validates
      pre-existing behavior" pattern spec 001's own T011/T012 hit)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T040 [P] Update README.md: document the four `COMFYUI_CURU_AUTH_OIDC_*`
      environment variables and link to `specs/002-oidc-login/quickstart.md`
- [ ] T041 Manually walk through `quickstart.md` end-to-end (configure,
      restart, log in via Authelia, confirm session) and correct any drift
- [ ] T042 One-time manual regression sanity check (mirrors spec 001's
      T013): temporarily break the ID-token verification (e.g. accept any
      signature), confirm T015-T's hermetic coverage and the live T028
      test both fail loudly, then revert. Proves the suite isn't
      tautologically green on the security-critical path this feature
      adds.
- [ ] T043 [P] `beacon doctor --strict` clean before calling this
      feature's bullets done

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories.
  T009's spike specifically blocks T010; if it fails, stop and reassess
  before continuing.
- **US1 (Phase 3)**: Depends on Foundational — no dependency on other
  stories
- **US2 (Phase 4)**: Depends on Foundational and on US1's `__init__.py`
  wiring and template conditional existing (T023-I, T025-I) to have
  something to verify is conditional
- **US3 (Phase 5)**: Depends on US1's callback handler existing (T018-I,
  T020-I) — there's no failure path to harden until the callback exists
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

Revised after adversarial engineering review (2026-07-23): this spec is
materially larger than 001-docker-comfyui-harness even before the
review's additions — a new cryptographic dependency, a new module, a new
Docker service, and three user stories each needing hermetic *and* live
coverage. The review's findings add a spike and several new pairs;
budget more bullets, not fewer.

1. **Bullet 1**: Phase 1 (Setup) + T004-T008 (gate.py public-paths
   generalization, `client_key` promotion, `resolve_oidc_config`) — pure
   Python, hermetic, no Docker.
2. **Bullet 2a**: T009 — the throwaway Authelia spike. Do not skip this
   to save time; it exists specifically to de-risk Bullets 2b and 5
   before any production code depends on its assumptions.
3. **Bullet 2b**: T010 (Authelia harness extension, informed by the
   spike) — Docker-iteration-cost bullet, budgeted at 2 sessions like
   spec 001's own US1 experience.
4. **Bullet 3 (crypto core, likely 2 sessions)**: T011-T016 (discovery
   fetch + PKCE/state/nonce + ID-token verification) — the
   security-critical heart of this feature; do not compress the `-T`/`-I`
   pairing to save time here of all places.
5. **Bullet 4**: T017-T022 (callback handler, session minting, replay
   rejection) — completes the callback logic hermetically.
6. **Bullet 5**: T023-T027 (`__init__.py` wiring, login-page template
   both directions, start-route rate-limit + store cap) — the routing/
   exposure slice, kept separate from Bullet 4's callback logic.
7. **Bullet 6**: T028 (US1 live test against real Authelia, using the
   Bullet 2a spike's proven sequence).
8. **Bullet 7**: Phase 4 (US2) — the unconfigured-path regression guard.
9. **Bullet 8**: Phase 5 (US3) — rate-limit/logging parity, hermetic +
   live.
10. **Bullet 9**: Phase 6 (Polish).

### MVP First

Complete Phases 1–3, then **STOP and VALIDATE**: run `quickstart.md`'s
manual login flow against the real Authelia instance and confirm all
three of US1's acceptance scenarios hold before starting US2.
