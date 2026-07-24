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

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

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


@dataclass(frozen=True)
class InFlightAuthRequest:
    """Transient, in-memory-only correlation between an authorization
    request and its callback (data-model.md) -- `state` (CSRF), `nonce`
    (replay-resistant, checked against the returned ID token), and a PKCE
    `pkce_verifier`. Never durably stored; cleared entirely on restart,
    exactly like :class:`gate.SessionStore` and :class:`gate.RateLimiter`
    (FR-008).
    """

    state: str
    nonce: str
    pkce_verifier: str
    created_at: float


class AuthorizationRequestStore:
    """In-memory store of :class:`InFlightAuthRequest` entries, keyed by
    `state`.

    Single-use by design: :meth:`pop` removes the entry it returns, so a
    verbatim replay of an already-completed state/code pair finds nothing
    and is rejected (FR-011) rather than re-validated and accepted again.

    Size-capped (`max_size`, FR-010): the route that calls :meth:`create`
    is necessarily unauthenticated (it must be reachable pre-session, the
    same as the login form already is -- ADR-003's public-paths
    mechanism), so nothing else bounds how many entries an unauthenticated
    caller could otherwise make this hold. Oldest entries are evicted
    first once the cap is exceeded -- independent of, and in addition to,
    whatever rate-limiting is applied to the route itself (research.md).
    """

    def __init__(self, *, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._entries: dict[str, InFlightAuthRequest] = {}

    def create(self) -> InFlightAuthRequest:
        entry = InFlightAuthRequest(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            pkce_verifier=secrets.token_urlsafe(64),
            created_at=time.monotonic(),
        )
        self._entries[entry.state] = entry
        while len(self._entries) > self._max_size:
            oldest_state = next(iter(self._entries))
            del self._entries[oldest_state]
        return entry

    def pop(self, state: str) -> InFlightAuthRequest | None:
        return self._entries.pop(state, None)

    def peek(self, state: str) -> InFlightAuthRequest | None:
        """Look up an entry without consuming it -- for tests/inspection
        only; the actual callback handler MUST use :meth:`pop`."""

        return self._entries.get(state)

    def __len__(self) -> int:
        return len(self._entries)


def _pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256: `base64url(sha256(verifier))`, no padding."""

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_url(
    config: OIDCConfig,
    discovery: dict[str, Any],
    store: AuthorizationRequestStore,
    *,
    scope: str = "openid profile email",
) -> str:
    """Build the redirect URL to the identity provider's authorization
    endpoint, recording a matching :class:`InFlightAuthRequest` in
    ``store`` keyed by the `state` it generates.
    """

    in_flight = store.create()
    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": in_flight.state,
        "nonce": in_flight.nonce,
        "code_challenge": _pkce_challenge(in_flight.pkce_verifier),
        "code_challenge_method": "S256",
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(query)}"


__all__ = [
    "AuthorizationRequestStore",
    "InFlightAuthRequest",
    "OIDCConfig",
    "OIDCDiscoveryError",
    "build_authorization_url",
    "fetch_discovery_document",
    "resolve_oidc_config",
]
