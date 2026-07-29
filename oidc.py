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

``joserfc`` is imported lazily, inside the two functions that actually use
it, rather than at module level (issue #5). ``__init__.py`` imports this
module unconditionally -- a missing *optional* OIDC dependency raising
``ModuleNotFoundError`` at module-import time would therefore have taken
the *mandatory* bearer-token gate down with it (fail-open, the opposite of
this project's intent). With the import deferred, a pod missing
``joserfc`` still gets the base credential gate; only an actual attempt to
verify an ID token fails, and it fails loudly (an unhandled
``ModuleNotFoundError`` surfaces as a 500 from that one request) rather
than silently.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
from aiohttp.typedefs import Handler

if TYPE_CHECKING:
    from joserfc.jwk import KeySet

#: Same logger name gate.py's own warnings use -- fail2ban/crowdsec key
#: off one stable, greppable format regardless of which path rejected
#: the request (research.md's T036/T037 decision).
_logger = logging.getLogger("comfyui_curu_auth")

try:
    # Real ComfyUI context: this module is loaded as <package>.oidc, with
    # a real package identity ComfyUI's custom-node loader gives it --
    # same reasoning as __init__.py's own `.gate` import. `ty check`, run
    # standalone with no such loader present, cannot model that synthetic
    # package context and would otherwise misreport this as unresolved.
    from .gate import (  # ty: ignore[unresolved-import]
        COOKIE_MAX_AGE_SECONDS,
        COOKIE_NAME,
        RateLimiter,
        SessionStore,
        client_key,
    )
except ImportError:
    # Hermetic test context: tests/test_oidc.py imports this module bare
    # (pyproject.toml's pythonpath = ["."] puts the repo root, and
    # therefore gate.py, directly on sys.path) -- no parent package
    # exists for a relative import to resolve against.
    from gate import (
        COOKIE_MAX_AGE_SECONDS,
        COOKIE_NAME,
        RateLimiter,
        SessionStore,
        client_key,
    )

#: The two OIDC routes -- reachable pre-session by definition, so
#: __init__.py registers them in gate.py's `public_paths` set (ADR-003)
#: only when OIDC is actually configured. Module-level constants, not
#: inlined in __init__.py, matching gate.py's own LOGIN_PATH precedent.
OIDC_START_PATH = "/curu-auth/oidc/start"
OIDC_CALLBACK_PATH = "/curu-auth/oidc/callback"


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


class OIDCTokenVerificationError(Exception):
    """Raised for any ID-token verification failure -- a JWKS fetch
    failure, bad signature, wrong issuer/audience, wrong or missing
    nonce, or an expired token all collapse to this one exception type,
    mirroring :class:`OIDCDiscoveryError`'s shape (FR-007). A forged or
    replayed callback MUST NOT succeed -- there is no partial-trust
    outcome here, only "verified" or this exception.
    """


async def _fetch_jwks(jwks_uri: str, *, timeout: float) -> KeySet:
    from joserfc.jwk import KeySet  # deferred -- see module docstring (issue #5)

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                jwks_uri, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response,
        ):
            response.raise_for_status()
            jwks_data = await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise OIDCTokenVerificationError(
            f"failed to fetch JWKS from {jwks_uri}: {exc}"
        ) from exc
    return KeySet.import_key_set(jwks_data)


async def verify_id_token(
    id_token: str,
    *,
    config: OIDCConfig,
    discovery: dict[str, Any],
    expected_nonce: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Verify ``id_token``'s RS256 signature against the provider's JWKS
    (fetched fresh -- no caching, research.md) and its `iss`/`aud`/`nonce`/
    `exp` claims. Returns the verified claims on success; raises
    :class:`OIDCTokenVerificationError` for any failure.
    """

    from joserfc import errors as jose_errors  # deferred -- module docstring (issue #5)
    from joserfc import jwt

    key_set = await _fetch_jwks(discovery["jwks_uri"], timeout=timeout)

    try:
        token = jwt.decode(id_token, key_set, algorithms=["RS256"])
        claims_registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": config.issuer_url},
            aud={"essential": True, "value": config.client_id},
            nonce={"essential": True, "value": expected_nonce},
        )
        claims_registry.validate(token.claims)
    except jose_errors.JoseError as exc:
        raise OIDCTokenVerificationError(
            f"ID token verification failed: {exc}"
        ) from exc

    return token.claims


async def _exchange_code_for_token(
    config: OIDCConfig,
    discovery: dict[str, Any],
    code: str,
    *,
    code_verifier: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST the authorization code to the provider's token endpoint.
    Raises :class:`OIDCTokenVerificationError` on any failure -- a failed
    exchange means the callback as a whole cannot be trusted, the same
    outcome as a failed signature/claims check.

    ``code_verifier`` MUST be the same :class:`InFlightAuthRequest`'s
    `pkce_verifier` that `build_authorization_url` derived the
    authorization request's `code_challenge` from (RFC 7636) -- a real
    provider (Authelia included) rejects the exchange with a 400 if it's
    missing or doesn't match, confirmed live.
    """

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code_verifier": code_verifier,
    }
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                discovery["token_endpoint"],
                data=data,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response,
        ):
            response.raise_for_status()
            return await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError, KeyError) as exc:
        raise OIDCTokenVerificationError(f"token exchange failed: {exc}") from exc


def build_oidc_routes(
    config: OIDCConfig,
    *,
    sessions: SessionStore,
    store: AuthorizationRequestStore,
    rate_limiter: RateLimiter | None = None,
) -> tuple[Handler, Handler]:
    """Return ``(start, callback)`` handlers for the OIDC login path,
    mirroring :func:`gate.build_login_routes`'s own shape.

    ``sessions`` MUST be the same :class:`gate.SessionStore` instance
    passed to :func:`gate.build_gate_middleware`, so a session minted
    here is one the middleware will actually recognise (ADR-002) -- the
    same requirement :func:`gate.build_login_routes` already documents
    for its own ``sessions`` parameter.

    ``rate_limiter``, when supplied, backs off the start route exactly
    like :func:`gate.build_login_routes` already backs off the login
    form (FR-010) -- the start route sits in the public-paths bypass by
    necessity (reachable pre-session, the same as the login form always
    has been), so nothing else limits how often an unauthenticated
    caller can hit it. ``rate_limiter=None`` (the default) leaves it
    unthrottled, matching every other opt-in ``rate_limiter`` parameter
    in this codebase (:func:`gate.build_gate_middleware`,
    :func:`gate.build_login_routes`).
    """

    async def start(request: web.Request) -> web.StreamResponse:
        if rate_limiter is not None:
            key = client_key(request)
            retry_after = rate_limiter.seconds_until_retry(key)
            if retry_after > 0:
                seconds = int(retry_after) + 1
                return web.json_response(
                    {"detail": "too many attempts", "retry_after": seconds},
                    status=429,
                    headers={"Retry-After": str(seconds)},
                )
            # Every hit counts, not just failed logins -- this route has
            # no credential to check, so (unlike the login form) there's
            # no separate "success" outcome that would otherwise reset
            # the count via record_success. Matches this gate's existing
            # posture: any unauthenticated hit on a rate-limited path
            # already counts against it (e.g. the Bearer-header path's
            # own middleware behavior).
            rate_limiter.record_failure(key)

        try:
            discovery = await fetch_discovery_document(config.issuer_url)
        except OIDCDiscoveryError as exc:
            raise web.HTTPServiceUnavailable(
                text="identity provider unreachable"
            ) from exc
        raise web.HTTPFound(build_authorization_url(config, discovery, store))

    def _reject_callback(key: str, *, cause: BaseException | None = None) -> NoReturn:
        # Same RateLimiter/logger the Bearer-header and login-form paths
        # already use (T036/T037, US3) -- not a parallel mechanism.
        # fail2ban/crowdsec key off this one stable, greppable format.
        if rate_limiter is not None:
            rate_limiter.record_failure(key)
        _logger.warning(
            "comfyui_curu_auth: authentication failure from %s (oidc callback)",
            key,
        )
        raise web.HTTPUnauthorized(text="OIDC login failed") from cause

    async def callback(request: web.Request) -> web.StreamResponse:
        key = client_key(request)

        state = request.query.get("state", "")
        in_flight = store.pop(state) if state else None

        # Rejects three distinct cases identically: a provider-reported
        # error (cancelled/failed login), a state nobody issued, and a
        # state already consumed by a prior callback (FR-011 -- pop()
        # already made this single-use, so a replay finds nothing here).
        #
        # The rate-limit check lives *inside* this branch, not ahead of
        # it -- deliberately. `start` (T027-I) charges a failure for
        # *every* hit, including a legitimate one, so a real login's own
        # start-then-callback round trip already carries one accrued
        # failure by the time it reaches here; gating on that unqualified
        # would occasionally 429 a real login that completes faster than
        # `base_delay` (confirmed live: a browser with an existing
        # Authelia session round-trips well under a second). A `state`
        # `store.pop()` just recognised is exactly as strong a proof of
        # legitimacy as a correct Bearer credential -- unguessable,
        # single-use, minted by this same process's own `start` call --
        # so it bypasses the check the same way a correct credential
        # bypasses the Bearer-header path's own rate limit (gate.py).
        # Only a request this gate is about to reject anyway (no such
        # state) pays the backoff.
        if "error" in request.query or in_flight is None:
            if rate_limiter is not None:
                retry_after = rate_limiter.seconds_until_retry(key)
                if retry_after > 0:
                    seconds = int(retry_after) + 1
                    return web.json_response(
                        {"detail": "too many attempts", "retry_after": seconds},
                        status=429,
                        headers={"Retry-After": str(seconds)},
                    )
            _reject_callback(key)

        code = request.query.get("code", "")
        try:
            discovery = await fetch_discovery_document(config.issuer_url)
            token_response = await _exchange_code_for_token(
                config, discovery, code, code_verifier=in_flight.pkce_verifier
            )
            id_token = token_response["id_token"]
            await verify_id_token(
                id_token,
                config=config,
                discovery=discovery,
                expected_nonce=in_flight.nonce,
            )
        except (OIDCDiscoveryError, OIDCTokenVerificationError, KeyError) as exc:
            _reject_callback(key, cause=exc)

        if rate_limiter is not None:
            rate_limiter.record_success(key)

        session_token = sessions.issue()
        redirect = web.HTTPFound("/")
        redirect.set_cookie(
            COOKIE_NAME,
            session_token,
            max_age=COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            secure=True,
            samesite="Strict",
        )
        raise redirect

    return start, callback


__all__ = [
    "OIDC_CALLBACK_PATH",
    "OIDC_START_PATH",
    "AuthorizationRequestStore",
    "InFlightAuthRequest",
    "OIDCConfig",
    "OIDCDiscoveryError",
    "OIDCTokenVerificationError",
    "build_authorization_url",
    "build_oidc_routes",
    "fetch_discovery_document",
    "resolve_oidc_config",
    "verify_id_token",
]
