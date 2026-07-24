"""Hermetic coverage for :mod:`gate` -- the gate's pure,
testable logic (credential generation, the constant-time comparison, and
the aiohttp middleware factory function), driven against a real, minimal
``aiohttp.web.Application`` via ``aiohttp.test_utils``.
Never imports ``__init__`` (this package's own ComfyUI entrypoint, which
requires a real ComfyUI ``server`` module) -- only ``gate.py`` itself.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from gate import (
    COOKIE_NAME,
    LOGIN_PATH,
    RateLimiter,
    SessionStore,
    build_gate_middleware,
    build_login_routes,
    client_key,
    generate_credential,
    resolve_credential,
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


class TestResolveCredential:
    """`COMFYUI_CURU_AUTH_TOKEN` (or whatever env var `__init__.py` reads)
    lets an operator (or an automated test harness) pin a known,
    persistent credential instead of scraping a freshly random one from
    the console every restart."""

    def test_an_empty_env_value_falls_back_to_a_generated_credential(self) -> None:
        credential = resolve_credential(None)
        assert isinstance(credential, str)
        assert credential != ""

    def test_a_blank_string_env_value_also_falls_back(self) -> None:
        # os.environ.get returns "" for a declared-but-empty env var, not
        # None -- both must fall back, not treat "" as a real credential.
        credential = resolve_credential("")
        assert credential != ""

    def test_a_supplied_env_value_is_used_verbatim(self) -> None:
        assert resolve_credential("fixed-test-credential") == "fixed-test-credential"


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


class TestFailedBearerAuthIsLogged:
    """A clear, stable, greppable log line per rejected Bearer-header
    request -- external log-watching tools (fail2ban, crowdsec) key off
    this to block at the network level, entirely outside this process's
    own control. Independent of, and unaffected by, whether a
    `rate_limiter` is also supplied (`TestBearerAuthIsRateLimited` below)
    -- logging is a separate, additive concern from blocking."""

    async def test_a_missing_credential_logs_a_warning_naming_the_client(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
            async with TestClient(TestServer(app)) as client:
                await client.get(
                    "/anything", headers={"X-Forwarded-For": "203.0.113.7"}
                )

        assert any(
            "authentication failure" in r.message and "203.0.113.7" in r.message
            for r in caplog.records
        )

    async def test_the_login_path_itself_never_logs_a_bearer_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # LOGIN_PATH is always let through unauthenticated by design (its
        # own docstring) -- it must never itself count as a failed Bearer
        # attempt, or a human's own successful login flow would spuriously
        # trip external log-watching tools on every single visit.
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get(LOGIN_PATH, _ok_handler)

        with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
            async with TestClient(TestServer(app)) as client:
                await client.get(LOGIN_PATH)

        assert not caplog.records


class TestBearerAuthIsRateLimited:
    """The Bearer-header/API path now backs off exactly like the login
    form does -- an earlier version of this gate deliberately exempted
    it (locking out a legitimately-configured automated client during a
    transient misconfiguration was judged a worse outcome than the
    brute-force risk). The credential's own 256 bits of entropy already
    makes a *successful* guess computationally infeasible regardless of
    backoff; leaving this path completely unthrottled was a real,
    unnecessary gap for noisy automated scanning, not a defensible
    tradeoff -- so it now gets the same defence in depth the login form
    already had.

    `rate_limiter=None` (the default) keeps every pre-existing
    caller/test of this function's behaviour unchanged -- this is an
    opt-in extension, mirroring `sessions=None`'s own precedent."""

    async def test_without_a_rate_limiter_repeated_failures_are_never_blocked(
        self,
    ) -> None:
        app = web.Application(middlewares=[build_gate_middleware("expected-token")])
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            for _ in range(10):
                response = await client.get(
                    "/anything", headers={"Authorization": "Bearer wrong-token"}
                )
                assert response.status == 401

    async def test_a_blocked_client_gets_429_before_the_credential_is_even_checked(
        self,
    ) -> None:
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            first = await client.get(
                "/anything", headers={"Authorization": "Bearer wrong-token"}
            )
            assert first.status == 401

            # Still blocked -- even the *correct* credential is rejected
            # with 429 while backed off, never reaching the credential
            # check at all (matches the login form's own established
            # semantics exactly).
            second = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert second.status == 429
            assert "Retry-After" in second.headers

    async def test_a_blocked_browser_request_redirects_to_login_not_bare_json(
        self,
    ) -> None:
        # The 401 branch already redirects an Accept: text/html request
        # to LOGIN_PATH instead of a bare JSON body a human has no way to
        # act on -- the 429 branch honours that same content negotiation,
        # or a real browser reloading a gated page while backed off (not
        # just a scanner) would hit exactly the failure mode that check
        # exists to avoid.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            await client.get("/anything", headers={"Accept": "text/html"})

            blocked = await client.get(
                "/anything", headers={"Accept": "text/html"}, allow_redirects=False
            )
            assert blocked.status == 302
            assert blocked.headers["Location"] == LOGIN_PATH

    async def test_a_correct_credential_resets_the_backoff(self) -> None:
        limiter = RateLimiter(base_delay=0.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            failed = await client.get(
                "/anything", headers={"Authorization": "Bearer wrong-token"}
            )
            assert failed.status == 401

            succeeded = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert succeeded.status == 200

    async def test_a_valid_cookie_session_bypasses_rate_limiting_entirely(
        self,
    ) -> None:
        # An already-established browser session (via the login form's
        # own separate rate-limited flow) must never be penalised by
        # backoff accrued on the Bearer-header path -- the cookie check
        # happens before the rate-limit check, not after.
        limiter = RateLimiter(base_delay=300.0, max_delay=300.0)
        sessions = SessionStore()
        token = sessions.issue()
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token", sessions=sessions, rate_limiter=limiter
                )
            ]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            blocked = await client.get(
                "/anything", headers={"Authorization": "Bearer wrong-token"}
            )
            assert blocked.status == 401

            client.session.cookie_jar.update_cookies({COOKIE_NAME: token})
            response = await client.get("/anything")
            assert response.status == 200


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
    oidc_start_path: str | None = None,
):
    sessions = sessions if sessions is not None else SessionStore()
    app = web.Application(
        middlewares=[build_gate_middleware(credential, sessions=sessions)]
    )
    app.router.add_get("/anything", _ok_handler)
    login_get, login_post = build_login_routes(
        credential,
        sessions=sessions,
        rate_limiter=rate_limiter,
        oidc_start_path=oidc_start_path,
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


class TestOidcLoginOptionOnLoginPage:
    """`build_login_routes`'s `oidc_start_path` parameter -- gate.py's one
    generic hook for a second, additive login option (spec 002). Additive
    only: omitting it (every pre-existing caller/test) MUST render
    byte-for-byte the same page as before this parameter existed
    (FR-002/FR-004)."""

    async def test_oidc_option_renders_when_a_start_path_is_given(self) -> None:
        app = _app_with_login("expected-token", oidc_start_path="/curu-auth/oidc/start")

        async with TestClient(TestServer(app)) as client:
            response = await client.get(LOGIN_PATH)
            body = await response.text()

        assert 'href="/curu-auth/oidc/start"' in body

    async def test_oidc_option_absent_when_no_start_path_is_given(self) -> None:
        app = _app_with_login("expected-token")

        async with TestClient(TestServer(app)) as client:
            response = await client.get(LOGIN_PATH)
            body = await response.text()

        assert "identity provider" not in body
        assert "oidc" not in body.lower()


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

    async def test_a_wrong_token_logs_a_warning_naming_the_client(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = _app_with_login("expected-token")

        with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    LOGIN_PATH,
                    data={"token": "wrong-token"},
                    headers={"X-Forwarded-For": "203.0.113.9"},
                )

        assert any(
            "authentication failure" in r.message and "203.0.113.9" in r.message
            for r in caplog.records
        )


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

    async def test_the_blocked_page_embeds_a_live_countdown_not_a_static_number(
        self,
    ) -> None:
        # A "Try again in 4s" message that never updates leaves a stale
        # number on screen long after the block actually expired -- a
        # human has no way to tell without submitting again. The response
        # instead embeds an element the countdown script decrements
        # client-side, once a second, down to 0.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            blocked = await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            assert blocked.status == 429
            body = await blocked.text()

            assert 'id="curu-auth-countdown"' in body
            script = body.split("<script>", 1)[1]
            assert "curu-auth-countdown" in script

    async def test_the_countdown_script_is_anchored_to_a_real_deadline(
        self,
    ) -> None:
        # A plain "decrement a counter every setInterval tick" countdown
        # silently drifts from the real server-side deadline whenever a
        # tick doesn't fire on time -- browsers throttle setInterval in a
        # backgrounded/inactive tab, sometimes to once a minute, so a
        # human tabbing away and back sees a display that still claims
        # "blocked" long after the real block already expired (live-
        # reported: the correct credential worked immediately once
        # actually retried, even while the display still showed time
        # remaining). Recomputing remaining = deadline - Date.now() on
        # every tick, instead of accumulating -1-per-tick, makes the
        # display self-correct to the true remaining time (or clear
        # itself) the very next tick that does fire, however late.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            blocked = await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            assert blocked.status == 429
            body = await blocked.text()

            script = body.split("<script>", 1)[1]
            assert "Date.now()" in script


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
    """`client_key`'s own real-deployment bug (T{n}): `request.remote`
    behind a reverse proxy (verified live against RunPod's own
    Cloudflare-fronted proxy.runpod.net) is the proxy's own connecting
    address, not a stable per-client value -- it silently defeated
    RateLimiter's whole per-client backoff, since every request looked
    like a fresh, never-seen-before client."""

    def test_prefers_the_first_x_forwarded_for_entry_when_present(self) -> None:
        request = _fake_request(
            headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1, 10.0.0.2"}
        )
        assert client_key(request) == "203.0.113.7"

    def test_falls_back_to_request_remote_when_the_header_is_absent(self) -> None:
        request = _fake_request(remote="198.51.100.9")
        assert client_key(request) == "198.51.100.9"

    def test_falls_back_to_unknown_when_neither_is_available(self) -> None:
        request = _fake_request(remote=None)
        assert client_key(request) == "unknown"
