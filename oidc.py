"""OIDC/OAuth login path -- optional, additive to comfyui_curu_auth's
default zero-config bearer-token gate. Never active unless fully
configured (:func:`resolve_oidc_config`); on success, mints a session
through the exact same :class:`gate.SessionStore`/``curu_auth`` cookie
mechanism the existing login form already uses (ADR-002) -- not a second,
parallel session mechanism.

Needs only ``aiohttp`` (discovery fetch, token exchange) and ``joserfc``
(ID-token JWK/JWT signature and claims verification) -- never ``server``
(ComfyUI's own module, imported solely by ``__init__.py``). This
separation is what lets this module's own logic run under this repo's
hermetic ``pytest`` suite, with no real ComfyUI process needed -- mirrors
``gate.py``'s own hermetic/live split.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp


class OIDCDiscoveryError(Exception):
    """Raised for any failure fetching or parsing the identity provider's
    discovery document -- timeout, connection error, or a malformed body
    all collapse to this one exception type, so callers only need to
    catch one thing regardless of the underlying cause. No cached
    fallback on failure (research.md): a login attempt that hits this
    simply fails, rather than silently serving a stale or
    partially-fetched endpoint set.
    """


@dataclass(frozen=True)
class OIDCConfig:
    """Fully-resolved OIDC provider configuration -- either every field is
    populated, or :func:`resolve_oidc_config` returns ``None`` entirely
    (FR-009). Never constructed partially filled.
    """

    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str


def resolve_oidc_config(
    *,
    issuer_url: str | None,
    client_id: str | None,
    client_secret: str | None,
    redirect_uri: str | None,
) -> OIDCConfig | None:
    """``OIDCConfig`` if all four values are real, non-empty strings;
    otherwise ``None`` -- never a partially-filled config (FR-009).

    Mirrors :func:`gate.resolve_credential`'s own handling: ``__init__.py``
    calls this with ``os.environ.get(...)`` for each of the four
    ``COMFYUI_CURU_AUTH_OIDC_*`` variables, and ``os.environ.get`` returns
    ``""`` for a declared-but-empty variable, not ``None`` -- both are
    treated as "not supplied", exactly like ``resolve_credential`` already
    treats an empty credential as absent.
    """

    if issuer_url and client_id and client_secret and redirect_uri:
        return OIDCConfig(
            issuer_url=issuer_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    return None


async def fetch_discovery_document(
    issuer_url: str, *, timeout: float = 10.0
) -> dict[str, Any]:
    """Fetch and parse ``{issuer_url}/.well-known/openid-configuration``.

    Fetched fresh on every call -- no caching (research.md's "no JWKS
    caching" reasoning applies identically here: login is infrequent
    enough that the extra round-trip is negligible, and an unstated cache
    would otherwise mask the provider changing its own endpoints). Any
    failure -- timeout, connection error, non-2xx status, or a body that
    isn't valid JSON -- raises :class:`OIDCDiscoveryError`; there is no
    partial-success or fallback path.
    """

    url = f"{issuer_url}/.well-known/openid-configuration"
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response,
        ):
            response.raise_for_status()
            return await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise OIDCDiscoveryError(
            f"failed to fetch discovery document from {url}: {exc}"
        ) from exc


__all__ = [
    "OIDCConfig",
    "OIDCDiscoveryError",
    "fetch_discovery_document",
    "resolve_oidc_config",
]
