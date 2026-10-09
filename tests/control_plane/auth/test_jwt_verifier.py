import time
from datetime import UTC, datetime
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.control_plane.auth.jwt_verifier import Auth0TokenVerifier


def test_claim_validation_requires_issuer_audience_subject_client_and_scope():
    verifier = Auth0TokenVerifier(
        issuer="https://tenant.us.auth0.com/",
        audience="https://dev-mcp.shipagent.app",
        jwks_client=None,
    )
    claims = {
        "iat": time.time() - 1,
        "exp": time.time() + 60,
        "iss": "https://tenant.us.auth0.com/",
        "aud": "https://dev-mcp.shipagent.app",
        "sub": "auth0|owner-1",
        "azp": "chatgpt-client",
        "scope": "shipments:preview jobs:read",
    }
    principal = verifier.validate_claims(claims)
    assert principal.client_id == "chatgpt-client"
    assert principal.scopes == frozenset({"shipments:preview", "jobs:read"})
    assert principal.auth_time is None


def test_claim_validation_parses_numeric_auth_time():
    verifier = Auth0TokenVerifier(
        issuer="https://tenant.us.auth0.com/",
        audience="https://dev-mcp.shipagent.app",
        jwks_client=None,
    )
    claims = {
        "iat": time.time() - 1,
        "exp": time.time() + 60,
        "iss": "https://tenant.us.auth0.com/",
        "aud": "https://dev-mcp.shipagent.app",
        "sub": "auth0|owner-1",
        "azp": "chatgpt-client",
        "auth_time": 1_714_050_000,
    }

    principal = verifier.validate_claims(claims)

    assert principal.auth_time == datetime.fromtimestamp(1_714_050_000, tz=UTC)


def test_claim_validation_ignores_bool_auth_time():
    verifier = Auth0TokenVerifier(
        issuer="https://tenant.us.auth0.com/",
        audience="https://dev-mcp.shipagent.app",
        jwks_client=None,
    )
    claims = {
        "iat": time.time() - 1,
        "exp": time.time() + 60,
        "iss": "https://tenant.us.auth0.com/",
        "aud": "https://dev-mcp.shipagent.app",
        "sub": "auth0|owner-1",
        "azp": "chatgpt-client",
        "auth_time": True,
    }

    principal = verifier.validate_claims(claims)

    assert principal.auth_time is None


@pytest.mark.parametrize("field", ["iss", "aud", "sub", "azp"])
def test_missing_or_wrong_required_claim_fails(field):
    claims = {
        "iat": time.time() - 1,
        "exp": time.time() + 60,
        "iss": "https://tenant.us.auth0.com/",
        "aud": "https://dev-mcp.shipagent.app",
        "sub": "auth0|owner-1",
        "azp": "chatgpt-client",
        "scope": "jobs:read",
    }
    claims.pop(field)
    verifier = Auth0TokenVerifier(
        issuer="https://tenant.us.auth0.com/",
        audience="https://dev-mcp.shipagent.app",
        jwks_client=None,
    )
    with pytest.raises(PermissionError):
        verifier.validate_claims(claims)


LINK_CLAIM = "https://synthetic.shipagent.invalid/provider_link"


@pytest.fixture(scope="module")
def signed_verifier():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())

    verifier = Auth0TokenVerifier(
        "https://tenant.us.auth0.com/",
        "https://dev-mcp.shipagent.app",
        Keys(),
        provider_link_claim=LINK_CLAIM,
    )

    def encode(**changes):
        claims = {
            "iss": verifier.issuer,
            "aud": verifier.audience,
            "sub": "auth0|strict-owner",
            "azp": "chatgpt-client",
            "iat": time.time() - 1,
            "exp": time.time() + 60,
            LINK_CLAIM: "grant_A-1",
            "scope": "shipagent.status shipagent.preview",
        }
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="RS256")

    return verifier, encode


def test_signed_link_preserves_verified_identity_and_fractional_expiry(signed_verifier):
    verifier, encode = signed_verifier
    expiry = int(time.time()) + 60.125
    principal = verifier.verify(encode(exp=expiry))
    assert principal.issuer == verifier.issuer
    assert principal.issuer_link_id == "grant_A-1"
    assert principal.expires_at == expiry
    assert type(principal.issued_at) is float


@pytest.mark.parametrize("field", ["iat", "exp"])
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "1700000000",
        None,
        float("nan"),
        float("inf"),
        float("-inf"),
        1e100,
        -1e100,
    ],
)
def test_signed_timestamp_requires_finite_number(signed_verifier, field, value):
    verifier, encode = signed_verifier
    with pytest.raises(PermissionError):
        verifier.verify(encode(**{field: value}))


@pytest.mark.parametrize(
    "changes",
    [
        {"iat": time.time() + 60},
        {"exp": time.time() - 1},
        {"iat": time.time() - 1, "exp": time.time() - 2},
    ],
)
def test_signed_timestamp_denies_invalid_lifetime(signed_verifier, changes):
    verifier, encode = signed_verifier
    with pytest.raises(PermissionError):
        verifier.verify(encode(**changes))


@pytest.mark.parametrize(
    "link", [None, "", "../path", "https://x.invalid", "é", "a" * 129, 1, True]
)
def test_configured_link_claim_has_no_fallback(signed_verifier, link):
    verifier, encode = signed_verifier
    with pytest.raises(PermissionError):
        verifier.verify(
            encode(**{LINK_CLAIM: link, "jti": "fallback", "sid": "fallback"})
        )


@pytest.mark.parametrize(
    "claim",
    [
        "link",
        "http://x.invalid/link",
        "https://u:p@x.invalid/link",
        "https://x.invalid/link?q=1",
        "https://x.invalid/link#x",
        "https://x.invalid/\\bad",
        "https://x.invalid/" + "x" * 513,
    ],
)
def test_claim_configuration_is_a_closed_https_namespace(claim):
    from src.control_plane.config import ControlPlaneSettings

    with pytest.raises(ValueError):
        Auth0TokenVerifier(
            "https://tenant.us.auth0.com/", "aud", provider_link_claim=claim
        )
    with pytest.raises(ValueError):
        ControlPlaneSettings(auth0_provider_link_claim=claim)


def test_signed_fractional_expiry_is_not_rounded_up_or_down(
    signed_verifier, monkeypatch
):
    verifier, encode = signed_verifier
    monkeypatch.setattr(
        "src.control_plane.auth.jwt_verifier.time.time", lambda: 1700000000.49
    )
    token = encode(iat=1699999999.0, exp=1700000000.5)
    assert verifier.verify(token).expires_at == 1700000000.5
    monkeypatch.setattr(
        "src.control_plane.auth.jwt_verifier.time.time", lambda: 1700000000.5
    )
    with pytest.raises(PermissionError):
        verifier.verify(token)
