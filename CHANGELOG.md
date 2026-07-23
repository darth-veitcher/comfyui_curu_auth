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

### Fixed

- Login page countdown now anchors to a real deadline instead of
  decrementing per tick, so it stays accurate regardless of tab throttling.

[Unreleased]: https://github.com/darth-veitcher/comfyui_curu_auth/commits/main
