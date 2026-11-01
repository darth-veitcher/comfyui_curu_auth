"""comfy-mcp, rauthy 0.37.2 and the real gate, end to end. Marker: ``comfy_mcp``.

comfy-mcp is the program that the resource-server mode is for. Here the real
``comfy-mcp`` command runs with a ``[backends.<name>.oidc]`` table: it gets
its own ``client_credentials`` token from rauthy, and sends it to the gate on
each HTTP call and on the ``/ws`` handshake. The test speaks MCP to it on
stdio, as an MCP client does.

comfy-mcp is a private repository, so this repository does not depend on it.
The test starts it with ``uvx`` from a pinned tag, with your own git access.
Set ``COMFY_MCP_COMMAND`` to run another build, for example
``uv run --project /abs/path/to/comfy-mcp comfy-mcp``. A relative path is
read from the root of this repository. Without access, each test fails: it
does not skip.

Run it with::

    uv run --group live pytest -m comfy_mcp
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests.live.conftest import (
    OTHER_RESOURCE,
    PROGRAM_CLIENT_ID,
    PROGRAM_CLIENT_SECRET,
    QUEUE_CALLS,
    WS_HANDSHAKES,
    Rauthy,
    StartGate,
)

pytestmark = pytest.mark.comfy_mcp

#: The comfy-mcp release that this test proves. v0.1.0 has the backend
#: OIDC client (comfy-mcp ADR-007).
COMFY_MCP_VERSION = "0.1.0"
COMFY_MCP_SOURCE = (
    f"git+ssh://git@github.com/darth-veitcher/comfy-mcp@v{COMFY_MCP_VERSION}"
)
#: Each start of comfy-mcp runs from here, so that a relative path in
#: ``COMFY_MCP_COMMAND`` means the same at the check and at each test.
ROOT = Path(__file__).resolve().parents[2]
#: The first ``uvx`` run builds comfy-mcp and its dependencies.
INSTALL_SECONDS = 600
#: The time for one MCP answer. A first call also gets a token from rauthy.
CALL_SECONDS = 60
#: comfy-mcp opens ``/ws`` in the background, after the first HTTP call.
WS_SECONDS = 10
SECRET_VARIABLE = "GATED_OIDC_SECRET"
#: The shape of a JWT. Neither log may hold one.
JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
WRONG_AUDIENCE = "(GET /queue: token refused: wrong audience)"


@pytest.fixture(scope="session")
def comfy_mcp_command() -> list[str]:
    """The command that starts comfy-mcp. The first run installs it."""
    if command := os.environ.get("COMFY_MCP_COMMAND"):
        argv = shlex.split(command)
    else:
        argv = ["uvx", "--from", COMFY_MCP_SOURCE, "comfy-mcp"]
    done = subprocess.run(
        [*argv, "--help"],
        capture_output=True,
        text=True,
        timeout=INSTALL_SECONDS,
        cwd=ROOT,
    )
    assert done.returncode == 0, (
        f"cannot start comfy-mcp with {argv}: {done.stderr[-2000:]}"
    )
    return argv


class McpSession:
    """A minimal MCP client on stdio: one JSON-RPC message on each line."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._next_id = 0

    async def _send(self, message: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message).encode() + b"\n")
        await self._process.stdin.drain()

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return await asyncio.wait_for(self._answer(request_id), CALL_SECONDS)

    async def _answer(self, request_id: int) -> dict[str, Any]:
        assert self._process.stdout is not None
        while True:
            line = await self._process.stdout.readline()
            assert line, "comfy-mcp closed stdout"
            message = json.loads(line)
            if message.get("id") == request_id:
                assert "error" not in message, message
                return message["result"]

    async def notify(self, method: str) -> None:
        await self._send({"jsonrpc": "2.0", "method": method})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})


class ComfyMcp:
    """One comfy-mcp process in its own process group, so that a stop also
    reaches comfy-mcp when ``uvx`` started it as a child."""

    def __init__(self, command: list[str], config: Path, workdir: Path) -> None:
        self._command = command
        self._config = config
        self._workdir = workdir
        self.process: asyncio.subprocess.Process | None = None
        self.server_info: dict[str, Any] = {}
        self.stderr = ""

    async def __aenter__(self) -> McpSession:
        # No COMFY_MCP_ variable and no configuration file of your own may
        # change the result.
        env = {k: v for k, v in os.environ.items() if not k.startswith("COMFY_MCP_")}
        env |= {
            "COMFY_MCP_CONFIG": str(self._config),
            "XDG_CONFIG_HOME": str(self._workdir / "no-config"),
            SECRET_VARIABLE: PROGRAM_CLIENT_SECRET,
        }
        self.process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=ROOT,
            start_new_session=True,
        )
        session = McpSession(self.process)
        try:
            result = await session.request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "comfyui-curu-auth-tests", "version": "0"},
                },
            )
            await session.notify("notifications/initialized")
        except BaseException:
            await self._stop()
            raise
        self.server_info = result.get("serverInfo", {})
        return session

    async def __aexit__(self, *exc: object) -> None:
        await self._stop()

    async def _stop(self) -> None:
        process = self.process
        assert process is not None
        if process.stdin is not None:
            process.stdin.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), 10)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        assert process.stderr is not None
        self.stderr = (await process.stderr.read()).decode(errors="replace")


def _config(path: Path, rauthy: Rauthy, resource: str) -> Path:
    path.write_text(
        f"""default_backend = "gated"

[backends.gated]
url = "{rauthy.audience}"

[backends.gated.oidc]
issuer = "{rauthy.issuer}"
client_id = "{PROGRAM_CLIENT_ID}"
client_secret_env = "{SECRET_VARIABLE}"
resource = "{resource}"
"""
    )
    return path


async def _start(rauthy: Rauthy, start_gate: StartGate) -> web.Application:
    return await start_gate(
        {
            "COMFYUI_CURU_AUTH_OIDC_AUDIENCE": rauthy.audience,
            "COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES": "comfy",
            "COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS": "nobody",
        }
    )


async def _wait_for_ws(app: web.Application) -> None:
    deadline = time.monotonic() + WS_SECONDS
    while not app[WS_HANDSHAKES] and time.monotonic() < deadline:
        await asyncio.sleep(0.1)


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    if "structuredContent" in result:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def _assert_no_token_or_secret(*logs: str) -> None:
    for text in logs:
        assert not JWT.search(text), "a log holds a JWT"
        assert PROGRAM_CLIENT_SECRET not in text, "a log holds the client secret"


def _assert_pinned_version(comfy_mcp: ComfyMcp) -> None:
    if "COMFY_MCP_COMMAND" not in os.environ:
        assert comfy_mcp.server_info.get("version") == COMFY_MCP_VERSION, (
            comfy_mcp.server_info
        )


async def test_comfy_mcp_reads_the_queue_through_the_gate_with_its_own_token(
    rauthy: Rauthy,
    start_gate: StartGate,
    comfy_mcp_command: list[str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="comfyui_curu_auth")
    app = await _start(rauthy, start_gate)
    config = _config(tmp_path / "config.toml", rauthy, rauthy.audience)

    comfy_mcp = ComfyMcp(comfy_mcp_command, config, tmp_path)
    async with comfy_mcp as session:
        queue = await session.call_tool("get_queue", {})
        backends = await session.call_tool("list_backends", {})
        await _wait_for_ws(app)
    stderr = comfy_mcp.stderr

    _assert_pinned_version(comfy_mcp)
    assert not queue.get("isError"), (queue, stderr)
    assert _structured(queue)["backend"] == "gated"
    listed = _structured(backends)["backends"]
    assert [(b["name"], b["online"]) for b in listed] == [("gated", True)], stderr
    # The call reached ComfyUI with a bearer token, not the static credential.
    sent = app[QUEUE_CALLS][0]
    assert sent is not None and JWT.fullmatch(sent.removeprefix("Bearer ")), (
        "GET /queue did not carry a JWT"
    )
    # comfy-mcp holds a /ws connection to the backend. The gate let the
    # handshake through, and it carried the same token as the HTTP call.
    assert app[WS_HANDSHAKES], f"no /ws handshake reached ComfyUI: {stderr}"
    assert app[WS_HANDSHAKES][0] == sent
    assert "token refused" not in caplog.text
    _assert_no_token_or_secret(stderr, caplog.text)


async def test_comfy_mcp_with_a_token_for_another_resource_gets_backend_auth_failed(
    rauthy: Rauthy,
    start_gate: StartGate,
    comfy_mcp_command: list[str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """comfy-mcp gets a new token after a 401 and tries one more time.

    The second try falls in the first wait of the gate. The gate checks a
    token also during a wait (ADR-008), so the answer is 401 again, not 429.
    """
    caplog.set_level(logging.DEBUG, logger="comfyui_curu_auth")
    app = await _start(rauthy, start_gate)
    config = _config(tmp_path / "config.toml", rauthy, OTHER_RESOURCE)

    comfy_mcp = ComfyMcp(comfy_mcp_command, config, tmp_path)
    async with comfy_mcp as session:
        queue = await session.call_tool("get_queue", {})
        # Only get_queue and its retry so far: list_backends also sends
        # GET /queue.
        refusals = [line for line in caplog.text.splitlines() if WRONG_AUDIENCE in line]
        backends = await session.call_tool("list_backends", {})
    stderr = comfy_mcp.stderr

    _assert_pinned_version(comfy_mcp)
    # Both tools fail for the right reason: the gate refused the audience,
    # and not the scope, the issuer or a rate limit.
    assert queue.get("isError"), (queue, stderr)
    assert _structured(queue)["code"] == "backend_auth_failed", (queue, stderr)
    listed = _structured(backends)["backends"]
    assert [(b["name"], b["online"], b.get("reason")) for b in listed] == [
        ("gated", False, "backend_auth_failed")
    ], stderr
    # The first try of get_queue and its retry with a new token. The retry
    # fell in the wait of the gate and still got 401: a 429 would give
    # backend_rate_limited above.
    assert len(refusals) == 2, caplog.text
    assert not app[QUEUE_CALLS]
    assert not app[WS_HANDSHAKES]
    _assert_no_token_or_secret(stderr, caplog.text)
