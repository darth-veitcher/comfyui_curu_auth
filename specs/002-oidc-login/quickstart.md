# Quickstart: OIDC/OAuth Login Path

## Configure an OIDC provider

```bash
export COMFYUI_CURU_AUTH_OIDC_ISSUER_URL="https://your-idp.example.com"
export COMFYUI_CURU_AUTH_OIDC_CLIENT_ID="comfyui-curu-auth"
export COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET="<registered client secret>"
export COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI="https://your-comfyui-host/curu-auth/oidc/callback"
```

All four MUST be set together — a partial set is treated as unconfigured
(FR-009), and ComfyUI starts exactly as it does today, no OIDC option
visible on the login page.

Restart ComfyUI. The login page now offers "Log in with your identity
provider" alongside the existing credential field.

## Log in

Choosing the OIDC option redirects to the configured provider; a
successful login there redirects back and lands you on ComfyUI's UI,
authenticated — the same `curu_auth` session cookie the credential-based
login form already sets (ADR-002). The Bearer-header path for automated
clients is completely unaffected either way.

## Run the live suite against Authelia

```bash
docker compose up -d      # now also brings up the authelia service
uv run pytest -m system -k oidc
```

Exercises the real authorization-code flow against a real Authelia (Lite
bundle) instance — not a mocked provider — per ADR-002, plus the
default-credential-path-unaffected regression check (US2) and the
rate-limit/logging parity check (US3).

## What this does NOT do

- Does not support more than one configured OIDC provider at a time (epic
  Non-Goals).
- Does not add any account/role concept — a successful OIDC login is
  still just "authenticated", the same single boundary the default
  credential already gates (epic Non-Goals: not multi-tenant).
- Does not change the default zero-config credential path in any way when
  OIDC is unconfigured (FR-002/FR-004) — verified explicitly, not just
  assumed, by US2's own tests.
