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

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
import warnings
from collections.abc import Awaitable, Callable
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
        TokenCheckUnavailableError,
        client_key,
        request_origin,
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
        TokenCheckUnavailableError,
        client_key,
        request_origin,
        set_session_cookie,
    )

#: The two OIDC routes -- reachable pre-session by definition, so
#: __init__.py registers them in gate.py's `public_paths` set (ADR-003)
#: only when OIDC is actually configured. Module-level constants, not
#: inlined in __init__.py, matching gate.py's own LOGIN_PATH precedent.
OIDC_START_PATH = "/curu-auth/oidc/start"
OIDC_CALLBACK_PATH = "/curu-auth/oidc/callback"

#: What a good callback answers: a page that moves the browser on to ComfyUI
#: from this site (see the callback's own comment). The link is for a browser
#: that does not follow a meta refresh.
_SIGNED_IN_PAGE = (
    "<!DOCTYPE html>\n"
    '<html><head><meta charset="utf-8">'
    '<meta http-equiv="refresh" content="0;url=/">'
    "<title>Signed in</title></head>"
    '<body><p>Signed in. <a href="/">Open ComfyUI</a>.</p></body></html>\n'
)


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

    ``redirect_uri`` is the default redirect URI, the first entry of the
    setting. ``other_redirect_uris`` holds the other entries, for a ComfyUI
    reached at more than one origin (issue #25). :meth:`redirect_uri_for`
    chooses among them; nothing else may.
    """

    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    allowlist: LoginAllowlist = LoginAllowlist()
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    other_redirect_uris: tuple[str, ...] = ()

    @property
    def redirect_uris(self) -> tuple[str, ...]:
        """Each configured redirect URI, the default first."""

        return (self.redirect_uri, *self.other_redirect_uris)

    def redirect_uri_for(self, origin: str) -> str:
        """The configured redirect URI whose origin is ``origin``, or the
        default when none is.

        ``origin`` comes from request headers that any client can write
        (:func:`gate.request_origin`). So the answer is always one of
        :attr:`redirect_uris`: a forged header can pick another configured
        URI, never a URI of its own (issue #25).
        """

        wanted = _origin_key(origin)
        if wanted is not None:
            for uri in self.redirect_uris:
                if _origin_key(uri) == wanted:
                    return uri
        return self.redirect_uri


class OIDCConfigError(Exception):
    """The four settings of the login are set, but the setup is not safe.

    ``__init__.py`` writes this as an error and keeps the OIDC login off. It
    never lets it escape: ComfyUI would then skip the node, and the gate
    would be off (ADR-007).
    """


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_key(url: str) -> tuple[str, str, int] | None:
    """``(scheme, host, port)`` of ``url``, for a comparison of origins.

    The host is in lower case, and a missing port is the default port of the
    scheme. ``None`` for a URL that is not ``http`` or ``https``, has no
    host, or has a bad port.
    """

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    return scheme, parts.hostname, port or _DEFAULT_PORTS[scheme]


def _redirect_uris(setting: str) -> tuple[str, ...]:
    """The entries of the redirect URI setting, in order, each one time.

    Raises :class:`OIDCConfigError` for an entry that is not an ``http`` or
    ``https`` URL with a host, or whose path does not end in
    :data:`OIDC_CALLBACK_PATH`: the provider would send the browser to a
    route that is not the callback.
    """

    uris = tuple(dict.fromkeys(_split(setting)))
    for uri in uris:
        if _origin_key(uri) is None or not urlsplit(uri).path.endswith(
            OIDC_CALLBACK_PATH
        ):
            raise OIDCConfigError(
                "OIDC login is off: each entry of "
                "COMFYUI_CURU_AUTH_OIDC_REDIRECT_URI must be an http or https "
                f"URL that ends in {OIDC_CALLBACK_PATH}; got {uri!r}"
            )
    return uris


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
    if not is_safe_url(issuer_url):
        # The discovery document comes from the issuer and names the keys, so
        # plain http to another host would let the network swap the keys.
        raise OIDCConfigError(
            "OIDC login is off: COMFYUI_CURU_AUTH_OIDC_ISSUER_URL must use https "
            "(plain http is allowed only on localhost, 127.0.0.1 and ::1)"
        )
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
    default_uri, *other_uris = _redirect_uris(redirect_uri)
    return OIDCConfig(
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=default_uri,
        allowlist=allowlist,
        scopes=_scopes(scopes),
        other_redirect_uris=tuple(other_uris),
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
            _require_ok(response)
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


def is_safe_url(url: str) -> bool:
    """Whether ``url`` uses ``https``, or plain ``http`` on a loopback host."""

    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return True
    return parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS


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
    if is_safe_url(url):
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
    #: The ``redirect_uri`` of the authorize request. The token exchange
    #: must send the same value (RFC 6749, section 4.1.3).
    redirect_uri: str = ""


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

    def create(self, *, redirect_uri: str = "") -> InFlightAuthRequest:
        entry = InFlightAuthRequest(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            pkce_verifier=secrets.token_urlsafe(64),
            created_at=time.monotonic(),
            redirect_uri=redirect_uri,
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
    redirect_uri: str | None = None,
) -> str:
    """Build the redirect URL to the identity provider's authorization
    endpoint, recording a matching :class:`InFlightAuthRequest` in
    ``store`` keyed by the `state` it generates. The scope is
    ``config.scopes`` (spec 003).

    ``redirect_uri`` is one of ``config.redirect_uris``, chosen by
    :meth:`OIDCConfig.redirect_uri_for`; ``None`` means the default. The
    entry in ``store`` keeps it for the token exchange (issue #25).
    """

    chosen = redirect_uri or config.redirect_uri
    in_flight = store.create(redirect_uri=chosen)
    query = {
        "client_id": config.client_id,
        "redirect_uri": chosen,
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

_HMAC_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})

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

    return _decode_segment(token, 0)


def _decode_segment(token: str, index: int) -> dict[str, Any]:
    """Part ``index`` of a compact JWS as a JSON object, with no check of the
    signature. Raises :class:`OIDCTokenVerificationError` for any other shape."""

    parts = token.split(".")
    if len(parts) != 3:
        raise OIDCTokenVerificationError("malformed token")
    try:
        padded = parts[index] + "=" * (-len(parts[index]) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError) as exc:
        raise OIDCTokenVerificationError("malformed token") from exc
    if not isinstance(value, dict):
        raise OIDCTokenVerificationError("malformed token")
    return value


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
    # The reason names the algorithm only when it is one of the fixed names
    # below: the value comes from the token, and a reason holds no token data.
    if alg.upper().startswith("HS"):
        name = alg if alg in _HMAC_ALGORITHMS else "an HMAC algorithm"
        raise OIDCTokenVerificationError(
            f"algorithm {name} is not allowed: the token is signed with a shared "
            "secret. An Authentik provider with no signing key does this; select "
            "a signing key on the provider"
        )
    if alg not in ALLOWED_ALGORITHMS:
        raise OIDCTokenVerificationError("the algorithm of the token is not allowed")
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
    from joserfc.errors import JoseError
    from joserfc.jwk import KeySet  # deferred -- see module docstring (issue #5)

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                jwks_uri,
                timeout=aiohttp.ClientTimeout(total=timeout),
                # A redirect could move the keys to plain http (ADR-007).
                allow_redirects=False,
            ) as response,
        ):
            _require_ok(response)
            jwks_data = await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise OIDCTokenVerificationError("failed to fetch the JWKS") from exc
    try:
        return KeySet.import_key_set(jwks_data)
    except (JoseError, TypeError, KeyError, ValueError, AttributeError) as exc:
        raise OIDCTokenVerificationError("the JWKS is not a valid key set") from exc


def _require_ok(response: aiohttp.ClientResponse) -> None:
    """Raise for any answer that is not 2xx -- also a redirect, which the
    gate never follows."""

    response.raise_for_status()
    if response.status >= 300:
        raise aiohttp.ClientError(f"HTTP {response.status}")


# --------------------------------------------------------------------------
# Resource-server mode: OIDC access tokens on the Bearer path (spec 004,
# ADR-008). It uses the issuer code and the key code above; nothing here is
# a second copy of a rule of the login.
# --------------------------------------------------------------------------

#: The ``typ`` values of an access token (RFC 9068). Compared in small letters.
ACCESS_TOKEN_TYPES = frozenset({"at+jwt", "application/at+jwt"})

#: The longest life of an access token, from ``iat`` to ``exp``, in seconds.
MAX_ACCESS_TOKEN_LIFETIME_SECONDS = 3600

#: The shortest time between two reads of the keys, in seconds (ADR-008).
KEY_REFRESH_SECONDS = 60.0

#: The longest time the gate trusts keys without a new read, in seconds. A
#: key that the identity provider removed stops working within this time.
KEY_MAX_AGE_SECONDS = 3600.0


@dataclass(frozen=True)
class ResourceServerConfig:
    """The settings of resource-server mode. The mode is on only when this
    exists: :func:`resolve_resource_server_config` never makes a partial one."""

    issuer_url: str
    audience: str
    required_scopes: tuple[str, ...] = ()


def resolve_resource_server_config(
    *,
    issuer_url: str | None,
    audience: str | None,
    required_scopes: str | None,
) -> ResourceServerConfig | None:
    """``ResourceServerConfig`` when the issuer and the audience are both set;
    ``None`` when the audience and the required scopes are both absent.

    Each other mix is a partial setup, and raises :class:`OIDCConfigError`
    (ADR-008): an audience with no issuer, required scopes with no audience,
    or an issuer that uses ``http`` off loopback. ``__init__.py`` logs the
    error and keeps the mode off, and the gate stays on. An issuer alone is
    not partial: the OIDC login can use it with no mode.
    """

    scopes = tuple(dict.fromkeys(_split(required_scopes)))
    if not audience:
        if scopes:
            raise OIDCConfigError(
                "OIDC access tokens are off: COMFYUI_CURU_AUTH_OIDC_REQUIRED_SCOPES "
                "needs COMFYUI_CURU_AUTH_OIDC_AUDIENCE"
            )
        return None
    if not issuer_url:
        raise OIDCConfigError(
            "OIDC access tokens are off: COMFYUI_CURU_AUTH_OIDC_AUDIENCE needs "
            "COMFYUI_CURU_AUTH_OIDC_ISSUER_URL"
        )
    if not is_safe_url(issuer_url):
        raise OIDCConfigError(
            "OIDC access tokens are off: COMFYUI_CURU_AUTH_OIDC_ISSUER_URL must "
            "use https (plain http is allowed only on localhost, 127.0.0.1 and ::1)"
        )
    return ResourceServerConfig(
        issuer_url=issuer_url, audience=audience, required_scopes=scopes
    )


class IssuerKeys:
    """The discovery document and the JWKS of one issuer, kept in memory.

    A known ``kid`` never waits for a read. An unknown ``kid`` causes one new
    read, at most one time in ``refresh_seconds``. A failed read also starts
    that time, so an issuer that is down gets few requests, and a stream of
    tokens with invented ``kid`` values cannot make the gate read the keys
    again and again (ADR-008). One read runs at a time.
    """

    def __init__(
        self,
        issuer_url: str,
        *,
        refresh_seconds: float = KEY_REFRESH_SECONDS,
        max_age_seconds: float = KEY_MAX_AGE_SECONDS,
        timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer_url = issuer_url
        self._refresh_seconds = refresh_seconds
        self._max_age_seconds = max_age_seconds
        self._loaded_at: float | None = None
        self._timeout = timeout
        self._clock = clock
        self._jwks_uri: str | None = None
        self._key_set: KeySet | None = None
        self._read_at: float | None = None
        self._lock = asyncio.Lock()

    def _select(self, header: dict[str, Any]) -> tuple[Any, str] | None:
        """The key, or None when the keys are absent or do not know the ``kid``."""

        if self._key_set is None:
            return None
        try:
            return select_signing_key(header, self._key_set)
        except OIDCTokenVerificationError as exc:
            if exc.reason != "unknown key":
                raise
            return None

    def _stale(self) -> bool:
        return (
            self._loaded_at is not None
            and self._clock() - self._loaded_at >= self._max_age_seconds
        )

    async def key_for(self, header: dict[str, Any]) -> tuple[Any, str]:
        found = self._select(header)
        if found is not None and not self._stale():
            return found
        async with self._lock:
            # Another request may have read the keys while this one waited.
            found = self._select(header)
            if found is not None and not self._stale():
                return found
            if self._read_at is None or (
                self._clock() - self._read_at >= self._refresh_seconds
            ):
                await self._read()
        if self._key_set is None:
            raise OIDCTokenVerificationError("issuer not available")
        found = self._select(header)
        if found is None:
            raise OIDCTokenVerificationError("unknown key")
        return found

    async def _read(self) -> None:
        self._read_at = self._clock()
        try:
            if self._jwks_uri is None:
                document = await fetch_discovery_document(
                    self._issuer_url, timeout=self._timeout
                )
                self._jwks_uri = str(document["jwks_uri"])
            self._key_set = await _fetch_jwks(self._jwks_uri, timeout=self._timeout)
            self._loaded_at = self._read_at
        except (OIDCDiscoveryError, OIDCTokenVerificationError) as exc:
            # A provider fault, not an authentication failure: another text,
            # so fail2ban and crowdsec do not ban the caller for it. The old
            # keys, if any, stay in use.
            _logger.error("comfyui_curu_auth: cannot read the OIDC keys: %s", exc)


def _scopes_of(claims: dict[str, Any]) -> set[str]:
    """The scopes of a token: ``scope`` (a string) or ``scp`` (a list or a string)."""

    found: set[str] = set()
    for name in ("scope", "scp"):
        value = claims.get(name)
        if isinstance(value, str):
            found.update(value.split())
        elif isinstance(value, list):
            found.update(item for item in value if isinstance(item, str))
    return found


async def verify_access_token(
    token: str, *, config: ResourceServerConfig, keys: IssuerKeys
) -> dict[str, Any]:
    """The claims of an access token that passes each check of ADR-008.

    Raises :class:`OIDCTokenVerificationError` with a fixed ``reason`` at the
    first check that fails. Checks 1 to 4 need no network, so a token that
    fails them never causes a read of the JWKS.
    """

    from joserfc import errors as jose_errors  # deferred -- module docstring (issue #5)
    from joserfc import jwt

    # 1-2. The shape, and no `none` or HMAC.
    header = read_token_header(token)
    check_token_algorithm(header)
    # 3. The token type.
    typ = header.get("typ")
    plain = typ is None or (isinstance(typ, str) and typ.lower() == "jwt")
    if not plain and not (isinstance(typ, str) and typ.lower() in ACCESS_TOKEN_TYPES):
        raise OIDCTokenVerificationError("wrong token type")
    # 4. The issuer, before any read of the keys.
    if _decode_segment(token, 1).get("iss") != config.issuer_url:
        raise OIDCTokenVerificationError("wrong issuer")
    # 5-6. The key sets the algorithm; then the signature.
    key, algorithm = await keys.key_for(header)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", jose_errors.SecurityWarning)
            claims = jwt.decode(token, key, algorithms=[algorithm]).claims
    except jose_errors.BadSignatureError as exc:
        raise OIDCTokenVerificationError("bad signature") from exc
    except (jose_errors.JoseError, ValueError) as exc:
        raise OIDCTokenVerificationError("malformed token") from exc
    # 7. The claims that each token must have.
    if any(name not in claims for name in ("iss", "aud", "exp", "iat")):
        raise OIDCTokenVerificationError("missing claim")
    if claims["iss"] != config.issuer_url:
        raise OIDCTokenVerificationError("wrong issuer")
    audience = claims["aud"]
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(audiences, list) or config.audience not in audiences:
        raise OIDCTokenVerificationError("wrong audience")
    # 8-9. The time. No leeway for exp; 60 seconds for iat and nbf.
    times = [claims["exp"], claims["iat"], claims.get("nbf", claims["iat"])]
    if not all(isinstance(value, int | float) for value in times):
        raise OIDCTokenVerificationError("malformed token")
    expires, issued, not_before = times
    now = time.time()
    if now >= expires:
        raise OIDCTokenVerificationError("expired")
    if max(issued, not_before) > now + CLOCK_LEEWAY_SECONDS:
        raise OIDCTokenVerificationError("not yet valid")
    if expires - issued > MAX_ACCESS_TOKEN_LIFETIME_SECONDS:
        raise OIDCTokenVerificationError("lifetime too long")
    # 10. A token of the type JWT, or with no type, is not an ID token.
    scopes = _scopes_of(claims)
    client = claims.get("azp") or claims.get("client_id") or claims.get("cid")
    if plain and not (client and scopes):
        raise OIDCTokenVerificationError("ID token or no client id and scope")
    # 11. The required scopes.
    if not set(config.required_scopes) <= scopes:
        raise OIDCTokenVerificationError("missing scope")
    return claims


def build_token_check(
    config: ResourceServerConfig, keys: IssuerKeys | None = None
) -> Callable[[str], Awaitable[str | None]]:
    """The ``token_check`` for :func:`gate.build_gate_middleware` (ADR-008).

    It returns ``None`` for a valid access token, and the fixed reason of
    :func:`verify_access_token` for a refused one. It never raises for a
    bad token. An accepted token writes its client id and ``sub`` at DEBUG,
    for an audit that joins this log with the log of the caller.
    """

    issuer_keys = keys if keys is not None else IssuerKeys(config.issuer_url)

    async def check(token: str) -> str | None:
        try:
            claims = await verify_access_token(token, config=config, keys=issuer_keys)
        except OIDCTokenVerificationError as exc:
            if exc.reason == "issuer not available":
                # No keys at all: the identity provider failed, not the caller.
                raise TokenCheckUnavailableError(exc.reason) from exc
            return exc.reason
        client = claims.get("azp") or claims.get("client_id") or claims.get("cid")
        _logger.debug(
            "comfyui_curu_auth: access token accepted (client %r, sub %r)",
            client,
            claims.get("sub"),
        )
        return None

    return check


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
    redirect_uri: str | None = None,
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

    ``redirect_uri`` MUST be the value that the authorization request sent
    (RFC 6749, section 4.1.3) -- the one that the same
    :class:`InFlightAuthRequest` keeps. ``None`` means the default.
    """

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or config.redirect_uri,
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
                # A 307 or 308 would send the client secret to the new target.
                allow_redirects=False,
            ) as response,
        ):
            _require_ok(response)
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
            # A setup or provider fault, not an authentication failure: a
            # different text, so fail2ban and crowdsec do not ban for it. The
            # message names both issuers when they differ (ADR-007).
            _logger.error("comfyui_curu_auth: OIDC login unavailable: %s", exc)
            raise web.HTTPServiceUnavailable(
                text="identity provider unreachable; see the ComfyUI log"
            ) from exc
        # The origin only chooses among the configured URIs (issue #25).
        redirect_uri = config.redirect_uri_for(request_origin(request))
        raise web.HTTPFound(
            build_authorization_url(config, discovery, store, redirect_uri=redirect_uri)
        )

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
                config,
                discovery,
                code,
                code_verifier=in_flight.pkce_verifier,
                redirect_uri=in_flight.redirect_uri,
            )
            id_token = token_response.get("id_token")
            if not isinstance(id_token, str):
                _reject_callback(key, reason="no id_token in the token response")
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

        if not config.allowlist.permits(claims):
            _reject_callback(key, reason="the person is not on the allowlist")

        if rate_limiter is not None:
            rate_limiter.record_success(key)

        session_token = sessions.issue()
        # A page that moves the browser on to `/`, not a redirect. The
        # browser reached this callback from the provider, another site, so
        # it counts a redirect from here as part of a cross-site chain and
        # sends no `SameSite=Strict` cookie with the `GET /` that follows:
        # the gate refuses the session it just issued, and the person lands
        # on the login page again (found live, Authentik on its own domain
        # and ComfyUI on a LAN address). A navigation that this page starts
        # is same-site, so the cookie stays `Strict`. A meta refresh, not a
        # script, so no Content-Security-Policy can stop it.
        response = web.Response(
            text=_SIGNED_IN_PAGE,
            content_type="text/html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
        # The same cookie, with the same scheme-dependent `Secure`, the
        # credential form sets (ADR-002, ADR-006).
        set_session_cookie(
            response, request, session_token, max_age=COOKIE_MAX_AGE_SECONDS
        )
        return response

    return start, callback


__all__ = [
    "ACCESS_TOKEN_TYPES",
    "ALLOWED_ALGORITHMS",
    "CLOCK_LEEWAY_SECONDS",
    "DEFAULT_SCOPES",
    "KEY_MAX_AGE_SECONDS",
    "KEY_REFRESH_SECONDS",
    "MAX_ACCESS_TOKEN_LIFETIME_SECONDS",
    "OIDC_CALLBACK_PATH",
    "OIDC_START_PATH",
    "AuthorizationRequestStore",
    "InFlightAuthRequest",
    "IssuerKeys",
    "LoginAllowlist",
    "OIDCConfig",
    "OIDCConfigError",
    "OIDCDiscoveryError",
    "OIDCTokenVerificationError",
    "ResourceServerConfig",
    "build_authorization_url",
    "build_oidc_routes",
    "build_token_check",
    "check_token_algorithm",
    "discovery_url",
    "fetch_discovery_document",
    "is_safe_url",
    "read_token_header",
    "resolve_oidc_config",
    "resolve_resource_server_config",
    "select_signing_key",
    "verify_access_token",
    "verify_id_token",
]
