"""The trusted proxies of the gate: which address is the client.

With no trusted proxy (the default), the client is the first entry of
``X-Forwarded-For``, or the peer address. With a list of trusted proxies,
the gate reads ``X-Forwarded-For`` only when the peer is on the list. It
then takes the right-most entry that is not on the list. So two browsers
behind one proxy get their own wait, and a client that reaches the gate
without the proxy cannot choose its own address.
"""

from __future__ import annotations

import ipaddress
import sys
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from gate import (
    LOGIN_PATH,
    RateLimiter,
    SessionStore,
    TrustedProxyError,
    build_gate_middleware,
    build_login_routes,
    client_key,
    resolve_trusted_proxies,
)


class _FakeTransport:
    def __init__(self, peername: tuple[str, int] | None) -> None:
        self._peername = peername

    def get_extra_info(self, name: str) -> object:
        return self._peername if name == "peername" else None


def _request(remote: str | None, forwarded_for: str | None = None) -> web.Request:
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for is not None else {}
    transport = _FakeTransport((remote, 0) if remote is not None else None)
    return make_mocked_request("GET", "/", headers=headers, transport=transport)


async def _ok_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


# --------------------------------------------------------------------------
# The setting.
# --------------------------------------------------------------------------


class TestResolveTrustedProxies:
    @pytest.mark.parametrize("setting", [None, "", "  ", " , "])
    def test_no_setting_trusts_no_proxy(self, setting: str | None) -> None:
        assert resolve_trusted_proxies(setting) == ()

    @pytest.mark.parametrize("separator", [",", " ", ", "])
    def test_takes_networks_and_addresses(self, separator: str) -> None:
        networks = resolve_trusted_proxies(
            separator.join(["10.89.1.0/24", "192.168.1.117", "fd00::/8"])
        )

        assert networks == (
            ipaddress.ip_network("10.89.1.0/24"),
            ipaddress.ip_network("192.168.1.117/32"),
            ipaddress.ip_network("fd00::/8"),
        )

    @pytest.mark.parametrize("entry", ["proxy.lan", "10.0.0.0/33", "10.0.0.1/24"])
    def test_a_bad_entry_is_a_setup_error(self, entry: str) -> None:
        with pytest.raises(
            TrustedProxyError, match="COMFYUI_CURU_AUTH_TRUSTED_PROXIES"
        ):
            resolve_trusted_proxies(f"192.168.1.117, {entry}")


# --------------------------------------------------------------------------
# client_key with trusted proxies.
# --------------------------------------------------------------------------

_PROXIES = resolve_trusted_proxies("192.168.1.117, 10.89.1.0/24")


class TestClientKeyWithTrustedProxies:
    def test_no_trusted_proxy_keeps_the_first_entry(self) -> None:
        request = _request("192.168.1.117", "203.0.113.7, 198.51.100.9")

        assert client_key(request) == "203.0.113.7"
        assert client_key(request, trusted_proxies=()) == "203.0.113.7"

    def test_a_peer_that_is_not_trusted_is_the_client(self) -> None:
        request = _request("198.51.100.20", "203.0.113.7")

        assert client_key(request, trusted_proxies=_PROXIES) == "198.51.100.20"

    def test_a_trusted_peer_gives_the_right_most_entry_that_is_not_trusted(
        self,
    ) -> None:
        # The client wrote 1.1.1.1 itself. The edge (10.89.1.124) added the
        # address that it saw, 203.0.113.7.
        request = _request("192.168.1.117", "1.1.1.1, 203.0.113.7, 10.89.1.124")

        assert client_key(request, trusted_proxies=_PROXIES) == "203.0.113.7"

    def test_a_trusted_peer_with_no_header_is_the_client(self) -> None:
        request = _request("192.168.1.117")

        assert client_key(request, trusted_proxies=_PROXIES) == "192.168.1.117"

    def test_each_entry_trusted_gives_the_first_entry(self) -> None:
        request = _request("192.168.1.117", "10.89.1.124")

        assert client_key(request, trusted_proxies=_PROXIES) == "10.89.1.124"

    def test_an_entry_that_is_not_an_address_ends_the_walk(self) -> None:
        # The client wrote "evil". Only trusted hops are on its right, so
        # the gate keeps the last trusted hop, not a text the client chose.
        request = _request("192.168.1.117", "evil, 10.89.1.124")

        assert client_key(request, trusted_proxies=_PROXIES) == "10.89.1.124"

    def test_an_entry_with_a_port_is_read_as_an_address(self) -> None:
        request = _request("192.168.1.117", "203.0.113.7:51234, [2001:db8::1]:443")

        assert client_key(request, trusted_proxies=_PROXIES) == "2001:db8::1"

    def test_ipv6_peer_and_entries(self) -> None:
        proxies = resolve_trusted_proxies("fd00::/8")
        request = _request("fd00::5", "2001:db8::7, fd00::9")

        assert client_key(request, trusted_proxies=proxies) == "2001:db8::7"

    def test_no_peer_and_no_header_is_unknown(self) -> None:
        assert client_key(_request(None), trusted_proxies=_PROXIES) == "unknown"


# --------------------------------------------------------------------------
# The wait of each path follows the setting. The test client connects
# from 127.0.0.1, so that address is the trusted proxy here.
# --------------------------------------------------------------------------

_LOOPBACK = resolve_trusted_proxies("127.0.0.1")


class TestTheWaitIsForEachClientBehindAProxy:
    async def test_bearer_path_waits_for_one_browser_only(self) -> None:
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token", rate_limiter=limiter, trusted_proxies=_LOOPBACK
                )
            ]
        )
        app.router.add_get("/anything", _ok_handler)
        wrong = {"Authorization": "Bearer wrong-token"}

        async with TestClient(TestServer(app)) as client:
            first = await client.get(
                "/anything", headers={**wrong, "X-Forwarded-For": "203.0.113.7"}
            )
            assert first.status == 401
            blocked = await client.get(
                "/anything", headers={**wrong, "X-Forwarded-For": "203.0.113.7"}
            )
            assert blocked.status == 429

            other = await client.get(
                "/anything", headers={**wrong, "X-Forwarded-For": "198.51.100.9"}
            )
            assert other.status == 401

    async def test_a_forged_header_from_an_untrusted_peer_does_not_avoid_the_wait(
        self,
    ) -> None:
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        proxies = resolve_trusted_proxies("192.168.1.117")
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token", rate_limiter=limiter, trusted_proxies=proxies
                )
            ]
        )
        app.router.add_get("/anything", _ok_handler)
        wrong = {"Authorization": "Bearer wrong-token"}

        async with TestClient(TestServer(app)) as client:
            await client.get(
                "/anything", headers={**wrong, "X-Forwarded-For": "1.1.1.1"}
            )
            blocked = await client.get(
                "/anything", headers={**wrong, "X-Forwarded-For": "2.2.2.2"}
            )
            assert blocked.status == 429

    async def test_the_log_line_names_the_forwarded_client(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = web.Application(
            middlewares=[
                build_gate_middleware("expected-token", trusted_proxies=_LOOPBACK)
            ]
        )
        app.router.add_get("/anything", _ok_handler)

        with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
            async with TestClient(TestServer(app)) as client:
                await client.get(
                    "/anything", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.7"}
                )

        assert any(
            "authentication failure from 203.0.113.7 " in r.getMessage()
            for r in caplog.records
        )

    async def test_login_form_waits_for_one_browser_only(self) -> None:
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        sessions = SessionStore()
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token", sessions=sessions, trusted_proxies=_LOOPBACK
                )
            ]
        )
        login_get, login_post = build_login_routes(
            "expected-token",
            sessions=sessions,
            rate_limiter=limiter,
            trusted_proxies=_LOOPBACK,
        )
        app.router.add_get(LOGIN_PATH, login_get)
        app.router.add_post(LOGIN_PATH, login_post)

        async with TestClient(TestServer(app)) as client:
            a = {"X-Forwarded-For": "203.0.113.7"}
            await client.post(LOGIN_PATH, data={"token": "wrong"}, headers=a)
            blocked = await client.post(LOGIN_PATH, data={"token": "wrong"}, headers=a)
            assert blocked.status == 429

            other = await client.post(
                LOGIN_PATH,
                data={"token": "wrong"},
                headers={"X-Forwarded-For": "198.51.100.9"},
            )
            assert other.status == 401

    async def test_oidc_callback_waits_for_one_browser_only(self) -> None:
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        config = OIDCConfig(
            issuer_url="https://idp.example.com",
            client_id="comfyui",
            client_secret="s3cr3t",
            redirect_uri="https://comfyui.example/curu-auth/oidc/callback",
        )
        _start, callback = build_oidc_routes(
            config,
            sessions=SessionStore(),
            store=AuthorizationRequestStore(),
            rate_limiter=RateLimiter(base_delay=60.0, max_delay=300.0),
            trusted_proxies=_LOOPBACK,
        )
        app = web.Application()
        app.router.add_get("/cb", callback)
        params = {"code": "c", "state": "never-issued"}

        async with TestClient(TestServer(app)) as client:
            a = {"X-Forwarded-For": "203.0.113.7"}
            await client.get("/cb", params=params, headers=a, allow_redirects=False)
            blocked = await client.get(
                "/cb", params=params, headers=a, allow_redirects=False
            )
            assert blocked.status == 429

            other = await client.get(
                "/cb",
                params=params,
                headers={"X-Forwarded-For": "198.51.100.9"},
                allow_redirects=False,
            )
            assert other.status != 429


# --------------------------------------------------------------------------
# The wiring in __init__.py.
# --------------------------------------------------------------------------


def _load(monkeypatch: pytest.MonkeyPatch, setting: str | None) -> Any:
    from tests.test_oidc import _load_init_with_fake_server

    monkeypatch.delenv("COMFYUI_CURU_AUTH_TRUSTED_PROXIES", raising=False)
    monkeypatch.setenv("COMFYUI_CURU_AUTH_TOKEN", "expected-token")
    env = {} if setting is None else {"COMFYUI_CURU_AUTH_TRUSTED_PROXIES": setting}
    app = _load_init_with_fake_server(monkeypatch, oidc_env=env)
    app.router.add_get("/anything", _ok_handler)
    return app


async def _two_browsers(app: web.Application) -> tuple[int, int]:
    wrong = {"Authorization": "Bearer wrong-token"}
    async with TestClient(TestServer(app)) as client:
        a = {**wrong, "X-Forwarded-For": "1.1.1.1, 203.0.113.7"}
        await client.get("/anything", headers=a)
        again = await client.get("/anything", headers=a)
        other = await client.get(
            "/anything", headers={**wrong, "X-Forwarded-For": "1.1.1.1, 198.51.100.9"}
        )
    return again.status, other.status


class TestInitPyReadsTheTrustedProxies:
    async def test_the_setting_reaches_the_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _load(monkeypatch, "127.0.0.1/32")

        assert await _two_browsers(app) == (429, 401)

    async def test_with_no_setting_the_first_entry_is_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _load(monkeypatch, None)

        # Both requests have the first entry 1.1.1.1, so they share the wait.
        assert await _two_browsers(app) == (429, 429)

    async def test_a_bad_setting_keeps_the_gate_on(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = _load(monkeypatch, "proxy.lan")

        assert len(app.middlewares) == 1
        assert "COMFYUI_CURU_AUTH_TRUSTED_PROXIES" in capsys.readouterr().out
        assert "_comfyui_curu_auth_under_test" in sys.modules
        # No proxy is trusted, so the gate keeps its default.
        assert await _two_browsers(app) == (429, 429)
