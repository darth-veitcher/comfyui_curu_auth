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

from tests.system.conftest import AUTH_HEADERS, BASE_URL, compose, wait_until_reachable

pytestmark = pytest.mark.system

WS_URL = "ws://localhost:8188/ws"


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
