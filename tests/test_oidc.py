"""Hermetic coverage for :mod:`oidc` -- the OIDC/OAuth login path's pure,
testable logic (config resolution, authorization-URL building, ID-token
verification, the callback handler), driven against a mocked provider
double via ``aiohttp.test_utils``. Never imports ``__init__`` -- only
``oidc.py`` and ``gate.py`` directly, mirroring ``tests/test_gate.py``'s
own hermetic conventions.
"""

from __future__ import annotations
