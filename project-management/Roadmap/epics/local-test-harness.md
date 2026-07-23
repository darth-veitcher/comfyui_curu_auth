# Epic: CPU-only Docker integration harness for ComfyUI + this node

## Status
Planning  — started 2026-07-23

## Why now
The one thing the README and existing test suite already flag as unverified
by automation — `__init__.py`'s real ComfyUI-side wiring against a live
`server.PromptServer.instance` — has been "install for real and eyeball it"
since day one. Every future gate change, including the two auth-expansion
epics queued behind this one, needs a cheap, repeatable way to prove the
gate still holds against a real ComfyUI process, not just the existing
mocked `aiohttp` app in `tests/test_gate.py`.

## Dependencies
_Other epics that must reach Done before this one starts. Add a bullet per
dependency: `- <slug> — <optional criterion>`. Leave empty if none._

None.

## Specs
_SpecKit specs that contribute to this epic. Linked automatically when
`beacon specify --epic <slug>` is used; otherwise add manually._

<!-- - specs/001-example/   — short description -->

- specs/001-docker-comfyui-harness/
## ADRs
_Cross-cutting decisions this epic required. Epic creation/editing is a
BEACON DESIGN-phase activity; the architectural choices that span specs
("OAuth vs own auth", "which database", "build vs buy") belong here,
not in any single spec.md. Create ADRs in `project-management/ADRs/`
(MADR format) and link them below._

<!-- - project-management/ADRs/ADR-NNN-decision-title.md -->

## Success criteria
- `docker compose up` brings up a real, CPU-only ComfyUI instance with
  comfyui_curu_auth installed from the local working tree (not a published
  release), first build included, in a few minutes
- An automated, opt-in test suite (separate from the existing hermetic
  `uv run pytest`) exercises the live gate: unauthenticated requests are
  rejected, the correct credential succeeds, the `/ws` handshake is gated,
  and repeated failures trigger rate-limiting — all against the real
  ComfyUI process, not a mock
- Teardown leaves no leftover state — a fresh `up` afterward behaves
  identically to the first run

## Non-goals
- Does not execute any ComfyUI workflow or exercise rendering/inference —
  no GPU, no checkpoint; proves the auth gate only
- Does not replace `tests/test_gate.py`'s existing hermetic suite — this is
  an additive, opt-in integration layer
- Not a CI requirement yet — a local dev-loop tool first; CI wiring is a
  possible follow-up, not part of this epic's Done

## Notes
`~/repos/JAMESVEITCH/curu` (sibling repo, same author) already has almost
exactly this: `docker-compose.yml` + `docker/comfyui/Dockerfile` build a
CPU-only ComfyUI image (`--cpu`, CPU torch wheels, pinned ComfyUI tag) with
comfyui_curu_auth installed via `git clone` from GitHub and a fixed
`COMFYUI_CURU_AUTH_TOKEN` so tests don't scrape a random credential from
logs. Its healthcheck already treats a `401` response as "alive and
correctly gated," not a failure — reuse that reasoning directly. Adapt by
swapping the GitHub clone for a bind-mount/COPY of this repo's own working
tree, and drop curu's `generate_checkpoint.py` step (that only exists to
prove workflow execution, out of scope here).
