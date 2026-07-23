"""Shared `docker compose` lifecycle helpers for the live ComfyUI harness.

Adapted from the equivalent module in the sibling repo
``~/repos/JAMESVEITCH/curu`` (same author) -- but the HTTP-polling helper
below is a fresh, async rewrite against ``aiohttp.ClientSession``, not a
port of curu's own ``httpx``-based version: this project deliberately has
no ``httpx``/``requests`` dependency (see ``research.md``'s "Drive the
harness from tests" decision).
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import time
from pathlib import Path

import aiohttp
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "http://localhost:8188"
HEALTH_URL = f"{BASE_URL}/"
COMFYUI_PORT = 8188

#: Fixed test credential this harness's docker-compose.yml pins via
#: COMFYUI_CURU_AUTH_TOKEN (spec FR-003) -- never meaningful outside this
#: local, disposable context.
TEST_AUTH_TOKEN = "local-harness-test-credential"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_AUTH_TOKEN}"}


def compose(
    *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `docker compose <args>` from the repo root, capturing output."""

    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def port_reachable(host: str = "localhost", port: int = COMFYUI_PORT) -> bool:
    """True iff a TCP connection to ``host:port`` succeeds right now."""

    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


async def wait_until_reachable(timeout: float = 180.0, interval: float = 2.0) -> float:
    """Poll ``HEALTH_URL`` until it answers with *any* HTTP response, or
    raise after ``timeout``. Returns the elapsed time in seconds.

    Deliberately treats both 200 and 401 as "reachable" here -- this helper
    only answers "is the port up and speaking HTTP yet", not "is the gate
    correctly enforcing". That second question is asserted explicitly by
    the tests that call this helper (e.g.
    ``test_harness_boots_and_gate_enforces``), which is the right place
    for it: a 200 here just means this helper returns sooner, and the
    test's own next assertion (expects 401 unauthenticated) fails loudly
    and specifically if the gate isn't actually active. Contrast with
    ``docker/comfyui/healthcheck.py``, which has no such follow-up
    assertion and therefore MUST require 401 specifically (FR-004).

    Polling, not sleeping-and-hoping, so the bound is on actual readiness,
    not a guessed sleep duration. 180s default matches SC-001's revised,
    realistic cold-start budget (research.md).
    """

    start = time.monotonic()
    deadline = start + timeout
    last_error: Exception | None = None
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            try:
                async with session.get(
                    HEALTH_URL, timeout=aiohttp.ClientTimeout(total=5.0)
                ) as response:
                    if response.status in (200, 401):
                        return time.monotonic() - start
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
            await asyncio.sleep(interval)
    raise TimeoutError(
        f"ComfyUI did not become reachable within {timeout}s "
        f"(last error: {last_error!r})"
    )


def wait_until_unreachable(timeout: float = 30.0, interval: float = 1.0) -> None:
    """Poll until the port is no longer accepting connections, or raise."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_reachable():
            return
        time.sleep(interval)
    raise TimeoutError(f"port {COMFYUI_PORT} was still reachable after {timeout}s")


@pytest.fixture(scope="package", autouse=True)
def _built_image() -> None:
    """Build the harness image once for the whole `tests/system` package."""

    result = compose("build")
    assert result.returncode == 0, result.stderr


@pytest.fixture
async def running_harness():
    """Bring the harness up, wait for readiness, yield its base URL, tear down."""

    result = compose("up", "-d")
    assert result.returncode == 0, result.stderr
    await wait_until_reachable(timeout=180.0)
    try:
        yield BASE_URL
    finally:
        compose("down", timeout=60)
