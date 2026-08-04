"""Live-harness witnesses driving `docker compose` directly against a real
ComfyUI process with comfyui_curu_auth installed from this repo's own
working tree (bind-mounted, not a published release -- see
specs/001-docker-comfyui-harness/research.md).

Marked `system` at module level: excluded from the default `pytest` run
(pyproject.toml addopts). Requires a working Docker daemon. Traceability to
specs/001-docker-comfyui-harness/features/docker_comfyui_harness.feature is
noted per test via docstring.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from gate import LOGIN_PATH
from tests.system.conftest import (
    AUTH_HEADERS,
    BASE_URL,
    TEST_AUTH_TOKEN,
    compose,
    wait_until_reachable,
    wait_until_unreachable,
)

pytestmark = pytest.mark.system

WS_URL = "ws://localhost:8188/ws"
LOGIN_URL = f"{BASE_URL}{LOGIN_PATH}"


@pytest.fixture(autouse=True)
def _ensure_torn_down_after_each_test():
    """Belt-and-braces: leave no harness running after any test, pass or fail."""

    yield
    compose("down", timeout=60)


class TestHarnessBootsAndGateEnforces:
    """Witness: feature scenarios "Boot a real, gated ComfyUI instance",
    "Unauthenticated HTTP requests are rejected", and "The fixed test
    credential succeeds" (spec.md US1, Acceptance Scenarios 1-3)."""

    async def test_harness_boots_and_gate_enforces(self) -> None:
        up_result = compose("up", "-d")
        assert up_result.returncode == 0, up_result.stderr

        elapsed = await wait_until_reachable(timeout=180.0)
        assert elapsed < 180.0

        # Distinct X-Forwarded-For per check, not just distinct assertions:
        # gate.py rate-limits per client_key, and even a *correct*
        # credential is rejected while that key is blocked (documented
        # behavior). Checking unauthenticated-rejected and
        # credential-succeeds back-to-back on the same identity means the
        # first check's own recorded "failure" blocks the second. The spec
        # describes these as independent Given/When/Then scenarios, not a
        # sequential flow for one client -- distinct simulated identities
        # keep them properly isolated (research.md).
        async with aiohttp.ClientSession() as session:
            async with session.get(
                BASE_URL, headers={"X-Forwarded-For": "203.0.113.10"}
            ) as unauthenticated_response:
                assert unauthenticated_response.status == 401

            async with session.get(
                BASE_URL,
                headers={**AUTH_HEADERS, "X-Forwarded-For": "203.0.113.20"},
            ) as authenticated_response:
                assert authenticated_response.status == 200


class TestCredentialAnnouncementReachesContainerLogs:
    """Regression witness for darth-veitcher/curu#216 (2026-08-04 rediscovery)
    and darth-veitcher/comfyui_curu_auth#<issue> -- ``__init__.py`` announces
    the resolved Bearer credential via plain ``print()`` immediately after
    ``resolve_persistent_credential()`` runs. External tooling that depends
    on that text actually reaching captured process/container output --
    this repo's own README/contrib fail2ban/crowdsec docs, an operator
    reading ``docker logs``, and curu's own SSH-based
    ``activate_auth_gate_and_get_credential`` -- all read it from there.

    Real ComfyUI (verified directly in ``app/logger.py``, this exact pinned
    version) replaces ``sys.stdout`` with ``LogInterceptor``, a plain
    ``io.TextIOWrapper`` built without ``write_through=True`` -- silently
    reverting ``PYTHONUNBUFFERED=1``'s own unbuffered guarantee for anything
    written through the new wrapper. A bare ``print()`` (no ``flush=True``)
    can sit in that wrapper's internal buffer indefinitely: confirmed live
    against this exact harness before this fix, the credential line never
    reached ``docker compose logs`` even after 30+ real authenticated/
    unauthenticated HTTP requests and a full graceful (SIGTERM) container
    shutdown -- ``logging``-module output (this file's own ``_logger.
    warning`` calls included) was unaffected, since ``logging.
    StreamHandler.emit`` flushes after every record regardless. ``__init__.
    py``'s two ``print(..., flush=True)`` calls are the fix: confirmed live
    that ``flush=True`` forces an explicit flush all the way through
    ``LogInterceptor.flush()`` (which does correctly forward to the real
    underlying stream) to captured container output.

    Deliberately checks ``docker compose logs`` (real captured container
    output), not a mock of ``print`` or of ``sys.stdout`` -- a hermetic unit
    test of ``__init__.py`` in isolation cannot observe this bug at all,
    since it never runs under a real ComfyUI process's own stdout
    replacement.
    """

    async def test_credential_announcement_reaches_container_logs(
        self, running_harness: str
    ) -> None:
        # By the time `running_harness` yields, wait_until_reachable already
        # proved the gate is enforcing (an authenticated request succeeded)
        # -- meaning __init__.py's whole wiring block, including both
        # print() calls, already ran. This only asserts that output actually
        # reached captured container logs, not that the gate itself works
        # (already covered by TestHarnessBootsAndGateEnforces).
        logs_result = compose("logs", "comfyui", timeout=30)
        assert logs_result.returncode == 0, logs_result.stderr
        combined_output = logs_result.stdout + logs_result.stderr
        assert "comfyui-curu-auth gate active. Credential:" in combined_output, (
            "the credential-announcement print() never reached captured "
            "container logs -- see darth-veitcher/curu#216"
        )
        assert (
            f"Browser login (paste the same credential above): {LOGIN_PATH}"
            in combined_output
        )


class TestWebsocketHandshakeIsGated:
    """Witness: feature scenario "The websocket handshake is gated too"
    (spec.md US2, Acceptance Scenario 1's /ws-specific claim)."""

    async def test_websocket_handshake_is_gated(self, running_harness: str) -> None:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.WSServerHandshakeError) as exc_info:
                async with session.ws_connect(
                    WS_URL, headers={"X-Forwarded-For": "203.0.113.30"}
                ):
                    pass
            assert exc_info.value.status == 401


class TestRepeatedWrongCredentialsTriggerBackoff:
    """Witness: feature scenario "Repeated wrong credentials trigger
    backoff" (spec.md US2, Acceptance Scenario 3).

    Does NOT hammer the wrong credential in a tight loop -- gate.py's
    RateLimiter checks the block *before* the credential comparison, so a
    deliberate failure only ever returns 401 (the block it sets applies to
    the *next* request, not this one); an immediate follow-up "probe" (any
    headers, while still blocked) is what returns 429 with the current
    Retry-After, and critically does NOT itself count as a failure -- the
    block-check short-circuits before record_failure is ever reached. This
    lets each cycle read the growing Retry-After without disturbing the
    count it's trying to observe (research.md's pacing decision).
    """

    async def test_repeated_wrong_credentials_trigger_backoff(
        self, running_harness: str
    ) -> None:
        client_id = {"X-Forwarded-For": "203.0.113.40"}
        wrong_credential = {"Authorization": "Bearer wrong-credential", **client_id}

        retry_afters: list[int] = []
        async with aiohttp.ClientSession() as session:
            for _ in range(3):
                async with session.get(BASE_URL, headers=wrong_credential) as failed:
                    assert failed.status == 401

                async with session.get(BASE_URL, headers=client_id) as probe:
                    assert probe.status == 429
                    retry_afters.append(int(probe.headers["Retry-After"]))

                await asyncio.sleep(retry_afters[-1] + 0.2)

        assert retry_afters[1] > retry_afters[0], retry_afters
        assert retry_afters[2] > retry_afters[1], retry_afters


class TestTeardownAndRestartLeavesNoStaleState:
    """Witness: feature scenario "Teardown and restart leave no stale
    state" (spec.md US3, Acceptance Scenario 1; FR-007)."""

    async def test_teardown_and_restart_leaves_no_stale_state(self) -> None:
        blocked_client = {"X-Forwarded-For": "203.0.113.50"}

        # First instance: mint a real session cookie, and put a client
        # into a blocked state.
        first_up = compose("up", "-d")
        assert first_up.returncode == 0, first_up.stderr
        await wait_until_reachable(timeout=180.0)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                LOGIN_URL, data={"token": TEST_AUTH_TOKEN}, allow_redirects=False
            ) as login_response:
                assert login_response.status == 302
                stale_cookie = login_response.cookies["curu_auth"].value

            async with session.get(
                BASE_URL, headers={"Authorization": "Bearer wrong", **blocked_client}
            ) as failed:
                assert failed.status == 401

            async with session.get(BASE_URL, headers=blocked_client) as probe:
                assert probe.status == 429, "setup didn't actually block the client"

        down_result = compose("down", timeout=60)
        assert down_result.returncode == 0, down_result.stderr
        wait_until_unreachable(timeout=30.0)

        # Second instance: neither the old cookie nor the old block should
        # carry over.
        second_up = compose("up", "-d")
        assert second_up.returncode == 0, second_up.stderr
        await wait_until_reachable(timeout=180.0)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                BASE_URL, cookies={"curu_auth": stale_cookie}
            ) as stale_cookie_response:
                assert stale_cookie_response.status == 401, (
                    "old session cookie was still accepted after restart"
                )

            async with session.get(
                BASE_URL, headers=blocked_client
            ) as fresh_client_response:
                assert fresh_client_response.status == 401, (
                    "client was still rate-limited after restart"
                )


class TestSecondUpWithoutDownIsNotDestructive:
    """Witness: spec.md Edge Case -- "a second `up` without an intervening
    `down` must not fail destructively or silently start a second
    conflicting instance" (adapted from curu's own TestIdempotentUp)."""

    async def test_second_up_without_down_is_not_destructive(self) -> None:
        first_up = compose("up", "-d")
        assert first_up.returncode == 0, first_up.stderr
        await wait_until_reachable(timeout=180.0)

        second_up = compose("up", "-d")
        assert second_up.returncode == 0, second_up.stderr

        ps = compose("ps", "-a", "--format", "{{.Names}}")
        names = [line for line in ps.stdout.splitlines() if line.strip()]
        # Was "exactly one container" before spec 002 added the authelia
        # service alongside comfyui (docker-compose.yml) -- the property
        # that actually matters is no *duplicates* per service, not a
        # hardcoded total.
        assert len(names) == len(set(names)), (
            f"expected no duplicate containers, found: {names}"
        )

        elapsed = await wait_until_reachable(timeout=30.0)
        assert elapsed < 30.0
