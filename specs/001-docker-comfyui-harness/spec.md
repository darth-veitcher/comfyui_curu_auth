# Feature Specification: Docker ComfyUI Integration Harness

**Feature Branch**: `001-docker-comfyui-harness`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "CPU-only Docker integration harness for ComfyUI with comfyui_curu_auth installed from the local working tree"

**Epic**: [local-test-harness](../../project-management/Roadmap/epics/local-test-harness.md)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Boot a real, gated ComfyUI instance locally (Priority: P1)

A developer working on this repo brings up a local, disposable ComfyUI
process — CPU-only, no GPU — with the current working tree's version of
comfyui_curu_auth installed into it, so they can see the gate enforced by a
real ComfyUI server instead of the mocked `aiohttp` app the existing
hermetic tests use.

**Why this priority**: Everything else in this spec depends on a real
ComfyUI instance existing and enforcing the gate. Without this, there is
nothing to test against.

**Independent Test**: Bring the harness up and confirm, by hand, that an
unauthenticated request to it returns 401 and the fixed test credential
succeeds. Delivers value on its own — a developer can already do the
manual verification the README describes today, just without reinstalling
into a real ComfyUI checkout each time.

**Acceptance Scenarios**:

1. **Given** Docker is available and the repo is checked out, **When** the
   developer brings the harness up, **Then** a local ComfyUI instance
   becomes reachable on a known port and reports healthy once it is up and
   enforcing the gate (not merely "process started").
2. **Given** the harness is healthy, **When** an unauthenticated request is
   made to it, **Then** the request is rejected (401), proving the gate
   from the current working tree is active — not a previously-published
   version.
3. **Given** the harness is healthy, **When** a request is made with the
   fixed, known test credential, **Then** the request succeeds.

---

### User Story 2 - Automated integration suite proves the gate against a live server (Priority: P1)

A developer runs a test command that exercises the live harness end to
end — unauthenticated access is rejected across representative routes
including the websocket handshake, the correct credential works, and
repeated wrong credentials trigger backoff — and gets a pass/fail result
without manually poking at the running instance.

**Why this priority**: This is the actual deliverable that closes the gap
the README already names: `__init__.py`'s real ComfyUI-side wiring has no
automated test today. User Story 1 makes the manual check possible; this
story makes it repeatable and automatic.

**Independent Test**: Run the integration test command against a harness
already brought up by User Story 1, and confirm it exits non-zero when the
gate is broken (e.g., temporarily bypass the middleware) and zero when it
isn't.

**Acceptance Scenarios**:

1. **Given** the harness is healthy, **When** the integration suite runs,
   **Then** it verifies unauthenticated requests are rejected on
   representative HTTP routes and on the websocket handshake specifically.
2. **Given** the harness is healthy, **When** the integration suite
   authenticates with the fixed test credential, **Then** those same routes
   succeed.
3. **Given** the harness is healthy, **When** the integration suite submits
   repeated wrong credentials, **Then** it observes increasing backoff
   consistent with the gate's documented rate-limiting behavior.
4. **Given** the gate's middleware is not actually wired up (simulated
   regression), **When** the integration suite runs, **Then** it fails
   loudly rather than passing silently.

---

### User Story 3 - Teardown and restart leave no stale state (Priority: P2)

A developer tears the harness down and brings it back up and gets an
instance that behaves identically to a first run — no leftover sessions,
no carried-over rate-limit counters — so the harness stays trustworthy
across many dev-loop iterations in a single day.

**Why this priority**: Lower priority than the first two — the harness is
still useful for a single session without this — but state leaking across
restarts would silently erode trust in every result from User Story 2 over
time.

**Independent Test**: Bring the harness up, trigger rate-limit backoff
against it, tear it down, bring it up again, and confirm the fresh instance
is not still rate-limited and issues a fresh session on first login.

**Acceptance Scenarios**:

1. **Given** the harness was previously brought up, torn down, and is being
   brought up again, **When** the developer checks its state, **Then** it
   behaves identically to a first-ever run (no stale rate-limit counters,
   no stale sessions).

---

### Edge Cases

- What happens if Docker isn't running, or the harness's port is already in
  use on the host? The harness MUST fail with a clear, actionable message —
  not hang silently waiting for a health check that will never pass.
- What happens if the working tree has uncommitted changes to the gate's
  code when the harness is built? Those changes MUST be what gets exercised
  — the entire point of this harness over curu's own (which installs a
  published release) is testing pre-push, in-progress changes.
- What happens if the integration suite runs before the harness reports
  healthy? It MUST wait for the health signal rather than racing against
  ComfyUI's startup time.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The harness MUST bring up a real ComfyUI server process,
  CPU-only, with no GPU device requirement, reachable on a fixed local
  port.
- **FR-002**: The harness MUST install comfyui_curu_auth from the current
  local working tree — not a pinned or published release — so in-progress,
  uncommitted changes are what gets exercised.
- **FR-003**: The harness MUST configure a fixed, known test credential
  (never a freshly randomized one) so the integration suite can
  authenticate deterministically, scoped to this local, disposable context
  only.
- **FR-004**: The harness MUST expose a health signal that distinguishes
  "ComfyUI is up and the gate is actively enforcing" from "ComfyUI failed
  to start" or "gate isn't wired up" — a plain process-running check is not
  sufficient.
- **FR-005**: An integration test suite MUST verify, against the live
  harness: unauthenticated requests are rejected on representative HTTP
  routes and on the websocket handshake; the fixed credential succeeds on
  those same routes; repeated wrong credentials trigger increasing backoff.
- **FR-006**: The integration test suite MUST run as an explicitly separate,
  opt-in command from the project's existing hermetic suite
  (`uv run pytest`) — it MUST NOT run as part of that command's default
  invocation.
- **FR-007**: Tearing the harness down and bringing it back up MUST leave
  no state (sessions, rate-limit counters) that changes the behavior of the
  fresh instance relative to a first-ever run.
- **FR-008**: The harness MUST NOT require a GPU, a model checkpoint, or
  exercise workflow execution/image rendering — it proves the auth gate
  only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean checkout with the container image already built,
  a developer reaches a healthy, gate-enforcing local ComfyUI instance in
  under 1 minute.
- **SC-002**: Every route the integration suite checks — including the
  websocket handshake — correctly rejects unauthenticated access on every
  run; zero tolerance for a route silently passing through ungated.
- **SC-003**: A developer can go from "I changed the gate's code" to "I
  have a pass/fail signal from a real ComfyUI process" using only commands
  documented in this repo — no manual install-and-eyeball step required.
- **SC-004**: Across 10 consecutive teardown/restart cycles, zero failures
  are attributable to state left over from a prior cycle.

## Non-Goals

*(Carried from the parent epic — see
[local-test-harness.md](../../project-management/Roadmap/epics/local-test-harness.md#non-goals).)*

- Does not execute any ComfyUI workflow or exercise rendering/inference —
  no GPU, no checkpoint; this harness proves the auth gate only.
- Does not replace `tests/test_gate.py`'s existing hermetic suite — this is
  an additive, opt-in integration layer, never a required part of
  `uv run pytest`.
- Not a CI requirement yet — a local dev-loop tool first; CI wiring is a
  possible future spec, not part of this one.

## Assumptions

- Docker (or a compatible OCI container engine) is available on the
  developer's machine; the harness is not required to work without
  container support.
- A pinned upstream ComfyUI version is acceptable for reproducibility,
  updated manually over time rather than always tracking `master`.
- The fixed test credential this harness configures is never meaningful
  outside this local, disposable context — mirrors the same, already-
  documented rationale in `~/repos/JAMESVEITCH/curu`'s own equivalent
  harness.
- Building the harness image for the first time (cloning ComfyUI, CPU
  torch install) is a one-time, multi-minute cost distinct from SC-001,
  which measures repeat use once the image already exists.
