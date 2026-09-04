"""Hermetic coverage for :mod:`gate` -- the gate's pure,
testable logic (credential generation, the constant-time comparison, and
the aiohttp middleware factory function), driven against a real, minimal
``aiohttp.web.Application`` via ``aiohttp.test_utils``.
Never imports ``__init__`` (this package's own ComfyUI entrypoint, which
requires a real ComfyUI ``server`` module) -- only ``gate.py`` itself.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
    resolve_persistent_credential,
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


class TestResolvePersistentCredential:
    """`COMFYUI_CURU_AUTH_TOKEN` (or whatever env var `__init__.py` reads)
    lets an operator pin a known credential; `state_path` (a file under
    ComfyUI's own `user/` directory, resolved by `__init__.py` -- `None`
    outside a real ComfyUI install) is what makes that credential -- pinned
    or freshly generated -- survive a restart that reuses the process's
    existing environment (an `os.execv`-based Manager reboot never
    refreshes `os.environ` from outside; only a persisted file does).
    """

    def test_an_empty_env_value_falls_back_to_a_generated_credential(
        self, tmp_path: Path
    ) -> None:
        credential = resolve_persistent_credential(None, tmp_path / "credential")
        assert isinstance(credential, str)
        assert credential != ""

    def test_a_blank_string_env_value_also_falls_back(self, tmp_path: Path) -> None:
        # os.environ.get returns "" for a declared-but-empty env var, not
        # None -- both must fall back, not treat "" as a real credential.
        credential = resolve_persistent_credential("", tmp_path / "credential")
        assert credential != ""

    def test_a_supplied_env_value_is_used_verbatim(self, tmp_path: Path) -> None:
        credential = resolve_persistent_credential(
            "fixed-test-credential", tmp_path / "credential"
        )
        assert credential == "fixed-test-credential"

    def test_supplied_env_value_is_persisted_to_state_path(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "credential"
        resolve_persistent_credential("pinned-token", state_path)
        assert state_path.read_text(encoding="utf-8").strip() == "pinned-token"

    def test_no_env_value_reuses_a_previously_persisted_credential(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "credential"
        state_path.write_text("already-persisted", encoding="utf-8")
        assert resolve_persistent_credential(None, state_path) == "already-persisted"

    def test_no_env_value_and_nothing_persisted_generates_and_persists(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "nested" / "credential"
        credential = resolve_persistent_credential(None, state_path)
        assert credential != ""
        assert state_path.read_text(encoding="utf-8").strip() == credential

    def test_generated_credential_is_stable_across_repeated_calls(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "credential"
        first = resolve_persistent_credential(None, state_path)
        second = resolve_persistent_credential(None, state_path)
        assert first == second

    def test_env_value_overrides_and_replaces_a_stale_persisted_value(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "credential"
        state_path.write_text("stale-value", encoding="utf-8")
        credential = resolve_persistent_credential("new-pinned-token", state_path)
        assert credential == "new-pinned-token"
        assert state_path.read_text(encoding="utf-8").strip() == "new-pinned-token"

    def test_none_state_path_still_resolves_without_persisting(self) -> None:
        # No ComfyUI install (folder_paths absent) -- __init__.py passes
        # None. Must still resolve a usable credential, just with nothing
        # surviving a restart -- today's exact pre-fix behaviour.
        credential = resolve_persistent_credential(None, None)
        assert credential != ""

    def test_state_path_whose_parent_is_a_file_degrades_gracefully(
        self, tmp_path: Path
    ) -> None:
        # A real (non-mocked) OSError condition: mkdir(parents=True) on a
        # path where a parent segment is itself a file, not a directory.
        # Must still resolve a credential rather than raising -- fail safe
        # to "gate stays on," never "gate breaks provisioning."
        blocking_file = tmp_path / "not_a_directory"
        blocking_file.write_text("i am a file", encoding="utf-8")
        state_path = blocking_file / "credential"
        credential = resolve_persistent_credential(None, state_path)
        assert credential != ""


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


class TestOfferingNoCredentialIsNotAFailedAttempt:
    """A request carrying *no* credential at all is not an authentication
    *attempt* -- it tested nothing -- so it must not consume the backoff
    budget, even though it is (still, unchanged) rejected with a 401.

    This is the fix for a defect that produced the same incident three
    separate times and was worked around twice: an unauthenticated
    readiness/health probe repeated every few seconds accrues escalating
    backoff (`base_delay=1.0`, `max_delay=300.0`) exactly as if it were
    guessing credentials, and the *next* correctly-credentialled request
    -- from an entirely legitimate client sharing that client key -- gets
    429 instead of being served. `docker/comfyui/healthcheck.py` had to
    accept 429 as proof-of-gate because of it; curu's own system-test
    harness had ~30 unauthenticated readiness polls turn its first real
    `POST /prompt` into a 429.

    The security reasoning: a brute-forcer must *supply* a candidate
    credential to test it, so counting only supplied-and-wrong attempts
    still bounds exactly the attempts that could ever succeed. Offering
    nothing tests nothing. What counts as "offered" is deliberately as
    wide as possible short of that -- see the individual tests below: a
    malformed header, a non-Bearer scheme, and a never-issued session
    cookie all count, so the exemption can never be turned into an
    unlimited supply of free guesses.
    """

    async def test_credential_less_requests_never_consume_the_failure_budget(
        self,
    ) -> None:
        # The real incident, reproduced: a readiness probe polling an
        # unauthenticated endpoint during boot, then the first real
        # credentialled request. Production defaults deliberately -- the
        # bug needs no exotic tuning to bite.
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            for _ in range(30):
                probe = await client.get("/anything")
                assert probe.status == 401

            served = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert served.status == 200

    async def test_a_credential_less_request_is_still_rejected_with_401(self) -> None:
        # Not recording a failure must not soften the rejection itself --
        # the 401 and its body are unchanged.
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get("/anything")
            assert response.status == 401
            assert await response.json() == {"detail": "missing or invalid credential"}

    async def test_a_credential_less_browser_request_still_redirects_to_login(
        self,
    ) -> None:
        # The 401 branch's existing content negotiation is untouched.
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            response = await client.get(
                "/anything",
                headers={"Accept": "text/html"},
                allow_redirects=False,
            )
            assert response.status == 302
            assert response.headers["Location"] == LOGIN_PATH

    async def test_an_empty_authorization_header_is_not_an_attempt_either(self) -> None:
        # `Authorization:` with a blank value carries no candidate
        # credential -- it can never equal `Bearer <credential>`, so it
        # tests nothing, exactly like sending no header at all. Treating
        # it as an attempt would let a proxy or client that emits a blank
        # header lock a legitimate caller out for free.
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            blank = await client.get("/anything", headers={"Authorization": ""})
            assert blank.status == 401

            served = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert served.status == 200

    async def test_a_whitespace_only_authorization_header_is_not_an_attempt(
        self,
    ) -> None:
        # Driven against the middleware directly, with a mocked request,
        # rather than through a real client: aiohttp's own HTTP parser
        # strips optional whitespace around a header value, so a
        # whitespace-only `Authorization` never survives the wire as
        # anything but "". The rule this pins belongs to the middleware,
        # not to that parser -- a client or proxy emitting
        # `Authorization: " "` offered no candidate credential either.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        gate = build_gate_middleware("expected-token", rate_limiter=limiter)
        request = make_mocked_request(
            "GET",
            "/anything",
            headers={"Authorization": "   ", "X-Forwarded-For": "203.0.113.13"},
        )

        response = await gate(request, _ok_handler)

        assert response.status == 401
        assert limiter.seconds_until_retry("203.0.113.13") == 0.0

    async def test_a_wrong_credential_still_consumes_the_failure_budget(self) -> None:
        # The control: a *supplied* and wrong credential is exactly the
        # attempt the limiter exists to bound, and is unaffected.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            wrong = await client.get(
                "/anything", headers={"Authorization": "Bearer wrong-token"}
            )
            assert wrong.status == 401

            blocked = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert blocked.status == 429

    async def test_a_malformed_authorization_header_still_counts_as_an_attempt(
        self,
    ) -> None:
        # "Offered" must not mean "well-formed": if malformed headers were
        # exempt, a client could hand over an unlimited number of free
        # attempts simply by malforming them. Anything non-blank in the
        # header is a candidate credential, however unlikely.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            malformed = await client.get(
                "/anything", headers={"Authorization": "Basic bm90LWEtYmVhcmVy"}
            )
            assert malformed.status == 401

            blocked = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert blocked.status == 429

    async def test_a_bare_scheme_with_no_token_still_counts_as_an_attempt(self) -> None:
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            bare = await client.get("/anything", headers={"Authorization": "Bearer"})
            assert bare.status == 401

            blocked = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert blocked.status == 429

    async def test_a_never_issued_session_cookie_still_counts_as_an_attempt(
        self,
    ) -> None:
        # The session cookie is the gate's *other* accepted credential
        # (256 bits, minted by SessionStore). A request presenting one
        # that was never issued has offered a credential and been wrong,
        # so it must stay counted -- keying the exemption on the
        # Authorization header alone would silently hand an attacker
        # unlimited free guesses at session tokens.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        sessions = SessionStore()
        app = web.Application(
            middlewares=[
                build_gate_middleware(
                    "expected-token", sessions=sessions, rate_limiter=limiter
                )
            ]
        )
        app.router.add_get("/anything", _ok_handler)

        async with TestClient(TestServer(app)) as client:
            client.session.cookie_jar.update_cookies(
                {COOKIE_NAME: "never-issued-token"},
                response_url=client.make_url("/"),
            )
            rejected = await client.get("/anything")
            assert rejected.status == 401

            client.session.cookie_jar.clear()
            blocked = await client.get(
                "/anything", headers={"Authorization": "Bearer expected-token"}
            )
            assert blocked.status == 429

    async def test_a_credential_less_request_is_still_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Logging is a separate concern from blocking (see
        # TestFailedBearerAuthIsLogged) -- fail2ban/crowdsec key off these
        # lines to block at the network level, which is the real defence
        # against an unauthenticated flood. Not consuming the *backoff*
        # budget must not make the request invisible to them.
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = web.Application(
            middlewares=[build_gate_middleware("expected-token", rate_limiter=limiter)]
        )
        app.router.add_get("/anything", _ok_handler)

        with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
            async with TestClient(TestServer(app)) as client:
                await client.get(
                    "/anything", headers={"X-Forwarded-For": "203.0.113.11"}
                )

        assert any(
            "authentication failure" in r.message and "203.0.113.11" in r.message
            for r in caplog.records
        )


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


class TestLoginSubmissionWithNoTokenIsNotAnAttempt:
    """`build_login_routes` has the same defect shape the Bearer-header
    path did: a POST whose `token` field is missing or blank offered no
    credential, tested nothing, and must not consume the backoff budget
    -- while still being rejected exactly as before. A human hitting
    Enter on the empty form (or any bot POSTing empty bodies) otherwise
    locks out the shared `RateLimiter` that `__init__.py` hands to the
    gate middleware, this form, *and* the OIDC routes alike."""

    async def test_an_empty_token_submission_never_consumes_the_budget(self) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            for _ in range(10):
                empty = await client.post(LOGIN_PATH, data={"token": ""})
                assert empty.status == 401

            accepted = await client.post(
                LOGIN_PATH, data={"token": "expected-token"}, allow_redirects=False
            )
            assert accepted.status == 302

    async def test_a_submission_with_no_token_field_at_all_is_not_an_attempt(
        self,
    ) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            missing = await client.post(LOGIN_PATH, data={"username": "curu"})
            assert missing.status == 401

            accepted = await client.post(
                LOGIN_PATH, data={"token": "expected-token"}, allow_redirects=False
            )
            assert accepted.status == 302

    async def test_an_empty_token_submission_still_renders_the_401_login_page(
        self,
    ) -> None:
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            response = await client.post(LOGIN_PATH, data={"token": ""})
            assert response.status == 401
            assert "text/html" in response.headers["Content-Type"]
            assert "Incorrect credential." in await response.text()
            assert "Set-Cookie" not in response.headers

    async def test_a_whitespace_only_token_submission_is_not_an_attempt(self) -> None:
        # Unlike a header value (aiohttp's HTTP parser strips optional
        # whitespace around those), a form field's whitespace survives
        # intact -- `token=%20%20%20` really does arrive as "   ". Still
        # nothing offered.
        limiter = RateLimiter(base_delay=1.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            blank = await client.post(LOGIN_PATH, data={"token": "   "})
            assert blank.status == 401

            accepted = await client.post(
                LOGIN_PATH, data={"token": "expected-token"}, allow_redirects=False
            )
            assert accepted.status == 302

    async def test_a_wrong_token_still_consumes_the_budget(self) -> None:
        # The control: a supplied, wrong token is the attempt this
        # limiter exists to bound (already covered by
        # TestLoginSubmissionIsRateLimited -- restated here so the
        # exemption above can never quietly widen to cover it).
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            wrong = await client.post(LOGIN_PATH, data={"token": "wrong-token"})
            assert wrong.status == 401

            blocked = await client.post(LOGIN_PATH, data={"token": "expected-token"})
            assert blocked.status == 429

    async def test_a_token_that_encodes_to_nothing_still_counts_as_an_attempt(
        self,
    ) -> None:
        # `errors="ignore"` drops every non-latin-1 character, so a token
        # of nothing but such characters encodes to `b""` -- which the
        # handler already had to reject as "not supplied". That must not
        # become the loophole: the *submitted* value was non-blank, so a
        # credential was offered and was wrong.
        limiter = RateLimiter(base_delay=60.0, max_delay=300.0)
        app = _app_with_login("expected-token", rate_limiter=limiter)

        async with TestClient(TestServer(app)) as client:
            unencodable = await client.post(LOGIN_PATH, data={"token": "中文"})
            assert unencodable.status == 401

            blocked = await client.post(LOGIN_PATH, data={"token": "expected-token"})
            assert blocked.status == 429


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
