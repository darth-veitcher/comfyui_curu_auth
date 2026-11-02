"""Hermetic tests of spec 003: the OIDC login works with rauthy, Authentik and
other providers (issue #13, ADR-007).

Each test runs the real ``oidc.py`` against :class:`FakeIssuer` on a loopback
port. The scenario names come from
``specs/003-oidc-provider-fixes/features/oidc_provider_fixes.feature``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import ClientResponse, web
from aiohttp.test_utils import TestClient, TestServer

from gate import LOGIN_PATH, RateLimiter, SessionStore, build_gate_middleware
from tests.support.fake_issuer import CLIENT_ID, CLIENT_SECRET, FakeIssuer

START = "/curu-auth/oidc/start"
CALLBACK = "/curu-auth/oidc/callback"


async def _home(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def _config(issuer: FakeIssuer, **extra: Any) -> Any:
    """A config for ``issuer``. Unless a test gives an allowlist, any user may
    log in: most tests here are about the provider, not about who logs in."""
    from oidc import LoginAllowlist, OIDCConfig

    extra.setdefault("allowlist", LoginAllowlist(allow_any=True))
    return OIDCConfig(
        issuer_url=issuer.issuer,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=f"http://127.0.0.1{CALLBACK}",
        **extra,
    )


async def _login(
    issuer: FakeIssuer,
    *,
    rate_limiter: RateLimiter | None = None,
    **config_extra: Any,
) -> ClientResponse:
    """Run start, then the callback, through a real gate. Return the callback."""
    from oidc import AuthorizationRequestStore, build_oidc_routes

    sessions = SessionStore()
    start, callback = build_oidc_routes(
        _config(issuer, **config_extra),
        sessions=sessions,
        store=AuthorizationRequestStore(),
        rate_limiter=rate_limiter,
    )
    gate = build_gate_middleware(
        "static-credential",
        sessions=sessions,
        public_paths={LOGIN_PATH, START, CALLBACK},
    )
    app = web.Application(middlewares=[gate])
    app.router.add_get("/", _home)
    app.router.add_get(START, start)
    app.router.add_get(CALLBACK, callback)
    async with TestClient(TestServer(app)) as client:
        started = await client.get(START, allow_redirects=False)
        assert started.status == 302, await started.text()
        query = parse_qs(urlsplit(started.headers["Location"]).query)
        issuer.nonce = query["nonce"][0]
        response = await client.get(
            CALLBACK,
            params={"code": "a-code", "state": query["state"][0]},
            allow_redirects=False,
        )
        # Read the body while the client is open: a good callback answers a
        # page, not a redirect (tests/test_oidc.py).
        await response.read()
        return response


def _session_cookie(response: ClientResponse) -> str | None:
    for value in response.headers.getall("Set-Cookie", []):
        if value.startswith("curu_auth="):
            return value.split(";", 1)[0].split("=", 1)[1]
    return None


# --------------------------------------------------------------------------
# User story 1: log in through rauthy or Authentik.
# --------------------------------------------------------------------------


class TestTheIssuerIsUsedExactly:
    """Scenarios: An issuer with a slash at the end; The iss of the ID token is
    the configured issuer; A discovery document that names another issuer."""

    @pytest.mark.parametrize(
        "issuer",
        ["http://h/auth/v1/", "http://h/auth/v1", "http://h/auth/v1//"],
    )
    def test_the_discovery_url_has_no_double_slash(self, issuer: str) -> None:
        from oidc import discovery_url

        assert discovery_url(issuer) == (
            "http://h/auth/v1/.well-known/openid-configuration"
        )

    async def test_the_document_of_an_issuer_that_ends_in_a_slash_is_read(
        self,
    ) -> None:
        from oidc import fetch_discovery_document

        async with FakeIssuer() as issuer:
            configured = issuer.issuer
            document = await fetch_discovery_document(configured)

        assert document["issuer"] == configured
        assert configured.endswith("/")

    async def test_a_document_that_names_another_issuer_is_refused(self) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        async with FakeIssuer() as issuer:
            configured = issuer.issuer
            issuer.discovery_overrides["issuer"] = configured.rstrip("/")
            with pytest.raises(OIDCDiscoveryError) as refused:
                await fetch_discovery_document(configured)

        # The error names both values, so the operator can copy the right one.
        assert repr(configured) in str(refused.value)
        assert repr(configured.rstrip("/")) in str(refused.value)

    async def test_a_login_with_another_issuer_in_the_document_gets_503(
        self,
    ) -> None:
        async with FakeIssuer() as issuer:
            issuer.discovery_overrides["issuer"] = "https://other.example/"
            from oidc import AuthorizationRequestStore, build_oidc_routes

            start, _callback = build_oidc_routes(
                _config(issuer),
                sessions=SessionStore(),
                store=AuthorizationRequestStore(),
            )
            app = web.Application()
            app.router.add_get(START, start)
            async with TestClient(TestServer(app)) as client:
                response = await client.get(START, allow_redirects=False)

        assert response.status == 503

    async def test_a_login_through_an_issuer_that_ends_in_a_slash_works(
        self,
    ) -> None:
        async with FakeIssuer() as issuer:
            response = await _login(issuer)

        assert response.status == 200, await response.text()
        assert _session_cookie(response)

    async def test_a_login_through_an_issuer_with_no_slash_works(self) -> None:
        async with FakeIssuer(trailing_slash=False) as issuer:
            response = await _login(issuer)

        assert response.status == 200, await response.text()
        assert _session_cookie(response)

    async def test_an_iss_without_the_slash_of_the_issuer_is_refused(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.login_claims["iss"] = issuer.issuer.rstrip("/")
            response = await _login(issuer)

        assert response.status == 401
        assert _session_cookie(response) is None


class TestTheKeySetsTheAlgorithm:
    """Scenario: An EdDSA ID token. ES256 and RS256 too, and a JWK with no
    ``alg``, where the key type sets the algorithm."""

    @pytest.mark.parametrize("publish_alg", [True, False])
    @pytest.mark.parametrize("kid", ["rsa-1", "ec-1", "ed-1"])
    async def test_the_gate_accepts_the_token(
        self, kid: str, publish_alg: bool
    ) -> None:
        async with FakeIssuer(publish_alg=publish_alg) as issuer:
            issuer.login_kid = kid
            response = await _login(issuer)

        assert response.status == 200, await response.text()
        assert _session_cookie(response)

    @pytest.mark.parametrize("alg", ["RS384", "RS512", "PS256"])
    async def test_each_other_allowed_rsa_algorithm_logs_in(self, alg: str) -> None:
        """These need ``alg`` in the JWK: an RSA key alone means RS256."""
        async with FakeIssuer() as issuer:
            issuer.add_key("rsa-x", alg)
            issuer.login_kid = "rsa-x"
            response = await _login(issuer)

        assert response.status == 200, await response.text()
        assert _session_cookie(response)


# --------------------------------------------------------------------------
# User story 3: the gate refuses an unsafe provider or token.
# --------------------------------------------------------------------------


async def _verify(issuer: FakeIssuer, token: str) -> dict[str, Any]:
    """Check ``token`` as the callback does, with the nonce of the issuer."""
    from oidc import fetch_discovery_document, verify_id_token

    discovery = await fetch_discovery_document(issuer.issuer)
    return await verify_id_token(
        token, config=_config(issuer), discovery=discovery, expected_nonce=issuer.nonce
    )


class TestTheGateRefusesUnsafeAlgorithms:
    """Scenarios: alg none; Key confusion; The HS256 reason."""

    async def test_alg_none_is_refused_before_the_jwks_is_read(self) -> None:
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            with pytest.raises(OIDCTokenVerificationError):
                await _verify(issuer, issuer.none_token())
            reads = issuer.jwks_reads

        assert reads == 0

    async def test_hs256_signed_with_the_public_key_is_refused(self) -> None:
        """The key-confusion attack: the public key as the HMAC secret."""
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            token = issuer.hs256_token(issuer.public_pem("rsa-1"))
            with pytest.raises(OIDCTokenVerificationError):
                await _verify(issuer, token)
            reads = issuer.jwks_reads

        assert reads == 0

    async def test_the_hs256_reason_names_the_signing_key_of_authentik(
        self,
    ) -> None:
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            token = issuer.hs256_token(CLIENT_SECRET.encode())
            with pytest.raises(OIDCTokenVerificationError) as refused:
                await _verify(issuer, token)

        assert "HS256" in refused.value.reason
        assert "Authentik" in refused.value.reason
        assert "signing key" in refused.value.reason

    @pytest.mark.parametrize("alg", ["HS384", "HS512", "None", "ES512", "RS1"])
    async def test_each_other_algorithm_is_refused(self, alg: str) -> None:
        import base64
        import json

        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            _header, _, rest = issuer.id_token(kid="rsa-1").partition(".")
            header = json.dumps({"alg": alg, "kid": "rsa-1"}).encode()
            forged = base64.urlsafe_b64encode(header).rstrip(b"=").decode()
            with pytest.raises(OIDCTokenVerificationError):
                await _verify(issuer, f"{forged}.{rest}")
            reads = issuer.jwks_reads

        assert reads == 0

    async def test_a_header_alg_that_is_not_the_key_alg_is_refused(self) -> None:
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            # A valid RS384 signature by the private key of "rsa-1", whose JWK
            # says RS256. A gate that trusted the header would accept it; only
            # the rule "the header alg is the key alg" refuses it.
            token = issuer.id_token(kid="rsa-1", sign_alg="RS384")
            with pytest.raises(OIDCTokenVerificationError) as refused:
                await _verify(issuer, token)

        assert "not the key algorithm" in refused.value.reason

    async def test_an_unknown_kid_is_refused(self) -> None:
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            token = issuer.id_token(kid="ec-1", header={"kid": "nobody"})
            with pytest.raises(OIDCTokenVerificationError):
                await _verify(issuer, token)


ENDPOINTS = ["authorization_endpoint", "token_endpoint", "jwks_uri"]


class TestTheDiscoveryDocumentIsChecked:
    """Scenario: An http endpoint."""

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    async def test_an_http_endpoint_off_loopback_is_refused(
        self, endpoint: str
    ) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        async with FakeIssuer() as issuer:
            issuer.discovery_overrides[endpoint] = "http://idp.example.com/x"
            with pytest.raises(OIDCDiscoveryError) as refused:
                await fetch_discovery_document(issuer.issuer)

        assert endpoint in str(refused.value)

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    async def test_a_missing_endpoint_is_refused(self, endpoint: str) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        async with FakeIssuer() as issuer:
            issuer.discovery_overrides[endpoint] = None
            with pytest.raises(OIDCDiscoveryError):
                await fetch_discovery_document(issuer.issuer)

    @pytest.mark.parametrize(
        "url",
        [
            "https://idp.example.com/x",
            "http://localhost:9/x",
            "http://127.0.0.1:9/x",
            "http://[::1]:9/x",
        ],
    )
    async def test_https_and_loopback_http_are_accepted(self, url: str) -> None:
        from oidc import fetch_discovery_document

        async with FakeIssuer() as issuer:
            issuer.discovery_overrides["authorization_endpoint"] = url
            document = await fetch_discovery_document(issuer.issuer)

        assert document["authorization_endpoint"] == url

    async def test_an_http_endpoint_off_loopback_stops_the_login(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.discovery_overrides["token_endpoint"] = "http://idp.example.com/t"
            from oidc import AuthorizationRequestStore, build_oidc_routes

            start, _callback = build_oidc_routes(
                _config(issuer),
                sessions=SessionStore(),
                store=AuthorizationRequestStore(),
            )
            app = web.Application()
            app.router.add_get(START, start)
            async with TestClient(TestServer(app)) as client:
                response = await client.get(START, allow_redirects=False)

        assert response.status == 503


class TestTheClaimsOfAnIdToken:
    """Scenarios: No exp or no iat; A wrong azp; The clock leeway."""

    @pytest.mark.parametrize("claim", ["exp", "iat"])
    async def test_a_token_with_no_exp_or_no_iat_is_refused(self, claim: str) -> None:
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            missing: dict[str, Any] = {claim: None}
            token = issuer.id_token(**missing)
            with pytest.raises(OIDCTokenVerificationError):
                await _verify(issuer, token)

    @pytest.mark.parametrize(
        ("aud", "azp", "accepted"),
        [
            ([CLIENT_ID, "other-client"], "other-client", False),
            ([CLIENT_ID, "other-client"], None, False),
            ([CLIENT_ID, "other-client"], CLIENT_ID, True),
            (CLIENT_ID, "other-client", False),
            (CLIENT_ID, CLIENT_ID, True),
            ([CLIENT_ID], None, True),
        ],
    )
    async def test_azp_must_be_the_client_id(
        self, aud: Any, azp: str | None, accepted: bool
    ) -> None:
        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            token = issuer.id_token(aud=aud, azp=azp)
            if accepted:
                claims = await _verify(issuer, token)
                assert claims["aud"] == aud
            else:
                with pytest.raises(OIDCTokenVerificationError):
                    await _verify(issuer, token)

    @pytest.mark.parametrize(
        ("exp_offset", "iat_offset", "accepted"),
        [
            (-30, -330, True),
            (-90, -390, False),
            (300, 30, True),
            (300, 90, False),
        ],
    )
    async def test_the_clock_leeway_is_60_seconds(
        self, exp_offset: int, iat_offset: int, accepted: bool
    ) -> None:
        import time

        from oidc import OIDCTokenVerificationError

        now = int(time.time())
        async with FakeIssuer() as issuer:
            token = issuer.id_token(exp=now + exp_offset, iat=now + iat_offset)
            if accepted:
                await _verify(issuer, token)
            else:
                with pytest.raises(OIDCTokenVerificationError):
                    await _verify(issuer, token)


# --------------------------------------------------------------------------
# User story 2: only the allowed people get a session.
# --------------------------------------------------------------------------


def _allowlist(**fields: Any) -> Any:
    from oidc import LoginAllowlist

    return LoginAllowlist(**fields)


class TestTheAllowlist:
    """Scenarios: A listed subject; A subject that is not listed; An email that
    is not verified; An allowed domain; Any user."""

    @pytest.mark.parametrize(
        ("fields", "claims", "permitted"),
        [
            ({"subjects": frozenset({"user-1"})}, {"sub": "user-1"}, True),
            ({"subjects": frozenset({"user-1"})}, {"sub": "user-2"}, False),
            ({"subjects": frozenset({"user-1"})}, {"sub": "USER-1"}, False),
            (
                {"emails": frozenset({"ann@example.com"})},
                {"sub": "x", "email": "Ann@Example.com", "email_verified": True},
                True,
            ),
            (
                {"emails": frozenset({"ann@example.com"})},
                {"sub": "x", "email": "ann@example.com", "email_verified": False},
                False,
            ),
            (
                {"emails": frozenset({"ann@example.com"})},
                {"sub": "x", "email": "ann@example.com"},
                False,
            ),
            (
                {"emails": frozenset({"ann@example.com"})},
                {"sub": "x", "email": "ann@example.com", "email_verified": "true"},
                True,
            ),
            ({"domain": "example.com"}, {"sub": "x", "hd": "Example.com"}, True),
            ({"domain": "example.com"}, {"sub": "x", "hd": "evil.com"}, False),
            (
                {"domain": "example.com"},
                {"sub": "x", "email": "a@example.com", "email_verified": True},
                False,
            ),
            ({"allow_any": True}, {"sub": "anyone"}, True),
            ({}, {"sub": "anyone"}, False),
        ],
    )
    def test_permits(
        self, fields: dict[str, Any], claims: dict[str, Any], permitted: bool
    ) -> None:
        assert _allowlist(**fields).permits(claims) is permitted

    async def test_a_listed_subject_gets_a_session(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.login_claims = {"sub": "user-1"}
            response = await _login(
                issuer, allowlist=_allowlist(subjects=frozenset({"user-1"}))
            )

        assert response.status == 200
        assert _session_cookie(response)

    async def test_a_subject_that_is_not_listed_gets_401_a_log_line_and_a_backoff(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        limiter = RateLimiter()
        async with FakeIssuer() as issuer:
            issuer.login_claims = {"sub": "intruder"}
            with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
                response = await _login(
                    issuer,
                    rate_limiter=limiter,
                    allowlist=_allowlist(subjects=frozenset({"user-1"})),
                )

        assert response.status == 401
        assert _session_cookie(response) is None
        lines = [r.getMessage() for r in caplog.records]
        assert any(
            line.startswith("comfyui_curu_auth: authentication failure from 127.0.0.1")
            and "not on the allowlist" in line
            for line in lines
        ), lines
        # The log line names no subject: the reason only.
        assert not any("intruder" in line for line in lines)
        assert limiter.seconds_until_retry("127.0.0.1") > 0

    async def test_an_email_that_is_not_verified_gets_401(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.login_claims = {
                "sub": "x",
                "email": "ann@example.com",
                "email_verified": False,
            }
            response = await _login(
                issuer, allowlist=_allowlist(emails=frozenset({"ann@example.com"}))
            )

        assert response.status == 401

    async def test_an_allowed_domain_gets_a_session(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.login_claims = {"sub": "x", "hd": "example.com"}
            response = await _login(issuer, allowlist=_allowlist(domain="example.com"))

        assert response.status == 200
        assert _session_cookie(response)

    async def test_with_no_allowlist_in_the_config_nobody_gets_a_session(
        self,
    ) -> None:
        from oidc import LoginAllowlist, OIDCConfig

        assert (
            OIDCConfig(
                issuer_url="https://idp.example.com/",
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri="https://h/cb",
            ).allowlist
            == LoginAllowlist()
        )
        async with FakeIssuer() as issuer:
            response = await _login(issuer, allowlist=LoginAllowlist())

        assert response.status == 401


_FULL: dict[str, Any] = {
    "issuer_url": "https://idp.example.com/",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": "https://h/curu-auth/oidc/callback",
}


class TestTheSettingsOfTheAllowlist:
    """Scenario: No allowlist (the resolver half)."""

    def test_a_full_setup_with_no_allowlist_is_an_error(self) -> None:
        from oidc import OIDCConfigError, resolve_oidc_config

        with pytest.raises(OIDCConfigError) as refused:
            resolve_oidc_config(**_FULL)

        assert "COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS" in str(refused.value)
        assert "COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true" in str(refused.value)

    @pytest.mark.parametrize("value", ["false", "1", "yes", "", " "])
    def test_only_true_lets_any_user_in(self, value: str) -> None:
        from oidc import OIDCConfigError, resolve_oidc_config

        with pytest.raises(OIDCConfigError):
            resolve_oidc_config(**_FULL, allow_any_user=value)

    @pytest.mark.parametrize("value", ["true", "TRUE", " True "])
    def test_true_lets_any_user_in(self, value: str) -> None:
        from oidc import resolve_oidc_config

        config = resolve_oidc_config(**_FULL, allow_any_user=value)
        assert config is not None
        assert config.allowlist.allow_any is True

    def test_the_lists_are_read_with_commas_and_spaces(self) -> None:
        from oidc import resolve_oidc_config

        config = resolve_oidc_config(
            **_FULL,
            allowed_subjects=" a , b,,c ",
            allowed_emails="Ann@Example.com, bob@example.com",
            allowed_domain=" Example.com ",
        )

        assert config is not None
        assert config.allowlist.subjects == frozenset({"a", "b", "c"})
        assert config.allowlist.emails == frozenset(
            {"ann@example.com", "bob@example.com"}
        )
        assert config.allowlist.domain == "example.com"
        assert config.allowlist.allow_any is False

    def test_a_partial_setup_is_still_unconfigured(self) -> None:
        from oidc import resolve_oidc_config

        partial = {**_FULL, "client_secret": ""}
        assert resolve_oidc_config(**partial, allow_any_user="true") is None


class TestStartWithNoAllowlist:
    """Scenario: No allowlist. ComfyUI starts, the OIDC routes do not exist,
    and the credential gate stays on."""

    def test_no_oidc_route_and_the_gate_stays_on(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from tests.test_oidc import _load_init_with_fake_server, _registered_paths

        with caplog.at_level("ERROR", logger="comfyui_curu_auth"):
            app = _load_init_with_fake_server(
                monkeypatch,
                oidc_env={
                    "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": "https://idp.example.com/",
                    "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": CLIENT_ID,
                    "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": CLIENT_SECRET,
                    "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": f"https://h{CALLBACK}",
                },
            )

        paths = _registered_paths(app)
        assert START not in paths
        assert CALLBACK not in paths
        assert LOGIN_PATH in paths
        assert len(app.middlewares) == 1
        assert any(
            "COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER" in r.getMessage()
            for r in caplog.records
        )

    def test_an_allowlist_turns_the_login_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.test_oidc import _load_init_with_fake_server, _registered_paths

        app = _load_init_with_fake_server(
            monkeypatch,
            oidc_env={
                "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": "https://idp.example.com/",
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": CLIENT_ID,
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": CLIENT_SECRET,
                "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": f"https://h{CALLBACK}",
                "COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS": "user-1",
            },
        )

        assert {START, CALLBACK} <= _registered_paths(app)


# --------------------------------------------------------------------------
# User story 4: set the scopes of the login.
# --------------------------------------------------------------------------


class TestTheScopes:
    """Scenarios: The default scopes; A scopes setting."""

    @pytest.mark.parametrize(
        ("setting", "expected"),
        [
            (None, ("openid", "profile", "email")),
            ("", ("openid", "profile", "email")),
            ("profile", ("openid", "profile")),
            ("openid,email", ("openid", "email")),
            ("email openid", ("openid", "email")),
            ("profile, profile groups", ("openid", "profile", "groups")),
        ],
    )
    def test_the_setting_always_includes_openid(
        self, setting: str | None, expected: tuple[str, ...]
    ) -> None:
        from oidc import resolve_oidc_config

        config = resolve_oidc_config(**_FULL, allow_any_user="true", scopes=setting)

        assert config is not None
        assert config.scopes == expected

    @pytest.mark.parametrize(
        ("scopes", "expected"),
        [
            (None, "openid profile email"),
            (("openid", "profile"), "openid profile"),
        ],
    )
    def test_the_authorization_url_asks_for_the_scopes(
        self, scopes: tuple[str, ...] | None, expected: str
    ) -> None:
        from oidc import (
            AuthorizationRequestStore,
            LoginAllowlist,
            OIDCConfig,
            build_authorization_url,
        )

        extra: dict[str, Any] = {} if scopes is None else {"scopes": scopes}
        config = OIDCConfig(**_FULL, allowlist=LoginAllowlist(), **extra)
        url = build_authorization_url(
            config,
            {"authorization_endpoint": "https://idp.example.com/authorize"},
            AuthorizationRequestStore(),
        )

        assert parse_qs(urlsplit(url).query)["scope"] == [expected]

    async def test_init_reads_the_scopes_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.test_oidc import _load_init_with_fake_server

        async with FakeIssuer() as issuer:
            app = _load_init_with_fake_server(
                monkeypatch,
                oidc_env={
                    "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": issuer.issuer,
                    "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": CLIENT_ID,
                    "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": CLIENT_SECRET,
                    "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": f"https://h{CALLBACK}",
                    "COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER": "true",
                    "COMFYUI_CURU_AUTH_OIDC_SCOPES": "profile groups",
                },
            )
            async with TestClient(TestServer(app)) as client:
                response = await client.get(START, allow_redirects=False)

        assert response.status == 302
        query = parse_qs(urlsplit(response.headers["Location"]).query)
        assert query["scope"] == ["openid profile groups"]


# --------------------------------------------------------------------------
# Review of spec 003: the issuer scheme, a bad key set, redirects, the log.
# --------------------------------------------------------------------------


class TestTheIssuerMustUseHttps:
    """The discovery document comes from the issuer, so the issuer itself needs
    the same https rule as the endpoints in it."""

    @pytest.mark.parametrize(
        "issuer", ["http://idp.lan/", "http://10.0.0.5/auth/v1/", "ftp://idp/"]
    )
    def test_an_http_issuer_off_loopback_is_a_setup_error(self, issuer: str) -> None:
        from oidc import OIDCConfigError, resolve_oidc_config

        with pytest.raises(OIDCConfigError) as refused:
            resolve_oidc_config(
                **{**_FULL, "issuer_url": issuer}, allow_any_user="true"
            )

        assert "https" in str(refused.value)

    @pytest.mark.parametrize(
        "issuer",
        [
            "https://idp.example.com/",
            "http://127.0.0.1:8080/auth/v1/",
            "http://localhost/",
        ],
    )
    def test_https_and_loopback_issuers_are_accepted(self, issuer: str) -> None:
        from oidc import resolve_oidc_config

        config = resolve_oidc_config(
            **{**_FULL, "issuer_url": issuer}, allow_any_user="true"
        )
        assert config is not None
        assert config.issuer_url == issuer


class TestABadKeySetIsARefusedLogin:
    """A malformed JWKS must give 401, a failure log line and a backoff, not 500."""

    @pytest.mark.parametrize(
        "jwks",
        [
            {"keys": [{"kty": "nonsense", "kid": "rsa-1"}]},
            {"keys": [{"kty": "RSA", "kid": "rsa-1"}]},
            [],
            {},
            "not a key set",
        ],
    )
    async def test_the_callback_refuses_and_logs(
        self, jwks: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        limiter = RateLimiter()
        async with FakeIssuer() as issuer:
            issuer.jwks_override = jwks
            with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
                response = await _login(issuer, rate_limiter=limiter)

        assert response.status == 401
        assert any(
            "authentication failure from 127.0.0.1 (oidc callback: " in r.getMessage()
            and "id_token" not in r.getMessage()
            for r in caplog.records
        ), [r.getMessage() for r in caplog.records]
        assert limiter.seconds_until_retry("127.0.0.1") > 0


class TestTheGateFollowsNoRedirect:
    """A redirect could move a request to plain http, or send the client secret
    to another host."""

    async def test_a_jwks_uri_that_redirects_is_refused(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.discovery_overrides["jwks_uri"] = (
                f"{issuer.base_url}/issuer/jwks-moved"
            )
            response = await _login(issuer)

        assert response.status == 401

    async def test_a_token_endpoint_that_redirects_gets_no_secret(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.discovery_overrides["token_endpoint"] = (
                f"{issuer.base_url}/issuer/token-moved"
            )
            response = await _login(issuer)

        assert response.status == 401


class TestTheReasonHoldsNoTokenData:
    async def test_an_hmac_alg_with_a_line_break_cannot_forge_a_log_line(
        self,
    ) -> None:
        import base64
        import json

        from oidc import OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            _header, _, rest = issuer.id_token().partition(".")
            header = json.dumps({"alg": "HS256\nforged line", "kid": "rsa-1"}).encode()
            forged = base64.urlsafe_b64encode(header).rstrip(b"=").decode()
            with pytest.raises(OIDCTokenVerificationError) as refused:
                await _verify(issuer, f"{forged}.{rest}")

        assert "\n" not in refused.value.reason
        assert "forged" not in refused.value.reason


class TestABadDiscoveryDocumentIsLoggedAtStart:
    """The start route gives 503 for a bad discovery document. The operator
    must see why in the log, with both issuer values."""

    async def test_the_start_route_logs_the_two_issuers(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from oidc import AuthorizationRequestStore, build_oidc_routes

        async with FakeIssuer() as issuer:
            configured = issuer.issuer
            issuer.discovery_overrides["issuer"] = configured.rstrip("/")
            start, _callback = build_oidc_routes(
                _config(issuer),
                sessions=SessionStore(),
                store=AuthorizationRequestStore(),
            )
            app = web.Application()
            app.router.add_get(START, start)
            with caplog.at_level("ERROR", logger="comfyui_curu_auth"):
                async with TestClient(TestServer(app)) as client:
                    response = await client.get(START, allow_redirects=False)

        assert response.status == 503
        messages = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any(
            repr(configured) in m and repr(configured.rstrip("/")) in m
            for m in messages
        ), messages
        # Not an authentication failure: fail2ban must not ban for a setup error.
        assert not any("authentication failure" in m for m in messages)
