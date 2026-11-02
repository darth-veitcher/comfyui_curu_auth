"""Hermetic tests of issue #25: the OIDC login accepts more than one redirect
URI and chooses one for each login from the origin of the request.

Each login test runs the real ``oidc.py`` against :class:`FakeIssuer` on a
loopback port. The request sets ``Host`` and the forwarded headers itself, as
a browser on the LAN or a reverse proxy does.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from gate import SessionStore
from tests.support.fake_issuer import CLIENT_ID, CLIENT_SECRET, FakeIssuer

START = "/curu-auth/oidc/start"
CALLBACK = "/curu-auth/oidc/callback"

LAN = f"http://192.168.1.117:8188{CALLBACK}"
PROXY = f"https://comfy.example.com{CALLBACK}"


def _resolve(redirect_uri: str | None) -> Any:
    from oidc import resolve_oidc_config

    return resolve_oidc_config(
        issuer_url="https://idp.example.com/",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=redirect_uri,
        allow_any_user="true",
    )


# --------------------------------------------------------------------------
# The setting.
# --------------------------------------------------------------------------


class TestTheSettingTakesAList:
    def test_one_value_gives_one_uri(self) -> None:
        config = _resolve(PROXY)

        assert config.redirect_uri == PROXY
        assert config.redirect_uris == (PROXY,)

    @pytest.mark.parametrize("separator", [",", ", ", " "])
    def test_the_first_entry_is_the_default(self, separator: str) -> None:
        config = _resolve(f"{LAN}{separator}{PROXY}")

        assert config.redirect_uri == LAN
        assert config.redirect_uris == (LAN, PROXY)

    def test_an_entry_given_twice_is_kept_once(self) -> None:
        assert _resolve(f"{LAN},{PROXY},{LAN}").redirect_uris == (LAN, PROXY)

    @pytest.mark.parametrize(
        "value",
        [
            "https://comfy.example.com/callback",
            f"{LAN},https://comfy.example.com/oidc/callback",
            f"https://comfy.example.com{CALLBACK}/",
        ],
    )
    def test_an_entry_with_another_path_is_a_setup_error(self, value: str) -> None:
        from oidc import OIDCConfigError

        with pytest.raises(OIDCConfigError, match="REDIRECT_URI"):
            _resolve(value)

    @pytest.mark.parametrize(
        "value",
        [CALLBACK, f"ftp://comfy.example.com{CALLBACK}", f"https://{CALLBACK}"],
    )
    def test_an_entry_that_is_not_an_http_url_is_a_setup_error(
        self, value: str
    ) -> None:
        from oidc import OIDCConfigError

        with pytest.raises(OIDCConfigError, match="REDIRECT_URI"):
            _resolve(value)

    def test_a_path_prefix_of_a_proxy_is_accepted(self) -> None:
        uri = f"https://example.com/comfy{CALLBACK}"

        assert _resolve(uri).redirect_uris == (uri,)


# --------------------------------------------------------------------------
# The origin of a request.
# --------------------------------------------------------------------------


class TestTheOriginOfARequest:
    @pytest.mark.parametrize(
        ("headers", "origin"),
        [
            ({"Host": "192.168.1.117:8188"}, "http://192.168.1.117:8188"),
            (
                {
                    "Host": "10.0.0.5:8188",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "comfy.example.com",
                },
                "https://comfy.example.com",
            ),
            (
                {
                    "Host": "10.0.0.5:8188",
                    "X-Forwarded-Proto": "https, http",
                    "X-Forwarded-Host": "comfy.example.com, 10.0.0.5:8188",
                },
                "https://comfy.example.com",
            ),
            (
                {
                    "Host": "10.0.0.5:8188",
                    "Forwarded": 'proto=https;host="comfy.example.com"',
                },
                "https://comfy.example.com",
            ),
        ],
    )
    def test_the_origin_follows_the_forwarded_headers(
        self, headers: dict[str, str], origin: str
    ) -> None:
        from gate import request_origin

        assert request_origin(make_mocked_request("GET", START, headers)) == origin


# --------------------------------------------------------------------------
# A login chooses its redirect URI.
# --------------------------------------------------------------------------


async def _login_from(
    issuer: FakeIssuer, redirect_uri: str, headers: dict[str, str]
) -> tuple[str, str, int]:
    """Start a login and send its callback, both with ``headers``. Return the
    ``redirect_uri`` of the authorize request, the ``redirect_uri`` of the
    token exchange, and the status of the callback."""
    from oidc import (
        AuthorizationRequestStore,
        LoginAllowlist,
        build_oidc_routes,
        resolve_oidc_config,
    )

    config = resolve_oidc_config(
        issuer_url=issuer.issuer,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=redirect_uri,
        allow_any_user="true",
    )
    assert config is not None
    assert config.allowlist == LoginAllowlist(allow_any=True)
    start, callback = build_oidc_routes(
        config, sessions=SessionStore(), store=AuthorizationRequestStore()
    )
    app = web.Application()
    app.router.add_get(START, start)
    app.router.add_get(CALLBACK, callback)
    async with TestClient(TestServer(app)) as client:
        started = await client.get(START, headers=headers, allow_redirects=False)
        assert started.status == 302, await started.text()
        query = parse_qs(urlsplit(started.headers["Location"]).query)
        issuer.nonce = query["nonce"][0]
        response = await client.get(
            CALLBACK,
            params={"code": "a-code", "state": query["state"][0]},
            headers=headers,
            allow_redirects=False,
        )
        await response.read()
    return (
        query["redirect_uri"][0],
        issuer.token_requests[-1]["redirect_uri"],
        response.status,
    )


_FROM_LAN = {"Host": "192.168.1.117:8188"}
_FROM_PROXY = {
    "Host": "comfy.example.com",
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "comfy.example.com",
}


class TestALoginReturnsToItsOrigin:
    @pytest.mark.parametrize(
        ("headers", "expected"), [(_FROM_LAN, LAN), (_FROM_PROXY, PROXY)]
    )
    async def test_each_origin_gets_its_own_uri_in_both_requests(
        self, headers: dict[str, str], expected: str
    ) -> None:
        async with FakeIssuer() as issuer:
            authorize, exchange, status = await _login_from(
                issuer, f"{LAN},{PROXY}", headers
            )

        assert authorize == expected
        assert exchange == expected
        assert status == 200

    async def test_the_order_of_the_list_does_not_change_the_choice(self) -> None:
        async with FakeIssuer() as issuer:
            authorize, exchange, _ = await _login_from(
                issuer, f"{PROXY},{LAN}", _FROM_LAN
            )

        assert (authorize, exchange) == (LAN, LAN)

    async def test_a_default_port_matches_an_entry_with_no_port(self) -> None:
        headers = {**_FROM_PROXY, "X-Forwarded-Host": "comfy.example.com:443"}
        async with FakeIssuer() as issuer:
            authorize, exchange, _ = await _login_from(
                issuer, f"{LAN},{PROXY}", headers
            )

        assert (authorize, exchange) == (PROXY, PROXY)

    async def test_capital_letters_in_the_host_do_not_matter(self) -> None:
        headers = {**_FROM_PROXY, "X-Forwarded-Host": "Comfy.Example.COM"}
        async with FakeIssuer() as issuer:
            authorize, _, _ = await _login_from(issuer, f"{LAN},{PROXY}", headers)

        assert authorize == PROXY

    @pytest.mark.parametrize(
        "headers",
        [
            {**_FROM_PROXY, "X-Forwarded-Host": "attacker.example"},
            {"Host": "attacker.example"},
            # The scheme is part of the origin.
            {"Host": "comfy.example.com"},
            {"Host": "192.168.1.117:8188", "X-Forwarded-Proto": "https"},
            {"Host": "192.168.1.117:not-a-port"},
        ],
    )
    async def test_an_origin_that_matches_no_entry_gets_the_first_entry(
        self, headers: dict[str, str]
    ) -> None:
        async with FakeIssuer() as issuer:
            authorize, exchange, _ = await _login_from(
                issuer, f"{LAN},{PROXY}", headers
            )

        assert (authorize, exchange) == (LAN, LAN)

    async def test_one_value_is_used_from_each_origin(self) -> None:
        async with FakeIssuer() as issuer:
            authorize, exchange, status = await _login_from(issuer, PROXY, _FROM_LAN)

        assert (authorize, exchange, status) == (PROXY, PROXY, 200)
