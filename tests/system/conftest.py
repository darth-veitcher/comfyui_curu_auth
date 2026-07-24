"""Shared `docker compose` lifecycle helpers for the live ComfyUI harness.

Adapted from the equivalent module in the sibling repo
``~/repos/JAMESVEITCH/curu`` (same author) -- but the HTTP-polling helper
below is a fresh, async rewrite against ``aiohttp.ClientSession``, not a
port of curu's own ``httpx``-based version: this project deliberately has
no ``httpx``/``requests`` dependency (see ``research.md``'s "Drive the
harness from tests" decision).
"""

from __future__ import annotations

import asyncio
import os
import socket
import ssl
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "http://localhost:8188"
HEALTH_URL = f"{BASE_URL}/"
COMFYUI_PORT = 8188

#: Fixed test credential this harness's docker-compose.yml pins via
#: COMFYUI_CURU_AUTH_TOKEN (spec FR-003) -- never meaningful outside this
#: local, disposable context.
TEST_AUTH_TOKEN = "local-harness-test-credential"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_AUTH_TOKEN}"}

# --------------------------------------------------------------------------
# OIDC/Authelia (spec 002) -- all fixed, repo-committed values, meaningless
# outside this disposable harness. See docker/authelia/configuration.yml
# and specs/002-oidc-login/research.md's issuer-URL-duality decision for
# why "authelia.internal" (not the bare service name, not an IP) is used
# throughout, and why the host-side test process needs a Host/SNI override
# rather than DNS to reach it.
# --------------------------------------------------------------------------

AUTHELIA_PUBLISHED_URL = "https://127.0.0.1:9091"
AUTHELIA_HOST_HEADER = "authelia.internal:9091"
AUTHELIA_CA_PATH = REPO_ROOT / "docker" / "authelia" / "ca.crt"
OIDC_TEST_USER = "curu-test-user"
OIDC_TEST_PASSWORD = "local-harness-test-password"
OIDC_CLIENT_ID = "comfyui-curu-auth"
OIDC_CLIENT_SECRET = "local-harness-oidc-client-secret"
#: MUST exactly match docker/authelia/configuration.yml's registered
#: client redirect_uris -- Authelia rejects a mismatch (standard OIDC
#: security check). 127.0.0.1, not localhost -- matching the client
#: registration exactly, not just "close enough".
OIDC_REDIRECT_URI = "http://127.0.0.1:8188/curu-auth/oidc/callback"
OIDC_ISSUER_URL = "https://authelia.internal:9091"

#: Passed as `env=` to `compose("up", "-d", env=OIDC_ENV)` -- the four
#: variables docker-compose.yml's comfyui service reads via `${VAR:-}`
#: substitution. Every other test in this package omits `env=` entirely,
#: leaving OIDC unconfigured (US2's own concern).
OIDC_ENV = {
    "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL": OIDC_ISSUER_URL,
    "COMFYUI_CURU_AUTH_OIDC_CLIENT_ID": OIDC_CLIENT_ID,
    "COMFYUI_CURU_AUTH_OIDC_CLIENT_SECRET": OIDC_CLIENT_SECRET,
    "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI": OIDC_REDIRECT_URI,
}


def authelia_ssl_context() -> ssl.SSLContext:
    """Trusts the same repo-committed CA `docker/comfyui/Dockerfile`
    installs into the gate's own OS trust store (research.md) -- test-only,
    confined to this module; production `oidc.py` code has no equivalent
    (and needs none, since it runs inside the container where that OS
    trust store already applies)."""

    return ssl.create_default_context(cafile=str(AUTHELIA_CA_PATH))


def rewrite_to_published_authelia_host(url: str) -> str:
    """Swap ``url``'s host:port to Authelia's published host address
    (127.0.0.1:9091) -- the host-side test process can't resolve
    `authelia.internal` (that alias only exists inside the Compose
    network), so any URL Authelia itself returns (e.g. an authorization
    redirect `Location`) needs its netloc rewritten before this process
    can physically connect to it. Pair with the `Host`/`server_hostname`
    overrides (`AUTHELIA_HOST_HEADER`, `authelia_ssl_context`) so Authelia
    still sees a request from `authelia.internal` regardless of the
    actual TCP destination.
    """

    parsed = urlsplit(url)
    return urlunsplit(parsed._replace(netloc="127.0.0.1:9091"))


async def authelia_firstfactor_login(session: aiohttp.ClientSession) -> str:
    """Complete Authelia's headless first-factor login (the T009 spike's
    proven sequence) and return the resulting session cookie's raw
    ``name=value`` string, ready to use as a literal ``Cookie`` header on
    a follow-up request -- NOT relying on `aiohttp`'s own cookie jar,
    which matches against the actual request URL, not the `Host` override
    used here (discovered live building T010; research.md).
    """

    async with session.post(
        f"{AUTHELIA_PUBLISHED_URL}/api/firstfactor",
        json={
            "username": OIDC_TEST_USER,
            "password": OIDC_TEST_PASSWORD,
            "keepMeLoggedIn": False,
        },
        headers={"Host": AUTHELIA_HOST_HEADER},
        server_hostname="authelia.internal",
        ssl=authelia_ssl_context(),
    ) as response:
        response.raise_for_status()
        set_cookie = response.headers.getall("Set-Cookie", [])
    return next(
        c.split(";")[0] for c in set_cookie if c.startswith("authelia_session=")
    )


def compose(
    *args: str,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `docker compose <args>` from the repo root, capturing output.

    ``env``, when given, is merged over the current process environment --
    used by OIDC-specific tests (spec 002) to set the four
    ``COMFYUI_CURU_AUTH_OIDC_*`` variables `docker-compose.yml` reads via
    ``${VAR:-}`` substitution, without touching the default (unset,
    unconfigured) behavior every other test in this package relies on.
    """

    merged_env = {**os.environ, **env} if env else None
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def port_reachable(host: str = "localhost", port: int = COMFYUI_PORT) -> bool:
    """True iff a TCP connection to ``host:port`` succeeds right now."""

    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


async def wait_until_reachable(timeout: float = 180.0, interval: float = 2.0) -> float:
    """Poll ``HEALTH_URL`` (authenticated with the fixed test credential)
    until it answers with *any* HTTP response, or raise after ``timeout``.
    Returns the elapsed time in seconds.

    Deliberately authenticates rather than polling unauthenticated: every
    unauthenticated request -- including polling/health-probe traffic --
    counts as a failure against ``gate.py``'s ``RateLimiter`` (discovered
    live: an unauthenticated polling loop puts its own client key into a
    blocked state after its first "successful" 401, so a test's very next
    request gets 429 instead of the 401 it expects). Authenticating here
    means a) this helper still detects reachability regardless of whether
    the gate is even wired up (a 200 either way), and b) `record_success`
    clears any prior failure count for this client key, so the caller's
    own subsequent assertions start from a clean rate-limiter state rather
    than inheriting pollution from this helper's own polling.

    This helper only answers "is the port up and speaking HTTP yet" -- gate
    correctness itself is asserted explicitly by the tests that call it.
    Contrast with ``docker/comfyui/healthcheck.py``, which polls
    unauthenticated on purpose (it exists specifically to prove the gate
    rejects that) and accordingly treats 429 as healthy too, not just 401.

    Polling, not sleeping-and-hoping, so the bound is on actual readiness,
    not a guessed sleep duration. 180s default matches SC-001's revised,
    realistic cold-start budget (research.md).
    """

    start = time.monotonic()
    deadline = start + timeout
    last_error: Exception | None = None
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            try:
                async with session.get(
                    HEALTH_URL,
                    headers=AUTH_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=5.0),
                ) as response:
                    # Any response at all (whatever its status) means the
                    # port is up and ComfyUI is speaking HTTP.
                    response.release()
                    return time.monotonic() - start
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
            await asyncio.sleep(interval)
    raise TimeoutError(
        f"ComfyUI did not become reachable within {timeout}s "
        f"(last error: {last_error!r})"
    )


def wait_until_unreachable(timeout: float = 30.0, interval: float = 1.0) -> None:
    """Poll until the port is no longer accepting connections, or raise."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_reachable():
            return
        time.sleep(interval)
    raise TimeoutError(f"port {COMFYUI_PORT} was still reachable after {timeout}s")


@pytest.fixture(scope="package", autouse=True)
def _built_image() -> None:
    """Build the harness image once for the whole `tests/system` package."""

    result = compose("build")
    assert result.returncode == 0, result.stderr


@pytest.fixture
async def running_harness():
    """Bring the harness up, wait for readiness, yield its base URL, tear down."""

    result = compose("up", "-d")
    assert result.returncode == 0, result.stderr
    await wait_until_reachable(timeout=180.0)
    try:
        yield BASE_URL
    finally:
        compose("down", timeout=60)
