"""``web/session_loss.js`` sends an open tab to the login page when the gate
rejects its session, and only then (spec 005).

Each test names its scenario from ``specs/005-session-loss-reload/features/``.
The rule ids (T1 to T11) are those of ``contracts/tab-module.md``.
"""

from __future__ import annotations

import asyncio

import pytest

from gate import LOGIN_PATH
from tests.browser.conftest import Gate, open_comfyui, wait_for_path

pytestmark = pytest.mark.browser

#: SC-001: the tab shows the login page within this many seconds.
LIMIT_SECONDS = 5


async def test_the_session_store_loses_the_session(gate: Gate, browser) -> None:
    """Scenario: The session store loses the session."""
    page = await open_comfyui(browser, gate)

    gate.lose_sessions()

    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)


async def test_the_gate_rejects_a_poll(gate: Gate, browser) -> None:
    """Scenario: The gate rejects a poll (rule T1)."""
    page = await open_comfyui(browser, gate, "?ws=0")

    gate.lose_sessions()

    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)


async def test_a_redirect_to_the_login_page_moves_the_tab(gate: Gate, browser) -> None:
    """Scenario: The gate rejects a poll, for a fetch that asks for HTML
    (rule T2). The gate answers with a redirect, and fetch follows it."""
    page = await open_comfyui(browser, gate, "?poll=0&ws=0")
    gate.lose_sessions()

    await page.evaluate(
        "fetch('/api/jobs', {headers: {Accept: 'text/html'}}).catch(() => {})"
    )

    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)


async def test_a_valid_session_keeps_the_tab(gate: Gate, browser) -> None:
    """The control of the tests above: with no session loss, the poll and
    the socket keep the tab on its page."""
    page = await open_comfyui(browser, gate)

    await asyncio.sleep(2)

    assert page.url == f"{gate.url}/"
