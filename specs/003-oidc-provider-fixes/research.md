# Research: spec 003

## R-1: The issuer of each provider

| Provider | Issuer | Source |
|---|---|---|
| rauthy 0.37.2 | `http://<host>/auth/v1/` | Tested live on 2026-11-01 (issue #13) |
| Authentik | `https://<host>/application/o/<slug>/` | Authentik documentation; curu-memory ADR-017 |
| Authelia | `https://<host>` | The system test of spec 002 |
| Keycloak | `https://<host>/realms/<realm>` | Keycloak documentation |
| Google | `https://accounts.google.com` | Google discovery document |

Decision: compare exactly, after the rule of Discovery section 4.3. See ADR-007.

## R-2: Algorithms in `joserfc` 1.7.4

- `joserfc` marks RS384, RS512, PS256 and EdDSA as "not recommended". `jwt.decode` then needs an explicit `algorithms` list.
- `joserfc` writes a `SecurityWarning` for EdDSA, because RFC 9864 names `Ed25519` as the new name. rauthy 0.37.2 writes `EdDSA` in the header. The gate hides that warning for its own call only.
- `KeySet.import_key_set` keeps `alg` when the JWK has it. `KeySet.get_by_kid` finds a key by `kid`.

Decision: find the key by `kid`, take the algorithm from the key, and pass only that algorithm to `jwt.decode`.

## R-3: rauthy facts for the live tier

These facts come from comfy-mcp `tests/oidc/conftest.py` and curu-memory `tests/integration/test_rauthy.py`:

- rauthy reads `BOOTSTRAP_DIR` only at its first start.
- `LOCAL_TEST=true` loads a demo configuration. Use it only in tests.
- A user in `users.json` needs `given_name`.
- The login page of rauthy uses a proof of work in JavaScript, so a browser is the simple way to log in. Playwright drives Chromium.

## R-4: Why a start error does not raise

ComfyUI imports each custom node in a `try` block. When the import raises, ComfyUI writes the error and skips the node. The middleware of the gate is then not installed. So the gate writes an error line and keeps the OIDC login off, but installs the gate.
