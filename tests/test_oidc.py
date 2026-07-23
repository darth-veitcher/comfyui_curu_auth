"""Hermetic coverage for :mod:`oidc` -- the OIDC/OAuth login path's pure,
testable logic (config resolution, authorization-URL building, ID-token
verification, the callback handler), driven against a mocked provider
double via ``aiohttp.test_utils``. Never imports ``__init__`` -- only
``oidc.py`` and ``gate.py`` directly, mirroring ``tests/test_gate.py``'s
own hermetic conventions.
"""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gate import LOGIN_PATH, build_gate_middleware

# --------------------------------------------------------------------------
# gate.py's public_paths generalization -- T004/T005 (ADR-003).
# --------------------------------------------------------------------------


async def _ok_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


class TestPublicPathsGeneralization:
    """`build_gate_middleware` must accept an iterable of unauthenticated
    -allowed paths, not just the single hardcoded `LOGIN_PATH` -- so a
    second additive auth method (this spec's OIDC start/callback routes)
    can register its own pre-session routes through the same mechanism
    (ADR-003), without a second special-cased check alongside the first.
    """

    async def test_every_path_in_public_paths_is_let_through_unauthenticated(
        self,
    ) -> None:
        oidc_start_path = "/curu-auth/oidc/start"
        oidc_callback_path = "/curu-auth/oidc/callback"
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token",
                    public_paths={LOGIN_PATH, oidc_start_path, oidc_callback_path},
                )
            ]
        )
        app.router.add_get(LOGIN_PATH, _ok_handler)
        app.router.add_get(oidc_start_path, _ok_handler)
        app.router.add_get(oidc_callback_path, _ok_handler)

        async with TestClient(TestServer(app)) as client:
            for path in (LOGIN_PATH, oidc_start_path, oidc_callback_path):
                response = await client.get(path)
                assert response.status == 200, path

    async def test_a_path_not_in_public_paths_is_still_gated(self) -> None:
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token",
                    public_paths={LOGIN_PATH, "/curu-auth/oidc/start"},
                )
            ]
        )
        app.router.add_get("/object_info", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/object_info")
            assert response.status == 401

    async def test_default_public_paths_is_login_path_only(self) -> None:
        # No public_paths argument supplied -- must behave byte-for-byte
        # like today's single-LOGIN_PATH check (FR-004: the default
        # Bearer-header path is untouched by this generalization).
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get(LOGIN_PATH, _ok_handler)
        app.router.add_get("/object_info", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            login_response = await client.get(LOGIN_PATH)
            assert login_response.status == 200

            gated_response = await client.get("/object_info")
            assert gated_response.status == 401
