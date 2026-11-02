"""The browser tier itself: Chromium starts, a login works, and the double
of the ComfyUI page loads behind the real gate."""

from __future__ import annotations

import pytest

from tests.browser.conftest import open_comfyui

pytestmark = pytest.mark.browser


async def test_the_double_page_loads_after_a_login(gate, browser) -> None:
    page = await open_comfyui(browser, gate, "?poll=0&ws=0")
    assert await page.text_content("#app") == "ComfyUI"
    assert page.url == f"{gate.url}/?poll=0&ws=0"
