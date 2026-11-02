# AGENTS.md

## What this repository is

comfyui_curu_auth is a ComfyUI custom node that gates each route of ComfyUI with a credential, a session cookie and an optional OIDC login. ComfyUI loads it from `custom_nodes/`; it is never built as a wheel. [curu](https://github.com/darth-veitcher/curu) and comfy-mcp are clients of this gate, and curu-memory shares its OIDC rules.

## Commands

| Purpose | Command |
|---|---|
| Set up | `uv sync` |
| Lint and format | `uv run ruff check --fix && uv run ruff format` |
| Check types | `uv run ty check` |
| Run the default tests | `uv run pytest` |
| Run the ComfyUI and Authelia tier (marker `system`) | `uv run --group live pytest -m system` |
| Run the script of the tab in Chromium (marker `browser`) | `uv run --group live pytest -m browser` |
| Run the rauthy tier (marker `rauthy`) | `uv run --group live pytest -m rauthy` |
| Install Chromium for the system, browser and rauthy tiers | `uv run --group live playwright install chromium` |
| Run comfy-mcp against the gate and rauthy (marker `comfy_mcp`) | `uv run --group live pytest -m comfy_mcp` |
| Check the project health | `beacon doctor --strict` |
| Check the documentation | `beacon docs check` |

A release is automatic. Each merge to `main` runs python-semantic-release in `.github/workflows/release.yml`. Do not push tags by hand.

## Rules

The articles are in [the constitution](.specify/memory/constitution.md).

- Write a failing test before the code (article IV). Commit the test alone, and then the code alone (project rule).
- Use Conventional Commits. The `commit-msg` hook checks them. Never use `--no-verify` (project rule).
- Cut each branch from `main`, and open each pull request to `main`. There is no `develop` branch (project rule).
- Never weaken the static credential path for an optional login method (article I).
- An error in an optional setting must keep the gate on. Never raise from `__init__.py`, because ComfyUI then skips the node (article III).
- Never log a credential (Security Requirements). Never log a token or a part of a token (project rule).
- A change to the log line `authentication failure from <IP>` breaks fail2ban and crowdsec. Say so in the pull request (Security Requirements).
- A change that a user can see also changes `README.md` or `docs/` in the same pull request (project rule).

## Where things are

| Path | Contents |
|---|---|
| `gate.py` | The credential, the middleware, the sessions, the rate limiter and the login form. |
| `web/session_loss.js` | The script that ComfyUI loads into its page. It sends an open tab to the login page when the gate rejects its session. |
| `oidc.py` | The OIDC login (discovery, keys, ID-token rules, the allowlist, the routes) and the access-token check with its key cache. |
| `__init__.py` | The wiring that ComfyUI imports. It reads the environment. |
| `tests/` | The default tests. `tests/support/fake_issuer.py` is the fake OIDC provider. |
| `tests/system/` | The `system` tier. It uses `docker-compose.yml` and `docker/` in the root of the repository. |
| `tests/browser/` | The `browser` tier. It runs `web/session_loss.js` in Chromium against the real gate and a small test page that acts like the ComfyUI page. |
| `tests/live/` | The `rauthy` tier, and the `comfy_mcp` tier in `test_comfy_mcp_end_to_end.py`. |
| `contrib/` | The fail2ban and crowdsec configurations. |
| `docs/` | The guides for people. |
| `specs/` | One folder for each spec: spec, plan, tasks and features. |
| `project-management/` | The ADRs, the epics and the roadmap. |

## Current work

Active spec: [specs/005-session-loss-reload/spec.md](specs/005-session-loss-reload/spec.md) and its [plan.md](specs/005-session-loss-reload/plan.md). `beacon bullet status` names the bullet of the current branch.

## Known problems

| Problem | Fix |
|---|---|
| Ruff reports N999 for `__init__.py`. | The directory of the checkout has a hyphen in its name. Use a name with no hyphen, for example for a git worktree. |
| The `rauthy` tier fails at once. | Start Docker. The tier fails on purpose without Docker, so a missing tier is never a silent pass. |
| `.specify/scripts/bash/create-new-feature.sh` makes the spec folder, but no branch. | Spec Kit 1.x does not create the branch. Run `git checkout -b <NNN-slug>` from `main`. |
| The `comfy_mcp` tier fails with `cannot start comfy-mcp`. | `uvx` cannot get the private comfy-mcp repository. Check your git access with `ssh -T git@github.com`, or set `COMFY_MCP_COMMAND` to a local build, for example `uv run --project /path/to/comfy-mcp comfy-mcp`. A relative path starts at the root of this repository. |
| rauthy ignores a change to the bootstrap files. | rauthy reads them only at its first start. Each test run starts a new container. |
| After a release, `CHANGELOG.md` still has entries under "Unreleased". | Move them out in the next pull request. python-semantic-release writes each version under `<!-- version list -->` and does not empty "Unreleased". |
