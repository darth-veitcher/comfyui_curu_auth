# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Bearer-token gate covering every ComfyUI route, including the `/ws`
  websocket handshake, via a single `aiohttp` middleware attached at import
  time.
- Browser login flow at `/curu-auth/login` with `HttpOnly` / `Secure` /
  `SameSite=Strict` session cookies (30-day session).
- `COMFYUI_CURU_AUTH_TOKEN` environment variable to pin a credential across
  restarts, instead of generating a fresh one every time.
- Exponential backoff (1s → 2s → 4s → … capped at 5 minutes) on repeated
  failed credentials, applied uniformly to both the login form and the
  Bearer-header path, with a live client-side countdown on the login page.
- Per-failure logging (source IP + path) for fail2ban/crowdsec integration,
  plus ready-to-install configs and setup instructions in `contrib/`.
- MIT license.
- The active credential (pinned via `COMFYUI_CURU_AUTH_TOKEN` or
  auto-generated) is now persisted to a file under ComfyUI's own `user/`
  directory and reused on every subsequent restart — including a
  Manager-triggered `os.execv` reboot, which reuses the process's existing
  environment and can never pick up an externally-set env var after the
  fact. Previously an auto-generated credential changed on every restart,
  and any operator-supplied env var set *after* the pod/container was first
  created never reached this module at all.

### Fixed

- Login page countdown now anchors to a real deadline instead of
  decrementing per tick, so it stays accurate regardless of tab throttling.
- `pytest`'s own `Package.setup()` unconditionally imports every
  `__init__.py` it finds as soon as *any* test in this repo runs — including
  this one, whose relative imports only resolve under the real parent-package
  context ComfyUI's custom-node loader provides. Previously this crashed the
  entire test suite outside of the one deliberate, hand-built import in
  `tests/test_oidc.py::TestInitPyWiringIsOidcAware`; `__init__.py` now
  degrades to its documented no-op instead.

[Unreleased]: https://github.com/darth-veitcher/comfyui_curu_auth/commits/main
