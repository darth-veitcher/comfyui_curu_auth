"""Hermetic tests of spec 004: the Bearer path accepts OIDC access tokens
(issue #14, ADR-008).

The scenario names come from
``specs/004-oidc-access-tokens/features/oidc_access_tokens.feature``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import pytest

from tests.support.fake_issuer import AUDIENCE, PROGRAM_ID, FakeIssuer


def _config(issuer: FakeIssuer, *, required_scopes: tuple[str, ...] = ()) -> Any:
    from oidc import ResourceServerConfig

    return ResourceServerConfig(
        issuer_url=issuer.issuer, audience=AUDIENCE, required_scopes=required_scopes
    )


async def _check(
    issuer: FakeIssuer,
    token: str,
    *,
    keys: Any = None,
    required_scopes: tuple[str, ...] = (),
) -> dict[str, Any]:
    from oidc import IssuerKeys, verify_access_token

    return await verify_access_token(
        token,
        config=_config(issuer, required_scopes=required_scopes),
        keys=keys or IssuerKeys(issuer.issuer),
    )


def _with_header(token: str, header: dict[str, Any]) -> str:
    _old, _, rest = token.partition(".")
    encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=")
    return f"{encoded.decode()}.{rest}"


# --------------------------------------------------------------------------
# User story 3: the gate refuses a bad token. User story 4: no needless read.
# --------------------------------------------------------------------------


class TestAValidAccessToken:
    """Scenario: A valid access token."""

    @pytest.mark.parametrize("kid", ["rsa-1", "ec-1", "ed-1"])
    async def test_a_rauthy_token_passes(self, kid: str) -> None:
        async with FakeIssuer() as issuer:
            claims = await _check(issuer, issuer.access_token(kid=kid))

        assert claims["azp"] == PROGRAM_ID

    @pytest.mark.parametrize("typ", ["at+jwt", "application/at+jwt", "AT+JWT"])
    async def test_the_rfc_9068_types_pass(self, typ: str) -> None:
        async with FakeIssuer() as issuer:
            await _check(issuer, issuer.access_token(typ=typ))

    async def test_an_authentik_token_passes(self) -> None:
        """typ JWT, aud the client id of the provider, azp and scope."""
        async with FakeIssuer() as issuer:
            token = issuer.access_token(
                typ="JWT", aud=AUDIENCE, azp=AUDIENCE, sub="svc", scope="openid profile"
            )
            await _check(issuer, token)

    async def test_an_okta_token_passes(self) -> None:
        """No typ, cid as the client id, scp as a list."""
        async with FakeIssuer() as issuer:
            token = issuer.access_token(
                typ=None, aud=AUDIENCE, azp=None, scope=None, cid="okta", scp=["comfy"]
            )
            await _check(issuer, token)


class TestTheGateRefusesABadToken:
    """Scenarios: Key confusion; alg none; An ID token; A token of 2 hours; An
    expired token; Another audience; No required scope; No read for a cheap
    refusal."""

    async def _refused(
        self,
        issuer: FakeIssuer,
        token: str,
        *,
        required_scopes: tuple[str, ...] = (),
    ) -> str:
        from oidc import OIDCTokenVerificationError

        with pytest.raises(OIDCTokenVerificationError) as refused:
            await _check(issuer, token, required_scopes=required_scopes)
        reason = refused.value.reason
        for part in token.split("."):
            if part:
                assert part not in reason
        return reason

    async def test_key_confusion_is_refused_with_no_read(self) -> None:
        async with FakeIssuer() as issuer:
            token = issuer.hs256_token(
                issuer.public_pem("rsa-1"), aud=AUDIENCE, azp=PROGRAM_ID, scope="comfy"
            )
            await self._refused(issuer, token)
            reads = issuer.jwks_reads

        assert reads == 0

    async def test_alg_none_is_refused_with_no_read(self) -> None:
        async with FakeIssuer() as issuer:
            token = issuer.none_token(aud=AUDIENCE, azp=PROGRAM_ID, scope="comfy")
            await self._refused(issuer, token)
            reads = issuer.jwks_reads

        assert reads == 0

    @pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c.d", "!!.??.**"])
    async def test_a_bad_shape_is_refused_with_no_read(self, token: str) -> None:
        async with FakeIssuer() as issuer:
            await self._refused(issuer, token)
            reads = issuer.jwks_reads

        assert reads == 0

    async def test_another_issuer_is_refused_with_no_read(self) -> None:
        async with FakeIssuer() as issuer:
            token = issuer.access_token(iss="https://other.example/")
            reason = await self._refused(issuer, token)
            reads = issuer.jwks_reads

        assert reads == 0
        assert reason == "wrong issuer"

    @pytest.mark.parametrize("typ", ["id+jwt", "JOSE", "secevent+jwt"])
    async def test_another_type_is_refused_with_no_read(self, typ: str) -> None:
        async with FakeIssuer() as issuer:
            await self._refused(issuer, issuer.access_token(typ=typ))
            reads = issuer.jwks_reads

        assert reads == 0

    async def test_an_id_token_is_refused(self) -> None:
        """typ JWT, the same aud, but no scope: an ID token."""
        async with FakeIssuer() as issuer:
            token = issuer.access_token(typ="JWT", aud=AUDIENCE, azp=None, scope=None)
            reason = await self._refused(issuer, token)

        assert reason == "ID token or no client id and scope"

    @pytest.mark.parametrize(
        "claims",
        [
            {"azp": None},
            {"scope": None},
            {"azp": None, "client_id": None, "cid": None},
        ],
    )
    async def test_no_typ_needs_a_client_id_and_a_scope(
        self, claims: dict[str, Any]
    ) -> None:
        async with FakeIssuer() as issuer:
            await self._refused(issuer, issuer.access_token(typ=None, **claims))

    async def test_a_token_of_2_hours_is_refused(self) -> None:
        async with FakeIssuer() as issuer:
            reason = await self._refused(issuer, issuer.access_token(lifetime=7200))

        assert reason == "lifetime too long"

    async def test_a_lifetime_of_1_hour_passes(self) -> None:
        async with FakeIssuer() as issuer:
            await _check(issuer, issuer.access_token(lifetime=3600))

    async def test_a_token_that_expired_1_second_ago_is_refused(self) -> None:
        now = int(time.time())
        async with FakeIssuer() as issuer:
            token = issuer.access_token(issued=now - 301, lifetime=300)
            reason = await self._refused(issuer, token)

        assert reason == "expired"

    @pytest.mark.parametrize(
        ("claims", "accepted"),
        [
            ({"iat_offset": 30}, True),
            ({"iat_offset": 90}, False),
            ({"nbf_offset": 90}, False),
        ],
    )
    async def test_iat_and_nbf_have_60_seconds_of_leeway(
        self, claims: dict[str, int], accepted: bool
    ) -> None:
        now = int(time.time())
        async with FakeIssuer() as issuer:
            extra: dict[str, Any] = {}
            if "iat_offset" in claims:
                extra["issued"] = now + claims["iat_offset"]
            if "nbf_offset" in claims:
                extra["nbf"] = now + claims["nbf_offset"]
            token = issuer.access_token(**extra)
            if accepted:
                await _check(issuer, token)
            else:
                await self._refused(issuer, token)

    @pytest.mark.parametrize("claim", ["exp", "iat", "aud", "iss"])
    async def test_a_missing_claim_is_refused(self, claim: str) -> None:
        async with FakeIssuer() as issuer:
            missing: dict[str, Any] = {claim: None}
            await self._refused(issuer, issuer.access_token(**missing))

    @pytest.mark.parametrize("aud", ["http://other.test", [PROGRAM_ID], []])
    async def test_another_audience_is_refused(self, aud: Any) -> None:
        async with FakeIssuer() as issuer:
            reason = await self._refused(issuer, issuer.access_token(aud=aud))

        assert reason in ("wrong audience", "missing claim")

    async def test_an_audience_as_one_string_passes(self) -> None:
        async with FakeIssuer() as issuer:
            await _check(issuer, issuer.access_token(aud=AUDIENCE))

    async def test_a_bad_signature_is_refused(self) -> None:
        async with FakeIssuer() as issuer:
            issuer.add_key("other", "RS256")
            # Signed by "other", but the header names "rsa-1".
            token = _with_header(
                issuer.access_token(kid="other"),
                {"alg": "RS256", "kid": "rsa-1", "typ": "at+jwt"},
            )
            reason = await self._refused(issuer, token)

        assert reason == "bad signature"

    @pytest.mark.parametrize(
        ("claims", "accepted"),
        [
            ({"scope": "openid comfy"}, True),
            ({"scope": "openid"}, False),
            ({"scope": None, "scp": ["comfy", "x"]}, True),
            ({"scope": None, "scp": "comfy x"}, True),
            ({"scope": None, "scp": ["x"]}, False),
        ],
    )
    async def test_each_required_scope_must_be_held(
        self, claims: dict[str, Any], accepted: bool
    ) -> None:
        async with FakeIssuer() as issuer:
            token = issuer.access_token(**claims)
            if accepted:
                await _check(issuer, token, required_scopes=("comfy",))
            else:
                reason = await self._refused(issuer, token, required_scopes=("comfy",))
                assert reason == "missing scope"


class TestTheKeysStayInMemory:
    """Scenarios: One read of the keys; A key rotation; The 60-second limit."""

    async def test_ten_tokens_cause_one_read(self) -> None:
        from oidc import IssuerKeys

        async with FakeIssuer() as issuer:
            keys = IssuerKeys(issuer.issuer)
            for _ in range(10):
                await _check(issuer, issuer.access_token(), keys=keys)
            reads = (issuer.discovery_reads, issuer.jwks_reads)

        assert reads == (1, 1)

    async def test_concurrent_tokens_cause_one_read(self) -> None:
        from oidc import IssuerKeys

        async with FakeIssuer() as issuer:
            keys = IssuerKeys(issuer.issuer)
            await asyncio.gather(
                *(_check(issuer, issuer.access_token(), keys=keys) for _ in range(5))
            )
            reads = issuer.jwks_reads

        assert reads == 1

    async def test_a_key_rotation_reads_the_keys_again(self) -> None:
        from oidc import IssuerKeys

        clock = [1000.0]
        async with FakeIssuer() as issuer:
            keys = IssuerKeys(issuer.issuer, clock=lambda: clock[0])
            await _check(issuer, issuer.access_token(), keys=keys)
            issuer.add_key("rsa-2", "RS256")
            clock[0] += 61
            claims = await _check(issuer, issuer.access_token(kid="rsa-2"), keys=keys)
            reads = issuer.jwks_reads

        assert claims["azp"] == PROGRAM_ID
        assert reads == 2

    async def test_an_unknown_kid_within_60_seconds_causes_no_read(self) -> None:
        from oidc import IssuerKeys, OIDCTokenVerificationError

        clock = [1000.0]
        async with FakeIssuer() as issuer:
            keys = IssuerKeys(issuer.issuer, clock=lambda: clock[0])
            await _check(issuer, issuer.access_token(), keys=keys)
            issuer.add_key("rsa-2", "RS256")
            clock[0] += 59
            with pytest.raises(OIDCTokenVerificationError) as refused:
                await _check(issuer, issuer.access_token(kid="rsa-2"), keys=keys)
            reads_inside = issuer.jwks_reads
            clock[0] += 2
            await _check(issuer, issuer.access_token(kid="rsa-2"), keys=keys)
            reads_after = issuer.jwks_reads

        assert refused.value.reason == "unknown key"
        assert (reads_inside, reads_after) == (1, 2)

    async def test_a_failed_read_also_starts_the_60_seconds(self) -> None:
        from oidc import IssuerKeys, OIDCTokenVerificationError

        clock = [1000.0]
        async with FakeIssuer() as issuer:
            issuer.jwks_override = "not a key set"
            keys = IssuerKeys(issuer.issuer, clock=lambda: clock[0])
            for _ in range(3):
                with pytest.raises(OIDCTokenVerificationError):
                    await _check(issuer, issuer.access_token(), keys=keys)
            reads = issuer.jwks_reads

        assert reads == 1

    async def test_the_discovery_rules_of_spec_003_apply(self) -> None:
        from oidc import IssuerKeys, OIDCTokenVerificationError

        async with FakeIssuer() as issuer:
            issuer.discovery_overrides["jwks_uri"] = "http://idp.example.com/jwks"
            with pytest.raises(OIDCTokenVerificationError) as refused:
                await _check(
                    issuer, issuer.access_token(), keys=IssuerKeys(issuer.issuer)
                )

        assert refused.value.reason == "issuer not available"
