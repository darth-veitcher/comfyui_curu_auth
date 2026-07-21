# comfyui_curu_auth

A ComfyUI custom node that protects a ComfyUI backend with a bearer-token
credential — every route the backend serves (including the `/ws`
connection its own progress streaming depends on) is rejected unless a
request carries the exact credential this gate generated at startup.

No configuration, no accounts, no external service: install it, restart
ComfyUI, and it prints a fresh credential to the console. Point any
Bearer-header-aware client at your ComfyUI instance with that credential,
or open ComfyUI's own UI directly in a browser and log in with it once.

## What the gate does

`server.PromptServer.instance.app` is ComfyUI's own, already-running
`aiohttp.web.Application` — this extension's `__init__.py` reads it at
import time and appends one `@web.middleware` function to
`app.middlewares`. Because ComfyUI registers every route (including its
`/ws` websocket handshake) onto that same `app`/`routes` object, this one
middleware covers every route the backend serves, not just plain HTTP
ones — verified directly against ComfyUI's own `server.py`.

The credential itself is `secrets.token_urlsafe(32)` (256 bits of
entropy), checked with `secrets.compare_digest` (constant-time, no timing
side-channel), transported as `Authorization: Bearer <credential>`. Both
the supplied header and the expected value are encoded to `latin-1`
bytes before comparison, a defence against a non-ASCII `Authorization`
header a plain `str` comparison would otherwise crash on.

## Install

Clone this repo directly into your ComfyUI installation's `custom_nodes/`
folder:

```bash
cd /path/to/ComfyUI/custom_nodes
git clone <this-repo-url> comfyui_curu_auth
```

Restart ComfyUI. Its own console prints, once, a freshly generated
credential:

```
comfyui-curu-auth gate active. Credential:
  Yx3fQvR8...
```

Copy that value into whatever client (or your own notes) needs to reach
this ComfyUI instance as `Authorization: Bearer <credential>`. There is
deliberately no automated way to retrieve that credential over the
network — an operator's own copy-paste from the console is the only path,
matching the "no accounts, no external service" design.

## Browsing ComfyUI's own UI directly

A human who wants to open ComfyUI's own UI directly in a browser has no
way to attach a custom header, so the gate also serves a minimal login
form at `/curu-auth/login`: paste the same credential printed at startup,
submit, and the gate sets an `HttpOnly` / `Secure` / `SameSite=Strict`
cookie good for 30 days — every other route now accepts either the
existing `Authorization: Bearer <credential>` header (any automated
client, completely unaffected) or that cookie.

The cookie's own value is a distinct session token, not the master
credential itself — the gate never transmits that credential over the
network itself, and a browser replaying a cookie on every request for 30
days is exactly such a transmission. A leaked cookie can therefore never
be replayed as the actual Bearer-header credential.

The login form pairs a hidden, fixed identity field with the real
credential field specifically so Chrome/Firefox/Safari's own
password-manager autofill offers to save it — a password-only form
generally doesn't trigger that prompt.

Repeated failed login attempts from the same client back off
exponentially (1s → 2s → 4s → ... capped at 5 minutes, resetting on a
correct login) — defence in depth against an automated scanner probing
the form; the credential itself is already computationally infeasible to
brute-force regardless. This backoff applies only to the login form,
never to the Bearer-header path every other route uses, so a transient
misconfiguration of an automated client can never lock itself out.

Opening any gated page directly with no credential or cookie yet — the
normal case for a first visit — redirects straight to `/curu-auth/login`
rather than showing a bare JSON 401 with no obvious next step. This is
based on the request's own `Accept: text/html` header, the same
page-load-vs-API-call signal many web frameworks use; an automated
Bearer-header client and the `/ws` handshake never send that header, so
neither is affected.

No custom node classes are registered (`NODE_CLASS_MAPPINGS` is empty by
design) and this extension serves no JS of its own (`WEB_DIRECTORY =
None`) — it is a server-side-only gate.

## Tests

```bash
uv sync
uv run pytest
```

`gate.py`'s pure logic (`generate_credential`, `build_gate_middleware`,
`SessionStore`, `RateLimiter`) is exercised directly against a real,
minimal `aiohttp.web.Application` via
`aiohttp.test_utils.TestClient`/`TestServer` — no real ComfyUI needed.

`__init__.py` — the real ComfyUI-side wiring (`import server`,
`server.PromptServer.instance.app.middlewares.append(...)`) — has **no**
automated test: it requires a real, running `server.PromptServer.instance`
that only exists inside an actual ComfyUI process, which this repo's
hermetic suite cannot fake without disproportionate, low-value
scaffolding. It is verified by installing this node into a real ComfyUI
instance and confirming the credential prints and the gate enforces it.

## Origin

Extracted from [curu](https://github.com/darth-veitcher/curu)'s own
`local-network-auth-and-encryption` epic, where this gate's credential
scheme was originally designed to harmonise with curu's own
control-plane API — reused here standalone, not re-derived.
