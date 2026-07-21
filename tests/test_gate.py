"""Hermetic coverage for :mod:`gate` -- the gate's pure,
testable logic (credential generation, the constant-time comparison, and
the aiohttp middleware factory function), driven against a real, minimal
``aiohttp.web.Application`` via ``aiohttp.test_utils``.
Never imports ``__init__`` (this package's own ComfyUI entrypoint, which
requires a real ComfyUI ``server`` module) -- only ``gate.py`` itself.
"""

from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from gate import (
    COOKIE_NAME,
    LOGIN_PATH,
    RateLimiter,
    SessionStore,
    _client_key,
    build_gate_middleware,
    build_login_routes,
    generate_credential,
)

# --------------------------------------------------------------------------
# generate_credential -- T004.
# --------------------------------------------------------------------------


class TestGenerateCredential:
    def test_returns_a_non_empty_string(self) -> None:
        credential = generate_credential()
        assert isinstance(credential, str)
        assert credential != ""

    def test_two_consecutive_calls_differ(self) -> None:
        assert generate_credential() != generate_credential()


# --------------------------------------------------------------------------
# build_gate_middleware -- T005.
# --------------------------------------------------------------------------


async def _ok_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


class TestBuildGateMiddleware:
    async def test_missing_credential_is_rejected(self) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/anything")
            assert response.status == 401
            body = await response.json()
            assert body == {"detail": "missing or invalid credential"}

    async def test_wrong_credential_is_rejected_with_the_same_body(self) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/anything", headers={"Authorization": "Bearer wrong-token"}
            )
            assert response.status == 401
            body = await response.json()
            assert body == {"detail": "missing or invalid credential"}

    async def test_correct_credential_reaches_the_real_handler(self) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert response.status == 200
            body = await response.json()
            assert body == {"ok": True}


class TestUnauthenticatedBrowserNavigationRedirectsToLogin:
    """A human opening any gated page directly (no cookie, no header yet)
    should land on the login form, not a bare JSON 401 they'd have no way
    to act on without already knowing `/curu-auth/login` exists.
    Distinguished from an automated API client (XHR/fetch calls, and the
    `/ws` handshake) by `Accept: text/html` -- the same signal-based
    approach many web frameworks use for exactly this "browser page load
    vs. API call" distinction. Neither an automated Bearer-header HTTP
    client nor a WebSocket handshake ever sends that header, so this
    never fires for either of them."""

    async def test_a_browser_style_get_redirects_to_the_login_page(self) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/anything",
                headers={"Accept": "text/html,application/xhtml+xml"},
                allow_redirects=False,
            )
            assert response.status == 302
            assert response.headers["Location"] == LOGIN_PATH

    async def test_a_plain_api_style_get_still_gets_a_bare_401(self) -> None:
        """No `Accept: text/html` at all (curu's own client's own real
        shape) -- unaffected by the redirect addition."""

        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/anything", headers={"Accept": "*/*"})
            assert response.status == 401
            body = await response.json()
            assert body == {"detail": "missing or invalid credential"}

    async def test_a_websocket_handshake_still_gets_a_bare_401_not_a_redirect(
        self,
    ) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/ws", _ws_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/ws")
            assert response.status == 401


# --------------------------------------------------------------------------
# The middleware covers a websocket route's own initial handshake, not
# only plain HTTP routes -- a load-bearing claim.
# --------------------------------------------------------------------------


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"hello": "world"})
    await ws.close()
    return ws


class TestMiddlewareCoversWebsocketRoute:
    async def test_connection_with_no_credential_is_rejected_before_upgrade(
        self,
    ) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/ws", _ws_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/ws")

        # The middleware's plain JSON 401 response, never an upgraded
        # websocket connection -- the handshake never even starts.
        assert response.status == 401
        assert response.headers.get("Upgrade") is None

    async def test_connection_with_the_correct_credential_succeeds(self) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/ws", _ws_handler)

        async with (
            TestClient(TestServer(app)) as client,
            client.ws_connect(
                "/ws", headers={"Authorization": "Bearer expected-token"}
            ) as ws,
        ):
            message = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert message == {"hello": "world"}


# --------------------------------------------------------------------------
# Browser login flow -- a human opening ComfyUI's own UI directly has no
# way to attach an Authorization header, so the gate now also accepts a
# session cookie set by a dedicated login form, without weakening or
# changing curu's own Bearer-header path at all.
# --------------------------------------------------------------------------


def _app_with_login(
    credential: str,
    rate_limiter: RateLimiter | None = None,
    sessions: SessionStore | None = None,
):
    sessions = sessions if sessions is not None else SessionStore()
    app = web.Application(
        middlewares=[build_gate_middleware(credential, sessions=sessions)]
    )
    app.router.add_get("/anything", _ok_handler)
    login_get, login_post = build_login_routes(
        credential, sessions=sessions, rate_limiter=rate_limiter
    )
    app.router.add_get(LOGIN_PATH, login_get)
    app.router.add_post(LOGIN_PATH, login_post)
    return app


class TestLoginPathIsAlwaysReachable:
    async def test_the_login_form_itself_needs_no_credential(self) -> None:
        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            response = await client.get(LOGIN_PATH)
            assert response.status == 200
            assert "text/html" in response.headers["Content-Type"]

    async def test_the_form_pairs_a_username_field_with_the_password_field(
        self,
    ) -> None:
        # A password-only form does not reliably trigger a browser's own
        # "save password?" prompt -- Chrome/Firefox/Safari's autofill
        # heuristics look for a username-like field immediately preceding
        # a password field within the same form (verified against
        # TScriptDoc/ComfyUI-Authenticator's own login.html, which does
        # exactly this and is known to trigger the prompt). curu's own
        # credential scheme has no separate username concept -- the fix
        # is a fixed, hidden identity field paired with the real
        # credential field, not a second secret the server checks.
        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            response = await client.get(LOGIN_PATH)
            body = await response.text()

        username_pos = body.find('autocomplete="username"')
        password_pos = body.find('autocomplete="current-password"')
        assert username_pos != -1
        assert password_pos != -1
        assert username_pos < password_pos, (
            "username field must precede the password field for browser "
            "autofill heuristics to pair them"
        )


class TestLoginSubmission:
    """Asserts the raw `Set-Cookie` response header directly, not via the
    client's own cookie jar + redirect-follow: the cookie is deliberately
    `Secure` (real-deployment correctness, RunPod's own HTTPS-terminating
    proxy), which a spec-compliant client -- correctly -- refuses to
    store at all when the connection is plain HTTP, as this hermetic
    `TestServer` is. That refusal is the client behaving correctly, not a
    bug in the gate; asserting the header directly tests this gate's own
    code without depending on that unrelated HTTP-vs-HTTPS distinction.
    """

    async def test_the_correct_token_sets_a_cookie_and_redirects(self) -> None:
        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                LOGIN_PATH, data={"token": "expected-token"}, allow_redirects=False
            )
            assert response.status == 302
            assert response.headers["Location"] == "/"
            set_cookie = response.headers["Set-Cookie"]
            assert "HttpOnly" in set_cookie
            assert "Secure" in set_cookie
            assert "SameSite=Strict" in set_cookie
            # The cookie's own value is a distinct, minted session token --
            # never the master credential itself.
            assert f"{COOKIE_NAME}=expected-token" not in set_cookie
            assert f"{COOKIE_NAME}=" in set_cookie

    async def test_the_wrong_token_is_rejected_and_sets_no_cookie(self) -> None:
        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            response = await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            assert response.status == 401
            assert "Set-Cookie" not in response.headers


class TestCookieAuthenticatesLikeTheHeaderDoes:
    async def test_a_request_carrying_the_valid_cookie_reaches_the_handler(
        self,
    ) -> None:
        sessions = SessionStore()
        app = _app_with_login("expected-token", sessions=sessions)
        token = sessions.issue()

        async with TestClient(TestServer(app)) as client:
            client.session.cookie_jar.update_cookies(
                {COOKIE_NAME: token}, response_url=client.make_url("/")
            )
            response = await client.get("/anything")
            assert response.status == 200

    async def test_a_request_carrying_the_wrong_cookie_is_still_rejected(
        self,
    ) -> None:
        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            client.session.cookie_jar.update_cookies(
                {COOKIE_NAME: "never-issued-token"}, response_url=client.make_url("/")
            )
            response = await client.get("/anything")
            assert response.status == 401

    async def test_the_master_credential_itself_is_not_a_valid_cookie(self) -> None:
        """FR-002: the credential must never travel as this cookie's own
        value -- confirming it that way is explicitly rejected, not just
        that *some* random string is."""

        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            client.session.cookie_jar.update_cookies(
                {COOKIE_NAME: "expected-token"}, response_url=client.make_url("/")
            )
            response = await client.get("/anything")
            assert response.status == 401

    async def test_the_header_still_works_with_no_cookie_at_all_unchanged(
        self,
    ) -> None:
        """The Bearer-header path -- an automated client's own use -- is
        completely unaffected by any of this (never
        touched by the browser-login addition)."""

        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert response.status == 200


class TestSessionStore:
    def test_a_freshly_issued_token_is_valid(self) -> None:
        sessions = SessionStore()
        token = sessions.issue()
        assert sessions.is_valid(token)

    def test_two_consecutive_tokens_differ(self) -> None:
        sessions = SessionStore()
        assert sessions.issue() != sessions.issue()

    def test_an_unissued_token_is_never_valid(self) -> None:
        sessions = SessionStore()
        sessions.issue()
        assert not sessions.is_valid("something-nobody-ever-issued")

    def test_an_empty_store_validates_nothing(self) -> None:
        sessions = SessionStore()
        assert not sessions.is_valid("")


class TestRateLimiter:
    """Exponential backoff on repeated failed login attempts (defence in
    depth -- the token itself is 256 bits of entropy from
    ``secrets.token_urlsafe(32)``, already computationally infeasible to
    brute-force regardless; this bounds the request/log volume an
    automated scanner probing the new, human-friendly login form can
    generate, and is deliberately NOT applied to the Bearer-header path
    every other route uses, so a transient misconfiguration of curu's own
    automated client can never lock itself out)."""

    def test_the_first_failure_blocks_for_the_base_delay(self) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        assert limiter.seconds_until_retry("client-a") == 0.0
        limiter.record_failure("client-a")
        assert limiter.seconds_until_retry("client-a") > 0.0

    def test_delay_grows_exponentially_with_consecutive_failures(self) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        limiter.record_failure("client-a")
        first_delay = limiter.seconds_until_retry("client-a")
        limiter.record_failure("client-a")
        second_delay = limiter.seconds_until_retry("client-a")
        assert second_delay > first_delay

    def test_delay_is_capped_at_max_delay(self) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=5.0)
        for _ in range(20):
            limiter.record_failure("client-a")
        assert limiter.seconds_until_retry("client-a") <= 5.0

    def test_a_success_resets_the_backoff_for_that_client(self) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        limiter.record_failure("client-a")
        limiter.record_failure("client-a")
        limiter.record_success("client-a")
        assert limiter.seconds_until_retry("client-a") == 0.0

    def test_clients_are_tracked_independently(self) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        limiter.record_failure("client-a")
        assert limiter.seconds_until_retry("client-b") == 0.0


class TestLoginSubmissionIsRateLimited:
    async def test_a_blocked_client_gets_429_before_the_token_is_even_checked(
        self,
    ) -> None:
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            first = await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            assert first.status == 401

            # Still blocked -- even the *correct* token is rejected with 429
            # while backed off, never reaching the credential check at all.
            second = await client.post(LOGIN_PATH, data={"token": "expected-token"})
            assert second.status == 429
            assert "Retry-After" in second.headers


class _FakeTransport:
    """Just enough of a real transport for `Request.remote` -- it reads
    the peer address via `get_extra_info("peername")`."""

    def __init__(self, peername: tuple[str, int] | None) -> None:
        self._peername = peername

    def get_extra_info(self, name: str) -> object:
        return self._peername if name == "peername" else None


def _fake_request(
    *, headers: dict[str, str] | None = None, remote: str | None = "127.0.0.1"
) -> web.Request:
    transport = _FakeTransport((remote, 0) if remote is not None else None)
    return make_mocked_request(
        "POST", LOGIN_PATH, headers=headers or {}, transport=transport
    )


class TestClientKey:
    """`_client_key`'s own real-deployment bug (T{n}): `request.remote`
    behind a reverse proxy (verified live against RunPod's own
    Cloudflare-fronted proxy.runpod.net) is the proxy's own connecting
    address, not a stable per-client value -- it silently defeated
    RateLimiter's whole per-client backoff, since every request looked
    like a fresh, never-seen-before client."""

    def test_prefers_the_first_x_forwarded_for_entry_when_present(self) -> None:
        request = _fake_request(
            headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1, 10.0.0.2"}
        )
        assert _client_key(request) == "203.0.113.7"

    def test_falls_back_to_request_remote_when_the_header_is_absent(self) -> None:
        request = _fake_request(remote="198.51.100.9")
        assert _client_key(request) == "198.51.100.9"

    def test_falls_back_to_unknown_when_neither_is_available(self) -> None:
        request = _fake_request(remote=None)
        assert _client_key(request) == "unknown"
