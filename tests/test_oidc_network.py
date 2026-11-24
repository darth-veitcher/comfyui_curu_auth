"""Hermetic tests of how the gate reaches the identity provider.

A host can run ComfyUI where its DNS does not know the name of the issuer, or
where the issuer has a certificate of a private CA, for example a Caddy local
CA. ``COMFYUI_CURU_AUTH_OIDC_RESOLVE`` gives the address of a host name, and
``COMFYUI_CURU_AUTH_OIDC_CA_FILE`` gives more CA certificates to trust. Both
apply only to the requests of the gate to the identity provider, not to the
rest of ComfyUI. The name in the URL stays the name that TLS checks.

Each test runs a TLS issuer on a loopback port, with a certificate for the
name ``idp.test``, signed by a CA of the test.
"""

from __future__ import annotations

import datetime
import ssl
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

ISSUER_HOST = "idp.test"


# --------------------------------------------------------------------------
# A CA, a certificate for idp.test, and a TLS issuer.
# --------------------------------------------------------------------------


def _write_ca_and_certificate(directory: Path) -> tuple[Path, Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ISSUER_HOST)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(ISSUER_HOST)]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = directory / "ca.pem"
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


class _TlsServer(TestServer):
    """A ``TestServer`` on TLS. See ``_TlsTestServer`` in ``test_gate.py``."""

    def __init__(self, app: web.Application, *, context: ssl.SSLContext) -> None:
        super().__init__(app, host="127.0.0.1")
        self._context = context

    async def start_server(self, loop=None, **kwargs) -> None:
        await super().start_server(loop=loop, ssl=self._context, **kwargs)


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ssl.SSLContext]:
    ca_path, cert_path, key_path = _write_ca_and_certificate(
        tmp_path_factory.mktemp("pki")
    )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_path, key_path)
    return ca_path, context


@pytest.fixture
async def issuer(pki: tuple[Path, ssl.SSLContext]) -> Any:
    """A TLS server that serves a discovery document for
    ``https://idp.test:<port>/``. It yields that issuer URL."""

    _, context = pki
    state: dict[str, str] = {}

    async def discovery(_: web.Request) -> web.Response:
        base = state["issuer"]
        return web.json_response(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}authorize",
                "token_endpoint": f"{base}token",
                "jwks_uri": f"{base}jwks",
            }
        )

    app = web.Application()
    app.router.add_get("/.well-known/openid-configuration", discovery)
    server = _TlsServer(app, context=context)
    await server.start_server()
    state["issuer"] = f"https://{ISSUER_HOST}:{server.port}/"
    try:
        yield state["issuer"]
    finally:
        await server.close()


@pytest.fixture(autouse=True)
def _default_network() -> Iterator[None]:
    """Each test starts, and ends, with the default network."""

    from oidc import OIDCNetwork, use_oidc_network

    use_oidc_network(OIDCNetwork())
    yield
    use_oidc_network(OIDCNetwork())


# --------------------------------------------------------------------------
# The settings.
# --------------------------------------------------------------------------


class TestTheSettings:
    def test_no_setting_gives_the_default_network(self) -> None:
        from oidc import OIDCNetwork, resolve_oidc_network

        assert resolve_oidc_network(resolve=None, ca_file=None) == OIDCNetwork()
        assert resolve_oidc_network(resolve="", ca_file="") == OIDCNetwork()

    @pytest.mark.parametrize("separator", [",", ", ", " "])
    def test_resolve_takes_a_list_of_host_and_address(self, separator: str) -> None:
        from oidc import resolve_oidc_network

        network = resolve_oidc_network(
            resolve=f"IdP.Test=192.168.1.117{separator}other.test=::1", ca_file=None
        )

        assert network.addresses == (
            ("idp.test", "192.168.1.117"),
            ("other.test", "::1"),
        )

    @pytest.mark.parametrize(
        "entry",
        ["idp.test", "idp.test=", "=192.168.1.117", "idp.test=not-an-address"],
    )
    def test_a_bad_resolve_entry_is_a_setup_error(self, entry: str) -> None:
        from oidc import OIDCConfigError, resolve_oidc_network

        with pytest.raises(OIDCConfigError, match="COMFYUI_CURU_AUTH_OIDC_RESOLVE"):
            resolve_oidc_network(resolve=entry, ca_file=None)

    def test_a_ca_file_that_cannot_be_read_is_a_setup_error(
        self, tmp_path: Path
    ) -> None:
        from oidc import OIDCConfigError, resolve_oidc_network

        with pytest.raises(OIDCConfigError, match="COMFYUI_CURU_AUTH_OIDC_CA_FILE"):
            resolve_oidc_network(resolve=None, ca_file=str(tmp_path / "missing.pem"))

    def test_a_ca_file_with_no_certificate_is_a_setup_error(
        self, tmp_path: Path
    ) -> None:
        from oidc import OIDCConfigError, resolve_oidc_network

        empty = tmp_path / "empty.pem"
        empty.write_text("not a certificate\n")
        with pytest.raises(OIDCConfigError, match="COMFYUI_CURU_AUTH_OIDC_CA_FILE"):
            resolve_oidc_network(resolve=None, ca_file=str(empty))


# --------------------------------------------------------------------------
# The requests to the identity provider.
# --------------------------------------------------------------------------


class TestTheGateReachesTheIssuer:
    async def test_without_the_settings_the_name_does_not_resolve(
        self, issuer: str
    ) -> None:
        from oidc import OIDCDiscoveryError, fetch_discovery_document

        with pytest.raises(OIDCDiscoveryError):
            await fetch_discovery_document(issuer, timeout=5)

    async def test_resolve_and_ca_file_reach_the_issuer_by_its_name(
        self, issuer: str, pki: tuple[Path, ssl.SSLContext]
    ) -> None:
        from oidc import (
            fetch_discovery_document,
            resolve_oidc_network,
            use_oidc_network,
        )

        ca_path, _ = pki
        use_oidc_network(
            resolve_oidc_network(
                resolve=f"{ISSUER_HOST}=127.0.0.1", ca_file=str(ca_path)
            )
        )

        document = await fetch_discovery_document(issuer, timeout=5)

        assert document["issuer"] == issuer

    async def test_resolve_without_the_ca_still_checks_the_certificate(
        self, issuer: str
    ) -> None:
        from oidc import (
            OIDCDiscoveryError,
            fetch_discovery_document,
            resolve_oidc_network,
            use_oidc_network,
        )

        use_oidc_network(
            resolve_oidc_network(resolve=f"{ISSUER_HOST}=127.0.0.1", ca_file=None)
        )

        with pytest.raises(OIDCDiscoveryError):
            await fetch_discovery_document(issuer, timeout=5)

    async def test_tls_checks_the_name_of_the_url_not_the_address(
        self, issuer: str, pki: tuple[Path, ssl.SSLContext]
    ) -> None:
        """The certificate is for idp.test only. A request to the address
        itself must fail, so the pass above proves that TLS checked the
        name."""

        from oidc import (
            OIDCDiscoveryError,
            fetch_discovery_document,
            resolve_oidc_network,
            use_oidc_network,
        )

        ca_path, _ = pki
        use_oidc_network(resolve_oidc_network(resolve=None, ca_file=str(ca_path)))
        port = issuer.rsplit(":", 1)[1].rstrip("/")

        with pytest.raises(OIDCDiscoveryError):
            await fetch_discovery_document(f"https://127.0.0.1:{port}/", timeout=5)


# --------------------------------------------------------------------------
# The wiring in __init__.py.
# --------------------------------------------------------------------------


def _load(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> Any:
    from tests.test_oidc import _load_init_with_fake_server

    for name in ("COMFYUI_CURU_AUTH_OIDC_RESOLVE", "COMFYUI_CURU_AUTH_OIDC_CA_FILE"):
        monkeypatch.delenv(name, raising=False)
    app = _load_init_with_fake_server(monkeypatch, oidc_env=env)
    return app, sys.modules["_comfyui_curu_auth_under_test.oidc"]


class TestInitPyReadsTheSettings:
    def test_the_settings_reach_the_requests_of_the_gate(
        self, monkeypatch: pytest.MonkeyPatch, pki: tuple[Path, ssl.SSLContext]
    ) -> None:
        ca_path, _ = pki
        _, module = _load(
            monkeypatch,
            {
                "COMFYUI_CURU_AUTH_OIDC_RESOLVE": f"{ISSUER_HOST}=127.0.0.1",
                "COMFYUI_CURU_AUTH_OIDC_CA_FILE": str(ca_path),
            },
        )

        assert module.current_oidc_network().addresses == ((ISSUER_HOST, "127.0.0.1"),)
        assert module.current_oidc_network().ca_file == str(ca_path)

    def test_a_bad_setting_keeps_the_gate_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app, module = _load(
            monkeypatch, {"COMFYUI_CURU_AUTH_OIDC_RESOLVE": "idp.test=nowhere"}
        )

        assert len(app.middlewares) == 1
        assert module.current_oidc_network() == module.OIDCNetwork()
