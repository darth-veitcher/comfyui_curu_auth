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


async def test_the_gate_rejects_the_ws_handshake(gate: Gate, browser) -> None:
    """Scenario: The gate rejects the ws handshake (rule T5).

    A restart closes the socket and empties the store. The frontend opens
    the socket again, and the gate rejects the handshake.
    """
    page = await open_comfyui(browser, gate, "?poll=0")
    await page.wait_for_function("window.socketOpens >= 1")

    gate.lose_sessions()
    await gate.close_sockets()

    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)


async def test_no_more_than_one_probe_in_2_seconds(gate: Gate, browser) -> None:
    """Rule T9: the frontend opens a socket each 300 ms after a close, but
    the module sends no more than one probe in 2 seconds."""
    page = await open_comfyui(browser, gate, "?poll=0")
    await page.wait_for_function("window.socketOpens >= 1")
    gate.refuse_ws = True
    gate.seen.clear()

    await gate.close_sockets()
    await asyncio.sleep(3)

    probes = [path for path in gate.seen if path.endswith("/session_loss.js")]
    handshakes = [path for path in gate.seen if path == "/ws"]
    assert len(handshakes) >= 5, "the double must open the socket again"
    assert 1 <= len(probes) <= 2
    assert page.url == f"{gate.url}/?poll=0"


def _failure_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "authentication failure" in record.getMessage()
    ]


async def test_no_new_log_line_after_the_move(
    gate: Gate, browser, caplog: pytest.LogCaptureFixture
) -> None:
    """Scenario: No new log line after the move (SC-002, SC-003)."""
    page = await open_comfyui(browser, gate)
    await page.wait_for_function("window.socketOpens >= 1")

    with caplog.at_level("WARNING", logger="comfyui_curu_auth"):
        gate.lose_sessions()
        await gate.close_sockets()
        assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)
        await asyncio.sleep(0.5)
        before_the_move = len(_failure_lines(caplog))
        await asyncio.sleep(60)
        after_the_move = len(_failure_lines(caplog)) - before_the_move

    assert 1 <= before_the_move <= 10
    assert after_the_move == 0


async def test_no_second_move_within_5_seconds(gate: Gate, browser) -> None:
    """Rule T10: the module does not move the tab again if the last move
    was less than 5 seconds ago, so a page cannot loop."""
    page = await open_comfyui(browser, gate, "?ws=0")
    await page.evaluate(
        "sessionStorage.setItem('curu-auth:left-at', String(Date.now()))"
    )

    gate.lose_sessions()

    await asyncio.sleep(2.5)
    assert page.url == f"{gate.url}/?ws=0", "a move inside the 5 seconds"
    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)


async def test_many_rejections_cause_one_move(gate: Gate, browser) -> None:
    """Rule T11: after the module starts to leave, each later rejection
    does nothing. The login page gets one request."""
    page = await open_comfyui(browser, gate, "?poll=0&ws=0")
    gate.lose_sessions()
    gate.seen.clear()

    await page.evaluate(
        "() => { for (let i = 0; i < 20; i++) fetch('/api/jobs').catch(() => null); }"
    )

    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)
    await asyncio.sleep(0.5)
    assert gate.seen.count(LOGIN_PATH) == 1
