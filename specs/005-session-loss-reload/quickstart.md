# Quickstart: An open tab goes to the login page when its session is lost

**Spec**: [spec.md](spec.md) · **Contracts**: [contracts/](contracts/)

These steps prove the feature. Run them from the root of the repository.

## Prerequisites

- `uv sync`
- `uv run --group live playwright install chromium`
- Docker, for step 3 only.

## 1. The mark on the gate rejections

```bash
uv run pytest
```

Expected: all tests pass. The new tests check rules G1 to G9 of [contracts/gate-rejection.md](contracts/gate-rejection.md).

## 2. The module in a browser, with no Docker

```bash
uv run --group live pytest -m browser
```

Expected: all tests pass. They check rules T1 to T11 of [contracts/tab-module.md](contracts/tab-module.md). The tier fails, and does not skip, when Chromium is not installed.

## 3. The real ComfyUI frontend and a real restart

```bash
uv run --group live pytest -m system -k session_loss
```

Expected: the test passes. It checks rule T12: the tab shows the login page within 5 seconds after the restart (SC-001).

## 4. By hand

1. Start the harness: `docker compose up -d --wait`.
2. Open `http://localhost:8188` in a browser, and log in with `local-harness-test-credential`.
3. Run `docker compose restart comfyui`, and keep the tab open.
4. Watch the tab. Expected: the tab shows the login page within 5 seconds after ComfyUI is ready again.
5. Run `docker compose logs comfyui | grep "authentication failure"`. Expected: no more than 10 lines after the restart (SC-002), and no new line after the move (SC-003).
6. Log in. Expected: the tab shows ComfyUI at `/`.
7. Stop the harness: `docker compose down`.
