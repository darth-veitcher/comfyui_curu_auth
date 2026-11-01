"""The full OIDC login through a real rauthy 0.37.2, in a real browser
(spec 003, SC-001; scenario "A real rauthy login"). Marker: ``rauthy``.

rauthy's login page is a two-step form with a proof of work in JavaScript,
so Playwright drives Chromium through it. The gate is the real
``__init__.py`` wiring on a loopback port (``tests/live/conftest.py``).
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from tests.live.conftest import (
    USER_EMAIL,
    USER_ID,
    USER_PASSWORD,
    Rauthy,
    StartGate,
)

pytestmark = pytest.mark.rauthy

#: The package name that ``tests.test_oidc._load_init_with_fake_server`` uses.
_OIDC_MODULE = "_comfyui_curu_auth_under_test.oidc"


def _spy_on_token_headers(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the header of each ID token the running gate checks."""
    module = sys.modules[_OIDC_MODULE]
    real = module.read_token_header
    headers: list[dict[str, Any]] = []

    def spy(token: str) -> dict[str, Any]:
        header = real(token)
        headers.append(header)
        return header

    monkeypatch.setattr(module, "read_token_header", spy)
    return headers


async def _log_in(gate_url: str) -> tuple[list[dict[str, Any]], int, int]:
    """Log in through rauthy in Chromium. Return the cookies of the gate, the
    status of the callback, and the status of ``GET /queue`` afterwards."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            callbacks: list[int] = []
            page.on(
                "response",
                lambda response: (
                    callbacks.append(response.status)
                    if "/curu-auth/oidc/callback" in response.url
                    else None
                ),
            )
            await page.goto(f"{gate_url}/curu-auth/oidc/start")
            await page.fill("input[name=email]", USER_EMAIL)
            await page.click("button[type=submit][name=Login]")
            password = page.locator("input[type=password]:visible")
            await password.wait_for(timeout=30_000)
            await password.fill(USER_PASSWORD)
            await page.click("button[type=submit][name=Login]")
            await page.wait_for_url(f"{gate_url}/**", timeout=30_000)
            await page.wait_for_load_state()
            cookies = [
                dict(cookie)
                for cookie in await context.cookies(gate_url)
                if cookie.get("name") == "curu_auth"
            ]
            queue = await context.request.get(f"{gate_url}/queue")
            return cookies, (callbacks or [0])[-1], queue.status
        finally:
            await browser.close()


async def test_a_rauthy_login_with_an_eddsa_id_token_gives_the_session_cookie(
    rauthy: Rauthy, start_gate: StartGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: A real rauthy login."""
    assert rauthy.issuer.endswith("/auth/v1/")
    await start_gate({"COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS": USER_ID})
    headers = _spy_on_token_headers(monkeypatch)

    cookies, callback_status, queue_status = await _log_in(
        f"http://127.0.0.1:{rauthy.gate_port}"
    )

    assert [header.get("alg") for header in headers] == ["EdDSA"]
    assert callback_status == 302
    assert len(cookies) == 1
    assert cookies[0]["httpOnly"] is True
    assert queue_status == 200


async def test_a_rauthy_person_who_is_not_on_the_allowlist_gets_no_cookie(
    rauthy: Rauthy, start_gate: StartGate
) -> None:
    """Scenario: A subject that is not listed, with a real provider."""
    await start_gate({"COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS": "someone-else"})

    cookies, callback_status, queue_status = await _log_in(
        f"http://127.0.0.1:{rauthy.gate_port}"
    )

    assert callback_status == 401
    assert cookies == []
    # 429 when the next request lands inside the backoff of the refused
    # callback (1 second), else 401. Both mean no access.
    assert queue_status in (401, 429)
