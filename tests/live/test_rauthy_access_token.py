"""Access tokens of a real rauthy 0.37.2 on the Bearer path (spec 004,
SC-001 and SC-002; scenarios "A real rauthy token" and "A rauthy token for
another resource"). Marker: ``rauthy``.

The program client gets its token with ``client_credentials`` and a
``resource``, as comfy-mcp does for a backend. rauthy puts the resource in
``aud`` only when ``allowed_resources`` of the client holds it, so the
fixture sets that list through the admin API.
"""

from __future__ import annotations

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

    status = await _queue(rauthy, _token(rauthy, resource=rauthy.audience))

    assert status == 200


async def test_a_rauthy_token_for_another_resource_gets_401(
    rauthy: Rauthy, start_gate: StartGate
) -> None:
    """Scenario: A rauthy token for another resource."""
    await _start(rauthy, start_gate)

    status = await _queue(rauthy, _token(rauthy, resource=OTHER_RESOURCE))

    assert status == 401


async def test_a_rauthy_token_with_no_resource_gets_401(
    rauthy: Rauthy, start_gate: StartGate
) -> None:
    """With no resource, rauthy puts only the client id in aud."""
    await _start(rauthy, start_gate)

    status = await _queue(rauthy, _token(rauthy))

    assert status in (401, 429)


async def test_rauthy_refuses_a_resource_that_is_not_allowed(rauthy: Rauthy) -> None:
    status, body = rauthy.program_token(resource="http://not-allowed.test")

    assert status == 400
    assert body.get("error") == "invalid_target"
