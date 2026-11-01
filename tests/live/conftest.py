"""The live tier: a real rauthy 0.37.2 in Docker, and the real gate on a
loopback port. Marker: ``rauthy``. Run it with::

    uv run --group live pytest -m rauthy

rauthy reads its bootstrap files only at its first start, so each test run
starts a new container. Without Docker, each test fails: it does not skip,
so a missing tier is never a silent pass (the same rule as comfy-mcp and
curu-memory).

The gate runs the real ``__init__.py`` wiring against a double of ComfyUI's
``server`` module, as ``tests/test_oidc.py`` does, but on a real port, so a
real browser and a real provider can reach it.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from aiohttp import web

IMAGE = "ghcr.io/sebadob/rauthy:0.37.2"
#: The login client of the gate. rauthy needs a secret of 64 characters.
#: Test values only.
LOGIN_CLIENT_ID = "comfyui-curu-auth"
LOGIN_CLIENT_SECRET = "c" * 64
#: The test person.
USER_ID = "curuauthtestuser00000001"
USER_EMAIL = "tester@localhost"
USER_PASSWORD = "Test-Password-For-Rauthy-1"
CALLBACK = "/curu-auth/oidc/callback"
#: The client of a program, as comfy-mcp uses it for a backend (spec 004).
PROGRAM_CLIENT_ID = "comfy-mcp-backend"
PROGRAM_CLIENT_SECRET = "p" * 64
#: Another resource that the program client may ask for.
OTHER_RESOURCE = "http://other-backend.test"
#: The bootstrap API key that sets allowed_resources. Test value only.
API_KEY_SECRET = "k" * 64


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class Rauthy:
    url: str
    issuer: str
    #: The port of the gate. The redirect URI of the login client names it.
    gate_port: int

    @property
    def audience(self) -> str:
        """The audience of the gate: its own URL, as a resource indicator."""
        return f"http://127.0.0.1:{self.gate_port}"

    def program_token(self, **form: str) -> tuple[int, dict[str, object]]:
        """A client_credentials token request, with the secret in the form,
        because rauthy 0.37.2 refuses HTTP Basic on this grant."""
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": PROGRAM_CLIENT_ID,
                "client_secret": PROGRAM_CLIENT_SECRET,
                **form,
            }
        ).encode()
        request = urllib.request.Request(f"{self.issuer}oidc/token", data=body)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)


def _bootstrap(directory: Path, gate_port: int) -> None:
    login_client = {
        "id": LOGIN_CLIENT_ID,
        "name": LOGIN_CLIENT_ID,
        "secret": {"Plain": LOGIN_CLIENT_SECRET},
        "redirect_uris": [f"http://127.0.0.1:{gate_port}{CALLBACK}"],
        "enabled": True,
        "flows_enabled": ["authorization_code"],
        "access_token_alg": "RS256",
        # The point of the live test: rauthy signs the ID token with EdDSA.
        "id_token_alg": "EdDSA",
        "auth_code_lifetime": 60,
        "access_token_lifetime": 300,
        "scopes": ["openid", "profile", "email"],
        "default_scopes": ["openid"],
        "challenges": ["S256"],
        "force_mfa": False,
    }
    user = {
        "id": USER_ID,
        "email": USER_EMAIL,
        "given_name": "Tester",
        "password": {"Plain": USER_PASSWORD},
        "roles": [],
        "enabled": True,
        "email_verified": True,
    }
    program_client = {
        "id": PROGRAM_CLIENT_ID,
        "name": PROGRAM_CLIENT_ID,
        "secret": {"Plain": PROGRAM_CLIENT_SECRET},
        "redirect_uris": [],
        "enabled": True,
        "flows_enabled": ["client_credentials"],
        "access_token_alg": "RS256",
        "id_token_alg": "RS256",
        "auth_code_lifetime": 60,
        "access_token_lifetime": 300,
        "scopes": ["openid", "comfy"],
        # rauthy puts only the default scopes in a client_credentials token.
        "default_scopes": ["openid", "comfy"],
        "force_mfa": False,
    }
    access = [{"group": "Clients", "access_rights": ["read", "update"]}]
    api_key = {
        "name": "bootstrap",
        "exp": int(time.time()) + 3600,
        "access": access,
        "secret": {"Plain": API_KEY_SECRET},
    }
    (directory / "clients.json").write_text(json.dumps([login_client, program_client]))
    (directory / "scopes.json").write_text(json.dumps([{"name": "comfy"}]))
    (directory / "api_keys.json").write_text(json.dumps([api_key]))
    (directory / "users.json").write_text(json.dumps([user]))
    # The container runs as user 10001, so it must read the files.
    for path in [directory, *directory.iterdir()]:
        path.chmod(0o755 if path.is_dir() else 0o644)


@pytest.fixture(scope="session")
def rauthy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Rauthy]:
    assert shutil.which("docker"), "the rauthy tier needs Docker"
    boot = tmp_path_factory.mktemp("rauthy-boot")
    gate_port = free_port()
    _bootstrap(boot, gate_port)
    port = free_port()
    name = f"comfyui-curu-auth-rauthy-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", "LOCAL_TEST=true", "-e", "LISTEN_SCHEME=http",
            "-e", f"PUB_URL=127.0.0.1:{port}", "-e", "BOOTSTRAP_DIR=/boot",
            "-v", f"{boot}:/boot:ro", "-p", f"127.0.0.1:{port}:8080", IMAGE,
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    try:
        # rauthy makes its keys at the first start; that took 90 s on 2026-11-01.
        deadline = time.monotonic() + 240
        while True:
            try:
                with urllib.request.urlopen(
                    f"{url}/auth/v1/.well-known/openid-configuration", timeout=2
                ) as response:
                    discovery = json.load(response)
                break
            except (OSError, ValueError):
                if time.monotonic() > deadline:
                    raise RuntimeError("rauthy did not start") from None
                time.sleep(0.5)
        server = Rauthy(url=url, issuer=discovery["issuer"], gate_port=gate_port)
        # The bootstrap files cannot set allowed_resources in 0.37.2.
        _allow_resources(url, PROGRAM_CLIENT_ID, [server.audience, OTHER_RESOURCE])
        yield server
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def _allow_resources(url: str, client_id: str, resources: list[str]) -> None:
    headers = {
        "Authorization": f"API-Key bootstrap${API_KEY_SECRET}",
        "Content-Type": "application/json",
    }
    path = f"{url}/auth/v1/clients/{client_id}"
    with urllib.request.urlopen(
        urllib.request.Request(path, headers=headers), timeout=30
    ) as response:
        client = json.load(response)
    client["allowed_resources"] = resources
    request = urllib.request.Request(
        path, data=json.dumps(client).encode(), headers=headers, method="PUT"
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


async def _home(request: web.Request) -> web.Response:
    return web.Response(
        text="<html><body>ComfyUI</body></html>", content_type="text/html"
    )


async def _queue(request: web.Request) -> web.Response:
    """A stand-in for ComfyUI's ``GET /queue``."""
    return web.json_response({"queue_running": [], "queue_pending": []})


StartGate = Callable[[dict[str, str]], Awaitable[web.Application]]


@pytest.fixture
async def start_gate(
    rauthy: Rauthy, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[StartGate]:
    """Start the real ``__init__.py`` wiring at ``rauthy.gate_port``.

    The argument holds the extra environment variables of the test. The
    login client of rauthy is always configured.
    """
    from tests.test_oidc import _load_init_with_fake_server

    runners: list[web.AppRunner] = []

    async def start(env: dict[str, str]) -> web.Application:
        app = _load_init_with_fake_server(
            monkeypatch,
            oidc_env={
                "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": rauthy.issuer,
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": LOGIN_CLIENT_ID,
                "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": LOGIN_CLIENT_SECRET,
                "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": (
                    f"http://127.0.0.1:{rauthy.gate_port}{CALLBACK}"
                ),
                **env,
            },
        )
        app.router.add_get("/", _home)
        app.router.add_get("/queue", _queue)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", rauthy.gate_port).start()
        runners.append(runner)
        return app

    yield start
    for runner in runners:
        await runner.cleanup()
