from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    RelayHandshakeChallenge,
    RelayTargetState,
    RelayVersionMetadata,
    ShipAgentStatus,
    build_handshake_claims,
    relay_public_key_fingerprint,
)


def test_fingerprint_is_stable_with_trailing_whitespace() -> None:
    public_key_pem = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"

    assert relay_public_key_fingerprint(public_key_pem) == relay_public_key_fingerprint(
        f"\n{public_key_pem}\n  "
    )


def test_shipagent_status_uses_target_agnostic_keys() -> None:
    status = ShipAgentStatus(
        status="ok",
        execution_target=ExecutionTargetStatus(
            state=RelayTargetState.READY,
            execution_target_id="target-123",
            device_id="device-123",
            capabilities=["rate_shipment"],
        ),
    )

    payload = status.model_dump(by_alias=False)

    assert "execution_target" in payload
    assert _contains_desktop_key(payload) is False


def test_protocol_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RelayHandshakeChallenge(
            relay_session_id="session-123",
            nonce="nonce-123",
            unexpected="value",
        )


def test_handshake_claims_validate_against_challenge_and_account() -> None:
    now = datetime.now(UTC)
    version = RelayVersionMetadata(
        shipagent_core_version="1.0.0",
        registry_contract_version="registry-v1",
        ups_boundary_contract_version="ups-v1",
        capabilities=["rate_shipment"],
    )
    challenge = RelayHandshakeChallenge(relay_session_id="session-123", nonce="nonce-123")
    claims = build_handshake_claims(
        device_id="device-123",
        account_id="account-123",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=version,
        now=now,
    )

    claims.validate_for(challenge, account_id="account-123")

    bad_nonce = claims.model_copy(update={"nonce": "wrong"})
    with pytest.raises(ValueError, match="nonce"):
        bad_nonce.validate_for(challenge, account_id="account-123")

    bad_audience = claims.model_copy(update={"audience": "wrong"})
    with pytest.raises(ValueError, match="audience"):
        bad_audience.validate_for(challenge, account_id="account-123")

    bad_account = claims.model_copy(update={"account_id": "wrong"})
    with pytest.raises(ValueError, match="account"):
        bad_account.validate_for(challenge, account_id="account-123")

    expired = claims.model_copy(update={"expires_at": now - timedelta(seconds=1)})
    with pytest.raises(ValueError, match="expired"):
        expired.validate_for(challenge, account_id="account-123")


def test_handshake_claims_reject_relay_session_mismatch() -> None:
    version = RelayVersionMetadata(
        shipagent_core_version="1.0.0",
        registry_contract_version="registry-v1",
        ups_boundary_contract_version="ups-v1",
        capabilities=[],
    )
    challenge = RelayHandshakeChallenge(relay_session_id="session-123", nonce="nonce-123")
    claims = build_handshake_claims(
        device_id="device-123",
        account_id="account-123",
        relay_session_id="wrong-session",
        nonce=challenge.nonce,
        version=version,
    )

    with pytest.raises(ValueError, match="relay_session_id"):
        claims.validate_for(challenge, account_id="account-123")


def _contains_desktop_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any("desktop" in key or _contains_desktop_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_desktop_key(item) for item in value)
    return False
