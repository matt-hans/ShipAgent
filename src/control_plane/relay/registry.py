from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.control_plane.models import RelayDevice as RelayDeviceRecord
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

_DISCONNECT_SESSION_SCRIPT = """
local session = redis.call("GET", KEYS[1])
if not session then
    return 0
end
local ok, payload = pcall(cjson.decode, session)
if not ok or type(payload) ~= "table" or payload["relay_session_id"] ~= ARGV[1] then
    return 0
end
local active = redis.call("GET", KEYS[3])
if active then
    local active_ok, active_payload = pcall(cjson.decode, active)
    if active_ok
        and type(active_payload) == "table"
        and active_payload["device_id"] == payload["device_id"]
        and active_payload["relay_session_id"] == ARGV[1]
    then
        return redis.call("DEL", KEYS[1], KEYS[2], KEYS[3])
    end
end
return redis.call("DEL", KEYS[1], KEYS[2])
"""

_REFRESH_SESSION_SCRIPT = """
local session = redis.call("GET", KEYS[1])
local heartbeat = redis.call("GET", KEYS[2])
if not session or not heartbeat then
    return 0
end
local ok, payload = pcall(cjson.decode, session)
if not ok or type(payload) ~= "table" or payload["relay_session_id"] ~= ARGV[1] then
    return 0
end
redis.call("EXPIRE", KEYS[1], tonumber(ARGV[2]))
redis.call("EXPIRE", KEYS[2], tonumber(ARGV[2]))
local active = redis.call("GET", KEYS[3])
if active then
    local active_ok, active_payload = pcall(cjson.decode, active)
    if active_ok
        and type(active_payload) == "table"
        and active_payload["device_id"] == payload["device_id"]
        and active_payload["relay_session_id"] == ARGV[1]
    then
        redis.call("EXPIRE", KEYS[3], tonumber(ARGV[2]))
    end
end
return 1
"""

_CONSUME_CHALLENGE_SCRIPT = """
local challenge = redis.call("GET", KEYS[1])
if not challenge then
    return nil
end
redis.call("DEL", KEYS[1])
return challenge
"""


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

    async def eval(self, script: str, numkeys: int, *keys_and_args: str): ...


class RelayDevice(RelayProtocolModel):
    account_id: str
    device_id: str
    device_name: str
    public_key_pem: str
    fingerprint: str
    revoked: bool = False
    active: bool = False


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
    def __init__(
        self,
        redis_client: RedisLike,
        *,
        db_session_factory: async_sessionmaker[AsyncSession] | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        if db_session_factory is None and db_session is None:
            raise ValueError("RelayDeviceRegistry requires a durable device store")
        self._redis = redis_client
        self._db_session_factory = db_session_factory
        self._db_session = db_session

    async def register_device(
        self,
        account_id: str,
        device_name: str,
        public_key_pem: str,
        fingerprint: str | None = None,
    ) -> RelayDevice:
        validate_relay_public_key(public_key_pem)
        device_id = f"relay_device_{uuid.uuid4().hex}"
        device_fingerprint = relay_public_key_fingerprint(public_key_pem)
        async with self._device_db_session() as session:
            active_device_id = await self._get_active_device_id(session, account_id)
            register_as_active = active_device_id is None
            record = _new_relay_device_record(
                device_id=device_id,
                account_id=account_id,
                device_name=device_name,
                public_key_pem=public_key_pem,
                fingerprint=device_fingerprint,
                active=register_as_active,
            )
            try:
                session.add(record)
                await _commit_device_session(session)
            except ValueError as exc:
                if not register_as_active or "active relay device" not in str(exc):
                    raise
                record = _new_relay_device_record(
                    device_id=device_id,
                    account_id=account_id,
                    device_name=device_name,
                    public_key_pem=public_key_pem,
                    fingerprint=device_fingerprint,
                    active=False,
                )
                session.add(record)
                await _commit_device_session(session)
            return _device_from_record(record)

    async def get_device(self, account_id: str, device_id: str) -> RelayDevice | None:
        async with self._device_db_session() as session:
            record = await self._get_device_record(session, account_id, device_id)
            if record is None:
                return None
            active_device_id = await self._get_active_device_id(session, account_id)
            return _device_from_record(
                record,
                active=record.id == active_device_id,
            )

    async def list_devices(self, account_id: str) -> list[RelayDevice]:
        async with self._device_db_session() as session:
            active_device_id = await self._get_active_device_id(session, account_id)
            records = await session.scalars(
                select(RelayDeviceRecord)
                .where(RelayDeviceRecord.account_id == account_id)
                .order_by(RelayDeviceRecord.created_at, RelayDeviceRecord.id)
            )
            return [
                _device_from_record(
                    record,
                    active=record.id == active_device_id,
                )
                for record in records
            ]

    async def set_active_device(self, account_id: str, device_id: str) -> RelayDevice:
        async with self._device_db_session() as session:
            previous_active_device_id = await self._get_active_device_id(
                session,
                account_id,
            )
            record = await self._get_device_record(session, account_id, device_id)
            if record is None:
                raise ValueError("device not found")
            if record.revoked:
                raise ValueError("device revoked")
            await session.execute(
                update(RelayDeviceRecord)
                .where(RelayDeviceRecord.account_id == account_id)
                .values(active=False)
            )
            record.active = True
            await _commit_device_session(session)
            selected = _device_from_record(record, active=True)

        if (
            previous_active_device_id is not None
            and previous_active_device_id != device_id
        ):
            await self._clear_current_liveness(account_id, previous_active_device_id)
        await self._publish_active_liveness_if_connected(account_id, device_id)
        return selected

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
        if device.revoked:
            raise ValueError("device revoked")
        await self._clear_current_liveness(account_id, device_id)
        return await self._rotate_device_key(account_id, device_id, public_key_pem)

    async def revoke_device(self, account_id: str, device_id: str) -> RelayDevice:
        device = await self.get_device(account_id, device_id)
        if device is None:
            raise ValueError("device not found")
        revoked = device.model_copy(update={"revoked": True, "active": False})
        await self._clear_current_liveness(account_id, device_id)
        await self._store_device(revoked)
        return revoked

    async def unlink_device(self, account_id: str, device_id: str) -> RelayDevice:
        device = await self.get_device(account_id, device_id)
        if device is None:
            raise ValueError("device not found")
        if device.revoked:
            raise ValueError("device revoked")
        return await self.revoke_device(account_id, device_id)

    async def disconnect_session(
        self,
        account_id: str,
        device_id: str,
        relay_session_id: str,
    ) -> None:
        await self._redis.eval(
            _DISCONNECT_SESSION_SCRIPT,
            3,
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(account_id),
            relay_session_id,
        )

    async def refresh_session(
        self,
        account_id: str,
        device_id: str,
        relay_session_id: str,
    ) -> None:
        await self._redis.eval(
            _REFRESH_SESSION_SCRIPT,
            3,
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(account_id),
            relay_session_id,
            str(RedisTtl.RELAY_SESSION_SECONDS),
        )

    async def get_active_heartbeat(self, account_id: str) -> RelayHeartbeat | None:
        payload = await self._redis.get(RedisKey.relay_active_target(account_id))
        if payload is None:
            return None
        active = _decode_liveness_model(RelaySession, payload)
        if active is None:
            return None
        if active.account_id != account_id:
            return None

        session = await self._get_session(active.device_id)
        heartbeat = await self._get_heartbeat(active.device_id)
        if session is None or heartbeat is None:
            return None
        if (
            session.account_id != account_id
            or heartbeat.account_id != account_id
            or session.device_id != active.device_id
            or heartbeat.device_id != active.device_id
            or session.relay_session_id != active.relay_session_id
            or heartbeat.relay_session_id != active.relay_session_id
        ):
            return None
        device = await self.get_device(account_id, active.device_id)
        if device is None or device.revoked or not device.active:
            return None
        if heartbeat.active_source_fingerprint != device.fingerprint:
            return None
        return heartbeat

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
        current_device = await self.get_device(binding.account_id, binding.device_id)
        if current_device is None:
            raise ValueError("device not found")
        if current_device.revoked:
            raise ValueError("device revoked")
        if (
            current_device.fingerprint != device.fingerprint
            or current_device.public_key_pem != device.public_key_pem
        ):
            raise ValueError("device changed")
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
        selected_device_id = await self._get_selected_active_device_id(
            session.account_id
        )
        if selected_device_id is None or selected_device_id == session.device_id:
            await self._redis.set(
                RedisKey.relay_active_target(session.account_id),
                session.model_dump_json(),
                ex=RedisTtl.RELAY_SESSION_SECONDS,
            )
        return session

    async def _get_challenge_binding(
        self, relay_session_id: str
    ) -> RelayChallengeBinding:
        key = RedisKey.relay_challenge(relay_session_id)
        payload = await self._redis.eval(_CONSUME_CHALLENGE_SCRIPT, 1, key)
        if payload is None:
            raise ValueError("challenge not found")
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return RelayChallengeBinding.model_validate_json(payload)

    async def _store_device(self, device: RelayDevice) -> None:
        async with self._device_db_session() as session:
            record = await self._get_device_record(
                session,
                device.account_id,
                device.device_id,
            )
            if record is None:
                session.add(
                    RelayDeviceRecord(
                        id=device.device_id,
                        account_id=device.account_id,
                        device_name=device.device_name,
                        public_key_pem=device.public_key_pem,
                        fingerprint=device.fingerprint,
                        revoked=device.revoked,
                    )
                )
            else:
                record.device_name = device.device_name
                record.public_key_pem = device.public_key_pem
                record.fingerprint = device.fingerprint
                if device.revoked:
                    record.revoked = True
                    record.active = False
            await _commit_device_session(session)

    async def _rotate_device_key(
        self,
        account_id: str,
        device_id: str,
        public_key_pem: str,
    ) -> RelayDevice:
        async with self._device_db_session() as session:
            record = await self._get_device_record(session, account_id, device_id)
            if record is None:
                raise ValueError("device not found")
            if record.revoked:
                raise ValueError("device revoked")
            record.public_key_pem = public_key_pem
            record.fingerprint = relay_public_key_fingerprint(public_key_pem)
            await _commit_device_session(session)
            return _device_from_record(record)

    async def _clear_current_liveness(self, account_id: str, device_id: str) -> None:
        session_payload = await self._redis.get(RedisKey.relay_session(device_id))
        if session_payload is None:
            active_payload = await self._redis.get(
                RedisKey.relay_active_target(account_id)
            )
            active = (
                _decode_liveness_model(RelaySession, active_payload)
                if active_payload is not None
                else None
            )
            if active is not None and active.device_id == device_id:
                await self._redis.delete(
                    RedisKey.relay_session(device_id),
                    RedisKey.relay_heartbeat(device_id),
                    RedisKey.relay_active_target(account_id),
                )
                return
            await self._redis.delete(
                RedisKey.relay_session(device_id),
                RedisKey.relay_heartbeat(device_id),
            )
            return
        session = _decode_liveness_model(RelaySession, session_payload)
        if session is None:
            await self._redis.delete(
                RedisKey.relay_session(device_id),
                RedisKey.relay_heartbeat(device_id),
            )
            return
        active_payload = await self._redis.get(RedisKey.relay_active_target(account_id))
        active = (
            _decode_liveness_model(RelaySession, active_payload)
            if active_payload is not None
            else None
        )
        if (
            active is not None
            and active.device_id == session.device_id
            and active.relay_session_id == session.relay_session_id
        ):
            await self._redis.delete(
                RedisKey.relay_session(device_id),
                RedisKey.relay_heartbeat(device_id),
                RedisKey.relay_active_target(account_id),
            )
            return
        await self._redis.delete(
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
        )

    async def _publish_active_liveness_if_connected(
        self,
        account_id: str,
        device_id: str,
    ) -> None:
        session = await self._get_session(device_id)
        heartbeat = await self._get_heartbeat(device_id)
        if (
            session is not None
            and heartbeat is not None
            and session.account_id == account_id
            and heartbeat.account_id == account_id
            and session.device_id == device_id
            and heartbeat.device_id == device_id
            and session.relay_session_id == heartbeat.relay_session_id
        ):
            await self._redis.set(
                RedisKey.relay_active_target(account_id),
                session.model_dump_json(),
                ex=RedisTtl.RELAY_SESSION_SECONDS,
            )
            return

    async def _get_selected_active_device_id(self, account_id: str) -> str | None:
        async with self._device_db_session() as session:
            return await self._get_active_device_id(session, account_id)

    @asynccontextmanager
    async def _device_db_session(self) -> AsyncIterator[AsyncSession]:
        if self._db_session is not None:
            yield self._db_session
            return
        if self._db_session_factory is None:
            raise RuntimeError("durable device store is not configured")
        async with self._db_session_factory() as session:
            yield session

    async def _get_device_record(
        self,
        session: AsyncSession,
        account_id: str,
        device_id: str,
    ) -> RelayDeviceRecord | None:
        return await session.scalar(
            select(RelayDeviceRecord).where(
                RelayDeviceRecord.account_id == account_id,
                RelayDeviceRecord.id == device_id,
            )
        )

    async def _get_active_device_id(
        self,
        session: AsyncSession,
        account_id: str,
    ) -> str | None:
        return await session.scalar(
            select(RelayDeviceRecord.id)
            .where(
                RelayDeviceRecord.account_id == account_id,
                RelayDeviceRecord.revoked.is_(False),
                RelayDeviceRecord.active.is_(True),
            )
            .order_by(RelayDeviceRecord.created_at, RelayDeviceRecord.id)
            .limit(1)
        )

    async def _get_session(self, device_id: str) -> RelaySession | None:
        payload = await self._redis.get(RedisKey.relay_session(device_id))
        if payload is None:
            return None
        return _decode_liveness_model(RelaySession, payload)

    async def _get_heartbeat(self, device_id: str) -> RelayHeartbeat | None:
        payload = await self._redis.get(RedisKey.relay_heartbeat(device_id))
        if payload is None:
            return None
        return _decode_liveness_model(RelayHeartbeat, payload)


def _decode_liveness_model(model_type, payload):
    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return model_type.model_validate_json(payload)
    except (UnicodeDecodeError, ValidationError, ValueError):
        return None


def _device_from_record(
    record: RelayDeviceRecord,
    *,
    active: bool | None = None,
) -> RelayDevice:
    return RelayDevice(
        account_id=record.account_id,
        device_id=record.id,
        device_name=record.device_name,
        public_key_pem=record.public_key_pem,
        fingerprint=record.fingerprint,
        revoked=record.revoked,
        active=(record.active and not record.revoked) if active is None else active,
    )


def _new_relay_device_record(
    *,
    device_id: str,
    account_id: str,
    device_name: str,
    public_key_pem: str,
    fingerprint: str,
    active: bool,
) -> RelayDeviceRecord:
    return RelayDeviceRecord(
        id=device_id,
        account_id=account_id,
        device_name=device_name,
        public_key_pem=public_key_pem,
        fingerprint=fingerprint,
        revoked=False,
        active=active,
    )


async def _commit_device_session(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(_device_integrity_message(exc)) from exc


def _device_integrity_message(exc: IntegrityError) -> str:
    message = str(exc.orig or exc).lower()
    if "fingerprint" in message or "account_fingerprint" in message:
        return "relay device fingerprint already registered"
    if (
        "active" in message
        or "one_active" in message
        or "relay_devices.account_id" in message
    ):
        return "active relay device already exists"
    return "relay device invariant violated"
