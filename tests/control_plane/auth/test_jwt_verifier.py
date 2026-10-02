from datetime import UTC, datetime

import pytest

from src.control_plane.auth.jwt_verifier import Auth0TokenVerifier


def test_claim_validation_requires_issuer_audience_subject_client_and_scope():
    verifier = Auth0TokenVerifier(
        issuer="https://tenant.us.auth0.com/",
        audience="https://dev-mcp.shipagent.app",
        jwks_client=None,
    )
    claims = {
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
