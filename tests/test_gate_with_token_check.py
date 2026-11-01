"""Each test of ``tests/test_gate.py`` again, with resource-server mode on.

Spec 004 (US2, SC-005): the static credential, the session cookie, the login
form and the wait behave the same when ``token_check`` is set. The check here
refuses each token, so a test that sends a value with the shape of a JWT sees
the mode at work; no test of ``test_gate.py`` does today.
"""

from __future__ import annotations

import functools

import pytest

import gate
from tests import test_gate as base
from tests.test_gate import *  # noqa: F403 -- collect each test again here


async def _refuse_each_token(token: str) -> str:
    return "refused by the test"


@pytest.fixture(autouse=True)
def _mode_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        base,
        "build_gate_middleware",
        functools.partial(gate.build_gate_middleware, token_check=_refuse_each_token),
    )
