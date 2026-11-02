"""The real ComfyUI frontend imports ``web/session_loss.js``, and a real
restart sends an open tab to the login page (spec 005, rule T12).

Marker: ``system``. It needs Docker and the ``live`` group for Chromium::

    uv run --group live pytest -m system -k session_loss
"""

from __future__ import annotations

import asyncio
import re
import time

import aiohttp
import pytest

from gate import LOGIN_PATH
from tests.system.conftest import (
    AUTH_HEADERS,
    BASE_URL,
    TEST_AUTH_TOKEN,
    compose,
    wait_until_reachable,
)

pytestmark = pytest.mark.system

#: Where ComfyUI serves the module of this node (``WEB_DIRECTORY``). The
#: harness mounts the repository as ``custom_nodes/comfyui_curu_auth``.
MODULE_URL = f"{BASE_URL}/extensions/comfyui_curu_auth/session_loss.js"
#: SC-001 and SC-002.
LIMIT_SECONDS = 5
MAX_LINES = 10
_FAILURE = re.compile(r"authentication failure from (\S+)")


@pytest.fixture(autouse=True)
def _ensure_torn_down_after_each_test():
    yield
    compose("down", timeout=60)


async def test_the_module_url_is_gated(running_harness: str) -> None:
    """Article II and FR-011: the gate covers the module like each other
    route, and serves it after a login."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            MODULE_URL, headers={"X-Forwarded-For": "203.0.113.50"}
        ) as response:
            assert response.status == 401
            assert response.headers.get("X-Curu-Auth") == "login-required"
        async with session.get(MODULE_URL, headers=AUTH_HEADERS) as response:
            assert response.status == 200
            assert "fetchWithSessionCheck" in await response.text()


def _tab_failure_lines(logs: str) -> list[str]:
    """The "authentication failure" lines of the tab. The health check of
    the container polls from 127.0.0.1 with no credential; it is not the
    tab."""
    return [
        line
        for line in logs.splitlines()
        if (match := _FAILURE.search(line)) and match.group(1) != "127.0.0.1"
    ]


async def test_a_restart_sends_the_open_tab_to_the_login_page(
    running_harness: str,
) -> None:
    """Scenario: The session store loses the session, with the real
    frontend of ComfyUI v0.27.0 and a real restart (SC-001, SC-002)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.goto(f"{BASE_URL}{LOGIN_PATH}")
            await page.fill("input[name=token]", TEST_AUTH_TOKEN)
            await page.press("input[name=token]", "Enter")
            await page.wait_for_url(f"{BASE_URL}/", timeout=30_000)
            # The real frontend imports the module of each node.
            await page.wait_for_function(
                "window.fetch.name === 'fetchWithSessionCheck'", timeout=120_000
            )

            # `restart` returns after the stop and the start. Docker Desktop
            # keeps the published port open during the restart, so the port
            # cannot show that ComfyUI is down. The browser tier checks that
            # the tab stays while the server is down (SC-004).
            restarted = compose("restart", "comfyui", timeout=120)
            assert restarted.returncode == 0, restarted.stderr
            await wait_until_reachable(timeout=180.0, interval=0.25)
            ready = time.monotonic()

            while time.monotonic() - ready < LIMIT_SECONDS:
                if page.url.endswith(LOGIN_PATH):
                    break
                await asyncio.sleep(0.05)
            assert page.url.endswith(LOGIN_PATH), "no move within 5 seconds"

            await asyncio.sleep(10)
            logs = compose("logs", "--since", "3m", "comfyui", timeout=60).stdout
            lines = _tab_failure_lines(logs.split("Credential:")[-1])
            assert 1 <= len(lines) <= MAX_LINES, lines
        finally:
            await browser.close()
