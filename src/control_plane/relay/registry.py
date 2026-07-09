from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.control_plane.models import CloudAccount, utc_now
from src.control_plane.models import RelayDevice as RelayDeviceRecord
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayHandshakeChallenge,
    RelayHandshakeToken,
    RelayHeartbeat,
    RelayProtocolModel,
    RelayTargetState,
    RelayVersionMetadata,
    decode_handshake_jwt_unverified,
    load_ed25519_public_key,
    relay_public_key_fingerprint,
    verify_handshake_jwt,
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
if not ok
    or type(payload) ~= "table"
    or payload["relay_session_id"] ~= ARGV[1]
    or payload["account_id"] ~= ARGV[4]
    or payload["device_id"] ~= ARGV[5]
then
    return 0
end
redis.call("SET", KEYS[2], ARGV[2])
redis.call("EXPIRE", KEYS[2], tonumber(ARGV[3]))
redis.call("EXPIRE", KEYS[1], tonumber(ARGV[3]))
local active = redis.call("GET", KEYS[3])
if active then
    local active_ok, active_payload = pcall(cjson.decode, active)
    if active_ok
        and type(active_payload) == "table"
        and active_payload["device_id"] == payload["device_id"]
        and active_payload["relay_session_id"] == ARGV[1]
    then
        redis.call("EXPIRE", KEYS[3], tonumber(ARGV[3]))
    end
end
return 1
"""

_PUBLISH_ACCEPTED_LIVENESS_SCRIPT = """
redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[4])
redis.call("SET", KEYS[2], ARGV[2], "EX", ARGV[4])
if ARGV[3] == "1" then
    redis.call("SET", KEYS[3], ARGV[1], "EX", ARGV[4])
end
return 1
"""

_CLEAR_LIVENESS_SNAPSHOT_SCRIPT = """
local session = redis.call("GET", KEYS[1])
if ARGV[1] == "" then
    if session then
        return 0
    end
    local deleted = redis.call("DEL", KEYS[2])
    local active = redis.call("GET", KEYS[3])
    if active then
        local active_ok, active_payload = pcall(cjson.decode, active)
        if active_ok
            and type(active_payload) == "table"
            and active_payload["device_id"] == ARGV[2]
        then
            deleted = deleted + redis.call("DEL", KEYS[3])
        end
    end
    return deleted
end
if not session or session ~= ARGV[1] then
    return 0
end
local deleted = redis.call("DEL", KEYS[1], KEYS[2])
local session_ok, session_payload = pcall(cjson.decode, session)
local active = redis.call("GET", KEYS[3])
if session_ok and type(session_payload) == "table" and active then
    local active_ok, active_payload = pcall(cjson.decode, active)
    if active_ok
        and type(active_payload) == "table"
        and active_payload["device_id"] == session_payload["device_id"]
        and active_payload["relay_session_id"] == session_payload["relay_session_id"]
    then
        deleted = deleted + redis.call("DEL", KEYS[3])
    end
end
return deleted
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
    key_version: int = 1
    revoked: bool = False
    revoked_at: datetime | None = None
    active: bool = False


@dataclass(frozen=True)
class RelayActiveDeviceTransition:
    selected_device: RelayDevice
    replaced_device_id: str | None


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
        return (
            await self.set_active_device_transition(account_id, device_id)
        ).selected_device

    async def set_active_device_transition(
        self,
        account_id: str,
        device_id: str,
    ) -> RelayActiveDeviceTransition:
        async with self._device_db_session() as session:
            await session.scalar(
                select(CloudAccount.id)
                .where(CloudAccount.id == account_id)
                .with_for_update()
            )
            previous_active_device_id = await self._get_active_device_id(
                session,
                account_id,
            )
            previous_liveness_snapshot = (
                await self._capture_liveness_session(previous_active_device_id)
                if previous_active_device_id is not None
                and previous_active_device_id != device_id
                else None
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
            await self._clear_current_liveness(
                account_id,
                previous_active_device_id,
                previous_liveness_snapshot,
            )
        await self._publish_active_liveness_if_connected(account_id, device_id)
        return RelayActiveDeviceTransition(
            selected_device=selected,
            replaced_device_id=(
                previous_active_device_id
                if previous_active_device_id != device_id
                else None
            ),
        )

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
        liveness_snapshot = await self._capture_liveness_session(device_id)
        rotated = await self._rotate_device_key(account_id, device_id, public_key_pem)
        await self._clear_current_liveness(account_id, device_id, liveness_snapshot)
        return rotated

    async def revoke_device(self, account_id: str, device_id: str) -> RelayDevice:
        device = await self.get_device(account_id, device_id)
        if device is None:
            raise ValueError("device not found")
        liveness_snapshot = await self._capture_liveness_session(device_id)
        revoked = await self._revoke_device(account_id, device_id)
        try:
            await self._clear_current_liveness(account_id, device_id, liveness_snapshot)
        except Exception:
            if not device.revoked:
                await self._restore_after_failed_revocation(
                    account_id,
                    device_id,
                    revoked,
                    active=device.active,
                )
            raise
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
        version: RelayVersionMetadata | None = None,
        active_source_fingerprint: str | None = None,
    ) -> None:
        current_heartbeat = await self._get_heartbeat(device_id)
        heartbeat_version = (
            version
            or (current_heartbeat.version if current_heartbeat is not None else None)
            or RelayVersionMetadata(
                shipagent_core_version="unknown",
                registry_contract_version="unknown",
                ups_boundary_contract_version="unknown",
            )
        )
        heartbeat = RelayHeartbeat(
            account_id=account_id,
            device_id=device_id,
            relay_session_id=relay_session_id,
            execution_target_id=f"relay:{device_id}",
            state=RelayTargetState.READY,
            version=heartbeat_version,
            active_source_fingerprint=(
                active_source_fingerprint
                if active_source_fingerprint is not None
                else (
                    current_heartbeat.active_source_fingerprint
                    if current_heartbeat is not None
                    else None
                )
            ),
        )
        await self._redis.eval(
            _REFRESH_SESSION_SCRIPT,
            3,
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(account_id),
            relay_session_id,
            heartbeat.model_dump_json(),
            str(RedisTtl.RELAY_SESSION_SECONDS),
            account_id,
            device_id,
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
        handshake: RelayHandshakeToken,
        challenge_relay_session_id: str | None = None,
    ) -> RelaySession:
        if not isinstance(handshake, RelayHandshakeToken):
            raise ValueError("handshake token required")
        if challenge_relay_session_id is None:
            unverified_claims = decode_handshake_jwt_unverified(handshake)
            challenge_relay_session_id = unverified_claims.relay_session_id
        binding = await self._get_challenge_binding(challenge_relay_session_id)
        device = await self.get_device(binding.account_id, binding.device_id)
        if device is None:
            raise ValueError("device not found")
        if device.revoked:
            raise ValueError("device revoked")
        claims = verify_handshake_jwt(handshake, device.public_key_pem)
        claims.validate_for(binding.challenge, account_id=binding.account_id)
        if claims.device_id != binding.device_id:
            raise ValueError("wrong device")
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
        selected_device_id = await self._get_selected_active_device_id(
            session.account_id
        )
        await self._redis.eval(
            _PUBLISH_ACCEPTED_LIVENESS_SCRIPT,
            3,
            RedisKey.relay_session(session.device_id),
            RedisKey.relay_heartbeat(session.device_id),
            RedisKey.relay_active_target(session.account_id),
            session.model_dump_json(),
            heartbeat.model_dump_json(),
            "1"
            if selected_device_id is None or selected_device_id == session.device_id
            else "0",
            str(RedisTtl.RELAY_SESSION_SECONDS),
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

    async def _revoke_device(self, account_id: str, device_id: str) -> RelayDevice:
        async with self._device_db_session() as session:
            update_result = await session.execute(
                update(RelayDeviceRecord)
                .where(
                    RelayDeviceRecord.account_id == account_id,
                    RelayDeviceRecord.id == device_id,
                )
                .values(
                    revoked=True,
                    revoked_at=func.coalesce(RelayDeviceRecord.revoked_at, utc_now()),
                    active=False,
                )
            )
            if update_result.rowcount != 1:
                raise ValueError("device not found")
            record = await self._get_device_record(session, account_id, device_id)
            if record is None:
                raise RuntimeError("revoked device missing")
            await _commit_device_session(session)
            return _device_from_record(record)

    async def _restore_after_failed_revocation(
        self,
        account_id: str,
        device_id: str,
        revoked: RelayDevice,
        *,
        active: bool,
    ) -> None:
        async with self._device_db_session() as session:
            update_result = await session.execute(
                update(RelayDeviceRecord)
                .where(
                    RelayDeviceRecord.account_id == account_id,
                    RelayDeviceRecord.id == device_id,
                    RelayDeviceRecord.revoked.is_(True),
                    RelayDeviceRecord.key_version == revoked.key_version,
                    RelayDeviceRecord.revoked_at == revoked.revoked_at,
                )
                .values(revoked=False, revoked_at=None, active=active)
            )
            if update_result.rowcount:
                await _commit_device_session(session)

    async def _rotate_device_key(
        self,
        account_id: str,
        device_id: str,
        public_key_pem: str,
    ) -> RelayDevice:
        async with self._device_db_session() as session:
            try:
                update_result = await session.execute(
                    update(RelayDeviceRecord)
                    .where(
                        RelayDeviceRecord.account_id == account_id,
                        RelayDeviceRecord.id == device_id,
                        RelayDeviceRecord.revoked.is_(False),
                    )
                    .values(
                        public_key_pem=public_key_pem,
                        fingerprint=relay_public_key_fingerprint(public_key_pem),
                        key_version=RelayDeviceRecord.key_version + 1,
                    )
                )
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(_device_integrity_message(exc)) from exc
            if update_result.rowcount != 1:
                record = await self._get_device_record(session, account_id, device_id)
                if record is None:
                    raise ValueError("device not found")
                if record.revoked:
                    raise ValueError("device revoked")
                raise ValueError("device rotation failed")
            record = await self._get_device_record(session, account_id, device_id)
            if record is None:
                raise RuntimeError("rotated device missing")
            await _commit_device_session(session)
            return _device_from_record(record)

    async def _capture_liveness_session(self, device_id: str) -> str | None:
        payload = await self._redis.get(RedisKey.relay_session(device_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            return payload.decode("utf-8")
        return payload

    async def _clear_current_liveness(
        self,
        account_id: str,
        device_id: str,
        session_snapshot: str | None,
    ) -> None:
        await self._redis.eval(
            _CLEAR_LIVENESS_SNAPSHOT_SCRIPT,
            3,
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(account_id),
            session_snapshot or "",
            device_id,
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
        key_version=record.key_version,
        revoked=record.revoked,
        revoked_at=_as_utc_timestamp(record.revoked_at),
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
        key_version=1,
        revoked=False,
        revoked_at=None,
        active=active,
    )


def _as_utc_timestamp(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


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
