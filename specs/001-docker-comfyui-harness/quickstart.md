# Quickstart: Docker ComfyUI Integration Harness

## Prerequisites

- Docker with the `docker compose` CLI (Docker Desktop, Docker Engine, or
  colima — plain `docker compose`, nothing engine-specific).

## Bring the harness up

```bash
docker compose up -d      # starts ComfyUI in the background
docker compose logs -f    # tail its output (Ctrl-C to stop tailing, container keeps running)
```

First run builds the image (clones the pinned ComfyUI tag, installs CPU
torch) — expect a few minutes. Subsequent runs reuse the built image; a
plain restart (no rebuild) is enough to pick up local edits to this node's
own code, since it's bind-mounted rather than baked into the image.

## Run the integration suite against it

```bash
uv run pytest -m system
```

Exercises: unauthenticated rejection on representative HTTP routes and the
`/ws` handshake, correct-credential success, rate-limit backoff, and
teardown/restart leaving no stale state.

## Tear down

```bash
docker compose down
```

Run `docker compose up -d` again afterward to confirm no leftover state
(spec SC-004) — startup should behave identically to the first run.

## Known quirk: the "gate active" banner doesn't appear in `docker compose logs`

`__init__.py`'s own `print("comfyui-curu-auth gate active...")` line
doesn't show up in this harness's container logs — ComfyUI's custom-node
loader appears to capture/discard stdout during its own import-timing
measurement (`Import times for custom nodes:`), while `logging.warning`
calls made later, at request time, aren't affected and do show up (visible
as `authentication failure from ...` lines once traffic hits the gate).
Confirmed live (2026-07-23) during `quickstart.md` validation. Not a
defect in the gate itself — this harness never needs to scrape the
credential from logs anyway, since `COMFYUI_CURU_AUTH_TOKEN` pins it to a
known value — but worth knowing if you go looking for that banner by hand.

## What this does NOT do

- Does not execute any ComfyUI workflow, load a model checkpoint, or
  exercise rendering/inference — no GPU, proves the auth gate only (spec
  Non-Goals).
- Does not affect `uv run pytest` (the default hermetic suite in
  `tests/test_gate.py`) — `uv run pytest -m system` is a fully separate,
  opt-in path; the default command excludes it.
- Is not wired into CI by this feature — a local dev-loop tool first (spec
  Non-Goals); CI wiring would be a separate, future spec.
