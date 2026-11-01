"""comfy-mcp, rauthy 0.37.2 and the real gate, end to end. Marker: ``comfy_mcp``.

comfy-mcp is the program that the resource-server mode is for. Here the real
``comfy-mcp`` command runs with a ``[backends.<name>.oidc]`` table: it gets
its own ``client_credentials`` token from rauthy, and sends it to the gate on
each HTTP call and on the ``/ws`` handshake. The test speaks MCP to it on
stdio, as an MCP client does.

comfy-mcp is a private repository, so this repository does not depend on it.
The test starts it with ``uvx`` from a pinned tag, with your own git access.
Set ``COMFY_MCP_COMMAND`` to run another build, for example
``uv run --project ../comfy-mcp comfy-mcp``. Without access, each test fails:
it does not skip.

Run it with::

    uv run --group live pytest -m comfy_mcp
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.live.conftest import (
    OTHER_RESOURCE,
    PROGRAM_CLIENT_ID,
    PROGRAM_CLIENT_SECRET,
    WS_HANDSHAKES,
    Rauthy,
    StartGate,
)

pytestmark = pytest.mark.comfy_mcp

#: The comfy-mcp release that this test proves. v0.1.0 has the backend
#: OIDC client (comfy-mcp ADR-007).
COMFY_MCP_SOURCE = "git+ssh://git@github.com/darth-veitcher/comfy-mcp@v0.1.0"
#: The first ``uvx`` run builds comfy-mcp and its dependencies.
INSTALL_SECONDS = 600
#: The time for one MCP answer. A first call also gets a token from rauthy.
CALL_SECONDS = 60
SECRET_VARIABLE = "GATED_OIDC_SECRET"


@pytest.fixture(scope="session")
def comfy_mcp_command() -> list[str]:
    """The command that starts comfy-mcp. The first run installs it."""
    if command := os.environ.get("COMFY_MCP_COMMAND"):
        argv = shlex.split(command)
    else:
        argv = ["uvx", "--from", COMFY_MCP_SOURCE, "comfy-mcp"]
    done = subprocess.run(
        [*argv, "--help"], capture_output=True, text=True, timeout=INSTALL_SECONDS
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
        assert self._process.stdout is not None
        while True:
            line = await asyncio.wait_for(self._process.stdout.readline(), CALL_SECONDS)
            assert line, "comfy-mcp closed stdout"
            message = json.loads(line)
            if message.get("id") == request_id:
                assert "error" not in message, message
                return message["result"]

    async def notify(self, method: str) -> None:
        await self._send({"jsonrpc": "2.0", "method": method})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})


async def _open(
    command: list[str], config: Path, workdir: Path
) -> tuple[asyncio.subprocess.Process, McpSession]:
    # No COMFY_MCP_ variable and no configuration file of your own may change
    # the result.
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMFY_MCP_")}
    env |= {
        "COMFY_MCP_CONFIG": str(config),
        "XDG_CONFIG_HOME": str(workdir / "no-config"),
        SECRET_VARIABLE: PROGRAM_CLIENT_SECRET,
    }
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=workdir,
    )
    session = McpSession(process)
    await session.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "comfyui-curu-auth-tests", "version": "0"},
        },
    )
    await session.notify("notifications/initialized")
    return process, session


async def _close(process: asyncio.subprocess.Process) -> str:
    """Stop comfy-mcp, and give its stderr for the failure message."""
    if process.stdin is not None:
        process.stdin.close()
    try:
        await asyncio.wait_for(process.wait(), 10)
    except TimeoutError:
        process.kill()
        await process.wait()
    assert process.stderr is not None
    return (await process.stderr.read()).decode(errors="replace")


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


async def _start(rauthy: Rauthy, start_gate: StartGate):
    return await start_gate(
        {
            "COMFYUI_CURU_AUTH_OIDC_AUDIENCE": rauthy.audience,
            "COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES": "comfy",
            "COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS": "nobody",
        }
    )


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    if "structuredContent" in result:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


async def test_comfy_mcp_reads_the_queue_through_the_gate_with_its_own_token(
    rauthy: Rauthy,
    start_gate: StartGate,
    comfy_mcp_command: list[str],
    tmp_path: Path,
) -> None:
    app = await _start(rauthy, start_gate)
    config = _config(tmp_path / "config.toml", rauthy, rauthy.audience)

    process, session = await _open(comfy_mcp_command, config, tmp_path)
    try:
        queue = await session.call_tool("get_queue", {})
        backends = await session.call_tool("list_backends", {})
    finally:
        stderr = await _close(process)

    assert not queue.get("isError"), (queue, stderr)
    assert _structured(queue)["backend"] == "gated"
    listed = _structured(backends)["backends"]
    assert [(b["name"], b["online"]) for b in listed] == [("gated", True)], stderr
    # comfy-mcp holds a /ws connection to each backend it uses. The gate
    # checked the same token on the handshake and let it through.
    assert app[WS_HANDSHAKES], stderr
    # Never a token in the log of comfy-mcp.
    assert PROGRAM_CLIENT_SECRET not in stderr


async def test_comfy_mcp_with_a_token_for_another_resource_gets_backend_auth_failed(
    rauthy: Rauthy,
    start_gate: StartGate,
    comfy_mcp_command: list[str],
    tmp_path: Path,
) -> None:
    """comfy-mcp gets a new token after a 401 and tries one more time.

    The second try falls in the first wait of the gate. The gate checks a
    token also during a wait (ADR-008), so the answer is 401 again, not 429.
    """
    app = await _start(rauthy, start_gate)
    config = _config(tmp_path / "config.toml", rauthy, OTHER_RESOURCE)

    process, session = await _open(comfy_mcp_command, config, tmp_path)
    try:
        queue = await session.call_tool("get_queue", {})
    finally:
        stderr = await _close(process)

    assert queue.get("isError"), (queue, stderr)
    text = json.dumps(queue)
    assert "backend_auth_failed" in text, (queue, stderr)
    assert "backend_rate_limited" not in text
    assert not app[WS_HANDSHAKES]
