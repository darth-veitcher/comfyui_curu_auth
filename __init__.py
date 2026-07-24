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

Importing ``gate`` (as ``tests/test_gate.py`` does) necessarily executes
this package's own ``__init__.py`` first -- that is how Python submodule
imports work. An unconditional ``import server`` here would therefore
break this package's own hermetic test collection outside a real ComfyUI
process, not just fail to run its side effect. The ``try``/``except
ImportError`` below is the minimal fix: identical behaviour inside a real
ComfyUI process (``server`` resolves, the credential is generated,
printed, and wired onto ``app.middlewares``), and a clean no-op when
imported anywhere else (this package's own tests, or any other
non-ComfyUI Python environment).
"""

from __future__ import annotations

import os

from .gate import (  # ty: ignore[unresolved-import]  # ComfyUI's own custom-
    # node loader gives this directory a real package identity
    # (submodule_search_locations) before exec'ing this file, so this
    # relative import resolves correctly at runtime -- `ty check`, run
    # standalone with no such loader present, cannot model that synthetic
    # package context (the same reason `import server` below needs its own
    # ignore comment) and would otherwise misreport this as unresolved.
    LOGIN_PATH,
    RateLimiter,
    SessionStore,
    build_gate_middleware,
    build_login_routes,
    resolve_credential,
)
from .oidc import (  # ty: ignore[unresolved-import]  # same synthetic-package
    # reasoning as the .gate import above.
    OIDC_CALLBACK_PATH,
    OIDC_START_PATH,
    AuthorizationRequestStore,
    build_oidc_routes,
    resolve_oidc_config,
)

WEB_DIRECTORY = None  # no JS of its own -- this is a server-side-only gate
NODE_CLASS_MAPPINGS: dict[str, object] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

try:
    import server  # ty: ignore[unresolved-import]  # ComfyUI's own module,
    # only importable inside a real ComfyUI installation -- never present in
    # this repo's own environment, so `ty check` cannot resolve it either.
except ImportError:
    server = None  # imported outside a real ComfyUI process -- nothing to wire up

if server is not None:
    # COMFYUI_CURU_AUTH_TOKEN lets an operator (or an automated test
    # harness) pin a known, persistent credential instead of always
    # scraping a freshly random one from the console -- see
    # resolve_credential's own docstring. Unset (the default) keeps prior
    # behaviour exactly: a fresh, random credential every restart.
    _credential = resolve_credential(os.environ.get("COMFYUI_CURU_AUTH_TOKEN"))
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
        )
        _app.router.add_get(OIDC_START_PATH, _oidc_start)
        _app.router.add_get(OIDC_CALLBACK_PATH, _oidc_callback)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
