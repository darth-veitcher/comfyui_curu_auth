# Implementation Plan: The Bearer path accepts OIDC access tokens

**Branch**: `004-oidc-access-tokens` | **Date**: 2026-11-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-oidc-access-tokens/spec.md`

## Summary

Add an opt-in resource-server mode. [ADR-008](../../project-management/ADRs/ADR-008-oidc-access-tokens-on-the-bearer-path.md) gives the settings, the checks and the rate-limit rule. `oidc.py` gets a key cache and a token check that use the functions of spec 003. `gate.py` gets one optional parameter, a token check, and does not import `oidc.py`.

## Technical Context

**Language/Version**: Python 3.12 or later.

**Primary Dependencies**: `aiohttp` and `joserfc`, as today. No new runtime dependency.

**Storage**: none. The key cache is in memory.

**Testing**: the default tier uses the fake issuer of spec 003. The `rauthy` tier gets a `client_credentials` client and sets `allowed_resources` with the admin API.

**Target Platform**: a ComfyUI server that loads this node from `custom_nodes/`.

**Project Type**: one Python package with no build step.

**Constraints**:

- The static credential path does not change (FR-004 of spec 002).
- A setup error never removes the gate.
- No token or part of a token goes into a log line.

## Constitution Check

| Principle | Assessment |
|---|---|
| I. Minimal Attack Surface | PASS. No new runtime dependency. The mode is off by default, and the static credential stays the default. |
| II. Total Route Coverage | PASS. The same middleware checks the token on each route, also the `/ws` handshake. A test covers `/ws`. |
| III. Zero-Config by Default | PASS. With no audience, nothing changes. A partial setup keeps the gate on. |
| IV. Test-First for Security-Critical Logic | PASS. Each check has a failing test in its own commit before the code. |
| V. Simplicity | PASS. The gate gets one function. The key cache is one small class, because it must hold state. |

## Project Structure

### Documentation (this feature)

```text
specs/004-oidc-access-tokens/
├── spec.md
├── plan.md
├── research.md
├── tasks.md
└── features/oidc_access_tokens.feature
```

### Source Code (repository root)

```text
oidc.py                              # IssuerKeys, verify_access_token, the settings
gate.py                              # build_gate_middleware(token_check=...)
__init__.py                          # reads the settings; logs a start error
docker-compose.yml                   # passes the settings to ComfyUI
tests/test_oidc_access_tokens.py     # the hermetic tests of this spec
tests/live/conftest.py               # a client_credentials client in rauthy
tests/live/test_rauthy_access_token.py
docs/oidc-providers.md               # a section for programs, for each provider
```

**Structure Decision**: the token check stays in `oidc.py`, next to the issuer and key code that it uses. `gate.py` gets the check as a function, so it stays free of `joserfc`.

## Complexity Tracking

Not applicable. The plan has no violation of the constitution.
