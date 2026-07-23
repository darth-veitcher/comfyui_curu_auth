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

import aiohttp
import pytest

from tests.system.conftest import AUTH_HEADERS, BASE_URL, compose, wait_until_reachable

pytestmark = pytest.mark.system


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
