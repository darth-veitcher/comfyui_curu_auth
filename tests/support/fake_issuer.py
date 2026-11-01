"""A fake OIDC issuer for the hermetic tests: a discovery document, a JWKS, a
token endpoint, and helpers that sign tokens with local keys.

It copies the shape of rauthy 0.37.2 and Authentik: the issuer ends in ``/``,
and the keys are RSA, EC (P-256) and Ed25519 (spec 003, research R-1). It runs
inside the test process on a loopback port, so a test needs no network.

The attack tokens (``alg: none``, and HS256 signed with the public key as the
HMAC secret) are built by hand here, because ``joserfc`` rightly refuses to
make them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import warnings
from typing import Any, ClassVar

from aiohttp import web
from aiohttp.test_utils import TestServer
from joserfc import jwt
from joserfc.errors import SecurityWarning
from joserfc.jwk import ECKey, KeyParameters, OKPKey, RSAKey

CLIENT_ID = "comfyui-curu-auth"
CLIENT_SECRET = "fake-client-secret"
#: The audience of the gate in resource-server mode, and the client id of a
#: program that calls it (spec 004).
AUDIENCE = "http://comfyui.test"
PROGRAM_ID = "comfy-mcp-backend"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _segment(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode())


class FakeIssuer:
    """Start it with ``async with FakeIssuer() as issuer:``.

    ``issuer.issuer`` is the issuer URL. With ``trailing_slash=True`` (the
    default, as rauthy and Authentik give it) it ends in ``/``.
    """

    #: The algorithm of each test key, by ``kid``.
    KEYS: ClassVar[dict[str, str]] = {
        "rsa-1": "RS256",
        "ec-1": "ES256",
        "ed-1": "EdDSA",
    }

    def __init__(
        self, *, trailing_slash: bool = True, publish_alg: bool = True
    ) -> None:
        self._trailing_slash = trailing_slash
        #: False leaves ``alg`` out of each JWK, so the key type must set it.
        self.publish_alg = publish_alg
        self.keys: dict[str, tuple[str, Any]] = {}
        for kid, alg in self.KEYS.items():
            self.add_key(kid, alg)
        #: Fields that replace fields of the discovery document.
        self.discovery_overrides: dict[str, Any] = {}
        #: The number of reads of the discovery document and of the JWKS.
        self.discovery_reads = 0
        self.jwks_reads = 0
        #: The claims and the key of the next ID token of the token endpoint.
        self.login_claims: dict[str, Any] = {"sub": "user-1"}
        self.login_kid = "rsa-1"
        #: The nonce of the last authorization request. A test copies it here.
        self.nonce = "fake-nonce"
        #: A body that replaces the JWKS, for a test of a malformed key set.
        self.jwks_override: Any = None
        self._server: TestServer | None = None

    def add_key(self, kid: str, alg: str) -> None:
        parameters: KeyParameters = {"kid": kid}
        if alg.startswith(("RS", "PS")):
            key: Any = RSAKey.generate_key(2048, parameters=parameters, private=True)
        elif alg == "ES256":
            key = ECKey.generate_key("P-256", parameters=parameters, private=True)
        else:
            key = OKPKey.generate_key("Ed25519", parameters=parameters, private=True)
        self.keys[kid] = (alg, key)

    async def __aenter__(self) -> FakeIssuer:
        self._server = TestServer(self._app(), host="127.0.0.1")
        await self._server.start_server()
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        await self._server.close()

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return str(self._server.make_url("")).rstrip("/")

    @property
    def issuer(self) -> str:
        return f"{self.base_url}/issuer" + ("/" if self._trailing_slash else "")

    def discovery_document(self) -> dict[str, Any]:
        root = f"{self.base_url}/issuer"
        document = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{root}/authorize",
            "token_endpoint": f"{root}/token",
            "jwks_uri": f"{root}/jwks",
        }
        return {**document, **self.discovery_overrides}

    def jwks(self) -> dict[str, Any]:
        keys = []
        for kid, (alg, key) in self.keys.items():
            entry = {**key.as_dict(private=False), "kid": kid, "use": "sig"}
            if self.publish_alg:
                entry["alg"] = alg
            keys.append(entry)
        return {"keys": keys}

    def public_pem(self, kid: str) -> bytes:
        return self.keys[kid][1].as_pem(private=False)

    def _app(self) -> web.Application:
        async def discovery(request: web.Request) -> web.Response:
            self.discovery_reads += 1
            return web.json_response(self.discovery_document())

        async def jwks(request: web.Request) -> web.Response:
            self.jwks_reads += 1
            if self.jwks_override is not None:
                return web.json_response(self.jwks_override)
            return web.json_response(self.jwks())

        async def redirect_to_jwks(request: web.Request) -> web.Response:
            raise web.HTTPFound("/issuer/jwks")

        async def redirect_to_token(request: web.Request) -> web.Response:
            # 307 keeps the method and the body: the client secret goes along.
            raise web.HTTPTemporaryRedirect("/issuer/token")

        async def token(request: web.Request) -> web.Response:
            form = await request.post()
            if form.get("client_id") != CLIENT_ID or not form.get("code_verifier"):
                return web.json_response({"error": "invalid_grant"}, status=400)
            id_token = self.id_token(kid=self.login_kid, **self.login_claims)
            return web.json_response(
                {"access_token": "opaque", "id_token": id_token, "token_type": "bearer"}
            )

        app = web.Application()
        app.router.add_get("/issuer/.well-known/openid-configuration", discovery)
        app.router.add_get("/issuer/jwks", jwks)
        app.router.add_post("/issuer/token", token)
        app.router.add_get("/issuer/jwks-moved", redirect_to_jwks)
        app.router.add_post("/issuer/token-moved", redirect_to_token)
        return app

    def claims(self, **claims: Any) -> dict[str, Any]:
        """The claims of a valid ID token. A claim with the value None is left out."""
        now = int(time.time())
        body: dict[str, Any] = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "sub": "user-1",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
        }
        body.update(claims)
        return {name: value for name, value in body.items() if value is not None}

    def id_token(
        self,
        *,
        kid: str = "rsa-1",
        header: dict[str, Any] | None = None,
        sign_alg: str | None = None,
        **claims: Any,
    ) -> str:
        """An ID token signed with the key ``kid``.

        ``header`` replaces fields of the header. ``sign_alg`` signs with
        another algorithm of the same key type, and names it in the header.
        """
        alg, key = self.keys[kid]
        alg = sign_alg or alg
        protected = {"alg": alg, "kid": kid, "typ": "JWT", **(header or {})}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SecurityWarning)
            return jwt.encode(protected, self.claims(**claims), key, algorithms=[alg])

    def access_token(
        self,
        *,
        kid: str = "rsa-1",
        typ: str | None = "at+jwt",
        lifetime: int = 600,
        issued: int | None = None,
        **claims: Any,
    ) -> str:
        """An access token as rauthy gives it for ``client_credentials``.

        The defaults pass each check of spec 004. A claim with the value None
        is left out, and ``typ=None`` leaves ``typ`` out of the header.
        """
        alg, key = self.keys[kid]
        now = int(time.time()) if issued is None else issued
        body: dict[str, Any] = {
            "iss": self.issuer,
            "aud": [PROGRAM_ID, AUDIENCE],
            "azp": PROGRAM_ID,
            "scope": "openid comfy",
            "iat": now,
            "nbf": now,
            "exp": now + lifetime,
            "jti": f"jti-{now}-{kid}",
        }
        body.update(claims)
        body = {name: value for name, value in body.items() if value is not None}
        protected: dict[str, Any] = {"alg": alg, "kid": kid}
        if typ is not None:
            protected["typ"] = typ
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SecurityWarning)
            return jwt.encode(protected, body, key, algorithms=[alg])

    def hs256_token(self, secret: bytes, *, kid: str = "rsa-1", **claims: Any) -> str:
        """An HS256 token, as an Authentik provider with no signing key gives it.

        With ``secret=self.public_pem(kid)`` it is the key-confusion attack.
        """
        header = _segment({"alg": "HS256", "kid": kid, "typ": "JWT"})
        signing_input = f"{header}.{_segment(self.claims(**claims))}"
        signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{_b64(signature)}"

    def none_token(self, *, kid: str = "rsa-1", **claims: Any) -> str:
        """A token with ``alg: none`` and no signature."""
        header = _segment({"alg": "none", "kid": kid})
        return f"{header}.{_segment(self.claims(**claims))}."
