"""Live-harness witnesses for the OIDC/OAuth login path, driving the full
authorization-code flow against a real Authelia instance (Lite bundle) --
see ADR-002 and specs/002-oidc-login/research.md. Not a mocked provider.

Marked `system` at module level: excluded from the default `pytest` run
(pyproject.toml addopts). Requires a working Docker daemon. Traceability to
specs/002-oidc-login/features/oidc_login.feature is noted per test via
docstring.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from tests.system.conftest import (
    AUTHELIA_HOST_HEADER,
    BASE_URL,
    OIDC_ENV,
    authelia_firstfactor_login,
    authelia_ssl_context,
    compose,
    rewrite_to_published_authelia_host,
    wait_until_reachable,
)

pytestmark = pytest.mark.system


@pytest.fixture(autouse=True)
def _ensure_torn_down_after_each_test():
    """Belt-and-braces: leave no harness running after any test, pass or fail."""

    yield
    compose("down", timeout=60)


class TestOidcLoginAgainstRealAuthelia:
    """Witness: the full authorization-code flow against the real Authelia
    instance this repo's own `docker-compose.yml` + `docker/authelia/`
    config bring up -- not T009's simplified spike, not a mocked provider.
    References the feature file's "Initiate login redirects to the
    identity provider" and "Successful provider login establishes a
    session" scenarios (spec.md US1, Acceptance Scenarios 1-2)."""

    async def test_oidc_login_establishes_a_session_identical_to_credential_login(
        self,
    ) -> None:
        up_result = compose("up", "-d", env=OIDC_ENV)
        assert up_result.returncode == 0, up_result.stderr
        await wait_until_reachable(timeout=180.0)

        ca_ssl = authelia_ssl_context()
        authelia_headers = {"Host": AUTHELIA_HOST_HEADER}

        async with aiohttp.ClientSession() as session:
            # 1. Headless Authelia login (T009 spike's proven sequence).
            authelia_session_cookie = await authelia_firstfactor_login(session)

            # 2. Hit comfyui's own start route -- redirects to Authelia's
            # authorization endpoint. Reachable unauthenticated by design
            # (ADR-003's public-paths mechanism).
            async with session.get(
                f"{BASE_URL}/curu-auth/oidc/start", allow_redirects=False
            ) as response:
                assert response.status in (302, 303, 307)
                authorization_url = response.headers["Location"]

            # 3. Complete authorization at Authelia, presenting the
            # session cookie explicitly (not via aiohttp's own cookie
            # jar, which can't match a Host-header-spoofed request --
            # research.md).
            async with session.get(
                rewrite_to_published_authelia_host(authorization_url),
                allow_redirects=False,
                headers={**authelia_headers, "Cookie": authelia_session_cookie},
                server_hostname="authelia.internal",
                ssl=ca_ssl,
            ) as response:
                assert response.status in (302, 303, 307)
                callback_url = response.headers["Location"]
            assert callback_url.startswith(BASE_URL.replace("localhost", "127.0.0.1"))

            # 4. Follow the callback back to comfyui -- this is where the
            # gate mints the curu_auth session (ADR-002/FR-003).
            async with session.get(callback_url, allow_redirects=False) as response:
                assert response.status in (302, 303, 307)
                set_cookie = response.headers.getall("Set-Cookie", [])
            curu_cookie = next(
                (c for c in set_cookie if c.startswith("curu_auth=")), None
            )
            assert curu_cookie is not None
            curu_cookie_value = curu_cookie.split(";")[0].split("=", 1)[1]

        # 5. That session cookie authenticates subsequent requests exactly
        # like a credential-login session does -- a fresh session/client,
        # proving the cookie itself carries the authentication, not
        # anything left over on the first session object.
        async with (
            aiohttp.ClientSession() as verify_session,
            verify_session.get(
                BASE_URL, cookies={"curu_auth": curu_cookie_value}
            ) as response,
        ):
            assert response.status == 200


class TestRepeatedFailedOidcCallbacksTriggerBackoff:
    """Witness: feature file's "Repeated failed OIDC attempts trigger
    backoff" scenario (spec 002 US3, T038/T039) -- the callback handler
    shares the exact same `RateLimiter` instance every other
    unauthenticated path already uses (T037-I), verified here against the
    real harness rather than only the hermetic mock.

    Paced identically to spec 001's own
    `TestRepeatedWrongCredentialsTriggerBackoff` (research.md): a failed
    callback only ever returns 401 itself (the block it sets applies to
    the *next* request), so an immediate follow-up "probe" -- any request
    to the same rate-limited route, from the same client identity --
    reads the current `Retry-After` as 429 without itself counting as a
    fresh failure (the block-check short-circuits before
    `record_failure`).
    """

    async def test_repeated_failed_oidc_callbacks_trigger_backoff(self) -> None:
        up_result = compose("up", "-d", env=OIDC_ENV)
        assert up_result.returncode == 0, up_result.stderr
        await wait_until_reachable(timeout=180.0)

        client_id = {"X-Forwarded-For": "203.0.113.41"}
        # A state nobody issued -- always rejected, with no side effects
        # beyond the rate-limiter/log entry T037-I added.
        bad_callback_url = f"{BASE_URL}/curu-auth/oidc/callback?state=never-issued"

        retry_afters: list[int] = []
        async with aiohttp.ClientSession() as session:
            for _ in range(3):
                async with session.get(
                    bad_callback_url, headers=client_id, allow_redirects=False
                ) as failed:
                    assert failed.status == 401

                async with session.get(
                    bad_callback_url, headers=client_id, allow_redirects=False
                ) as probe:
                    assert probe.status == 429
                    retry_afters.append(int(probe.headers["Retry-After"]))

                await asyncio.sleep(retry_afters[-1] + 0.2)

        assert retry_afters[1] > retry_afters[0], retry_afters
        assert retry_afters[2] > retry_afters[1], retry_afters
