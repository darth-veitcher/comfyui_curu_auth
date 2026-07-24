"""Hermetic coverage for :mod:`oidc` -- the OIDC/OAuth login path's pure,
testable logic (config resolution, authorization-URL building, ID-token
verification, the callback handler), driven against a mocked provider
double via ``aiohttp.test_utils``. Mostly exercises ``oidc.py`` and
``gate.py`` directly, mirroring ``tests/test_gate.py``'s own hermetic
conventions -- except ``TestInitPyWiringIsOidcAware`` below, which loads
the real ``__init__.py`` against a minimal double of ComfyUI's own
``server`` module, because the actual routing decision US2 cares about
(are the OIDC routes registered at all?) only exists at that level.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

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

    def test_missing_redirect_uri_resolves_to_none_not_a_partial_config(
        self,
    ) -> None:
        # FR-009 / spec.md's Edge Cases: the *other* partial-config example
        # it names alongside a missing client secret -- an issuer, client
        # ID, and secret with no redirect URI must fail safe identically,
        # not start half-configured missing just the callback target.
        from oidc import resolve_oidc_config

        assert (
            resolve_oidc_config(
                issuer_url="https://idp.example.com",
                client_id="comfyui-curu-auth",
                client_secret="s3cr3t",
                redirect_uri=None,
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


# --------------------------------------------------------------------------
# Authorization-URL builder + In-Flight Auth Request store -- T013/T014.
# --------------------------------------------------------------------------

_CONFIG_KWARGS = {
    "issuer_url": "https://idp.example.com",
    "client_id": "comfyui-curu-auth",
    "client_secret": "s3cr3t",
    "redirect_uri": "https://host/curu-auth/oidc/callback",
}


class TestBuildAuthorizationUrl:
    """`build_authorization_url` must produce a redirect URL carrying
    `state`, `nonce`, and a PKCE `code_challenge`, and record the matching
    In-Flight Auth Request (data-model.md) keyed by `state` -- the PKCE
    challenge must actually derive correctly from the stored verifier
    (`base64url(sha256(verifier))`), not merely be present (strengthened
    after adversarial engineering review, 2026-07-23)."""

    def test_url_targets_the_discovery_authorization_endpoint(self) -> None:
        from urllib.parse import urlparse

        from oidc import AuthorizationRequestStore, OIDCConfig, build_authorization_url

        config = OIDCConfig(**_CONFIG_KWARGS)
        store = AuthorizationRequestStore()

        url = build_authorization_url(config, _DISCOVERY_DOCUMENT, store)

        parsed = urlparse(url)
        expected = urlparse(_DISCOVERY_DOCUMENT["authorization_endpoint"])
        assert (parsed.scheme, parsed.netloc, parsed.path) == (
            expected.scheme,
            expected.netloc,
            expected.path,
        )

    def test_query_carries_client_id_redirect_uri_response_type_and_scope(
        self,
    ) -> None:
        from urllib.parse import parse_qs, urlparse

        from oidc import AuthorizationRequestStore, OIDCConfig, build_authorization_url

        config = OIDCConfig(**_CONFIG_KWARGS)
        store = AuthorizationRequestStore()

        url = build_authorization_url(config, _DISCOVERY_DOCUMENT, store)
        query = parse_qs(urlparse(url).query)

        assert query["client_id"] == [config.client_id]
        assert query["redirect_uri"] == [config.redirect_uri]
        assert query["response_type"] == ["code"]
        assert "openid" in query["scope"][0]
        assert query["code_challenge_method"] == ["S256"]

    def test_code_challenge_actually_derives_from_the_stored_verifier(
        self,
    ) -> None:
        import base64
        import hashlib
        from urllib.parse import parse_qs, urlparse

        from oidc import AuthorizationRequestStore, OIDCConfig, build_authorization_url

        config = OIDCConfig(**_CONFIG_KWARGS)
        store = AuthorizationRequestStore()

        url = build_authorization_url(config, _DISCOVERY_DOCUMENT, store)
        query = parse_qs(urlparse(url).query)
        state = query["state"][0]
        code_challenge = query["code_challenge"][0]

        in_flight = store.peek(state)
        assert in_flight is not None
        expected_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(in_flight.pkce_verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        assert code_challenge == expected_challenge

    def test_state_and_nonce_match_the_stored_in_flight_request(self) -> None:
        from urllib.parse import parse_qs, urlparse

        from oidc import AuthorizationRequestStore, OIDCConfig, build_authorization_url

        config = OIDCConfig(**_CONFIG_KWARGS)
        store = AuthorizationRequestStore()

        url = build_authorization_url(config, _DISCOVERY_DOCUMENT, store)
        query = parse_qs(urlparse(url).query)

        in_flight = store.peek(query["state"][0])
        assert in_flight is not None
        assert in_flight.nonce == query["nonce"][0]

    def test_two_consecutive_calls_produce_distinct_state_and_nonce(self) -> None:
        from urllib.parse import parse_qs, urlparse

        from oidc import AuthorizationRequestStore, OIDCConfig, build_authorization_url

        config = OIDCConfig(**_CONFIG_KWARGS)
        store = AuthorizationRequestStore()

        url1 = build_authorization_url(config, _DISCOVERY_DOCUMENT, store)
        url2 = build_authorization_url(config, _DISCOVERY_DOCUMENT, store)
        q1 = parse_qs(urlparse(url1).query)
        q2 = parse_qs(urlparse(url2).query)

        assert q1["state"] != q2["state"]
        assert q1["nonce"] != q2["nonce"]


class TestAuthorizationRequestStoreSingleUseAndCap:
    """FR-010 (adversarial engineering review): the store's total size
    MUST be bounded -- the login-initiation route that creates entries is
    necessarily unauthenticated (public_paths), so nothing else limits
    how many entries an attacker could otherwise cause it to hold."""

    def test_pop_removes_the_entry_single_use(self) -> None:
        from oidc import AuthorizationRequestStore

        store = AuthorizationRequestStore()
        in_flight = store.create()

        first = store.pop(in_flight.state)
        second = store.pop(in_flight.state)

        assert first is not None
        assert first.state == in_flight.state
        assert second is None

    def test_pop_of_an_unknown_state_returns_none(self) -> None:
        from oidc import AuthorizationRequestStore

        store = AuthorizationRequestStore()
        assert store.pop("never-issued-state") is None

    def test_store_evicts_oldest_entries_once_the_cap_is_exceeded(self) -> None:
        from oidc import AuthorizationRequestStore

        store = AuthorizationRequestStore(max_size=3)
        first = store.create()
        store.create()
        store.create()
        store.create()  # exceeds cap of 3 -- oldest (first) must be evicted

        assert store.peek(first.state) is None
        assert len(store) == 3


# --------------------------------------------------------------------------
# ID-token verification -- T015/T016.
# --------------------------------------------------------------------------

_ISSUER = "https://idp.example.com"
_CLIENT_ID = "comfyui-curu-auth"
_KEY_ID = "test-key"


def _generate_rsa_key():
    from joserfc.jwk import RSAKey

    key = RSAKey.generate_key(2048, private=True)
    return RSAKey.import_key(key.as_dict(private=True), {"kid": _KEY_ID})


def _jwks_for(key) -> dict:
    return {"keys": [key.as_dict(private=False, kid=_KEY_ID)]}


def _sign(key, claims: dict) -> str:
    from joserfc import jwt

    return jwt.encode({"alg": "RS256", "kid": _KEY_ID}, claims, key)


def _valid_claims(*, nonce: str = "expected-nonce", **overrides) -> dict:
    import time

    now = int(time.time())
    claims = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "exp": now + 300,
        "iat": now,
        "sub": "user-123",
        "nonce": nonce,
    }
    claims.update(overrides)
    return claims


class TestVerifyIdToken:
    """`verify_id_token` fetches the provider's JWKS fresh (no cache) and
    verifies the ID token's signature and claims -- every failure mode
    (bad signature, wrong issuer/audience, wrong/missing nonce, expired,
    JWKS fetch failure) MUST raise the one `OIDCTokenVerificationError`,
    exactly mirroring `OIDCDiscoveryError`'s single-exception-type shape
    (FR-007)."""

    async def _serve_jwks(self, jwks: dict):
        """Yields (discovery, base_url) for a mocked provider serving
        `jwks` at /jwks.json."""

        async def _jwks_handler(request: web.Request) -> web.Response:
            return web.json_response(jwks)

        app = web.Application()
        app.router.add_get("/jwks.json", _jwks_handler)
        return app

    async def test_valid_token_is_accepted_and_claims_returned(self) -> None:
        from oidc import OIDCConfig, verify_id_token

        key = _generate_rsa_key()
        app = await self._serve_jwks(_jwks_for(key))

        async with TestClient(TestServer(app)) as client:
            discovery = {"jwks_uri": str(client.make_url("/jwks.json"))}
            config = OIDCConfig(
                issuer_url=_ISSUER,
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            token = _sign(key, _valid_claims())

            claims = await verify_id_token(
                token,
                config=config,
                discovery=discovery,
                expected_nonce="expected-nonce",
                timeout=5.0,
            )

        assert claims["sub"] == "user-123"
        assert claims["iss"] == _ISSUER

    async def test_wrong_signature_is_rejected(self) -> None:
        from oidc import OIDCConfig, OIDCTokenVerificationError, verify_id_token

        real_key = _generate_rsa_key()
        attacker_key = _generate_rsa_key()
        app = await self._serve_jwks(_jwks_for(real_key))

        async with TestClient(TestServer(app)) as client:
            discovery = {"jwks_uri": str(client.make_url("/jwks.json"))}
            config = OIDCConfig(
                issuer_url=_ISSUER,
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            forged_token = _sign(attacker_key, _valid_claims())

            with pytest.raises(OIDCTokenVerificationError):
                await verify_id_token(
                    forged_token,
                    config=config,
                    discovery=discovery,
                    expected_nonce="expected-nonce",
                    timeout=5.0,
                )

    async def test_wrong_audience_is_rejected(self) -> None:
        from oidc import OIDCConfig, OIDCTokenVerificationError, verify_id_token

        key = _generate_rsa_key()
        app = await self._serve_jwks(_jwks_for(key))

        async with TestClient(TestServer(app)) as client:
            discovery = {"jwks_uri": str(client.make_url("/jwks.json"))}
            config = OIDCConfig(
                issuer_url=_ISSUER,
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            token = _sign(key, _valid_claims(aud="some-other-client"))

            with pytest.raises(OIDCTokenVerificationError):
                await verify_id_token(
                    token,
                    config=config,
                    discovery=discovery,
                    expected_nonce="expected-nonce",
                    timeout=5.0,
                )

    async def test_wrong_nonce_is_rejected(self) -> None:
        from oidc import OIDCConfig, OIDCTokenVerificationError, verify_id_token

        key = _generate_rsa_key()
        app = await self._serve_jwks(_jwks_for(key))

        async with TestClient(TestServer(app)) as client:
            discovery = {"jwks_uri": str(client.make_url("/jwks.json"))}
            config = OIDCConfig(
                issuer_url=_ISSUER,
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            token = _sign(key, _valid_claims(nonce="wrong-nonce"))

            with pytest.raises(OIDCTokenVerificationError):
                await verify_id_token(
                    token,
                    config=config,
                    discovery=discovery,
                    expected_nonce="expected-nonce",
                    timeout=5.0,
                )

    async def test_expired_token_is_rejected(self) -> None:
        import time

        from oidc import OIDCConfig, OIDCTokenVerificationError, verify_id_token

        key = _generate_rsa_key()
        app = await self._serve_jwks(_jwks_for(key))

        async with TestClient(TestServer(app)) as client:
            discovery = {"jwks_uri": str(client.make_url("/jwks.json"))}
            config = OIDCConfig(
                issuer_url=_ISSUER,
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://host/curu-auth/oidc/callback",
            )
            now = int(time.time())
            token = _sign(key, _valid_claims(exp=now - 100, iat=now - 400))

            with pytest.raises(OIDCTokenVerificationError):
                await verify_id_token(
                    token,
                    config=config,
                    discovery=discovery,
                    expected_nonce="expected-nonce",
                    timeout=5.0,
                )

    async def test_jwks_fetch_failure_is_rejected(self) -> None:
        from oidc import OIDCConfig, OIDCTokenVerificationError, verify_id_token

        key = _generate_rsa_key()
        config = OIDCConfig(
            issuer_url=_ISSUER,
            client_id=_CLIENT_ID,
            client_secret="s3cr3t",
            redirect_uri="https://host/curu-auth/oidc/callback",
        )
        token = _sign(key, _valid_claims())
        # Nothing listens on this port -- a real connection failure.
        discovery = {"jwks_uri": "http://127.0.0.1:1/jwks.json"}

        with pytest.raises(OIDCTokenVerificationError):
            await verify_id_token(
                token,
                config=config,
                discovery=discovery,
                expected_nonce="expected-nonce",
                timeout=2.0,
            )


# --------------------------------------------------------------------------
# Callback handler -- T017/T018, T019/T020, T021/T022.
# --------------------------------------------------------------------------

_CALLBACK_PATH = "/curu-auth/oidc/callback"


def _mock_provider_app(key, holder: dict) -> web.Application:
    """A mocked OIDC provider serving discovery/JWKS/token -- ``holder``
    is filled in lazily (base_url isn't known until the TestServer
    actually starts) and read by the handlers via closure. ``holder["nonce"]``
    controls the nonce embedded in the minted id_token, so each test can
    simulate a callback whose in-flight nonce it controls independently.
    """

    async def _discovery_handler(request: web.Request) -> web.Response:
        base = holder["base_url"]
        return web.json_response(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/api/oidc/authorization",
                "token_endpoint": f"{base}/api/oidc/token",
                "jwks_uri": f"{base}/jwks.json",
            }
        )

    async def _jwks_handler(request: web.Request) -> web.Response:
        return web.json_response(_jwks_for(key))

    async def _token_handler(request: web.Request) -> web.Response:
        # A real OIDC provider (Authelia included) rejects a code exchange
        # missing the PKCE `code_verifier` -- or carrying a wrong one --
        # with a 400. Only enforced when a test opts in via
        # ``holder["pkce_verifier"]`` (start-route-only tests never reach
        # this handler at all, and don't set it).
        expected_verifier = holder.get("pkce_verifier")
        if expected_verifier is not None:
            body = await request.post()
            if body.get("code_verifier") != expected_verifier:
                return web.json_response({"error": "invalid_grant"}, status=400)

        claims = _valid_claims(
            nonce=holder["nonce"], iss=holder["base_url"], aud=_CLIENT_ID
        )
        id_token = _sign(key, claims)
        return web.json_response(
            {
                "access_token": "mock-access-token",
                "id_token": id_token,
                "token_type": "bearer",
                "expires_in": 3600,
            }
        )

    app = web.Application()
    app.router.add_get("/.well-known/openid-configuration", _discovery_handler)
    app.router.add_get("/jwks.json", _jwks_handler)
    app.router.add_post("/api/oidc/token", _token_handler)
    return app


class TestOidcCallbackHandler:
    """The callback handler is the one place this feature mints a
    session -- it MUST reuse the *existing* `SessionStore`/`curu_auth`
    cookie mechanism (ADR-002/FR-003), not a new one, and MUST reject a
    mismatched or already-consumed `state` (FR-011)."""

    async def test_valid_callback_establishes_a_session_via_existing_sessionstore(
        self,
    ) -> None:
        from gate import COOKIE_MAX_AGE_SECONDS, COOKIE_NAME, SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        key = _generate_rsa_key()
        holder: dict = {}
        provider_app = _mock_provider_app(key, holder)

        async with TestClient(TestServer(provider_app)) as provider_client:
            holder["base_url"] = str(provider_client.make_url("")).rstrip("/")

            config = OIDCConfig(
                issuer_url=holder["base_url"],
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri=f"https://comfyui.example{_CALLBACK_PATH}",
            )
            store = AuthorizationRequestStore()
            sessions = SessionStore()
            in_flight = store.create()
            holder["nonce"] = in_flight.nonce
            # Regression witness for the token exchange actually presenting
            # the PKCE code_verifier it promised in the authorization
            # request's code_challenge (RFC 7636) -- found live against a
            # real Authelia instance, which rejects a code exchange missing
            # it with a 400 (specs/002-oidc-login/research.md).
            holder["pkce_verifier"] = in_flight.pkce_verifier

            _start, callback = build_oidc_routes(config, sessions=sessions, store=store)
            node_app = web.Application()
            node_app.router.add_get(_CALLBACK_PATH, callback)

            async with TestClient(TestServer(node_app)) as node_client:
                response = await node_client.get(
                    _CALLBACK_PATH,
                    params={"code": "mock-auth-code", "state": in_flight.state},
                    allow_redirects=False,
                )

        assert response.status in (302, 303, 307)
        cookie = response.cookies.get(COOKIE_NAME)
        assert cookie is not None
        assert sessions.is_valid(cookie.value)
        assert cookie["max-age"] == str(COOKIE_MAX_AGE_SECONDS)
        assert cookie["httponly"]
        assert cookie["secure"]

    async def test_mismatched_state_does_not_establish_a_session(self) -> None:
        from gate import SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        key = _generate_rsa_key()
        holder: dict = {"nonce": "irrelevant"}
        provider_app = _mock_provider_app(key, holder)

        async with TestClient(TestServer(provider_app)) as provider_client:
            holder["base_url"] = str(provider_client.make_url("")).rstrip("/")

            config = OIDCConfig(
                issuer_url=holder["base_url"],
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri=f"https://comfyui.example{_CALLBACK_PATH}",
            )
            store = AuthorizationRequestStore()
            sessions = SessionStore()
            store.create()  # a real in-flight request exists, but...

            _start, callback = build_oidc_routes(config, sessions=sessions, store=store)
            node_app = web.Application()
            node_app.router.add_get(_CALLBACK_PATH, callback)

            async with TestClient(TestServer(node_app)) as node_client:
                response = await node_client.get(
                    _CALLBACK_PATH,
                    # ...the callback presents a state nobody issued.
                    params={"code": "mock-auth-code", "state": "never-issued"},
                    allow_redirects=False,
                )

        assert response.status not in (302, 303, 307)
        assert "curu_auth" not in response.cookies

    async def test_provider_error_param_does_not_establish_a_session(self) -> None:
        from gate import SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        config = OIDCConfig(
            issuer_url="https://idp.example.com",
            client_id=_CLIENT_ID,
            client_secret="s3cr3t",
            redirect_uri=f"https://comfyui.example{_CALLBACK_PATH}",
        )
        store = AuthorizationRequestStore()
        sessions = SessionStore()
        in_flight = store.create()

        _start, callback = build_oidc_routes(config, sessions=sessions, store=store)
        node_app = web.Application()
        node_app.router.add_get(_CALLBACK_PATH, callback)

        async with TestClient(TestServer(node_app)) as node_client:
            response = await node_client.get(
                _CALLBACK_PATH,
                params={
                    "error": "access_denied",
                    "state": in_flight.state,
                },
                allow_redirects=False,
            )

        assert response.status not in (302, 303, 307)
        assert "curu_auth" not in response.cookies

    async def test_replaying_a_completed_callback_verbatim_is_rejected(self) -> None:
        from gate import SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        key = _generate_rsa_key()
        holder: dict = {}
        provider_app = _mock_provider_app(key, holder)

        async with TestClient(TestServer(provider_app)) as provider_client:
            holder["base_url"] = str(provider_client.make_url("")).rstrip("/")

            config = OIDCConfig(
                issuer_url=holder["base_url"],
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri=f"https://comfyui.example{_CALLBACK_PATH}",
            )
            store = AuthorizationRequestStore()
            sessions = SessionStore()
            in_flight = store.create()
            holder["nonce"] = in_flight.nonce
            holder["pkce_verifier"] = in_flight.pkce_verifier

            _start, callback = build_oidc_routes(config, sessions=sessions, store=store)
            node_app = web.Application()
            node_app.router.add_get(_CALLBACK_PATH, callback)

            async with TestClient(TestServer(node_app)) as node_client:
                params = {"code": "mock-auth-code", "state": in_flight.state}
                first = await node_client.get(
                    _CALLBACK_PATH, params=params, allow_redirects=False
                )
                assert first.status in (302, 303, 307)

                second = await node_client.get(
                    _CALLBACK_PATH, params=params, allow_redirects=False
                )

        assert second.status not in (302, 303, 307)


# --------------------------------------------------------------------------
# Start-route rate-limit + in-flight store cap -- T026/T027 (FR-010).
# --------------------------------------------------------------------------

_START_PATH = "/curu-auth/oidc/start"


class TestOidcStartRouteIsRateLimitedAndCapped:
    """The start route sits in the public-paths bypass by necessity (it's
    reachable pre-session, the same as the login form already is) --
    found during adversarial engineering review that this left it
    unauthenticated *and* unthrottled, an unbounded resource-exhaustion
    path. MUST be subject to the same shared `RateLimiter` every other
    unauthenticated path already uses."""

    async def test_repeated_hits_from_the_same_client_are_rate_limited(
        self,
    ) -> None:
        from gate import RateLimiter, SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        holder = {"base_url": "https://idp.example.com"}
        provider_app = _mock_provider_app(_generate_rsa_key(), holder)

        async with TestClient(TestServer(provider_app)) as provider_client:
            holder["base_url"] = str(provider_client.make_url("")).rstrip("/")
            config = OIDCConfig(
                issuer_url=holder["base_url"],
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://comfyui.example/curu-auth/oidc/callback",
            )
            store = AuthorizationRequestStore()
            sessions = SessionStore()
            limiter = RateLimiter()

            start, _callback = build_oidc_routes(
                config, sessions=sessions, store=store, rate_limiter=limiter
            )
            node_app = web.Application()
            node_app.router.add_get(_START_PATH, start)

            async with TestClient(TestServer(node_app)) as node_client:
                first = await node_client.get(_START_PATH, allow_redirects=False)
                assert first.status in (302, 303, 307)

                second = await node_client.get(_START_PATH, allow_redirects=False)

        assert second.status == 429
        assert "Retry-After" in second.headers

    async def test_without_a_rate_limiter_repeated_hits_are_never_blocked(
        self,
    ) -> None:
        from gate import SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        holder = {"base_url": "https://idp.example.com"}
        provider_app = _mock_provider_app(_generate_rsa_key(), holder)

        async with TestClient(TestServer(provider_app)) as provider_client:
            holder["base_url"] = str(provider_client.make_url("")).rstrip("/")
            config = OIDCConfig(
                issuer_url=holder["base_url"],
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://comfyui.example/curu-auth/oidc/callback",
            )
            store = AuthorizationRequestStore()
            sessions = SessionStore()

            start, _callback = build_oidc_routes(config, sessions=sessions, store=store)
            node_app = web.Application()
            node_app.router.add_get(_START_PATH, start)

            async with TestClient(TestServer(node_app)) as node_client:
                for _ in range(5):
                    response = await node_client.get(_START_PATH, allow_redirects=False)
                    assert response.status in (302, 303, 307)

    async def test_the_store_used_by_the_start_route_stays_size_capped(
        self,
    ) -> None:
        from gate import SessionStore
        from oidc import AuthorizationRequestStore, OIDCConfig, build_oidc_routes

        holder = {"base_url": "https://idp.example.com"}
        provider_app = _mock_provider_app(_generate_rsa_key(), holder)

        async with TestClient(TestServer(provider_app)) as provider_client:
            holder["base_url"] = str(provider_client.make_url("")).rstrip("/")
            config = OIDCConfig(
                issuer_url=holder["base_url"],
                client_id=_CLIENT_ID,
                client_secret="s3cr3t",
                redirect_uri="https://comfyui.example/curu-auth/oidc/callback",
            )
            store = AuthorizationRequestStore(max_size=3)
            sessions = SessionStore()

            start, _callback = build_oidc_routes(config, sessions=sessions, store=store)
            node_app = web.Application()
            node_app.router.add_get(_START_PATH, start)

            async with TestClient(TestServer(node_app)) as node_client:
                # No rate_limiter here -- isolates the store's own cap
                # from rate-limiting (a distinct, independent bound).
                for _ in range(6):
                    await node_client.get(_START_PATH, allow_redirects=False)

        assert len(store) == 3


# --------------------------------------------------------------------------
# __init__.py's own wiring -- T029/T030, T031/T032 (US2).
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_init_with_fake_server(
    monkeypatch: pytest.MonkeyPatch, *, oidc_env: dict[str, str] | None = None
) -> web.Application:
    """Load this repo's own ``__init__.py`` as a real package's ``__init__``
    module against a minimal double of ComfyUI's own ``server`` module,
    and return the ``web.Application`` it wired up.

    ``__init__.py``'s ``from .gate import ...`` / ``from .oidc import
    ...`` are genuine relative imports -- they need a real parent-package
    context to resolve at all, the same one ComfyUI's custom-node loader
    gives this directory at runtime (its own docstring). A bare
    ``importlib.util.spec_from_file_location`` with no
    ``submodule_search_locations`` can't satisfy that; passing this
    repo's own root directory as the search path can, letting
    ``__init__.py`` run completely unmodified.

    Every OIDC env var is cleared first regardless of ``oidc_env`` -- the
    ambient shell environment must never leak into what this test
    considers "unconfigured".
    """

    for var in (
        "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL",
        "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID",
        "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET",
        "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI",
    ):
        monkeypatch.delenv(var, raising=False)
    for key, value in (oidc_env or {}).items():
        monkeypatch.setenv(key, value)

    app = web.Application()

    class _Instance:
        def __init__(self, app: web.Application) -> None:
            self.app = app

    class _FakePromptServer:
        instance: _Instance

    _FakePromptServer.instance = _Instance(app)

    fake_server = types.ModuleType("server")
    fake_server.PromptServer = _FakePromptServer  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "server", fake_server)

    pkg_name = "_comfyui_curu_auth_under_test"
    for name in (pkg_name, f"{pkg_name}.gate", f"{pkg_name}.oidc"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    spec = importlib.util.spec_from_file_location(
        pkg_name,
        _REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(_REPO_ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, pkg_name, module)
    spec.loader.exec_module(module)
    return app


def _registered_paths(app: web.Application) -> set[str]:
    return {
        route.resource.canonical
        for route in app.router.routes()
        if route.resource is not None
    }


class TestInitPyWiringIsOidcAware:
    """``__init__.py`` is this project's real ComfyUI entrypoint -- the
    one place that decides, from the environment, whether OIDC routes
    exist at all (US2/FR-002/FR-004/FR-009). References the feature
    file's "No OIDC routes or behavior when unconfigured" and "Existing
    credential and login form are unaffected" scenarios."""

    def test_no_oidc_routes_when_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _load_init_with_fake_server(monkeypatch)

        paths = _registered_paths(app)
        assert "/curu-auth/oidc/start" not in paths
        assert "/curu-auth/oidc/callback" not in paths

    def test_oidc_routes_exist_when_fully_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _load_init_with_fake_server(
            monkeypatch,
            oidc_env={
                "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": "https://idp.example.com",
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": "client-id",
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": "s3cr3t",
                "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": (
                    "https://comfyui.example/curu-auth/oidc/callback"
                ),
            },
        )

        paths = _registered_paths(app)
        assert "/curu-auth/oidc/start" in paths
        assert "/curu-auth/oidc/callback" in paths

    async def test_login_page_has_no_oidc_option_when_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _load_init_with_fake_server(monkeypatch)

        async with TestClient(TestServer(app)) as client:
            response = await client.get(LOGIN_PATH)
            body = await response.text()

        assert "identity provider" not in body

    async def test_login_page_has_oidc_option_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _load_init_with_fake_server(
            monkeypatch,
            oidc_env={
                "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": "https://idp.example.com",
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": "client-id",
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": "s3cr3t",
                "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": (
                    "https://comfyui.example/curu-auth/oidc/callback"
                ),
            },
        )

        async with TestClient(TestServer(app)) as client:
            response = await client.get(LOGIN_PATH)
            body = await response.text()

        assert "identity provider" in body
