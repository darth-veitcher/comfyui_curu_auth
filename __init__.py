"""ComfyUI-loaded entrypoint -- runs at ComfyUI's own custom-node import time.

Generates a fresh credential, prints it once to ComfyUI's own console, and
installs :func:`~gate.build_gate_middleware` onto the real,
already-running ``server.PromptServer.instance.app`` -- covering every
route ComfyUI serves, including ``/ws``, verified directly against
ComfyUI's own ``server.py`` (every route it registers, including the
``/ws`` websocket handshake, shares that one ``app``/``routes`` object).
Also registers :func:`~gate.build_login_routes` at ``LOGIN_PATH`` on that
same app, so a human can open ComfyUI's own UI directly in a browser (no
way to attach a custom header) by logging in with the printed credential
once.

``server`` is ComfyUI's own module -- it only resolves inside a real
ComfyUI installation, so this file's own hermetic test coverage
(``tests/test_gate.py``) never imports this module at all, only
``gate.py`` directly.

The ``.gate``/``.oidc`` relative imports below only resolve under a real
parent-package context: ComfyUI's own custom-node loader gives this
directory one (``submodule_search_locations``) before exec'ing this file,
and this repo's own ``_load_init_with_fake_server`` test helper
(``tests/test_oidc.py``) constructs an equivalent one deliberately. Any
*other* import of this file -- notably ``pytest``'s own ``Package.setup()``,
which unconditionally imports every ``__init__.py`` it finds as soon as
*any* test elsewhere in this repo runs, regardless of whether that test
has anything to do with this module -- has no such context, and hits a
plain ``ImportError: attempted relative import with no known parent
package``. The ``try``/``except ImportError`` below covers both that case
and the (previously separately-handled) "no real ComfyUI ``server``"
case identically: neither has anything to wire up, so both are a clean
no-op.
"""

from __future__ import annotations

import os
from pathlib import Path

WEB_DIRECTORY = None  # no JS of its own -- this is a server-side-only gate
NODE_CLASS_MAPPINGS: dict[str, object] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

try:
    import server  # ty: ignore[unresolved-import]  # ComfyUI's own module,

    from .gate import (  # ty: ignore[unresolved-import]  # see module docstring
        LOGIN_PATH,
        RateLimiter,
        SessionStore,
        build_gate_middleware,
        build_login_routes,
        resolve_persistent_credential,
    )
    from .oidc import (  # ty: ignore[unresolved-import]  # same reasoning
        OIDC_CALLBACK_PATH,
        OIDC_START_PATH,
        AuthorizationRequestStore,
        build_oidc_routes,
        resolve_oidc_config,
    )
    # only importable inside a real ComfyUI installation -- never present in
    # this repo's own environment, so `ty check` cannot resolve it either.
except ImportError:
    server = None  # nothing to wire up -- see module docstring

if server is not None:
    # folder_paths is ComfyUI's own module (same resolution story as
    # `server` above) exposing where ComfyUI persists per-install state --
    # `user/default/...` is where its own settings/workflows already live.
    # Absence degrades to "no persistence" (state_path=None), not to
    # disabling the gate entirely -- a working, just non-restart-stable,
    # credential is still strictly better than no auth at all (constitution
    # III: "fail safe to gate stays on", never to "gate is open").
    try:
        import folder_paths  # ty: ignore[unresolved-import]

        _state_path: Path | None = (
            Path(folder_paths.get_user_directory())
            / "default"
            / "comfyui_curu_auth"
            / "credential"
        )
    except ImportError:
        _state_path = None

    # COMFYUI_CURU_AUTH_TOKEN lets an operator (or an automated test
    # harness, or `runpod-comfy`'s own provisioning) pin a known credential
    # -- see resolve_persistent_credential's own docstring for how it and
    # `_state_path` interact to survive a restart that reuses the process's
    # existing environment (an `os.execv`-based Manager reboot never picks
    # up an externally-set env var after the fact; only a persisted file
    # does, since re-importing this module re-reads it from scratch).
    _credential = resolve_persistent_credential(
        os.environ.get("COMFYUI_CURU_AUTH_TOKEN"), _state_path
    )
    print(f"comfyui-curu-auth gate active. Credential:\n  {_credential}")
    print(f"Browser login (paste the same credential above): {LOGIN_PATH}")
    _sessions = SessionStore()
    # One shared instance for every path -- a client backed off on one
    # (e.g. hammering the Bearer header) is backed off on the others too.
    _rate_limiter = RateLimiter()

    # Entirely opt-in (spec 002 FR-001/FR-002/FR-009): resolve_oidc_config
    # returns None unless all four are real, non-empty values -- a
    # partial set is treated identically to none at all, never a
    # half-configured state that starts anyway.
    _oidc_config = resolve_oidc_config(
        issuer_url=os.environ.get("COMFYUI_CURU_AUTH_OIDC_ISSUER_URL"),
        client_id=os.environ.get("COMFYUI_CURU_AUTH_OIDC_CLIENT_ID"),
        client_secret=os.environ.get("COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET"),
        redirect_uri=os.environ.get("COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI"),
    )
    _public_paths = {LOGIN_PATH}
    if _oidc_config is not None:
        _public_paths |= {OIDC_START_PATH, OIDC_CALLBACK_PATH}

    _app = server.PromptServer.instance.app
    _app.middlewares.append(
        build_gate_middleware(
            _credential,
            sessions=_sessions,
            rate_limiter=_rate_limiter,
            public_paths=_public_paths,
        )
    )
    _login_get, _login_post = build_login_routes(
        _credential,
        sessions=_sessions,
        rate_limiter=_rate_limiter,
        oidc_start_path=OIDC_START_PATH if _oidc_config is not None else None,
    )
    _app.router.add_get(LOGIN_PATH, _login_get)
    _app.router.add_post(LOGIN_PATH, _login_post)

    if _oidc_config is not None:
        print(f"OIDC login also available at: {OIDC_START_PATH}")
        _oidc_store = AuthorizationRequestStore()
        _oidc_start, _oidc_callback = build_oidc_routes(
            _oidc_config,
            sessions=_sessions,
            store=_oidc_store,
            rate_limiter=_rate_limiter,
        )
        _app.router.add_get(OIDC_START_PATH, _oidc_start)
        _app.router.add_get(OIDC_CALLBACK_PATH, _oidc_callback)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
