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
import json
import logging
import secrets
import time
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import urlencode, urlsplit

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
        RateLimiter,
        SessionStore,
        client_key,
        set_session_cookie,
    )
except ImportError:
    # Hermetic test context: tests/test_oidc.py imports this module bare
    # (pyproject.toml's pythonpath = ["."] puts the repo root, and
    # therefore gate.py, directly on sys.path) -- no parent package
    # exists for a relative import to resolve against.
    from gate import (
        COOKIE_MAX_AGE_SECONDS,
        RateLimiter,
        SessionStore,
        client_key,
        set_session_cookie,
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
class LoginAllowlist:
    """Who may get a session from the OIDC login (ADR-007).

    A person is allowed when ``allow_any`` is true, when the ``sub`` of the
    ID token is in ``subjects``, when a verified ``email`` is in ``emails``,
    or when the ``hd`` claim equals ``domain``. ``emails`` and ``domain``
    hold small letters only; :func:`resolve_oidc_config` makes them so.

    The empty allowlist (the default) allows nobody -- the safe default for
    a security type. ``allow_any`` is the explicit decision to let the
    provider decide, for example an Authentik application with a group
    binding.
    """

    subjects: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    domain: str | None = None
    allow_any: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.allow_any or self.subjects or self.emails or self.domain)

    def permits(self, claims: dict[str, Any]) -> bool:
        if self.allow_any:
            return True
        if claims.get("sub") in self.subjects:
            return True
        email = claims.get("email")
        verified = claims.get("email_verified") in (True, "true")
        if verified and isinstance(email, str) and email.lower() in self.emails:
            return True
        domain = claims.get("hd")
        return (
            self.domain is not None
            and isinstance(domain, str)
            and domain.lower() == self.domain
        )


#: The scopes the login asks for when the operator sets none.
DEFAULT_SCOPES = ("openid", "profile", "email")


@dataclass(frozen=True)
class OIDCConfig:
    """Fully-resolved OIDC provider configuration -- either every field is
    populated, or :func:`resolve_oidc_config` returns ``None`` entirely
    (FR-009). Never constructed partially filled.

    ``allowlist`` defaults to the empty allowlist, which allows nobody.
    """

    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    allowlist: LoginAllowlist = LoginAllowlist()
    scopes: tuple[str, ...] = DEFAULT_SCOPES


class OIDCConfigError(Exception):
    """The four settings of the login are set, but the setup is not safe.

    ``__init__.py`` writes this as an error and keeps the OIDC login off. It
    never lets it escape: ComfyUI would then skip the node, and the gate
    would be off (ADR-007).
    """


def _split(value: str | None) -> list[str]:
    """The items of a setting, with a comma or a space between them."""

    return [item for item in (value or "").replace(",", " ").split() if item]


def resolve_oidc_config(
    *,
    issuer_url: str | None,
    client_id: str | None,
    client_secret: str | None,
    redirect_uri: str | None,
    allowed_subjects: str | None = None,
    allowed_emails: str | None = None,
    allowed_domain: str | None = None,
    allow_any_user: str | None = None,
    scopes: str | None = None,
) -> OIDCConfig | None:
    """``OIDCConfig`` if all four values are real, non-empty strings and an
    allowlist is set; ``None`` if any of the four is missing -- never a
    partially-filled config (FR-009 of spec 002).

    With all four set but an empty allowlist and ``allow_any_user`` not
    ``true``, raises :class:`OIDCConfigError` (ADR-007): the login must not
    give a session to each account at the provider by accident.

    ``__init__.py`` passes ``os.environ.get(...)`` for each value, and an
    empty variable counts as not set. ``allow_any_user`` is true only for
    the word ``true``, with any capital letters; any other value is false,
    so a typing error fails closed.

    ``scopes`` is a list with a comma or a space between the items. The
    result always starts with ``openid``, and has no item twice. With no
    value, it is :data:`DEFAULT_SCOPES`.
    """

    if not (issuer_url and client_id and client_secret and redirect_uri):
        return None
    domain = (allowed_domain or "").strip().lower()
    allowlist = LoginAllowlist(
        subjects=frozenset(_split(allowed_subjects)),
        emails=frozenset(email.lower() for email in _split(allowed_emails)),
        domain=domain or None,
        allow_any=(allow_any_user or "").strip().lower() == "true",
    )
    if allowlist.is_empty:
        raise OIDCConfigError(
            "OIDC login is off: set COMFYUI_CURU_AUTH_OIDC_ALLOWED_SUBJECTS, "
            "COMFYUI_CURU_AUTH_OIDC_ALLOWED_EMAILS or "
            "COMFYUI_CURU_AUTH_OIDC_ALLOWED_DOMAIN, or set "
            "COMFYUI_CURU_AUTH_OIDC_ALLOW_ANY_USER=true to let the provider "
            "decide who can log in"
        )
    return OIDCConfig(
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        allowlist=allowlist,
        scopes=_scopes(scopes),
    )


def _scopes(setting: str | None) -> tuple[str, ...]:
    """The scopes of ``setting``, with ``openid`` first and no item twice."""

    items = _split(setting)
    if not items:
        return DEFAULT_SCOPES
    return tuple(dict.fromkeys(["openid", *items]))


def discovery_url(issuer_url: str) -> str:
    """The URL of the discovery document of ``issuer_url``.

    Removes each ``/`` at the end of the issuer before it adds the path
    (OpenID Connect Discovery 1.0, section 4). rauthy and Authentik give an
    issuer that ends in ``/``; without this rule the gate asked for
    ``.../auth/v1//.well-known/openid-configuration`` and rauthy answered 404
    (issue #13). The issuer itself is never changed -- see
    :func:`fetch_discovery_document`.
    """

    return issuer_url.rstrip("/") + "/.well-known/openid-configuration"


async def fetch_discovery_document(
    issuer_url: str, *, timeout: float = 10.0
) -> dict[str, Any]:
    """Fetch, parse and check the discovery document of ``issuer_url``.

    The ``issuer`` of the document must equal ``issuer_url`` exactly, as
    the operator wrote it (Discovery 1.0, section 4.3; ADR-007). The gate
    then compares the ``iss`` of each ID token with that same value, so a
    ``/`` at the end matters: copy the issuer from the document.

    Fetched fresh on every call -- no caching. A login is rare enough that
    the extra round trip costs nothing, and a cache would hide a change of
    the endpoints at the provider. Any failure -- timeout, connection error,
    non-2xx status, a body that isn't a JSON object, or a check that fails
    -- raises :class:`OIDCDiscoveryError`; there is no fallback path.
    """

    url = discovery_url(issuer_url)
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=False,
            ) as response,
        ):
            response.raise_for_status()
            document = await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise OIDCDiscoveryError(
            f"failed to fetch discovery document from {url}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise OIDCDiscoveryError(f"the discovery document at {url} is not an object")
    if document.get("issuer") != issuer_url:
        raise OIDCDiscoveryError(
            f"the discovery document at {url} names the issuer "
            f"{document.get('issuer')!r}, not the configured issuer "
            f"{issuer_url!r}; set the issuer to the exact value of the document"
        )
    for endpoint in _DISCOVERY_ENDPOINTS:
        _require_safe_url(document, endpoint)
    return document


#: The endpoints of a discovery document that the gate uses (ADR-007).
_DISCOVERY_ENDPOINTS = ("authorization_endpoint", "token_endpoint", "jwks_uri")

#: The hosts where plain ``http`` is allowed: a provider on this computer.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_safe_url(document: dict[str, Any], endpoint: str) -> None:
    """Refuse an endpoint that is absent, or plain ``http`` off loopback.

    A person's browser goes to ``authorization_endpoint``, the client secret
    goes to ``token_endpoint``, and the keys come from ``jwks_uri``. Over
    plain ``http`` to another computer, each one is open to a change on the
    network (ADR-007; curu-memory does the same in ``_safe_url``).
    """

    url = document.get(endpoint)
    if not isinstance(url, str) or not url:
        raise OIDCDiscoveryError(f"the discovery document has no {endpoint}")
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS:
        return
    raise OIDCDiscoveryError(
        f"the {endpoint} of the discovery document must use https "
        "(plain http is allowed only on localhost, 127.0.0.1 and ::1)"
    )


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
) -> str:
    """Build the redirect URL to the identity provider's authorization
    endpoint, recording a matching :class:`InFlightAuthRequest` in
    ``store`` keyed by the `state` it generates. The scope is
    ``config.scopes`` (spec 003).
    """

    in_flight = store.create()
    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
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

    ``reason`` is a short text for the log line. It never holds the token
    or a part of it.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


#: The JWS algorithms the gate accepts -- asymmetric only (ADR-007). The key
#: sets the algorithm (:func:`select_signing_key`), never the token header.
ALLOWED_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "PS256", "ES256", "EdDSA"})

#: The clock difference, in seconds, allowed for ``exp``, ``iat`` and ``nbf``
#: of an ID token (ADR-007).
CLOCK_LEEWAY_SECONDS = 60

#: The algorithm of a JWK that has no ``alg``, by its key type and curve.
_DEFAULT_ALGORITHMS = {
    ("RSA", None): "RS256",
    ("EC", "P-256"): "ES256",
    ("OKP", "Ed25519"): "EdDSA",
}


def read_token_header(token: str) -> dict[str, Any]:
    """The JOSE header of a compact JWS, read with no check of the signature.

    Raises :class:`OIDCTokenVerificationError` for a value that is not a
    compact JWS with a JSON object as its header.
    """

    parts = token.split(".")
    if len(parts) != 3:
        raise OIDCTokenVerificationError("malformed token")
    try:
        padded = parts[0] + "=" * (-len(parts[0]) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError) as exc:
        raise OIDCTokenVerificationError("malformed token") from exc
    if not isinstance(header, dict):
        raise OIDCTokenVerificationError("malformed token")
    return header


def check_token_algorithm(header: dict[str, Any]) -> str:
    """The ``alg`` of ``header``, if the gate can accept it at all.

    Runs before the gate reads the JWKS, so a token with ``none`` or an
    HMAC algorithm never causes a fetch (ADR-007). An HMAC check uses a
    shared secret, and a gate that accepted one could be tricked into using
    the public key of the provider as that secret (key confusion).
    """

    alg = header.get("alg")
    if not isinstance(alg, str):
        raise OIDCTokenVerificationError("malformed token")
    if alg.upper().startswith("HS"):
        raise OIDCTokenVerificationError(
            f"algorithm {alg} is not allowed: the token is signed with a shared "
            "secret. An Authentik provider with no signing key does this; select "
            "a signing key on the provider"
        )
    if alg not in ALLOWED_ALGORITHMS:
        raise OIDCTokenVerificationError(f"algorithm {alg!r} is not allowed")
    return alg


def _key_algorithm(key: Any) -> str | None:
    """The algorithm of a JWK: its ``alg``, else the default of its type."""

    alg = key.get("alg")
    if isinstance(alg, str):
        return alg
    curve = key.get("crv")
    return _DEFAULT_ALGORITHMS.get(
        (key.key_type, curve if key.key_type != "RSA" else None)
    )


def select_signing_key(header: dict[str, Any], key_set: KeySet) -> tuple[Any, str]:
    """The key of the JWKS that checks a token with ``header``, and its algorithm.

    The key with the ``kid`` of the header sets the algorithm (ADR-007).
    The ``alg`` of the header must name the same algorithm, and it must be
    in :data:`ALLOWED_ALGORITHMS`. A header with no ``kid`` matches only a
    key set that holds exactly one signing key.
    """

    kid = header.get("kid")
    candidates = [key for key in key_set.keys if key.get("use", "sig") == "sig"]
    if kid is not None:
        candidates = [key for key in candidates if key.kid == kid]
    if len(candidates) != 1:
        raise OIDCTokenVerificationError("unknown key")
    key = candidates[0]
    algorithm = _key_algorithm(key)
    if algorithm not in ALLOWED_ALGORITHMS:
        raise OIDCTokenVerificationError(f"key algorithm {algorithm} is not allowed")
    if header.get("alg") != algorithm:
        raise OIDCTokenVerificationError("the token algorithm is not the key algorithm")
    return key, algorithm


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
    """Verify ``id_token``'s signature against the provider's JWKS (fetched
    fresh -- a login is rare) and its ``iss``/``aud``/``nonce``/``exp``
    claims. The key with the ``kid`` of the token sets the algorithm
    (:func:`select_signing_key`). Returns the verified claims on success;
    raises :class:`OIDCTokenVerificationError` for any failure.
    """

    from joserfc import errors as jose_errors  # deferred -- module docstring (issue #5)
    from joserfc import jwt

    header = read_token_header(id_token)
    check_token_algorithm(header)
    key_set = await _fetch_jwks(discovery["jwks_uri"], timeout=timeout)
    key, algorithm = select_signing_key(header, key_set)

    try:
        with warnings.catch_warnings():
            # joserfc warns that RFC 9864 renames EdDSA to Ed25519. rauthy
            # 0.37.2 still writes EdDSA, and the key already fixed the curve.
            warnings.simplefilter("ignore", jose_errors.SecurityWarning)
            token = jwt.decode(id_token, key, algorithms=[algorithm])
        claims_registry = jwt.JWTClaimsRegistry(
            leeway=CLOCK_LEEWAY_SECONDS,
            iss={"essential": True, "value": config.issuer_url},
            aud={"essential": True, "value": config.client_id},
            nonce={"essential": True, "value": expected_nonce},
            exp={"essential": True},
            iat={"essential": True},
        )
        claims_registry.validate(token.claims)
    except jose_errors.JoseError as exc:
        raise OIDCTokenVerificationError(
            f"ID token verification failed: {exc}"
        ) from exc

    # OpenID Connect Core 1.0, section 3.1.3.7: with more than one audience,
    # azp names the client the token was issued to. When azp is present at
    # all, it must be this client.
    audience = token.claims.get("aud")
    azp = token.claims.get("azp")
    several = isinstance(audience, list) and len(audience) > 1
    if (several or azp is not None) and azp != config.client_id:
        raise OIDCTokenVerificationError("the azp of the ID token is not this client")

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
            # the count via record_success.
            #
            # Deliberately NOT the rule gate.py's own paths follow, which
            # count only a request that offered a credential and got it
            # wrong (build_gate_middleware's docstring; an earlier version
            # of this comment cited that "any unauthenticated hit counts"
            # posture, which no longer exists). This route is different in
            # kind: it is public by necessity, has no credential to be
            # wrong about, and each hit makes this process perform an
            # outbound discovery fetch against the identity provider --
            # the cost being throttled is that fetch, not a guess. The
            # matching relaxation is one step later instead: a `state`
            # the callback recognises bypasses the check entirely, so a
            # real login never pays for the failure charged here.
            rate_limiter.record_failure(key)

        try:
            discovery = await fetch_discovery_document(config.issuer_url)
        except OIDCDiscoveryError as exc:
            raise web.HTTPServiceUnavailable(
                text="identity provider unreachable"
            ) from exc
        raise web.HTTPFound(build_authorization_url(config, discovery, store))

    def _reject_callback(
        key: str, *, reason: str = "", cause: BaseException | None = None
    ) -> NoReturn:
        # Same RateLimiter/logger the Bearer-header and login-form paths
        # already use (T036/T037, US3) -- not a parallel mechanism.
        # fail2ban/crowdsec key off the stable prefix "authentication
        # failure from <IP>"; the reason in the parentheses is for the
        # operator, and never holds a token or a claim value.
        if rate_limiter is not None:
            rate_limiter.record_failure(key)
        _logger.warning(
            "comfyui_curu_auth: authentication failure from %s (oidc callback%s)",
            key,
            f": {reason}" if reason else "",
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
            claims = await verify_id_token(
                id_token,
                config=config,
                discovery=discovery,
                expected_nonce=in_flight.nonce,
            )
        except OIDCTokenVerificationError as exc:
            _reject_callback(key, reason=exc.reason, cause=exc)
        except OIDCDiscoveryError as exc:
            _reject_callback(key, reason="discovery document refused", cause=exc)
        except KeyError as exc:
            _reject_callback(key, reason="no id_token in the token response", cause=exc)

        if not config.allowlist.permits(claims):
            _reject_callback(key, reason="the person is not on the allowlist")

        if rate_limiter is not None:
            rate_limiter.record_success(key)

        session_token = sessions.issue()
        redirect = web.HTTPFound("/")
        # The same cookie, with the same scheme-dependent `Secure`, the
        # credential form sets (ADR-002, ADR-006).
        set_session_cookie(
            redirect, request, session_token, max_age=COOKIE_MAX_AGE_SECONDS
        )
        raise redirect

    return start, callback


__all__ = [
    "ALLOWED_ALGORITHMS",
    "CLOCK_LEEWAY_SECONDS",
    "DEFAULT_SCOPES",
    "OIDC_CALLBACK_PATH",
    "OIDC_START_PATH",
    "AuthorizationRequestStore",
    "InFlightAuthRequest",
    "LoginAllowlist",
    "OIDCConfig",
    "OIDCConfigError",
    "OIDCDiscoveryError",
    "OIDCTokenVerificationError",
    "build_authorization_url",
    "build_oidc_routes",
    "check_token_algorithm",
    "discovery_url",
    "fetch_discovery_document",
    "read_token_header",
    "resolve_oidc_config",
    "select_signing_key",
    "verify_id_token",
]
