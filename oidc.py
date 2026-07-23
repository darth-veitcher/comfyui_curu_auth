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


__all__ = ["OIDCConfig", "resolve_oidc_config"]
