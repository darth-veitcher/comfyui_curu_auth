"""The browser tier: ``web/session_loss.js`` in a real Chromium, against the
real gate middleware on a loopback port. Marker: ``browser``. Run it with::

    uv run --group live pytest -m browser

Install Chromium once with ``uv run --group live playwright install
chromium``. Without Playwright or Chromium each test fails: it does not
skip, so a missing tier is never a silent pass (the rule of the other
tiers).

The gate is wired as ``__init__.py`` wires it (one ``SessionStore`` and one
``RateLimiter`` for the middleware and the login form). In front of it is a
small double of the ComfyUI page. The double page imports the module, polls
``/api/jobs`` and opens ``/ws`` again 300 ms after each close, as the real
frontend does (ADR-005).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from aiohttp import WSCloseCode, web

from gate import (
    LOGIN_PATH,
    RateLimiter,
    SessionStore,
    build_gate_middleware,
    build_login_routes,
)

#: Test value only. Never used outside this tier.
CREDENTIAL = "browser-tier-test-credential"
REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_FILE = REPO_ROOT / "web" / "session_loss.js"
#: Where ComfyUI serves the files of ``WEB_DIRECTORY`` for this node.
MODULE_PATH = "/extensions/comfyui_curu_auth/session_loss.js"

#: The double of the ComfyUI page. The query string selects the parts:
#: ``poll=0`` stops the ``/api/jobs`` poll, ``ws=0`` stops the socket.
PAGE = """<!doctype html>
<html><head><title>ComfyUI</title></head><body>
<p id="app">ComfyUI</p>
<script type="module">
  const params = new URLSearchParams(location.search);
  window.results = [];
  try {
    await import("MODULE_PATH");
    window.moduleLoaded = true;
  } catch (error) {
    window.moduleLoaded = false;
  }
  window.callOther = async () => {
    const response = await fetch("/api/other");
    window.results.push(response.status);
    return response.status;
  };
  if (params.get("poll") !== "0") {
    setInterval(() => {
      fetch("/api/jobs").then(
        (response) => window.results.push(response.status),
        () => window.results.push("network-error"),
      );
    }, 1000);
  }
  if (params.get("ws") !== "0") {
    window.socketOpens = 0;
    const open = () => {
      const ws = new WebSocket(`ws://${location.host}/ws`);
      ws.addEventListener("open", () => { window.socketOpens += 1; });
      ws.addEventListener("close", () => setTimeout(open, 300));
    };
    open();
  }
</script>
</body></html>
""".replace("MODULE_PATH", MODULE_PATH)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class Gate:
    """The real gate on a loopback port, with a double of ComfyUI behind it."""

    port: int
    sessions: SessionStore = field(default_factory=SessionStore)
    rate_limiter: RateLimiter = field(default_factory=RateLimiter)
    sockets: set[web.WebSocketResponse] = field(default_factory=set)
    #: The paths of the requests that reached ComfyUI (the double).
    reached: list[str] = field(default_factory=list)
    #: The path of each request that reached the server, before the gate.
    seen: list[str] = field(default_factory=list)
    #: When true, ``/ws`` refuses each handshake with its own HTTP 403, as
    #: a proxy or a broken ComfyUI can. This is not a gate rejection.
    refuse_ws: bool = False
    #: An ``oidc.OIDCConfig``. When set, the OIDC routes are on.
    oidc_config: Any = None
    runner: web.AppRunner | None = None
    site: web.TCPSite | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def build_app(self) -> web.Application:
        from oidc import OIDC_CALLBACK_PATH, OIDC_START_PATH

        public_paths = {LOGIN_PATH}
        if self.oidc_config is not None:
            public_paths |= {OIDC_START_PATH, OIDC_CALLBACK_PATH}
        app = web.Application(
            middlewares=[
                self._count,
                build_gate_middleware(
                    CREDENTIAL,
                    sessions=self.sessions,
                    rate_limiter=self.rate_limiter,
                    public_paths=public_paths,
                ),
            ]
        )
        login_get, login_post = build_login_routes(
            CREDENTIAL, sessions=self.sessions, rate_limiter=self.rate_limiter
        )
        app.router.add_get(LOGIN_PATH, login_get)
        app.router.add_post(LOGIN_PATH, login_post)
        if self.oidc_config is not None:
            from oidc import AuthorizationRequestStore, build_oidc_routes

            start, callback = build_oidc_routes(
                self.oidc_config,
                sessions=self.sessions,
                store=AuthorizationRequestStore(),
                rate_limiter=self.rate_limiter,
            )
            app.router.add_get(OIDC_START_PATH, start)
            app.router.add_get(OIDC_CALLBACK_PATH, callback)
        app.router.add_get("/", self._page)
        app.router.add_get(MODULE_PATH, self._module)
        app.router.add_get("/api/jobs", self._jobs)
        app.router.add_get("/api/other", self._other)
        app.router.add_get("/ws", self._ws)
        return app

    @web.middleware
    async def _count(self, request: web.Request, handler: Any) -> web.StreamResponse:
        self.seen.append(request.path)
        return await handler(request)

    async def _page(self, request: web.Request) -> web.Response:
        self.reached.append(request.path)
        return web.Response(text=PAGE, content_type="text/html")

    async def _module(self, request: web.Request) -> web.StreamResponse:
        # Served as ComfyUI serves a file of WEB_DIRECTORY. Read at each
        # request, so the tier loads the file of the working tree.
        self.reached.append(request.path)
        if not MODULE_FILE.is_file():
            raise web.HTTPNotFound()
        return web.Response(
            text=MODULE_FILE.read_text(), content_type="application/javascript"
        )

    async def _jobs(self, request: web.Request) -> web.Response:
        self.reached.append(request.path)
        return web.json_response({"jobs": []})

    async def _other(self, request: web.Request) -> web.Response:
        """A ComfyUI route or another node that gives its own HTTP 401."""
        self.reached.append(request.path)
        return web.json_response({"error": "not allowed"}, status=401)

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        self.reached.append(request.path)
        if self.refuse_ws:
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            self.sockets.discard(ws)
        return ws

    async def start(self) -> None:
        if self.runner is None:
            self.runner = web.AppRunner(self.build_app())
            await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await self.site.start()

    async def stop(self) -> None:
        """Make the server unreachable, and keep the sessions. The cleanup
        of the runner also closes each keep-alive connection, so no request
        of the tab reaches the server until :meth:`start`."""
        await self.close_sockets()
        if self.runner is not None:
            await self.runner.cleanup()
        self.runner = None
        self.site = None

    async def close_sockets(self) -> None:
        """Close each open ``/ws`` socket from the server side."""
        for ws in list(self.sockets):
            await ws.close(code=WSCloseCode.GOING_AWAY)

    def lose_sessions(self) -> None:
        """Do what a ComfyUI restart does to the in-memory sessions."""
        self.sessions._tokens.clear()

    async def cleanup(self) -> None:
        await self.close_sockets()
        if self.runner is not None:
            await self.runner.cleanup()


@pytest.fixture
async def gate() -> AsyncIterator[Gate]:
    instance = Gate(port=free_port())
    await instance.start()
    yield instance
    await instance.cleanup()


@pytest.fixture
async def browser() -> AsyncIterator[Any]:
    """A Chromium from Playwright. Fails, and does not skip, without it."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.fail(
            "the browser tier needs Playwright: "
            "run it with `uv run --group live pytest -m browser`"
        )
    async with async_playwright() as playwright:
        try:
            instance = await playwright.chromium.launch()
        except Exception as error:
            pytest.fail(
                "the browser tier needs Chromium: run "
                f"`uv run --group live playwright install chromium` ({error})"
            )
        yield instance
        await instance.close()


async def log_in(page: Any, gate: Gate) -> None:
    """Log in through the login form of the gate, as a person does."""
    await page.goto(f"{gate.url}{LOGIN_PATH}")
    await page.fill("input[name=token]", CREDENTIAL)
    await page.press("input[name=token]", "Enter")
    await page.wait_for_url(f"{gate.url}/", timeout=5_000)


async def open_comfyui(browser: Any, gate: Gate, query: str = "") -> Any:
    """Log in in a new context, and open the double of the ComfyUI page."""
    context = await browser.new_context()
    page = await context.new_page()
    await log_in(page, gate)
    await page.goto(f"{gate.url}/{query}")
    await page.wait_for_function("window.moduleLoaded !== undefined")
    return page


async def wait_for_path(page: Any, path: str, timeout: float) -> bool:
    """Whether the tab reaches ``path`` within ``timeout`` seconds."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if page.url.split("?")[0].endswith(path):
            return True
        await asyncio.sleep(0.05)
    return page.url.split("?")[0].endswith(path)
