# Implementation Plan: An open tab goes to the login page when its session is lost

**Branch**: `005-session-loss-reload` | **Date**: 2026-11-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-session-loss-reload/spec.md`

## Summary

The gate marks each HTTP 401 and HTTP 429 of its middleware with the header `X-Curu-Auth: login-required`. The node ships one ES module, `web/session_loss.js`, through `WEB_DIRECTORY`. The module watches `fetch` answers and failed `/ws` handshakes, and sends the tab to the login page on a gate rejection. [ADR-009](../../project-management/ADRs/ADR-009-a-module-in-the-comfyui-page-acts-on-a-gate-rejection.md) records the decision. [research.md](research.md) gives each choice and the alternatives.

## Technical Context

**Language/Version**: Python 3.12 or later. JavaScript as an ES module that the ComfyUI frontend imports, with no build step.

**Primary Dependencies**: `aiohttp`, as today. No new runtime dependency. Playwright is already in the `live` group.

**Storage**: none on the server. The tab keeps one time value in `sessionStorage` (see [data-model.md](data-model.md)).

**Testing**:

- The default tier tests the mark with the aiohttp test client.
- A new `browser` tier (`tests/browser/`) runs the module in Chromium against the real middleware and a double of ComfyUI.
- One new test in the `system` tier restarts the real ComfyUI v0.27.0 of the docker harness.

**Target Platform**: a ComfyUI server that loads this node from `custom_nodes/`, and a current desktop browser.

**Project Type**: one Python package with no build step, plus one static JavaScript file.

**Performance Goals**: the tab shows the login page within 5 seconds after a session loss (SC-001).

**Constraints**:

- The static credential path does not change (FR-015).
- The status and the body of each rejection do not change (FR-007).
- The log line does not change (FR-014).
- An error in the module never breaks the ComfyUI page, and an error in the wiring never removes the gate (FR-012, FR-013).
- No token or part of a token goes into a log line or into the console.

**Scale/Scope**: one header in `gate.py`, one line in `__init__.py`, one JavaScript file of about 100 lines, and the tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Article | Check | Result |
|---|---|---|
| I. Minimal Attack Surface | No new runtime dependency and no new route. The probe uses the URL of the module, which is already a gated route. The static credential path does not change. | Pass |
| II. Total Route Coverage | The middleware covers `/extensions/<node folder>/session_loss.js` like each other route. A `system` test sends an unauthenticated request to it and expects HTTP 401. | Pass |
| III. Zero-Config by Default | The feature works with no new setting. `WEB_DIRECTORY` is a constant string, so `__init__.py` cannot raise because of it. If ComfyUI cannot load the module, the gate stays on, and the tab behaves as today. | Pass |
| IV. Test-First | A failing test comes before the header in `gate.py` and before each behaviour of the module. Each test is committed alone, before its code. | Pass |
| V. Simplicity | One header, one file, no build step and no Node toolchain. The module wraps two global objects and does not depend on internals of the ComfyUI frontend. | Pass |
| Security Requirements | The log line of each rejection does not change, so `contrib/` needs no change. The header value is a fixed string with no secret. The cookie attributes do not change. | Pass |
| Documentation for people and for agents | A user can see the behaviour. So the same pull request changes the sections "Log in from a browser" and "Technical notes" of `README.md`. `AGENTS.md` gets the `browser` tier command and the `web/` folder. `CHANGELOG.md` gets an entry under "Unreleased". | Pass |

**Re-check after Phase 1**: the contracts and the data model add no route, no dependency and no setting. All articles still pass.

## Project Structure

### Documentation (this feature)

```text
specs/005-session-loss-reload/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1 to R7
├── data-model.md        # Phase 1: the mark and the tab state
├── quickstart.md        # Phase 1: how to prove the feature
├── contracts/
│   ├── gate-rejection.md  # Rules G1 to G9 for the header
│   └── tab-module.md      # Rules T1 to T12 for the module
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not this command)
```

### Source Code (repository root)

```text
gate.py                         # Add the header to the 401 and the 429 of the middleware
__init__.py                     # WEB_DIRECTORY = "./web"
web/
└── session_loss.js             # NEW: the module in the tab
tests/
├── test_gate.py                # The rules G1 to G9
├── browser/                    # NEW tier, marker `browser`
│   ├── conftest.py             # The real middleware, a double of ComfyUI, Chromium
│   └── test_session_loss.py    # The rules T1 to T11
└── system/
    └── test_session_loss.py    # NEW: rule T12, and the gate covers the module URL
pyproject.toml                  # Register the `browser` marker; exclude it by default
README.md                       # "Log in from a browser" and "Technical notes"
AGENTS.md                       # The `browser` tier command; `web/` in "Where things are"
CHANGELOG.md                    # Entry under "Unreleased"
```

**Structure Decision**: The repository stays one flat package at the root. The new `web/` folder holds the one file that ComfyUI serves to the page. The new `tests/browser/` tier follows the pattern of `tests/live/`. It uses a real gate on a free port, a double of ComfyUI, and Chromium.

## Complexity Tracking

No article is violated, so this table is empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
