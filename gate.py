"""The gate's pure, testable logic -- credential generation and the
``aiohttp`` middleware that enforces it.

Needs only ``aiohttp`` -- never ``server`` (ComfyUI's own module, which
only resolves inside a real ComfyUI installation and is imported solely
by ``__init__.py``, this package's ComfyUI-loaded entrypoint). This
separation is what lets ``gate.py``'s own logic run under this repo's
hermetic ``pytest`` suite at all, with no real ComfyUI process needed.
"""

from __future__ import annotations

import logging
import secrets
import time

from aiohttp import web
from aiohttp.typedefs import Handler, Middleware

#: A stable, greppable logger name -- external log-watching tools
#: (fail2ban, crowdsec) match on the "authentication failure from <IP>"
#: message text itself, not this logger's own name, but a fixed name
#: keeps `logging.getLogger("comfyui_curu_auth").setLevel(...)`-style
#: operator configuration stable too. See README's own fail2ban/crowdsec
#: integration docs.
_logger = logging.getLogger("comfyui_curu_auth")

#: The one path the gate itself must always let through unauthenticated --
#: otherwise a human with no cookie or header yet could never reach the
#: form that would let them get one (a chicken-and-egg 401 on the login
#: page itself).
LOGIN_PATH = "/curu-auth/login"

#: The cookie a successful browser login sets, carrying a distinct
#: session token (:class:`SessionStore`) -- never the master credential
#: itself (the gate must never transmit that credential over the network
#: itself; a browser replaying a cookie on every request is exactly such
#: a transmission, so this cookie must carry something else).
#: `secure=True`/`samesite="Strict"` on the `set_cookie` call (below)
#: mean it is only ever sent back over the same HTTPS origin that issued
#: it (e.g. a cloud GPU host's own TLS-terminating proxy) -- never over
#: plain HTTP, never cross-site.
COOKIE_NAME = "curu_auth"

_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def generate_credential() -> str:
    """A fresh, cryptographically-secure credential -- ``secrets.
    token_urlsafe(32)``, 256 bits of entropy, computationally infeasible
    to brute-force. This package deliberately has no dependency on any
    other project's own client code: it runs inside a ComfyUI
    installation's own Python environment, which has no reason to have
    anything else installed.
    """

    return secrets.token_urlsafe(32)


def resolve_credential(env_value: str | None) -> str:
    """`env_value` if it's a real, non-empty string; otherwise a fresh
    :func:`generate_credential`.

    Lets an operator (or an automated test harness) pin a known,
    persistent credential via an environment variable --
    `__init__.py` calls this with
    ``os.environ.get("COMFYUI_CURU_AUTH_TOKEN")`` -- instead of always
    scraping a freshly random one from the console after every restart.
    ``os.environ.get`` returns ``""`` for a declared-but-empty variable,
    not ``None``, so both are treated as "not supplied", not as a
    (useless, insecure) empty credential.
    """

    if env_value:
        return env_value
    return generate_credential()


def build_gate_middleware(
    credential: str, *, sessions: SessionStore | None = None
) -> Middleware:
    """Return an aiohttp ``@web.middleware`` function that rejects any
    request lacking ``credential`` -- as ``Authorization: Bearer
    <credential>`` (an automated HTTP client's own request) or, when
    ``sessions`` is supplied, as a ``curu_auth`` cookie carrying a token
    :meth:`SessionStore.issue` minted (a human browsing ComfyUI's own UI
    directly, who has no way to attach a custom header) -- covers every
    route on the app it's installed into, including a websocket route's
    own initial handshake, verified directly against ComfyUI's own
    ``server.py`` (every route it registers shares one ``app``/``routes``
    object). ``LOGIN_PATH`` itself is always let through unauthenticated
    -- see its own docstring for why.

    ``sessions=None`` (the default) disables cookie auth entirely --
    every pre-browser-login caller/test of this function keeps its exact
    original behaviour (Bearer header only).

    A rejected request that also carries ``Accept: text/html`` gets a
    302 redirect to :data:`LOGIN_PATH` instead of a bare JSON 401 -- a
    human navigating directly to any gated page has no way to act on a
    JSON error body without already knowing the login form's URL. A
    real, automated Bearer-header HTTP client and a WebSocket handshake
    both never send that header, so this never changes behaviour for
    either of them (only a real browser page-load does).

    ``secrets.compare_digest`` on ``bytes`` (not ``str``) avoids a crash
    a plain ``str`` comparison would raise on a non-ASCII
    ``Authorization`` header -- applied to the header check; the cookie
    check's own constant-time comparison lives in
    :meth:`SessionStore.is_valid`.
    """

    expected_header = f"Bearer {credential}".encode("latin-1")

    @web.middleware
    async def gate(request: web.Request, handler: Handler) -> web.StreamResponse:
        if request.path == LOGIN_PATH:
            return await handler(request)

        supplied_header = request.headers.get("Authorization", "").encode("latin-1")
        if secrets.compare_digest(supplied_header, expected_header):
            return await handler(request)

        if sessions is not None:
            supplied_cookie = request.cookies.get(COOKIE_NAME, "")
            if supplied_cookie and sessions.is_valid(supplied_cookie):
                return await handler(request)

        # Logged, never rate-limited or blocked here (RateLimiter's own
        # docstring: blocking this path risks locking a legitimate
        # automated client out of recovering from a transient
        # misconfiguration) -- an external log-watching tool decides
        # whether/how to act on repeated failures, this gate only ever
        # reports them.
        _logger.warning(
            "comfyui_curu_auth: authentication failure from %s (%s %s)",
            _client_key(request),
            request.method,
            request.path,
        )

        if "text/html" in request.headers.get("Accept", ""):
            raise web.HTTPFound(LOGIN_PATH)

        return web.json_response(
            {"detail": "missing or invalid credential"}, status=401
        )

    return gate


class SessionStore:
    """A small, in-memory set of currently-valid browser-login session
    tokens.

    Deliberately a *distinct* token per login, never the master
    credential itself (the gate must never transmit that credential over
    the network itself -- a cookie replayed on every request is exactly
    such a transmission). This separation also means a single leaked
    cookie can never be replayed as the actual Bearer-header credential,
    and a suspected-compromised browser session could, in principle, be
    revoked without regenerating (and thereby breaking) the configured
    credential every other client depends on -- though this minimal
    version has no revoke-one API yet, only the store as a whole, cleared
    on every ComfyUI restart exactly like the credential and
    :class:`RateLimiter`'s own state.
    """

    def __init__(self) -> None:
        self._tokens: set[str] = set()

    def issue(self) -> str:
        """Mint and remember a fresh session token."""

        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        return token

    def is_valid(self, token: str) -> bool:
        """Whether ``token`` was issued by this store and not since
        cleared. Compares against every issued token via
        ``secrets.compare_digest`` (not a plain ``in``/set-membership
        check) for the same constant-time discipline this gate applies
        to its other secret comparisons."""

        candidate = token.encode("latin-1", errors="ignore")
        return any(
            secrets.compare_digest(candidate, existing.encode("latin-1"))
            for existing in self._tokens
        )


class RateLimiter:
    """Per-client exponential backoff after repeated failed login
    attempts against :data:`LOGIN_PATH` (defence in depth -- the
    credential itself is 256 bits of entropy from
    :func:`generate_credential`, already computationally infeasible to
    brute-force regardless of this; this bounds the request/log volume an
    automated scanner probing a human-friendly login form can generate).

    Deliberately in-process, in-memory state, not durable storage --
    mirrors this gate's own fully-stateless design elsewhere (simple, no
    persistent state); a ComfyUI restart clears it, exactly like the
    credential itself resets on every restart.

    Deliberately scoped to the login form only, never the Bearer-header
    path every other route uses -- rate-limiting that path risks locking
    an automated client out of recovering from a transient
    misconfiguration, a strictly worse outcome than the brute-force risk
    this class defends against.
    """

    def __init__(self, *, base_delay: float = 1.0, max_delay: float = 300.0) -> None:
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._failures: dict[str, int] = {}
        self._blocked_until: dict[str, float] = {}

    def seconds_until_retry(self, client_key: str) -> float:
        """0.0 if `client_key` may attempt now; otherwise how many seconds
        remain before it may."""

        remaining = self._blocked_until.get(client_key, 0.0) - time.monotonic()
        return max(0.0, remaining)

    def record_failure(self, client_key: str) -> None:
        failures = self._failures.get(client_key, 0) + 1
        self._failures[client_key] = failures
        delay = min(self._max_delay, self._base_delay * (2 ** (failures - 1)))
        self._blocked_until[client_key] = time.monotonic() + delay

    def record_success(self, client_key: str) -> None:
        self._failures.pop(client_key, None)
        self._blocked_until.pop(client_key, None)


#: A small, self-contained design system applied directly as inline CSS
#: custom properties -- this page is served standalone from inside a
#: ComfyUI installation with no build step and no access to any other
#: project's own design tokens, so the values are restated here rather
#: than shared; system-font stacks only (no CDN font fetch) keeps this a
#: purely self-contained, single response, matching this whole gate's own
#: "no network dependency" posture.
#:
#: The hidden `username` field (a fixed constant, never read by
#: `build_login_routes`'s own POST handler below) exists purely so
#: Chrome/Firefox/Safari's own password-manager autofill heuristics
#: recognise this as a login form and offer to save the credential --
#: verified against TScriptDoc/ComfyUI-Authenticator's own `login.html`
#: (which runpod-comfy can also install), whose real username+password
#: pair is exactly why it reliably triggers the "save password?" prompt
#: that a password-only form generally does not. curu's own scheme has
#: no actual second identity to check -- this restores the browser UX
#: parity without inventing one server-side.
_LOGIN_PAGE_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>curu ComfyUI auth</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg-primary: #1a1d23;
    --bg-secondary: #2a2d35;
    --border-muted: #4a5060;
    --text-primary: #e8e4dc;
    --text-secondary: #b8b4a8;
    --accent-olive: #7a8a5a;
    --accent-error: #b85a5a;
    --ease-organic: cubic-bezier(0.4, 0, 0.2, 1);
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg-primary: #f4f2ed;
      --bg-secondary: #ebe8e1;
      --border-muted: #c8c4ba;
      --text-primary: #2a2d35;
      --text-secondary: #4a5060;
      --accent-olive: #5a6a3a;
      --accent-error: #8a5a3a;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: 'Inter', 'SF Pro Display', -apple-system, sans-serif;
  }}
  main {{
    width: min(360px, calc(100vw - 48px));
    background: var(--bg-secondary);
    border: 1px solid var(--border-muted);
    border-radius: 8px;
    padding: 40px 32px;
    animation: breathe-in 0.6s var(--ease-organic);
  }}
  @keyframes breathe-in {{
    from {{ opacity: 0; transform: translateY(4px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  h1 {{
    margin: 0 0 24px;
    font-size: 28px;
    font-weight: 400;
    letter-spacing: 0.01em;
  }}
  label {{
    display: block;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-secondary);
    margin-bottom: 8px;
  }}
  input {{
    width: 100%;
    padding: 12px;
    font-family: 'JetBrains Mono', 'SF Mono', monospace;
    font-size: 14px;
    color: var(--text-primary);
    background: var(--bg-primary);
    border: 1px solid var(--border-muted);
    border-radius: 4px;
  }}
  input:focus {{
    outline: none;
    border-color: var(--accent-olive);
  }}
  button {{
    width: 100%;
    margin-top: 16px;
    padding: 12px;
    font-family: inherit;
    font-size: 14px;
    font-weight: 500;
    color: #ffffff;
    background: var(--accent-olive);
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }}
  .message-slot p {{
    margin: 0 0 16px;
    font-size: 14px;
    color: var(--accent-error);
  }}
</style>
</head>
<body>
<main>
  <h1>curu ComfyUI auth</h1>
  <div class="message-slot">{message}</div>
  <form method="post" action="{login_path}">
    <input type="text" name="username" value="curu" autocomplete="username" hidden>
    <label for="token">Credential</label>
    <input type="password" id="token" name="token"
           autocomplete="current-password" autofocus>
    <button type="submit">Log in</button>
  </form>
</main>
</body>
</html>
"""


def _render_login_page(*, message: str = "") -> str:
    return _LOGIN_PAGE_TEMPLATE.format(message=message, login_path=LOGIN_PATH)


def _client_key(request: web.Request) -> str:
    """The identity :class:`RateLimiter` keys backoff on for one request.

    Prefers ``X-Forwarded-For``'s first (left-most, closest-to-client)
    entry over ``request.remote`` -- verified live against a real RunPod
    deployment (Cloudflare fronting a ``proxy.runpod.net`` origin) that
    ``request.remote`` is the *proxy's own* connecting address there, not
    a stable per-client value, which silently defeated the backoff
    entirely (every request looked like a different, fresh client).
    Falls back to ``request.remote`` when the header is absent (a direct
    connection, e.g. this gate reached with no reverse proxy in front at
    all).

    This is honestly best-effort, not a hard security boundary: a client
    with direct network access to this gate's own origin (bypassing
    whatever proxy is in front) could forge this header to evade
    per-client backoff. That is an acceptable trade here -- as
    :class:`RateLimiter`'s own docstring already states, the credential's
    256 bits of entropy is the actual protection against brute force;
    this key only decides whose request volume gets throttled, not
    whether the credential can be guessed.
    """

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote or "unknown"


def build_login_routes(
    credential: str,
    *,
    sessions: SessionStore,
    rate_limiter: RateLimiter | None = None,
) -> tuple[Handler, Handler]:
    """Return ``(login_get, login_post)`` handlers for :data:`LOGIN_PATH` --
    a minimal HTML form letting a human paste the same credential
    :func:`build_gate_middleware`'s Bearer-header check already accepts,
    so they can browse ComfyUI's own UI directly. Never changes the
    Bearer-header path an automated client uses at all.

    ``sessions`` MUST be the same :class:`SessionStore` instance passed to
    :func:`build_gate_middleware`, so a token minted here is one the
    middleware will actually recognise -- there is no default, since a
    private, unshared store would silently issue cookies the middleware
    could never validate.

    ``rate_limiter`` defaults to a fresh :class:`RateLimiter` (module-level
    default parameters) when omitted -- pass one explicitly to share state
    across calls, or to tune the backoff.
    """

    limiter = rate_limiter if rate_limiter is not None else RateLimiter()
    expected = credential.encode("latin-1")

    async def login_get(request: web.Request) -> web.Response:
        return web.Response(text=_render_login_page(), content_type="text/html")

    async def login_post(request: web.Request) -> web.StreamResponse:
        client_key = _client_key(request)
        retry_after = limiter.seconds_until_retry(client_key)
        if retry_after > 0:
            # The styled login page, not a bare JSON body: this route is
            # only ever reached by a real browser form submission (no
            # automated client posts to LOGIN_PATH), so a rate-limited
            # human should see the same page, not an unstyled API error.
            seconds = int(retry_after) + 1
            return web.Response(
                text=_render_login_page(
                    message=f"<p>Too many attempts. Try again in {seconds}s.</p>"
                ),
                content_type="text/html",
                status=429,
                headers={"Retry-After": str(seconds)},
            )

        data = await request.post()
        supplied = str(data.get("token", "")).encode("latin-1", errors="ignore")
        if not supplied or not secrets.compare_digest(supplied, expected):
            limiter.record_failure(client_key)
            _logger.warning(
                "comfyui_curu_auth: authentication failure from %s (login form)",
                client_key,
            )
            return web.Response(
                text=_render_login_page(message="<p>Incorrect credential.</p>"),
                content_type="text/html",
                status=401,
            )

        limiter.record_success(client_key)
        session_token = sessions.issue()
        redirect = web.HTTPFound("/")
        redirect.set_cookie(
            COOKIE_NAME,
            session_token,
            max_age=_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            secure=True,
            samesite="Strict",
        )
        # aiohttp deprecates *returning* an HTTPException subclass in
        # favour of raising it (it's still a real Response underneath --
        # the cookie set above travels with it either way).
        raise redirect

    return login_get, login_post


__all__ = [
    "COOKIE_NAME",
    "LOGIN_PATH",
    "RateLimiter",
    "SessionStore",
    "build_gate_middleware",
    "build_login_routes",
    "generate_credential",
]
