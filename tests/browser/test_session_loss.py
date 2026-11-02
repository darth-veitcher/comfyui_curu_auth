"""``web/session_loss.js`` sends an open tab to the login page when the gate
rejects its session, and only then (spec 005).

Each test names its scenario from ``specs/005-session-loss-reload/features/``.
The rule ids (T1 to T11) are those of ``contracts/tab-module.md``.
"""

from __future__ import annotations

import asyncio

import pytest

from gate import LOGIN_PATH
from tests.browser.conftest import CREDENTIAL, Gate, open_comfyui, wait_for_path

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


async def test_the_user_logs_in_again(gate: Gate, browser) -> None:
    """Scenario: The user logs in again. The login form sends the tab to
    ``/``, and the ComfyUI page loads with the module."""
    page = await open_comfyui(browser, gate, "?ws=0")
    gate.lose_sessions()
    assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)
    # The first rejection of the stale cookie counts as one failure, so the
    # login form waits 1 second (ADR-004, ADR-005). A person needs longer.
    await asyncio.sleep(1.5)

    await page.fill("input[name=token]", CREDENTIAL)
    await page.press("input[name=token]", "Enter")
    await page.wait_for_url(f"{gate.url}/", timeout=5_000)
    await page.wait_for_function("window.moduleLoaded !== undefined")

    assert await page.evaluate("window.moduleLoaded") is True
    assert await page.text_content("#app") == "ComfyUI"
    await asyncio.sleep(2)
    assert page.url == f"{gate.url}/"


async def test_an_oidc_session_is_lost(browser) -> None:
    """Scenario: An OIDC session is lost. The OIDC login gives a session of
    the same store, so its loss moves the tab in the same way."""
    from urllib.parse import parse_qs, urlsplit

    from oidc import OIDC_CALLBACK_PATH, OIDC_START_PATH, LoginAllowlist, OIDCConfig
    from tests.browser.conftest import free_port
    from tests.support.fake_issuer import CLIENT_ID, CLIENT_SECRET, FakeIssuer

    async with FakeIssuer() as issuer:
        port = free_port()
        gate = Gate(
            port=port,
            oidc_config=OIDCConfig(
                issuer_url=issuer.issuer,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri=f"http://127.0.0.1:{port}{OIDC_CALLBACK_PATH}",
                allowlist=LoginAllowlist(allow_any=True),
            ),
        )
        await gate.start()
        try:
            context = await browser.new_context()
            started = await context.request.get(
                f"{gate.url}{OIDC_START_PATH}", max_redirects=0
            )
            query = parse_qs(urlsplit(started.headers["location"]).query)
            issuer.nonce = query["nonce"][0]
            callback = await context.request.get(
                f"{gate.url}{OIDC_CALLBACK_PATH}",
                params={"code": "a-code", "state": query["state"][0]},
                max_redirects=0,
            )
            assert callback.status == 200, await callback.text()

            page = await context.new_page()
            await page.goto(f"{gate.url}/?ws=0")
            await page.wait_for_function("window.moduleLoaded !== undefined")
            assert page.url == f"{gate.url}/?ws=0", "the OIDC login gave no session"

            gate.lose_sessions()

            assert await wait_for_path(page, LOGIN_PATH, LIMIT_SECONDS)
        finally:
            await gate.cleanup()
