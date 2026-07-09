from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from pydantic import ValidationError

import src.control_plane.relay.protocol as relay_protocol
from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    RelayAuthenticatedMessage,
    RelayAuthenticateMessage,
    RelayHandshakeChallenge,
    RelayHandshakeToken,
    RelayHeartbeatFrame,
    RelayInvocationEnvelope,
    RelayInvocationResultFrame,
    RelayTargetState,
    RelayVersionMetadata,
    ShipAgentStatus,
    build_handshake_claims,
    encode_handshake_jwt,
    relay_invocation_input_hash,
    relay_public_key_fingerprint,
    verify_handshake_jwt,
)
from src.services.relay_key_service import RelayKeyService


class InMemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_fingerprint_is_stable_with_trailing_whitespace() -> None:
    public_key_pem = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"

    assert relay_public_key_fingerprint(public_key_pem) == relay_public_key_fingerprint(
        f"\n{public_key_pem}\n  "
    )


def test_shipagent_status_uses_target_agnostic_keys() -> None:
    status = ShipAgentStatus(
        status=RelayTargetState.READY,
        execution_target=ExecutionTargetStatus(
            state=RelayTargetState.READY,
            target_id="target-123",
            capabilities=["rate_shipment"],
        ),
    )

    payload = status.model_dump(mode="json", by_alias=True)

    assert payload == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": "target-123",
            "capabilities": ["rate_shipment"],
            "message": None,
        },
    }
    assert _contains_provider_specific_status_key(payload) is False


def test_protocol_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RelayHandshakeChallenge(
            relay_session_id="session-123",
            nonce="nonce-123",
            unexpected="value",
        )


def test_authenticate_message_uses_canonical_wire_type() -> None:
    handshake = RelayAuthenticateMessage(token="signed.jwt.value")

    assert handshake.model_dump(mode="json") == {
        "type": "relay.authenticate",
        "token": "signed.jwt.value",
    }


def test_invocation_envelopes_round_trip_and_reject_unknown_fields() -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=5)
    arguments = {"service": "ground", "package": {"weight": 2}}
    invocation = RelayInvocationEnvelope(
        type="relay.invoke",
        relay_session_id="relay-session-1",
        sequence=1,
        relay_invocation_id="invocation-1",
        tool_name="get_shipagent_status",
        arguments=arguments,
        input_hash=relay_invocation_input_hash("get_shipagent_status", arguments),
        deadline_at=deadline,
        idempotency_key="idempotency-1",
        audit_correlation_id="corr-1",
    )

    payload = invocation.model_dump(mode="json")

    assert RelayInvocationEnvelope.model_validate(payload) == invocation
    with pytest.raises(ValidationError):
        RelayInvocationEnvelope.model_validate({**payload, "unexpected": "value"})

    assert relay_invocation_input_hash(
        "get_shipagent_status",
        {"package": {"weight": 2}, "service": "ground"},
    ) == relay_invocation_input_hash("get_shipagent_status", arguments)

    result = RelayInvocationResultFrame(
        type="relay.invocation_result",
        relay_session_id="relay-session-1",
        relay_invocation_id="invocation-1",
        status="ok",
        result={"status": "ok"},
    )

    result_payload = result.model_dump(mode="json")

    assert RelayInvocationResultFrame.model_validate(result_payload) == result
    with pytest.raises(ValidationError):
        RelayInvocationResultFrame.model_validate(
            {**result_payload, "credentials": "secret"}
        )


def test_canonical_relay_frames_use_global_wire_types() -> None:
    sent_at = datetime.now(UTC)
    version = RelayVersionMetadata(
        shipagent_core_version="1.0.0",
        registry_contract_version="registry-v1",
        ups_boundary_contract_version="ups-v1",
    )
    challenge = RelayHandshakeChallenge(relay_session_id="session-1", nonce="nonce-1")
    authenticated = RelayAuthenticatedMessage(
        relay_session_id="session-1",
        execution_target_id="relay:device-1",
        state="ready",
    )
    heartbeat = RelayHeartbeatFrame(
        relay_session_id="session-1",
        device_id="device-1",
        version=version,
        active_source_fingerprint=None,
        sent_at=sent_at,
    )
    invocation = RelayInvocationEnvelope(
        type="relay.invoke",
        relay_session_id="session-1",
        sequence=1,
        relay_invocation_id="invocation-1",
        tool_name="get_shipagent_status",
        arguments={},
        input_hash=relay_invocation_input_hash("get_shipagent_status", {}),
        deadline_at=sent_at + timedelta(seconds=5),
        idempotency_key="idempotency-1",
        audit_correlation_id="corr-1",
    )
    result = RelayInvocationResultFrame(
        type="relay.invocation_result",
        relay_session_id="session-1",
        relay_invocation_id="invocation-1",
        status="ok",
    )

    assert [
        challenge.type,
        authenticated.type,
        heartbeat.type,
        invocation.type,
        result.type,
    ] == [
        "relay.challenge",
        "relay.authenticated",
        "relay.heartbeat",
        "relay.invoke",
        "relay.invocation_result",
    ]


def test_handshake_claims_validate_against_challenge_and_account() -> None:
    now = datetime.now(UTC)
    version = RelayVersionMetadata(
        shipagent_core_version="1.0.0",
        registry_contract_version="registry-v1",
        ups_boundary_contract_version="ups-v1",
        capabilities=["rate_shipment"],
    )
    challenge = RelayHandshakeChallenge(
        relay_session_id="session-123", nonce="nonce-123"
    )
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
    challenge = RelayHandshakeChallenge(
        relay_session_id="session-123", nonce="nonce-123"
    )
    claims = build_handshake_claims(
        device_id="device-123",
        account_id="account-123",
        relay_session_id="wrong-session",
        nonce=challenge.nonce,
        version=version,
    )

    with pytest.raises(ValueError, match="relay_session_id"):
        claims.validate_for(challenge, account_id="account-123")


def test_handshake_jwt_round_trips_claims_with_eddsa() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="session-123",
        nonce="nonce-123",
    )
    claims = build_handshake_claims(
        device_id="device-123",
        account_id="account-123",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=RelayVersionMetadata(
            shipagent_core_version="1.0.0",
            registry_contract_version="registry-v1",
            ups_boundary_contract_version="ups-v1",
            capabilities=["rate_shipment"],
        ),
        now=datetime.now(UTC),
    )

    token = service.sign_handshake_jwt(claims)

    assert isinstance(token, RelayHandshakeToken)
    assert set(token.model_dump(mode="json")) == {"type", "token"}
    assert verify_handshake_jwt(token, keypair.public_key_pem) == claims


def test_handshake_jwt_rejects_wrong_key_audience_expiry_and_malformed_token() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()
    other_keypair = RelayKeyService(InMemoryStore()).generate_or_load_keypair()
    claims = build_handshake_claims(
        device_id="device-123",
        account_id="account-123",
        relay_session_id="session-123",
        nonce="nonce-123",
        version=RelayVersionMetadata(
            shipagent_core_version="1.0.0",
            registry_contract_version="registry-v1",
            ups_boundary_contract_version="ups-v1",
        ),
    )

    token = service.sign_handshake_jwt(claims)

    with pytest.raises(ValueError, match="handshake token"):
        verify_handshake_jwt(token, other_keypair.public_key_pem)
    with pytest.raises(ValueError, match="handshake token"):
        verify_handshake_jwt(
            RelayHandshakeToken(token="not-a-jwt"),
            keypair.public_key_pem,
        )

    wrong_audience = service.sign_handshake_jwt(
        claims.model_copy(update={"audience": "wrong-audience"})
    )
    with pytest.raises(ValueError, match="handshake token"):
        verify_handshake_jwt(wrong_audience, keypair.public_key_pem)

    now = datetime.now(UTC) - timedelta(seconds=120)
    expired = service.sign_handshake_jwt(
        build_handshake_claims(
            device_id="device-123",
            account_id="account-123",
            relay_session_id="session-123",
            nonce="nonce-123",
            version=claims.version,
            lifetime_seconds=1,
            now=now,
        )
    )
    with pytest.raises(ValueError, match="handshake token"):
        verify_handshake_jwt(expired, keypair.public_key_pem)


def test_handshake_jwt_rejects_lifetime_longer_than_sixty_seconds() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()
    now = datetime.now(UTC).replace(microsecond=0)
    token = encode_handshake_jwt(
        build_handshake_claims(
            device_id="device-1",
            account_id="acct-1",
            relay_session_id="session-1",
            nonce="nonce-1",
            version=RelayVersionMetadata(
                shipagent_core_version="1.0.0",
                registry_contract_version="registry-v1",
                ups_boundary_contract_version="ups-v1",
            ),
            lifetime_seconds=61,
            now=now,
        ),
        keypair.private_key_pem,
    )

    with pytest.raises(ValueError, match="lifetime"):
        verify_handshake_jwt(token, keypair.public_key_pem)


def test_handshake_jwt_rejects_future_issued_at_time() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()
    token = service.sign_handshake_jwt(
        build_handshake_claims(
            device_id="device-1",
            account_id="acct-1",
            relay_session_id="session-1",
            nonce="nonce-1",
            version=RelayVersionMetadata(
                shipagent_core_version="1.0.0",
                registry_contract_version="registry-v1",
                ups_boundary_contract_version="ups-v1",
            ),
            now=datetime.now(UTC) + timedelta(seconds=61),
        )
    )

    with pytest.raises(ValueError, match="handshake token"):
        verify_handshake_jwt(token, keypair.public_key_pem)


def test_handshake_jwt_rejects_fractional_future_issued_at_time(
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    issued_at = now + timedelta(seconds=0.5)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None) -> datetime:
            return now if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(relay_protocol, "datetime", FrozenDateTime)
    monkeypatch.setattr(jwt.api_jwt, "datetime", FrozenDateTime)
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()
    version = RelayVersionMetadata(
        shipagent_core_version="1.0.0",
        registry_contract_version="registry-v1",
        ups_boundary_contract_version="ups-v1",
    )
    token = RelayAuthenticateMessage(
        token=jwt.encode(
            {
                "sub": "device-1",
                "account_id": "acct-1",
                "relay_session_id": "session-1",
                "nonce": "nonce-1",
                "aud": "shipagent-cloud-relay",
                "version": version.model_dump(mode="json"),
                "iat": issued_at.timestamp(),
                "exp": (issued_at + timedelta(seconds=60)).timestamp(),
            },
            keypair.private_key_pem,
            algorithm="EdDSA",
        )
    )

    with pytest.raises(ValueError, match="issued_at"):
        verify_handshake_jwt(token, keypair.public_key_pem)


def _contains_provider_specific_status_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"device_id", "execution_target_id"}
            or _contains_provider_specific_status_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_provider_specific_status_key(item) for item in value)
    return False
