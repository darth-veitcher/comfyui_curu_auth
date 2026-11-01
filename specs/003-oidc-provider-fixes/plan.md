# Implementation Plan: The OIDC login works with rauthy, Authentik and other providers

**Branch**: `003-oidc-provider-fixes` | **Date**: 2026-11-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-oidc-provider-fixes/spec.md`

## Summary

Fix the issuer rule, the algorithm rule and the claim rules of the OIDC login in `oidc.py`. Add an allowlist that fails closed, and a scopes setting. [ADR-007](../../project-management/ADRs/ADR-007-oidc-issuer-algorithms-and-allowlist.md) records the rules and the settings names. Spec 004 reuses the issuer code and the key code, so these are plain functions with no login state.

## Technical Context

**Language/Version**: Python 3.12 or later.

**Primary Dependencies**: `aiohttp` and `joserfc`, as today. No new runtime dependency.

**Storage**: none. The allowlist is configuration in memory.

**Testing**: `pytest` with three tiers.

- The hermetic tier uses a fake issuer in `tests/support/fake_issuer.py`, with local RSA, EC and Ed25519 keys.
- The new `rauthy` tier starts `ghcr.io/sebadob/rauthy:0.37.2` in Docker and drives a browser with Playwright.
- The `system` tier of spec 002 keeps its Authelia test.

**Target Platform**: a ComfyUI server that loads this node from `custom_nodes/`.

**Project Type**: one Python package with no build step.

**Constraints**:

- The static credential path does not change.
- A setup error never removes the gate.
- No token or part of a token goes into a log line.

## Constitution Check

| Principle | Assessment |
|---|---|
| I. Minimal Attack Surface | PASS. No new runtime dependency. Playwright is in the `live` dependency group, for the `rauthy` tier only. |
| II. Total Route Coverage | PASS. No new route. The OIDC routes stay in the public paths only when the login is on. |
| III. Zero-Config by Default | PASS. A setup with no allowlist keeps the credential gate on, and only the OIDC login stays off. |
| IV. Test-First for Security-Critical Logic | PASS. Each rule has a failing test in its own commit before the code. |
| V. Simplicity | PASS. The rules are functions. The allowlist is one frozen dataclass with one method. |

## Project Structure

### Documentation (this feature)

```text
specs/003-oidc-provider-fixes/
├── spec.md
├── plan.md
├── research.md
├── tasks.md
└── features/oidc_provider_fixes.feature
```

### Source Code (repository root)

```text
oidc.py                         # the issuer, key, claim and allowlist rules
__init__.py                     # reads the new settings; logs a start error
docker-compose.yml              # passes the new settings to ComfyUI
tests/support/fake_issuer.py    # a fake issuer on a loopback port
tests/test_oidc_providers.py    # the hermetic tests of this spec
tests/live/conftest.py          # rauthy 0.37.2 in Docker
tests/live/test_rauthy_login.py # the full login in a browser
docs/oidc-providers.md          # the guide for each provider
```

**Structure Decision**: the rules stay in `oidc.py`. Spec 004 imports `fetch_discovery_document` and `select_signing_key` from it. A second module would only move the same functions.

## Complexity Tracking

Not applicable. The plan has no violation of the constitution.
