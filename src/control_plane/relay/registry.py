from __future__ import annotations

import re
import uuid
from typing import Protocol

from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayHandshakeChallenge,
    RelayHeartbeat,
    RelayProtocolModel,
    RelaySignedHandshakeClaims,
    RelayTargetState,
    RelayVersionMetadata,
    load_ed25519_public_key,
    relay_public_key_fingerprint,
    verify_handshake_signature,
)

_PRIVATE_KEY_PEM_HEADER = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----",
    re.IGNORECASE,
)


def reject_private_key_pem(public_key_pem: str) -> None:
    if _PRIVATE_KEY_PEM_HEADER.search(public_key_pem):
        raise ValueError("private key material is not allowed")


def validate_relay_public_key(public_key_pem: str) -> None:
    reject_private_key_pem(public_key_pem)
    load_ed25519_public_key(public_key_pem)


class RedisLike(Protocol):
    async def get(self, key: str): ...

    async def set(self, key: str, value: str, ex: int | None = None): ...

    async def delete(self, *keys: str): ...

    async def expire(self, key: str, seconds: int): ...


class RelayDevice(RelayProtocolModel):
    account_id: str
    device_id: str
    device_name: str
    public_key_pem: str
    fingerprint: str
    revoked: bool = False


class RelaySession(RelayProtocolModel):
    account_id: str
    device_id: str
    relay_session_id: str
    execution_target_id: str
    state: RelayTargetState
    version: RelayVersionMetadata


class RelayChallengeBinding(RelayProtocolModel):
    account_id: str
    device_id: str
    challenge: RelayHandshakeChallenge


class RelayDeviceRegistry:
    def __init__(self, redis_client: RedisLike) -> None:
        self._redis = redis_client

    async def register_device(
        self,
        account_id: str,
        device_name: str,
        public_key_pem: str,
        fingerprint: str | None = None,
    ) -> RelayDevice:
        validate_relay_public_key(public_key_pem)
        device = RelayDevice(
            account_id=account_id,
            device_id=f"relay_device_{uuid.uuid4().hex}",
            device_name=device_name,
            public_key_pem=public_key_pem,
            fingerprint=relay_public_key_fingerprint(public_key_pem),
            revoked=False,
        )
        await self._store_device(device)
        return device

    async def get_device(self, account_id: str, device_id: str) -> RelayDevice | None:
        payload = await self._redis.get(RedisKey.relay_device(account_id, device_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return RelayDevice.model_validate_json(payload)

    async def rotate_key(
        self,
        account_id: str,
        device_id: str,
        public_key_pem: str,
        fingerprint: str | None = None,
    ) -> RelayDevice:
        validate_relay_public_key(public_key_pem)
        device = await self.get_device(account_id, device_id)
        if device is None:
            raise ValueError("device not found")
        rotated = device.model_copy(
            update={
                "public_key_pem": public_key_pem,
                "fingerprint": relay_public_key_fingerprint(public_key_pem),
            }
        )
        await self._store_device(rotated)
        return rotated

    async def revoke_device(self, account_id: str, device_id: str) -> RelayDevice:
        device = await self.get_device(account_id, device_id)
        if device is None:
            raise ValueError("device not found")
        revoked = device.model_copy(update={"revoked": True})
        await self._store_device(revoked)
        await self._redis.delete(
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
        )
        return revoked

    async def create_challenge(
        self, account_id: str, device_id: str
    ) -> RelayHandshakeChallenge:
        device = await self.get_device(account_id, device_id)
        if device is None:
            raise ValueError("device not found")
        if device.revoked:
            raise ValueError("device revoked")
        challenge = RelayHandshakeChallenge(
            relay_session_id=f"relay_session_{uuid.uuid4().hex}",
            nonce=f"nonce_{uuid.uuid4().hex}",
        )
        binding = RelayChallengeBinding(
            account_id=account_id,
            device_id=device_id,
            challenge=challenge,
        )
        await self._redis.set(
            RedisKey.relay_challenge(challenge.relay_session_id),
            binding.model_dump_json(),
            ex=RedisTtl.REPLAY_NONCE_SECONDS,
        )
        return challenge

    async def accept_handshake(
        self,
        signed_claims: RelaySignedHandshakeClaims,
    ) -> RelaySession:
        if not isinstance(signed_claims, RelaySignedHandshakeClaims):
            raise ValueError("signed handshake claims required")
        claims = signed_claims.claims
        binding = await self._get_challenge_binding(claims.relay_session_id)
        claims.validate_for(binding.challenge, account_id=binding.account_id)
        if claims.device_id != binding.device_id:
            raise ValueError("wrong device")
        device = await self.get_device(binding.account_id, binding.device_id)
        if device is None:
            raise ValueError("device not found")
        if device.revoked:
            raise ValueError("device revoked")
        verify_handshake_signature(signed_claims, device.public_key_pem)
        session = RelaySession(
            account_id=binding.account_id,
            device_id=binding.device_id,
            relay_session_id=claims.relay_session_id,
            execution_target_id=f"relay:{binding.device_id}",
            state=RelayTargetState.READY,
            version=claims.version,
        )
        heartbeat = RelayHeartbeat(
            account_id=session.account_id,
            device_id=session.device_id,
            relay_session_id=session.relay_session_id,
            execution_target_id=session.execution_target_id,
            state=session.state,
            version=session.version,
            active_source_fingerprint=device.fingerprint,
        )
        await self._redis.set(
            RedisKey.relay_session(session.device_id),
            session.model_dump_json(),
            ex=RedisTtl.RELAY_SESSION_SECONDS,
        )
        await self._redis.set(
            RedisKey.relay_heartbeat(session.device_id),
            heartbeat.model_dump_json(),
            ex=RedisTtl.RELAY_SESSION_SECONDS,
        )
        return session

    async def _get_challenge_binding(
        self, relay_session_id: str
    ) -> RelayChallengeBinding:
        key = RedisKey.relay_challenge(relay_session_id)
        getdel = getattr(self._redis, "getdel", None)
        if getdel is not None:
            payload = await getdel(key)
        else:
            payload = await self._redis.get(key)
            await self._redis.delete(key)
        if payload is None:
            raise ValueError("challenge not found")
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return RelayChallengeBinding.model_validate_json(payload)

    async def _store_device(self, device: RelayDevice) -> None:
        await self._redis.set(
            RedisKey.relay_device(device.account_id, device.device_id),
            device.model_dump_json(),
        )
