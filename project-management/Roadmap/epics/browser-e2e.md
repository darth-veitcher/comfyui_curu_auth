# Epic: Browser-driven E2E harness (Playwright + virtual authenticator)

## Status
Planning  — started 2026-07-23

## Why now
Surfaced by adversarial engineering review (2026-07-23) of `local-test-harness`
and `passkey-auth`: `local-test-harness`'s harness is deliberately
HTTP/WS-only (`aiohttp.ClientSession`, no browser tooling — see
`specs/001-docker-comfyui-harness/research.md`), but `passkey-auth`'s own
success criterion — "verify the WebAuthn ceremony against a real ComfyUI
instance" — cannot be exercised headlessly. A WebAuthn ceremony needs a
real browser plus a platform/virtual authenticator (e.g. Playwright's
WebAuthn virtual-authenticator API). Without this epic, `passkey-auth` has
no way to satisfy its own verification criterion.

## Dependencies
_Other epics that must reach Done before this one starts. Add a bullet per
dependency: `- <slug> — <optional criterion>`. Leave empty if none._

- local-test-harness — this epic extends that harness's ComfyUI instance
  with browser-driven verification; it doesn't stand alone

## Specs
_SpecKit specs that contribute to this epic. Linked automatically when
`beacon specify --epic <slug>` is used; otherwise add manually._

<!-- - specs/001-example/   — short description -->

## ADRs
_Cross-cutting decisions this epic required. Epic creation/editing is a
BEACON DESIGN-phase activity; the architectural choices that span specs
("OAuth vs own auth", "which database", "build vs buy") belong here,
not in any single spec.md. Create ADRs in `project-management/ADRs/`
(MADR format) and link them below._

<!-- - project-management/ADRs/ADR-NNN-decision-title.md -->

## Success criteria
- A browser (Playwright), driven against the `local-test-harness` ComfyUI
  instance, can complete a full WebAuthn registration + login ceremony
  using a virtual (software) authenticator — no physical security key
  required to run the suite
- The resulting browser-driven test layer is opt-in (its own pytest marker
  or equivalent), like `local-test-harness`'s own `system` marker — never
  part of the default `uv run pytest`
- `passkey-auth` can point its own verification criterion at this layer
  instead of the HTTP/WS-only harness

## Non-goals
- Not a general browser-testing framework for this project — scoped
  specifically to what WebAuthn verification requires
- Not real hardware security key testing — virtual/software authenticator
  only, per the Success Criteria

## Notes
Playwright (or an equivalent browser-automation tool with a WebAuthn
virtual-authenticator API) is the leading candidate, but the actual
build-vs-alternative choice hasn't been researched yet — do that when this
epic is specced, not assumed here.
