from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field


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
    relay_session_id: str
    nonce: str
    audience: str = "shipagent-cloud-relay"


class RelayHandshakeClaims(RelayProtocolModel):
    device_id: str
    account_id: str
    relay_session_id: str
    nonce: str
    audience: str
    version: RelayVersionMetadata
    issued_at: datetime
    expires_at: datetime

    def validate_for(
        self, challenge: RelayHandshakeChallenge, account_id: str
    ) -> None:
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


class RelaySignedHandshakeClaims(RelayProtocolModel):
    claims: RelayHandshakeClaims
    signature: str


class RelayHeartbeatFrame(RelayProtocolModel):
    type: Literal["heartbeat"]
    relay_session_id: str


class RelayInvocationResultFrame(RelayProtocolModel):
    type: Literal["invocation_result"]
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
    type: Literal["invocation"]
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


def handshake_signature_payload(claims: RelayHandshakeClaims) -> bytes:
    payload = claims.model_dump(mode="json")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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


def verify_handshake_signature(
    signed_claims: RelaySignedHandshakeClaims,
    public_key_pem: str,
) -> None:
    public_key = load_ed25519_public_key(public_key_pem)
    try:
        signature = base64.b64decode(signed_claims.signature, validate=True)
        public_key.verify(
            signature,
            handshake_signature_payload(signed_claims.claims),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("invalid handshake signature") from exc


def build_handshake_claims(
    device_id: str,
    account_id: str,
    relay_session_id: str,
    nonce: str,
    version: RelayVersionMetadata,
    lifetime_seconds: int = 60,
    now: datetime | None = None,
) -> RelayHandshakeClaims:
    issued_at = now or datetime.now(UTC)
    return RelayHandshakeClaims(
        device_id=device_id,
        account_id=account_id,
        relay_session_id=relay_session_id,
        nonce=nonce,
        audience="shipagent-cloud-relay",
        version=version,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=lifetime_seconds),
    )
