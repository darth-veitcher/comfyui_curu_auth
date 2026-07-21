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
    SessionStore,
    build_gate_middleware,
    build_login_routes,
    resolve_credential,
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
    _app = server.PromptServer.instance.app
    _app.middlewares.append(build_gate_middleware(_credential, sessions=_sessions))
    _login_get, _login_post = build_login_routes(_credential, sessions=_sessions)
    _app.router.add_get(LOGIN_PATH, _login_get)
    _app.router.add_post(LOGIN_PATH, _login_post)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
