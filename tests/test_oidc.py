"""Hermetic coverage for :mod:`oidc` -- the OIDC/OAuth login path's pure,
testable logic (config resolution, authorization-URL building, ID-token
verification, the callback handler), driven against a mocked provider
double via ``aiohttp.test_utils``. Never imports ``__init__`` -- only
``oidc.py`` and ``gate.py`` directly, mirroring ``tests/test_gate.py``'s
own hermetic conventions.
"""

from __future__ import annotations

import asyncio

import pytest
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


# --------------------------------------------------------------------------
# resolve_oidc_config -- T007/T008.
# --------------------------------------------------------------------------


class TestResolveOidcConfig:
    """All four settings MUST be present together (FR-001); any subset
    missing MUST resolve to `None` -- "OIDC is unconfigured" -- never a
    partially-filled config object (FR-009)."""

    def test_all_four_present_resolves_to_a_populated_config(self) -> None:
        from oidc import resolve_oidc_config

        config = resolve_oidc_config(
            issuer_url="https://idp.example.com",
            client_id="comfyui-curu-auth",
            client_secret="s3cr3t",
            redirect_uri="https://host/curu-auth/oidc/callback",
        )
        assert config is not None
        assert config.issuer_url == "https://idp.example.com"
        assert config.client_id == "comfyui-curu-auth"
        assert config.client_secret == "s3cr3t"
        assert config.redirect_uri == "https://host/curu-auth/oidc/callback"

    def test_all_four_absent_resolves_to_none(self) -> None:
        from oidc import resolve_oidc_config

        assert (
            resolve_oidc_config(
                issuer_url=None,
                client_id=None,
                client_secret=None,
                redirect_uri=None,
            )
            is None
        )

    def test_missing_client_secret_resolves_to_none_not_a_partial_config(
        self,
    ) -> None:
        # FR-009 / Edge Case: a client ID but no client secret must fail
        # safe to unconfigured, not start in a half-configured state.
        from oidc import resolve_oidc_config

        assert (
            resolve_oidc_config(
                issuer_url="https://idp.example.com",
                client_id="comfyui-curu-auth",
                client_secret=None,
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            is None
        )

    def test_blank_string_values_are_treated_like_absent(self) -> None:
        # os.environ.get returns "" for a declared-but-empty var, not
        # None -- mirrors resolve_credential's own established handling.
        from oidc import resolve_oidc_config

        assert (
            resolve_oidc_config(
                issuer_url="https://idp.example.com",
                client_id="comfyui-curu-auth",
                client_secret="",
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            is None
        )


# --------------------------------------------------------------------------
# Discovery-document fetch -- T011/T012.
# --------------------------------------------------------------------------

_DISCOVERY_DOCUMENT = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/api/oidc/authorization",
    "token_endpoint": "https://idp.example.com/api/oidc/token",
    "jwks_uri": "https://idp.example.com/jwks.json",
}


class TestFetchDiscoveryDocument:
    """`fetch_discovery_document` is the one HTTP call this feature makes
    with no dependency on a resolved session/flow state -- every failure
    mode (timeout, connection error, malformed body) MUST raise the same
    `OIDCDiscoveryError`, never fall back to a cache or partial result
    (research.md's "fetch fresh, fail closed" decision; Edge Case:
    "identity provider is unreachable or times out")."""

    async def test_successful_fetch_returns_the_parsed_document(self) -> None:
        from oidc import fetch_discovery_document

        async def _discovery_handler(request: web.Request) -> web.Response:
            return web.json_response(_DISCOVERY_DOCUMENT)

        app = web.Application()
        app.router.add_get("/.well-known/openid-configuration", _discovery_handler)

        async with TestClient(TestServer(app)) as client:
            base_url = str(client.make_url(""))
            document = await fetch_discovery_document(base_url.rstrip("/"), timeout=5.0)

        assert document == _DISCOVERY_DOCUMENT

    async def test_timeout_raises_oidc_discovery_error(self) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        async def _slow_handler(request: web.Request) -> web.Response:
            await asyncio.sleep(2.0)
            return web.json_response(_DISCOVERY_DOCUMENT)

        app = web.Application()
        app.router.add_get("/.well-known/openid-configuration", _slow_handler)

        async with TestClient(TestServer(app)) as client:
            base_url = str(client.make_url(""))
            with pytest.raises(OIDCDiscoveryError):
                await fetch_discovery_document(base_url.rstrip("/"), timeout=0.1)

    async def test_connection_error_raises_oidc_discovery_error(self) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        # Nothing listens on this port -- a real connection failure, not a
        # mock, so the underlying aiohttp.ClientConnectorError is genuine.
        with pytest.raises(OIDCDiscoveryError):
            await fetch_discovery_document("http://127.0.0.1:1", timeout=2.0)

    async def test_malformed_body_raises_oidc_discovery_error(self) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        async def _not_json_handler(request: web.Request) -> web.Response:
            return web.Response(text="not json", content_type="text/plain")

        app = web.Application()
        app.router.add_get("/.well-known/openid-configuration", _not_json_handler)

        async with TestClient(TestServer(app)) as client:
            base_url = str(client.make_url(""))
            with pytest.raises(OIDCDiscoveryError):
                await fetch_discovery_document(base_url.rstrip("/"), timeout=5.0)
