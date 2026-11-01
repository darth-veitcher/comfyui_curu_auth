"""Access tokens of a real rauthy 0.37.2 on the Bearer path (spec 004,
SC-001 and SC-002; scenarios "A real rauthy token" and "A rauthy token for
another resource"). Marker: ``rauthy``.

The program client gets its token with ``client_credentials`` and a
``resource``, as comfy-mcp does for a backend. rauthy puts the resource in
``aud`` only when ``allowed_resources`` of the client holds it, so the
fixture sets that list through the admin API.
"""

from __future__ import annotations

import base64
import json

import pytest
from aiohttp import ClientSession

from tests.live.conftest import OTHER_RESOURCE, Rauthy, StartGate

pytestmark = pytest.mark.rauthy


async def _queue(rauthy: Rauthy, token: str) -> int:
    async with (
        ClientSession() as session,
        session.get(
            f"{rauthy.audience}/queue", headers={"Authorization": f"Bearer {token}"}
        ) as response,
    ):
        return response.status


def _part(token: str, index: int) -> dict:
    segment = token.split(".")[index]
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def _audiences(token: str) -> list[str]:
    aud = _part(token, 1)["aud"]
    return aud if isinstance(aud, list) else [aud]


def _token(rauthy: Rauthy, **form: str) -> str:
    status, body = rauthy.program_token(**form)
    assert status == 200, body
    return str(body["access_token"])


async def _start(rauthy: Rauthy, start_gate: StartGate) -> None:
    await start_gate(
        {
            "COMFYUI_CURU_AUTH_OIDC_AUDIENCE": rauthy.audience,
            "COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES": "comfy",
            # The browser login stays on too; the two modes share the issuer.
            "COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS": "nobody",
        }
    )


async def test_a_rauthy_client_credentials_token_gets_200_on_queue(
    rauthy: Rauthy, start_gate: StartGate
) -> None:
    """Scenario: A real rauthy token."""
    await _start(rauthy, start_gate)

    token = _token(rauthy, resource=rauthy.audience)

    status = await _queue(rauthy, token)

    assert status == 200
    assert _part(token, 0)["typ"] == "at+jwt"
    assert rauthy.audience in _audiences(token)


async def test_a_rauthy_token_for_another_resource_gets_401(
    rauthy: Rauthy, start_gate: StartGate
) -> None:
    """Scenario: A rauthy token for another resource."""
    await _start(rauthy, start_gate)

    token = _token(rauthy, resource=OTHER_RESOURCE)

    status = await _queue(rauthy, token)

    assert status == 401
    assert OTHER_RESOURCE in _audiences(token)
    assert rauthy.audience not in _audiences(token)


async def test_a_rauthy_token_with_no_resource_gets_401(
    rauthy: Rauthy, start_gate: StartGate
) -> None:
    """With no resource, the token does not hold the audience of the gate.

    Each test starts a new gate with a new rate limiter, so a 429 from an
    earlier test cannot come here: the answer must be 401.
    """
    await _start(rauthy, start_gate)
    token = _token(rauthy)

    status = await _queue(rauthy, token)

    assert status == 401
    assert rauthy.audience not in _audiences(token)


async def test_rauthy_refuses_a_resource_that_is_not_allowed(rauthy: Rauthy) -> None:
    status, body = rauthy.program_token(resource="http://not-allowed.test")

    assert status == 400
    assert body.get("error") == "invalid_target"


def test_rauthy_refuses_http_basic_on_client_credentials(rauthy: Rauthy) -> None:
    """rauthy 0.37.2 wants the secret in the form, not in HTTP Basic."""
    import urllib.error
    import urllib.parse
    import urllib.request

    from tests.live.conftest import PROGRAM_CLIENT_ID, PROGRAM_CLIENT_SECRET

    basic = base64.b64encode(
        f"{PROGRAM_CLIENT_ID}:{PROGRAM_CLIENT_SECRET}".encode()
    ).decode()
    request = urllib.request.Request(
        f"{rauthy.issuer}oidc/token",
        data=urllib.parse.urlencode(
            {"grant_type": "client_credentials", "resource": rauthy.audience}
        ).encode(),
        headers={"Authorization": f"Basic {basic}"},
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=30)

    assert 400 <= refused.value.code < 500
