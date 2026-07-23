"""Live-harness witnesses for the OIDC/OAuth login path, driving the full
authorization-code flow against a real Authelia instance (Lite bundle) --
see ADR-002 and specs/002-oidc-login/research.md. Not a mocked provider.

Marked `system` at module level: excluded from the default `pytest` run
(pyproject.toml addopts). Requires a working Docker daemon. Traceability to
specs/002-oidc-login/features/oidc_login.feature is noted per test via
docstring.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.system
