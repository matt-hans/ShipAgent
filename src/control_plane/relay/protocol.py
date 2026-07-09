from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

HANDSHAKE_AUDIENCE = "shipagent-cloud-relay"
MAX_RELAY_HANDSHAKE_LIFETIME_SECONDS = 60


class RelayProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RelayTargetState(StrEnum):
    READY = "ready"
    OFFLINE = "offline"
    UPDATE_REQUIRED = "update_required"


class RelayVersionMetadata(RelayProtocolModel):
    shipagent_core_version: str
    registry_contract_version: str
    ups_boundary_contract_version: str
    capabilities: list[str] = Field(default_factory=list)


class RelayHandshakeChallenge(RelayProtocolModel):
    type: Literal["relay.challenge"] = "relay.challenge"
    relay_session_id: str
    nonce: str
    audience: str = HANDSHAKE_AUDIENCE


class RelayHandshakeClaims(RelayProtocolModel):
    device_id: str
    account_id: str
    relay_session_id: str
    nonce: str
    audience: str
    version: RelayVersionMetadata
    issued_at: datetime
    expires_at: datetime

    def validate_for(self, challenge: RelayHandshakeChallenge, account_id: str) -> None:
        if self.audience != challenge.audience:
            raise ValueError("wrong audience")
        if self.relay_session_id != challenge.relay_session_id:
            raise ValueError("wrong relay_session_id")
        if self.nonce != challenge.nonce:
            raise ValueError("wrong nonce")
        if self.account_id != account_id:
            raise ValueError("wrong account")
        now = datetime.now(UTC)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            raise ValueError("expired")


class RelayAuthenticateMessage(RelayProtocolModel):
    type: Literal["relay.authenticate"] = "relay.authenticate"
    token: str


RelayHandshakeToken = RelayAuthenticateMessage


class RelayAuthenticatedMessage(RelayProtocolModel):
    type: Literal["relay.authenticated"] = "relay.authenticated"
    relay_session_id: str
    execution_target_id: str
    state: RelayTargetState


class RelayHeartbeatFrame(RelayProtocolModel):
    type: Literal["relay.heartbeat"] = "relay.heartbeat"
    relay_session_id: str
    device_id: str
    version: RelayVersionMetadata
    active_source_fingerprint: str | None = None
    sent_at: datetime


class RelayInvocationResultFrame(RelayProtocolModel):
    type: Literal["relay.invocation_result"] = "relay.invocation_result"
    relay_session_id: str
    relay_invocation_id: str
    status: Literal["ok", "error"]
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None


class RelayHeartbeat(RelayProtocolModel):
    account_id: str
    device_id: str
    relay_session_id: str
    execution_target_id: str
    state: RelayTargetState
    version: RelayVersionMetadata
    active_source_fingerprint: str | None = None


class RelayInvocationEnvelope(RelayProtocolModel):
    type: Literal["relay.invoke"] = "relay.invoke"
    relay_session_id: str
    sequence: int = Field(ge=1)
    relay_invocation_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    input_hash: str
    deadline_at: datetime
    idempotency_key: str
    audit_correlation_id: str


class RelayInvocationResult(RelayProtocolModel):
    relay_invocation_id: str
    status: str
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None


class ExecutionTargetStatus(RelayProtocolModel):
    state: RelayTargetState
    target_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    message: str | None = None


class ShipAgentStatus(RelayProtocolModel):
    status: RelayTargetState
    execution_target: ExecutionTargetStatus = Field(alias="executionTarget")


def relay_public_key_fingerprint(public_key_pem: str) -> str:
    normalized = public_key_pem.strip().replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def relay_invocation_input_hash(
    tool_name: str,
    arguments: dict[str, object],
) -> str:
    payload = {"arguments": arguments, "tool_name": tool_name}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def load_ed25519_public_key(public_key_pem: str) -> Ed25519PublicKey:
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except ValueError as exc:
        raise ValueError("relay public key is not an Ed25519 public key") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("relay public key is not an Ed25519 public key")
    return public_key


def encode_handshake_jwt(
    claims: RelayHandshakeClaims,
    private_key_pem: str,
) -> RelayAuthenticateMessage:
    try:
        token = jwt.encode(
            _handshake_jwt_payload(claims),
            private_key_pem,
            algorithm="EdDSA",
            headers={"typ": "JWT"},
        )
    except jwt.PyJWTError as exc:
        raise ValueError("invalid handshake token") from exc
    return RelayAuthenticateMessage(token=token)


def decode_handshake_jwt_unverified(
    handshake: RelayAuthenticateMessage,
) -> RelayHandshakeClaims:
    try:
        payload = jwt.decode(
            handshake.token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        return _handshake_claims_from_jwt_payload(payload)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid handshake token") from exc


def verify_handshake_jwt(
    handshake: RelayAuthenticateMessage,
    public_key_pem: str,
) -> RelayHandshakeClaims:
    load_ed25519_public_key(public_key_pem)
    try:
        payload = jwt.decode(
            handshake.token,
            public_key_pem,
            algorithms=["EdDSA"],
            audience=HANDSHAKE_AUDIENCE,
            options={
                "require": ["aud", "exp", "iat", "sub"],
                "verify_exp": True,
                "verify_iat": True,
            },
        )
        claims = _handshake_claims_from_jwt_payload(payload)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid handshake token") from exc
    _validate_handshake_lifetime(claims)
    return claims


def _validate_handshake_lifetime(claims: RelayHandshakeClaims) -> None:
    issued_at = claims.issued_at
    expires_at = claims.expires_at
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        expires_at <= issued_at
        or (expires_at - issued_at).total_seconds()
        > MAX_RELAY_HANDSHAKE_LIFETIME_SECONDS
    ):
        raise ValueError("invalid handshake lifetime")


def _handshake_jwt_payload(claims: RelayHandshakeClaims) -> dict[str, object]:
    issued_at = claims.issued_at
    expires_at = claims.expires_at
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return {
        "sub": claims.device_id,
        "account_id": claims.account_id,
        "relay_session_id": claims.relay_session_id,
        "nonce": claims.nonce,
        "aud": claims.audience,
        "version": claims.version.model_dump(mode="json"),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }


def _handshake_claims_from_jwt_payload(
    payload: dict[str, object],
) -> RelayHandshakeClaims:
    audience = payload["aud"]
    if isinstance(audience, list):
        if len(audience) != 1:
            raise ValueError("wrong audience")
        audience = audience[0]
    if not isinstance(audience, str):
        raise ValueError("wrong audience")
    version = payload["version"]
    if not isinstance(version, dict):
        raise ValueError("invalid version")
    return RelayHandshakeClaims(
        device_id=_required_string(payload, "sub"),
        account_id=_required_string(payload, "account_id"),
        relay_session_id=_required_string(payload, "relay_session_id"),
        nonce=_required_string(payload, "nonce"),
        audience=audience,
        version=RelayVersionMetadata.model_validate(version),
        issued_at=_datetime_from_jwt_time(payload["iat"]),
        expires_at=_datetime_from_jwt_time(payload["exp"]),
    )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid {key}")
    return value


def _datetime_from_jwt_time(value: object) -> datetime:
    if not isinstance(value, int | float):
        raise ValueError("invalid jwt timestamp")
    return datetime.fromtimestamp(value, tz=UTC)


def build_handshake_claims(
    device_id: str,
    account_id: str,
    relay_session_id: str,
    nonce: str,
    version: RelayVersionMetadata,
    lifetime_seconds: int = 60,
    now: datetime | None = None,
) -> RelayHandshakeClaims:
    issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
    return RelayHandshakeClaims(
        device_id=device_id,
        account_id=account_id,
        relay_session_id=relay_session_id,
        nonce=nonce,
        audience=HANDSHAKE_AUDIENCE,
        version=version,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=lifetime_seconds),
    )
