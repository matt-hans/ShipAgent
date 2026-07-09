from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.execution_targets import TargetToolRequest
from src.control_plane.models import CloudAccount, ControlPlaneBase
from src.control_plane.models import RelayDevice as RelayDeviceRecord
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.invocations import (
    NoLiveRelaySession,
    RelayInvocationBroker,
)
from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    RelayHeartbeat,
    RelayInvocationEnvelope,
    RelayInvocationResultFrame,
    RelayTargetState,
    RelayVersionMetadata,
    ShipAgentStatus,
    build_handshake_claims,
    relay_public_key_fingerprint,
)
from src.control_plane.relay.registry import RelayDeviceRegistry, RelaySession
from src.control_plane.relay.routes import build_relay_router
from src.services.relay_key_service import RelayKeyService


class InMemoryKeyStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


KEY_SERVICE = RelayKeyService(InMemoryKeyStore())
KEYPAIR = KEY_SERVICE.generate_or_load_keypair()
PUBLIC_KEY = KEYPAIR.public_key_pem
OTHER_KEY_SERVICE = RelayKeyService(InMemoryKeyStore())
OTHER_KEYPAIR = OTHER_KEY_SERVICE.generate_or_load_keypair()
THIRD_KEY_SERVICE = RelayKeyService(InMemoryKeyStore())
THIRD_KEYPAIR = THIRD_KEY_SERVICE.generate_or_load_keypair()
PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
INVALID_PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
VERSION = RelayVersionMetadata(
    shipagent_core_version="1.0.0",
    registry_contract_version="registry-v1",
    ups_boundary_contract_version="ups-v1",
    capabilities=["rate_shipment"],
)


class FakeStatusInvocationBroker:
    def __init__(self, *sessions: RelaySession) -> None:
        self.statuses = {
            session.relay_session_id: ShipAgentStatus(
                status=RelayTargetState.READY,
                execution_target=ExecutionTargetStatus(
                    state=RelayTargetState.READY,
                    target_id=session.execution_target_id,
                    capabilities=list(session.version.capabilities),
                    message=None,
                ),
            )
            for session in sessions
        }
        self.calls: list[dict[str, object]] = []

    async def invoke(
        self,
        *,
        relay_session_id: str,
        tool_name: str,
        arguments: dict[str, object],
        audit_correlation_id: str,
        timeout_seconds: float,
    ) -> RelayInvocationResultFrame:
        self.calls.append(
            {
                "relay_session_id": relay_session_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "audit_correlation_id": audit_correlation_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        status = self.statuses[relay_session_id]
        return RelayInvocationResultFrame(
            type="relay.invocation_result",
            relay_session_id=relay_session_id,
            relay_invocation_id="test-invocation",
            status="ok",
            result=status.model_dump(mode="json", by_alias=True),
        )


class BusyStatusInvocationBroker(FakeStatusInvocationBroker):
    async def invoke(
        self,
        *,
        relay_session_id: str,
        tool_name: str,
        arguments: dict[str, object],
        audit_correlation_id: str,
        timeout_seconds: float,
    ) -> RelayInvocationResultFrame:
        from src.control_plane.relay.invocations import RelayInvocationBusy

        raise RelayInvocationBusy("relay session already has an in-flight invocation")


class FailingSendRelayConnection:
    async def send_json(self, payload: dict[str, object]) -> None:
        raise RuntimeError("relay transport unavailable")

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        return None


def _status_request(context: AuthorizationContext) -> TargetToolRequest:
    return TargetToolRequest(
        account_id=context.account_id,
        provider_connection_id=context.provider_connection_id,
        provider_surface=context.provider_surface,
        tool_name="get_shipagent_status",
        arguments={},
        correlation_id="get_shipagent_status",
    )


async def _status_from_target(target, context: AuthorizationContext) -> ShipAgentStatus:
    return ShipAgentStatus.model_validate(await target.invoke(_status_request(context)))


async def _ensure_account(control_db, account_id: str = "acct-1") -> None:
    existing = await control_db.scalar(
        select(CloudAccount).where(CloudAccount.id == account_id)
    )
    if existing is not None:
        return
    control_db.add(
        CloudAccount(
            id=account_id,
            auth0_subject=f"auth0|{account_id}",
        )
    )
    await control_db.commit()


async def _registry(
    control_db,
    redis: FakeRedis | None = None,
) -> RelayDeviceRegistry:
    await _ensure_account(control_db)
    return RelayDeviceRegistry(redis or FakeRedis(), db_session=control_db)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def getdel(self, key: str):
        return self.values.pop(key, None)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str):
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return deleted

    async def _script_delete(self, *keys: str):
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return deleted

    async def expire(self, key: str, seconds: int):
        if key not in self.values:
            return False
        self.ttls[key] = seconds
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: str):
        if "relay active liveness CAS" in script:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                expected_session_snapshot,
                expected_heartbeat_snapshot,
                active_snapshot,
                ttl,
            ) = keys_and_args
            if self.values.get(session_key) != expected_session_snapshot:
                return 0
            if self.values.get(heartbeat_key) != expected_heartbeat_snapshot:
                return 0
            self.values[active_target_key] = active_snapshot
            self.ttls[active_target_key] = int(ttl)
            return 1
        if numkeys == 1:
            key = keys_and_args[0]
            self.ttls.pop(key, None)
            return self.values.pop(key, None)
        if numkeys == 4 and len(keys_and_args) == 5:
            (
                device_key,
                session_key,
                heartbeat_key,
                active_target_key,
                device_payload,
            ) = keys_and_args
            current_payload = self.values.get(device_key)
            if current_payload is None:
                return "missing"
            if isinstance(current_payload, bytes):
                current_payload = current_payload.decode("utf-8")
            current_device = json.loads(current_payload)
            if current_device.get("revoked") is True:
                await self._delete_current_liveness(
                    session_key, heartbeat_key, active_target_key
                )
                return "revoked"
            self.values[device_key] = device_payload
            await self._delete_current_liveness(
                session_key, heartbeat_key, active_target_key
            )
            return "ok"
        if numkeys == 3 and len(keys_and_args) == 8:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                expected_relay_session_id,
                heartbeat_payload,
                ttl,
                account_id,
                device_id,
            ) = keys_and_args
            payload = self.values.get(session_key)
            if payload is None or heartbeat_key not in self.values:
                return 0
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            try:
                session = json.loads(payload)
            except json.JSONDecodeError:
                return 0
            if not isinstance(session, dict):
                return 0
            if (
                session.get("relay_session_id") != expected_relay_session_id
                or session.get("account_id") != account_id
                or session.get("device_id") != device_id
            ):
                return 0
            self.values[heartbeat_key] = heartbeat_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            active_payload = self.values.get(active_target_key)
            if active_payload is not None:
                if isinstance(active_payload, bytes):
                    active_payload = active_payload.decode("utf-8")
                active = json.loads(active_payload)
                if (
                    isinstance(active, dict)
                    and active.get("device_id") == session.get("device_id")
                    and active.get("relay_session_id") == expected_relay_session_id
                ):
                    self.ttls[active_target_key] = int(ttl)
            return 1
        if numkeys == 3 and len(keys_and_args) == 7:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                session_payload,
                heartbeat_payload,
                publish_active,
                ttl,
            ) = keys_and_args
            self.values[session_key] = session_payload
            self.values[heartbeat_key] = heartbeat_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            if publish_active == "1":
                self.values[active_target_key] = session_payload
                self.ttls[active_target_key] = int(ttl)
            return 1
        if numkeys == 3 and len(keys_and_args) == 5:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                expected_session_payload,
                device_id,
            ) = keys_and_args
            session_payload = self.values.get(session_key)
            if expected_session_payload == "":
                if session_payload is not None:
                    return 0
                deleted = await self._script_delete(heartbeat_key)
                active_payload = self.values.get(active_target_key)
                if active_payload is None:
                    return deleted
                try:
                    active = json.loads(active_payload)
                except json.JSONDecodeError:
                    return deleted
                if isinstance(active, dict) and active.get("device_id") == device_id:
                    deleted += await self._script_delete(active_target_key)
                return deleted
            if session_payload != expected_session_payload:
                return 0
            deleted = await self._script_delete(session_key, heartbeat_key)
            try:
                session = json.loads(session_payload)
            except json.JSONDecodeError:
                return deleted
            active_payload = self.values.get(active_target_key)
            if active_payload is None or not isinstance(session, dict):
                return deleted
            try:
                active = json.loads(active_payload)
            except json.JSONDecodeError:
                return deleted
            if (
                isinstance(active, dict)
                and active.get("device_id") == session.get("device_id")
                and active.get("relay_session_id") == session.get("relay_session_id")
            ):
                deleted += await self._script_delete(active_target_key)
            return deleted
        if numkeys == 4 and len(keys_and_args) == 4:
            device_key, session_key, heartbeat_key, active_target_key = keys_and_args
            current_payload = self.values.get(device_key)
            if current_payload is None:
                return "missing"
            if isinstance(current_payload, bytes):
                current_payload = current_payload.decode("utf-8")
            current_device = json.loads(current_payload)
            current_device["revoked"] = True
            revoked_payload = json.dumps(current_device)
            self.values[device_key] = revoked_payload
            await self._delete_current_liveness(
                session_key, heartbeat_key, active_target_key
            )
            return revoked_payload
        if numkeys == 4:
            (
                device_key,
                session_key,
                heartbeat_key,
                active_target_key,
                expected_fingerprint,
                expected_public_key_pem,
                session_payload,
                heartbeat_payload,
                ttl,
            ) = keys_and_args
            device_payload = self.values.get(device_key)
            if device_payload is None:
                return "missing"
            if isinstance(device_payload, bytes):
                device_payload = device_payload.decode("utf-8")
            device = json.loads(device_payload)
            if device.get("revoked") is True:
                return "revoked"
            if (
                device.get("fingerprint") != expected_fingerprint
                or device.get("public_key_pem") != expected_public_key_pem
            ):
                return "stale"
            self.values[session_key] = session_payload
            self.values[heartbeat_key] = heartbeat_payload
            self.values[active_target_key] = session_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            self.ttls[active_target_key] = int(ttl)
            return "ok"
        session_key, heartbeat_key, active_target_key, expected_relay_session_id = (
            keys_and_args
        )
        payload = self.values.get(session_key)
        if payload is None:
            return 0
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        try:
            session = json.loads(payload)
        except json.JSONDecodeError:
            return 0
        if not isinstance(session, dict):
            return 0
        if session.get("relay_session_id") != expected_relay_session_id:
            return 0
        active_payload = self.values.get(active_target_key)
        if active_payload is not None:
            if isinstance(active_payload, bytes):
                active_payload = active_payload.decode("utf-8")
            active = json.loads(active_payload)
            if (
                isinstance(active, dict)
                and active.get("device_id") == session.get("device_id")
                and active.get("relay_session_id") == expected_relay_session_id
            ):
                return await self._script_delete(
                    session_key, heartbeat_key, active_target_key
                )
        return await self._script_delete(session_key, heartbeat_key)

    async def _delete_current_liveness(
        self,
        session_key: str,
        heartbeat_key: str,
        active_target_key: str,
    ):
        payload = self.values.get(session_key)
        if payload is None:
            return await self._script_delete(session_key, heartbeat_key)
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        try:
            session = json.loads(payload)
        except json.JSONDecodeError:
            return await self._script_delete(session_key, heartbeat_key)
        if not isinstance(session, dict):
            return await self._script_delete(session_key, heartbeat_key)
        active_payload = self.values.get(active_target_key)
        if active_payload is not None:
            if isinstance(active_payload, bytes):
                active_payload = active_payload.decode("utf-8")
            active = json.loads(active_payload)
            if (
                isinstance(active, dict)
                and active.get("device_id") == session.get("device_id")
                and active.get("relay_session_id") == session.get("relay_session_id")
            ):
                return await self._script_delete(
                    session_key, heartbeat_key, active_target_key
                )
        return await self._script_delete(session_key, heartbeat_key)


class InterleavingRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.race_session_key: str | None = None
        self.race_values: dict[str, str] = {}
        self.race_armed = False
        self.publish_session_key: str | None = None
        self.publish_started = asyncio.Event()
        self.publish_release = asyncio.Event()
        self.publish_paused = False

    def arm_cleanup_race(
        self,
        *,
        session_key: str,
        race_values: dict[str, str],
    ) -> None:
        self.race_session_key = session_key
        self.race_values = race_values
        self.race_armed = True

    def arm_publish_race(self, session_key: str) -> None:
        self.publish_session_key = session_key
        self.publish_started = asyncio.Event()
        self.publish_release = asyncio.Event()
        self.publish_paused = False

    async def set(self, key: str, value: str, ex: int | None = None):
        result = await super().set(key, value, ex)
        if key == self.publish_session_key and not self.publish_paused:
            self.publish_paused = True
            self.publish_started.set()
            await asyncio.wait_for(self.publish_release.wait(), timeout=1)
        return result

    async def get(self, key: str):
        value = await super().get(key)
        if self.race_armed and key == self.race_session_key:
            self.values.update(self.race_values)
            self.race_armed = False
        return value

    async def eval(self, script: str, numkeys: int, *keys_and_args: str):
        if (
            numkeys == 3
            and len(keys_and_args) == 7
            and keys_and_args[0] == self.publish_session_key
            and not self.publish_paused
        ):
            self.publish_paused = True
            result = await super().eval(script, numkeys, *keys_and_args)
            self.publish_started.set()
            await asyncio.wait_for(self.publish_release.wait(), timeout=1)
            return result
        if numkeys in {2, 3}:
            session_key = keys_and_args[0]
        else:
            session_key = None
        if (
            session_key is not None
            and self.race_armed
            and session_key == self.race_session_key
        ):
            self.values.update(self.race_values)
            self.race_armed = False
        return await super().eval(script, numkeys, *keys_and_args)


class FailingSeparateDeleteRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_delete = False

    def fail_separate_delete(self) -> None:
        self.fail_next_delete = True

    async def delete(self, *keys: str):
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise RuntimeError("delete failed")
        return await super().delete(*keys)

    async def eval(self, script: str, numkeys: int, *keys_and_args: str):
        if self.fail_next_delete and numkeys == 3 and len(keys_and_args) == 5:
            self.fail_next_delete = False
            raise RuntimeError("delete failed")
        return await super().eval(script, numkeys, *keys_and_args)


class NoGetDelConcurrentRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.concurrent_get_key: str | None = None
        self.concurrent_get_count = 0
        self.concurrent_get_release = asyncio.Event()

    def arm_concurrent_get(self, key: str) -> None:
        self.concurrent_get_key = key
        self.concurrent_get_count = 0
        self.concurrent_get_release = asyncio.Event()

    async def get(self, key: str):
        value = self.values.get(key)
        if key == self.concurrent_get_key:
            self.concurrent_get_count += 1
            if self.concurrent_get_count == 2:
                self.concurrent_get_release.set()
            await asyncio.wait_for(self.concurrent_get_release.wait(), timeout=1)
        return value

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str):
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return deleted

    async def expire(self, key: str, seconds: int):
        if key not in self.values:
            return False
        self.ttls[key] = seconds
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: str):
        if "relay active liveness CAS" in script:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                expected_session_snapshot,
                expected_heartbeat_snapshot,
                active_snapshot,
                ttl,
            ) = keys_and_args
            if self.values.get(session_key) != expected_session_snapshot:
                return 0
            if self.values.get(heartbeat_key) != expected_heartbeat_snapshot:
                return 0
            self.values[active_target_key] = active_snapshot
            self.ttls[active_target_key] = int(ttl)
            return 1
        if numkeys == 3 and len(keys_and_args) == 7:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                session_payload,
                heartbeat_payload,
                publish_active,
                ttl,
            ) = keys_and_args
            self.values[session_key] = session_payload
            self.values[heartbeat_key] = heartbeat_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            if publish_active == "1":
                self.values[active_target_key] = session_payload
                self.ttls[active_target_key] = int(ttl)
            return 1
        if numkeys == 4:
            (
                device_key,
                session_key,
                heartbeat_key,
                active_target_key,
                expected_fingerprint,
                expected_public_key_pem,
                session_payload,
                heartbeat_payload,
                ttl,
            ) = keys_and_args
            device_payload = self.values.get(device_key)
            if device_payload is None:
                return "missing"
            if isinstance(device_payload, bytes):
                device_payload = device_payload.decode("utf-8")
            device = json.loads(device_payload)
            if device.get("revoked") is True:
                return "revoked"
            if (
                device.get("fingerprint") != expected_fingerprint
                or device.get("public_key_pem") != expected_public_key_pem
            ):
                return "stale"
            self.values[session_key] = session_payload
            self.values[heartbeat_key] = heartbeat_payload
            self.values[active_target_key] = session_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            self.ttls[active_target_key] = int(ttl)
            return "ok"
        key = keys_and_args[0]
        self.ttls.pop(key, None)
        return self.values.pop(key, None)


class RotatingBeforePublishRegistry(RelayDeviceRegistry):
    def __init__(self, redis: FakeRedis, control_db) -> None:
        super().__init__(redis, db_session=control_db)
        self._armed = False
        self._armed_get_device_calls = 0

    def arm_rotation_before_publish(self) -> None:
        self._armed = True
        self._armed_get_device_calls = 0

    async def get_device(self, account_id: str, device_id: str):
        device = await super().get_device(account_id, device_id)
        if self._armed and device is not None:
            self._armed_get_device_calls += 1
            if self._armed_get_device_calls == 2:
                return device.model_copy(
                    update={
                        "public_key_pem": OTHER_KEYPAIR.public_key_pem,
                        "fingerprint": relay_public_key_fingerprint(
                            OTHER_KEYPAIR.public_key_pem
                        ),
                    }
                )
        return device


class RevokingDuringRotateRegistry(RelayDeviceRegistry):
    def __init__(self, redis: FakeRedis, control_db) -> None:
        super().__init__(redis, db_session=control_db)
        self._armed_device_id: str | None = None

    def arm_revocation_during_rotate(self, device_id: str) -> None:
        self._armed_device_id = device_id

    async def _rotate_device_key(
        self,
        account_id: str,
        device_id: str,
        public_key_pem: str,
    ):
        if self._armed_device_id != device_id:
            return await super()._rotate_device_key(
                account_id,
                device_id,
                public_key_pem,
            )
        record = await self._db_session.get(RelayDeviceRecord, device_id)
        record.revoked = True
        await self._db_session.commit()
        self._armed_device_id = None
        return await super()._rotate_device_key(
            account_id,
            device_id,
            public_key_pem,
        )


class PausingRevokeRegistry(RelayDeviceRegistry):
    def __init__(self, redis: FakeRedis, *, db_session_factory) -> None:
        super().__init__(redis, db_session_factory=db_session_factory)
        self.device_read_started = asyncio.Event()
        self.device_read_release = asyncio.Event()
        self._pause_next_device_read = False

    def pause_next_device_read(self) -> None:
        self.device_read_started = asyncio.Event()
        self.device_read_release = asyncio.Event()
        self._pause_next_device_read = True

    async def get_device(self, account_id: str, device_id: str):
        device = await super().get_device(account_id, device_id)
        if self._pause_next_device_read:
            self._pause_next_device_read = False
            self.device_read_started.set()
            await asyncio.wait_for(self.device_read_release.wait(), timeout=2)
        return device


def test_relay_device_registry_requires_durable_store() -> None:
    with pytest.raises(ValueError, match="durable device store"):
        RelayDeviceRegistry(FakeRedis())


async def test_register_device_can_be_read_without_private_key_material(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())

    device = await registry.register_device(
        account_id="acct-1",
        device_name="Dock Mac",
        public_key_pem=PUBLIC_KEY,
    )

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored == device
    assert device.account_id == "acct-1"
    assert device.device_name == "Dock Mac"
    assert device.fingerprint.startswith("sha256:")
    assert device.revoked is False
    assert "private" not in device.model_dump_json().lower()


async def test_register_device_rejects_duplicate_fingerprint_for_account(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)

    with pytest.raises(ValueError, match="fingerprint already registered"):
        await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)


async def test_concurrent_first_device_registration_retries_loser_inactive(
    tmp_path,
) -> None:
    database_path = tmp_path / "relay-devices.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        ControlPlaneBase.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class FirstRegistrationRace:
        def __init__(self) -> None:
            self.count = 0
            self.ready = asyncio.Event()

        async def wait_for_both_registrations(self) -> None:
            self.count += 1
            if self.count == 2:
                self.ready.set()
            await asyncio.wait_for(self.ready.wait(), timeout=2)

    race = FirstRegistrationRace()

    class RacingRegistry(RelayDeviceRegistry):
        async def _get_active_device_id(self, session, account_id):
            active_device_id = await super()._get_active_device_id(
                session,
                account_id,
            )
            if active_device_id is None:
                await race.wait_for_both_registrations()
            return active_device_id

    try:
        async with factory() as session:
            session.add(
                CloudAccount(
                    id="acct-race",
                    auth0_subject="auth0|acct-race",
                )
            )
            await session.commit()
        first_registry = RacingRegistry(FakeRedis(), db_session_factory=factory)
        second_registry = RacingRegistry(FakeRedis(), db_session_factory=factory)

        first, second = await asyncio.gather(
            first_registry.register_device("acct-race", "Dock Mac", PUBLIC_KEY),
            second_registry.register_device(
                "acct-race",
                "Warehouse Mac",
                OTHER_KEYPAIR.public_key_pem,
            ),
        )
        devices = await first_registry.list_devices("acct-race")
    finally:
        await engine.dispose()

    assert {device.device_id for device in devices} == {
        first.device_id,
        second.device_id,
    }
    assert [device.active for device in devices].count(True) == 1
    assert [device.active for device in devices].count(False) == 1


async def test_concurrent_set_active_disconnects_authoritative_replaced_device(
    tmp_path,
) -> None:
    database_path = tmp_path / "relay-device-active-transition.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        ControlPlaneBase.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class PausingActiveTransitionRegistry(RelayDeviceRegistry):
        def __init__(self, redis: FakeRedis) -> None:
            super().__init__(redis, db_session_factory=factory)
            self.paused_device_id: str | None = None
            self.transition_started = asyncio.Event()
            self.transition_release = asyncio.Event()

        async def set_active_device_transition(self, account_id, device_id, **kwargs):
            if device_id == self.paused_device_id:
                self.transition_started.set()
                await asyncio.wait_for(self.transition_release.wait(), timeout=2)
            return await super().set_active_device_transition(
                account_id,
                device_id,
                **kwargs,
            )

    class RelayConnection:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.close_calls: list[tuple[int, str | None]] = []

        async def send_json(self, payload: dict[str, object]) -> None:
            self.sent.append(payload)

        async def close(
            self,
            code: int = 1000,
            reason: str | None = None,
        ) -> None:
            self.close_calls.append((code, reason))

    try:
        async with factory() as session:
            session.add(
                CloudAccount(
                    id="acct-transition",
                    auth0_subject="auth0|acct-transition",
                )
            )
            await session.commit()

        redis = FakeRedis()
        registry = PausingActiveTransitionRegistry(redis)
        first = await registry.register_device(
            "acct-transition",
            "Dock Mac",
            PUBLIC_KEY,
        )
        second = await registry.register_device(
            "acct-transition",
            "Warehouse Mac",
            OTHER_KEYPAIR.public_key_pem,
        )
        third = await registry.register_device(
            "acct-transition",
            "Packing Mac",
            THIRD_KEYPAIR.public_key_pem,
        )
        unrelated_key_service = RelayKeyService(InMemoryKeyStore())
        unrelated = await registry.register_device(
            "acct-transition",
            "Unrelated Mac",
            unrelated_key_service.generate_or_load_keypair().public_key_pem,
        )

        async def accept(device, key_service: RelayKeyService) -> RelaySession:
            challenge = await registry.create_challenge(
                "acct-transition",
                device.device_id,
            )
            return await registry.accept_handshake(
                key_service.sign_handshake_claims(
                    build_handshake_claims(
                        device_id=device.device_id,
                        account_id="acct-transition",
                        relay_session_id=challenge.relay_session_id,
                        nonce=challenge.nonce,
                        version=VERSION,
                    )
                )
            )

        first_session = await accept(first, KEY_SERVICE)
        second_session = await accept(second, OTHER_KEY_SERVICE)
        third_session = await accept(third, THIRD_KEY_SERVICE)
        unrelated_session = await accept(unrelated, unrelated_key_service)

        broker = RelayInvocationBroker()
        first_connection = RelayConnection()
        second_connection = RelayConnection()
        third_connection = RelayConnection()
        unrelated_connection = RelayConnection()
        for relay_session, connection in (
            (first_session, first_connection),
            (second_session, second_connection),
            (third_session, third_connection),
            (unrelated_session, unrelated_connection),
        ):
            await broker.register(
                relay_session.relay_session_id,
                connection,
                account_id=relay_session.account_id,
                device_id=relay_session.device_id,
            )

        router = build_relay_router(registry, broker)
        set_active = next(
            route.endpoint
            for route in router.routes
            if route.path == "/relay/devices/{device_id}/set-active"
        )
        context = AuthorizationContext(
            account_id="acct-transition",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject="auth0|owner-1",
            client_id="chatgpt-client",
            scopes=frozenset({"relay:device:manage"}),
            auth_time=datetime.now(UTC),
        )

        async def activate(device_id: str):
            token = set_authorization_context(context)
            try:
                return await set_active(device_id)
            finally:
                clear_authorization_context(token)

        registry.paused_device_id = third.device_id
        third_activation = asyncio.create_task(activate(third.device_id))
        await asyncio.wait_for(registry.transition_started.wait(), timeout=1)

        await activate(second.device_id)
        second_pending = asyncio.create_task(
            broker.invoke(
                relay_session_id=second_session.relay_session_id,
                tool_name="get_shipagent_status",
                arguments={},
                audit_correlation_id="second-pending",
                timeout_seconds=30,
            )
        )
        for _ in range(20):
            if second_connection.sent:
                break
            await asyncio.sleep(0)
        assert second_connection.sent

        registry.transition_release.set()
        await third_activation

        with pytest.raises(NoLiveRelaySession, match="disconnected"):
            await second_pending
        devices = await registry.list_devices("acct-transition")
        assert [device.device_id for device in devices if device.active] == [
            third.device_id
        ]
        assert second_connection.close_calls == [(1008, "relay device policy changed")]
        assert unrelated_connection.close_calls == []

        unrelated_pending = asyncio.create_task(
            broker.invoke(
                relay_session_id=unrelated_session.relay_session_id,
                tool_name="get_shipagent_status",
                arguments={},
                audit_correlation_id="unrelated-pending",
                timeout_seconds=1,
            )
        )
        for _ in range(20):
            if unrelated_connection.sent:
                break
            await asyncio.sleep(0)
        assert unrelated_connection.sent
        envelope = RelayInvocationEnvelope.model_validate(unrelated_connection.sent[0])
        await broker.accept_result(
            RelayInvocationResultFrame(
                type="relay.invocation_result",
                relay_session_id=unrelated_session.relay_session_id,
                relay_invocation_id=envelope.relay_invocation_id,
                status="ok",
                result={"status": "ok"},
            )
        )
        await unrelated_pending
    finally:
        await engine.dispose()


async def test_isolated_sessions_assign_distinct_versions_for_concurrent_rotations(
    tmp_path,
) -> None:
    database_path = tmp_path / "relay-device-rotation.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        ControlPlaneBase.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            session.add(
                CloudAccount(
                    id="acct-rotation",
                    auth0_subject="auth0|acct-rotation",
                )
            )
            await session.commit()
        seed_registry = RelayDeviceRegistry(FakeRedis(), db_session_factory=factory)
        device = await seed_registry.register_device(
            "acct-rotation",
            "Dock Mac",
            PUBLIC_KEY,
        )
        first_registry = RelayDeviceRegistry(FakeRedis(), db_session_factory=factory)
        second_registry = RelayDeviceRegistry(FakeRedis(), db_session_factory=factory)

        first, second = await asyncio.gather(
            first_registry.rotate_key(
                "acct-rotation",
                device.device_id,
                OTHER_KEYPAIR.public_key_pem,
            ),
            second_registry.rotate_key(
                "acct-rotation",
                device.device_id,
                THIRD_KEYPAIR.public_key_pem,
            ),
        )
        persisted = await seed_registry.get_device("acct-rotation", device.device_id)
    finally:
        await engine.dispose()

    assert {first.key_version, second.key_version} == {2, 3}
    assert persisted is not None
    assert persisted.key_version == 3


async def test_stale_revoke_does_not_roll_back_newer_rotation_version(tmp_path) -> None:
    database_path = tmp_path / "relay-device-stale-revoke.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        ControlPlaneBase.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            session.add(
                CloudAccount(
                    id="acct-stale-revoke",
                    auth0_subject="auth0|acct-stale-revoke",
                )
            )
            await session.commit()
        seed_registry = RelayDeviceRegistry(FakeRedis(), db_session_factory=factory)
        device = await seed_registry.register_device(
            "acct-stale-revoke",
            "Dock Mac",
            PUBLIC_KEY,
        )
        stale_revoke_registry = PausingRevokeRegistry(
            FakeRedis(),
            db_session_factory=factory,
        )
        rotating_registry = RelayDeviceRegistry(FakeRedis(), db_session_factory=factory)
        stale_revoke_registry.pause_next_device_read()

        revoke_task = asyncio.create_task(
            stale_revoke_registry.revoke_device("acct-stale-revoke", device.device_id)
        )
        await asyncio.wait_for(
            stale_revoke_registry.device_read_started.wait(), timeout=2
        )
        rotated = await rotating_registry.rotate_key(
            "acct-stale-revoke",
            device.device_id,
            OTHER_KEYPAIR.public_key_pem,
        )
        stale_revoke_registry.device_read_release.set()
        revoked = await revoke_task
        persisted = await seed_registry.get_device(
            "acct-stale-revoke", device.device_id
        )
    finally:
        await engine.dispose()

    assert rotated.key_version == 2
    assert revoked.key_version == 2
    assert persisted is not None
    assert persisted.key_version == 2
    assert persisted.public_key_pem == OTHER_KEYPAIR.public_key_pem
    assert persisted.revoked is True


async def test_list_devices_returns_account_devices_only(control_db) -> None:
    await _ensure_account(control_db, "acct-2")
    registry = await _registry(control_db, FakeRedis())
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    other = await registry.register_device("acct-2", "Other Dock", PUBLIC_KEY)

    devices = await registry.list_devices("acct-1")

    assert [device.device_id for device in devices] == [
        first.device_id,
        second.device_id,
    ]
    assert other.device_id not in {device.device_id for device in devices}


async def test_set_active_device_selects_unrevoked_device(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )

    selected = await registry.set_active_device("acct-1", second.device_id)
    devices = await registry.list_devices("acct-1")

    assert selected.device_id == second.device_id
    assert selected.active is True
    assert [(device.device_id, device.active) for device in devices] == [
        (first.device_id, False),
        (second.device_id, True),
    ]


async def test_unselected_device_handshake_does_not_replace_active_target(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    registry = await _registry(control_db, FakeRedis())
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    await registry.set_active_device("acct-1", first.device_id)
    first_challenge = await registry.create_challenge("acct-1", first.device_id)
    first_claims = build_handshake_claims(
        device_id=first.device_id,
        account_id="acct-1",
        relay_session_id=first_challenge.relay_session_id,
        nonce=first_challenge.nonce,
        version=VERSION,
    )
    first_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(first_claims)
    )
    second_challenge = await registry.create_challenge("acct-1", second.device_id)
    second_claims = build_handshake_claims(
        device_id=second.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )

    await registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(
        RelayExecutionTarget(registry, FakeStatusInvocationBroker(first_session)),
        context,
    )
    devices = await registry.list_devices("acct-1")

    assert status.execution_target.target_id == first_session.execution_target_id
    assert [(device.device_id, device.active) for device in devices] == [
        (first.device_id, True),
        (second.device_id, False),
    ]


async def test_active_selection_survives_fresh_redis_and_blocks_unselected_handshake(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    first_registry = await _registry(control_db, FakeRedis())
    first = await first_registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await first_registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    await first_registry.set_active_device("acct-1", first.device_id)
    fresh_registry = RelayDeviceRegistry(FakeRedis(), db_session=control_db)
    second_challenge = await fresh_registry.create_challenge("acct-1", second.device_id)
    second_claims = build_handshake_claims(
        device_id=second.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    await fresh_registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(RelayExecutionTarget(fresh_registry), context)
    devices = await fresh_registry.list_devices("acct-1")

    assert status.execution_target.state == RelayTargetState.OFFLINE
    assert status.execution_target.target_id is None
    assert [(device.device_id, device.active) for device in devices] == [
        (first.device_id, True),
        (second.device_id, False),
    ]


async def test_set_active_device_after_redis_loss_selects_reconnected_target(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    first_registry = await _registry(control_db, FakeRedis())
    first = await first_registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await first_registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    fresh_registry = RelayDeviceRegistry(FakeRedis(), db_session=control_db)

    selected = await fresh_registry.set_active_device("acct-1", second.device_id)
    second_challenge = await fresh_registry.create_challenge("acct-1", second.device_id)
    second_claims = build_handshake_claims(
        device_id=second.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await fresh_registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(
        RelayExecutionTarget(
            fresh_registry, FakeStatusInvocationBroker(second_session)
        ),
        context,
    )
    devices = await fresh_registry.list_devices("acct-1")

    assert selected.active is True
    assert status.execution_target.target_id == second_session.execution_target_id
    assert [(device.device_id, device.active) for device in devices] == [
        (first.device_id, False),
        (second.device_id, True),
    ]


async def test_set_active_device_switches_to_connected_device_and_clears_previous_liveness(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    first_challenge = await registry.create_challenge("acct-1", first.device_id)
    first_claims = build_handshake_claims(
        device_id=first.device_id,
        account_id="acct-1",
        relay_session_id=first_challenge.relay_session_id,
        nonce=first_challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(first_claims))
    second_challenge = await registry.create_challenge("acct-1", second.device_id)
    second_claims = build_handshake_claims(
        device_id=second.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    selected = await registry.set_active_device("acct-1", second.device_id)

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(
        RelayExecutionTarget(registry, FakeStatusInvocationBroker(second_session)),
        context,
    )
    assert selected.active is True
    assert await redis.get(RedisKey.relay_session(first.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(first.device_id)) is None
    assert status.execution_target.target_id == second_session.execution_target_id


async def test_active_selection_does_not_overwrite_reconnected_target_session(
    control_db,
) -> None:
    class PausingActiveTargetRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.compare_and_set_started = asyncio.Event()
            self.release_compare_and_set = asyncio.Event()
            self._heartbeat_key: str | None = None

        def pause_active_target_compare_and_set(self, heartbeat_key: str) -> None:
            self.compare_and_set_started = asyncio.Event()
            self.release_compare_and_set = asyncio.Event()
            self._heartbeat_key = heartbeat_key

        async def get(self, key: str):
            value = await super().get(key)
            if key == self._heartbeat_key:
                self._heartbeat_key = None
                self.compare_and_set_started.set()
                await self.release_compare_and_set.wait()
            return value

    await _ensure_account(control_db)
    redis = PausingActiveTargetRedis()
    registry = RelayDeviceRegistry(redis, db_session=control_db)
    reconnecting_registry = RelayDeviceRegistry(redis, db_session=control_db)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)

    async def accept_session(candidate: RelayDeviceRegistry):
        challenge = await candidate.create_challenge("acct-1", device.device_id)
        return await candidate.accept_handshake(
            KEY_SERVICE.sign_handshake_claims(
                build_handshake_claims(
                    device_id=device.device_id,
                    account_id="acct-1",
                    relay_session_id=challenge.relay_session_id,
                    nonce=challenge.nonce,
                    version=VERSION,
                )
            )
        )

    await accept_session(registry)
    redis.pause_active_target_compare_and_set(
        RedisKey.relay_heartbeat(device.device_id)
    )
    transition = asyncio.create_task(
        registry.set_active_device_transition("acct-1", device.device_id)
    )
    await asyncio.wait_for(redis.compare_and_set_started.wait(), timeout=1)
    second_session = await accept_session(reconnecting_registry)
    redis.release_compare_and_set.set()
    await transition

    heartbeat = await registry.get_active_heartbeat("acct-1")

    assert heartbeat is not None
    assert heartbeat.relay_session_id == second_session.relay_session_id


async def test_active_switch_does_not_delete_session_published_after_cleanup_snapshot(
    control_db,
) -> None:
    redis = InterleavingRedis()
    registry = await _registry(control_db, redis)
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    first_challenge = await registry.create_challenge("acct-1", first.device_id)
    first_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(
            build_handshake_claims(
                device_id=first.device_id,
                account_id="acct-1",
                relay_session_id=first_challenge.relay_session_id,
                nonce=first_challenge.nonce,
                version=VERSION,
            )
        )
    )
    second_challenge = await registry.create_challenge("acct-1", second.device_id)
    second_session = await registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(
            build_handshake_claims(
                device_id=second.device_id,
                account_id="acct-1",
                relay_session_id=second_challenge.relay_session_id,
                nonce=second_challenge.nonce,
                version=VERSION,
            )
        )
    )
    newer_first_challenge = await registry.create_challenge("acct-1", first.device_id)
    newer_first_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(
            build_handshake_claims(
                device_id=first.device_id,
                account_id="acct-1",
                relay_session_id=newer_first_challenge.relay_session_id,
                nonce=newer_first_challenge.nonce,
                version=VERSION,
            )
        )
    )
    session_key = RedisKey.relay_session(first.device_id)
    heartbeat_key = RedisKey.relay_heartbeat(first.device_id)
    active_target_key = RedisKey.relay_active_target("acct-1")
    newer_session_payload = await redis.get(session_key)
    newer_heartbeat_payload = await redis.get(heartbeat_key)
    newer_active_payload = await redis.get(active_target_key)
    assert newer_session_payload is not None
    assert newer_heartbeat_payload is not None
    assert newer_active_payload is not None
    await redis.set(session_key, first_session.model_dump_json())
    await redis.set(
        heartbeat_key,
        RelayHeartbeat(
            account_id=first_session.account_id,
            device_id=first_session.device_id,
            relay_session_id=first_session.relay_session_id,
            execution_target_id=first_session.execution_target_id,
            state=first_session.state,
            version=first_session.version,
        ).model_dump_json(),
    )
    await redis.set(active_target_key, first_session.model_dump_json())
    redis.arm_cleanup_race(
        session_key=session_key,
        race_values={
            session_key: newer_session_payload,
            heartbeat_key: newer_heartbeat_payload,
            active_target_key: newer_active_payload,
        },
    )

    await registry.set_active_device("acct-1", second.device_id)

    stored_session = RelaySession.model_validate_json(await redis.get(session_key))
    stored_heartbeat = RelayHeartbeat.model_validate_json(
        await redis.get(heartbeat_key)
    )
    active = RelaySession.model_validate_json(await redis.get(active_target_key))

    assert stored_session.relay_session_id == newer_first_session.relay_session_id
    assert stored_heartbeat.relay_session_id == newer_first_session.relay_session_id
    assert active.relay_session_id == second_session.relay_session_id


async def test_set_active_device_rejects_missing_and_revoked_devices(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    await registry.revoke_device("acct-1", device.device_id)

    with pytest.raises(ValueError, match="device not found"):
        await registry.set_active_device("acct-1", "missing-device")

    with pytest.raises(ValueError, match="revoked"):
        await registry.set_active_device("acct-1", device.device_id)


async def test_registered_device_survives_fresh_registry_with_empty_redis(
    control_db,
) -> None:
    control_db.add(CloudAccount(id="acct-1", auth0_subject="auth0|owner-1"))
    await control_db.commit()
    first_registry = RelayDeviceRegistry(FakeRedis(), db_session=control_db)

    device = await first_registry.register_device(
        account_id="acct-1",
        device_name="Dock Mac",
        public_key_pem=PUBLIC_KEY,
    )

    fresh_registry = RelayDeviceRegistry(FakeRedis(), db_session=control_db)
    stored = await fresh_registry.get_device("acct-1", device.device_id)
    challenge = await fresh_registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await fresh_registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(claims)
    )

    assert stored == device
    assert session.device_id == device.device_id


async def test_register_device_rejects_private_key_material(control_db) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)

    try:
        await registry.register_device(
            account_id="acct-1",
            device_name="Dock Mac",
            public_key_pem=PRIVATE_KEY,
        )
    except ValueError as exc:
        assert "private key" in str(exc)
    else:
        raise AssertionError("expected private key material to be rejected")
    assert all("PRIVATE KEY" not in value for value in redis.values.values())


async def test_register_device_rejects_invalid_public_key_material(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())

    try:
        await registry.register_device(
            account_id="acct-1",
            device_name="Dock Mac",
            public_key_pem=INVALID_PUBLIC_KEY,
        )
    except ValueError as exc:
        assert "public key" in str(exc)
    else:
        raise AssertionError("expected invalid public key material to be rejected")


async def test_register_device_derives_fingerprint_ignoring_caller_value(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())

    device = await registry.register_device(
        account_id="acct-1",
        device_name="Dock Mac",
        public_key_pem=PUBLIC_KEY,
        fingerprint="sha256:attacker-controlled",
    )

    assert device.fingerprint == relay_public_key_fingerprint(PUBLIC_KEY)


async def test_rotate_key_preserves_device_id_and_updates_public_key(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    rotated_key = OTHER_KEYPAIR.public_key_pem

    rotated = await registry.rotate_key(
        account_id="acct-1",
        device_id=device.device_id,
        public_key_pem=rotated_key,
    )

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored == rotated
    assert rotated.device_id == device.device_id
    assert rotated.public_key_pem == rotated_key
    assert rotated.fingerprint != device.fingerprint
    assert rotated.revoked is False


async def test_rotate_key_clears_ready_liveness_and_rejects_old_key_claims(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    await registry.rotate_key(
        account_id="acct-1",
        device_id=device.device_id,
        public_key_pem=OTHER_KEYPAIR.public_key_pem,
    )

    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None
    rotated_challenge = await registry.create_challenge("acct-1", device.device_id)
    old_key_claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=rotated_challenge.relay_session_id,
        nonce=rotated_challenge.nonce,
        version=VERSION,
    )
    try:
        await registry.accept_handshake(
            KEY_SERVICE.sign_handshake_claims(old_key_claims)
        )
    except ValueError as exc:
        assert "handshake token" in str(exc)
    else:
        raise AssertionError("expected old-key signed claims to be rejected")
    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None


async def test_rotate_key_duplicate_fingerprint_preserves_live_liveness(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    await registry.register_device(
        "acct-1",
        "Warehouse Mac",
        OTHER_KEYPAIR.public_key_pem,
    )
    challenge = await registry.create_challenge("acct-1", first.device_id)
    claims = build_handshake_claims(
        device_id=first.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    with pytest.raises(ValueError, match="fingerprint"):
        await registry.rotate_key(
            account_id="acct-1",
            device_id=first.device_id,
            public_key_pem=OTHER_KEYPAIR.public_key_pem,
        )

    stored = await registry.get_device("acct-1", first.device_id)
    assert stored is not None
    assert stored.public_key_pem == PUBLIC_KEY
    assert await redis.get(RedisKey.relay_session(first.device_id)) is not None
    assert await redis.get(RedisKey.relay_heartbeat(first.device_id)) is not None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is not None


async def test_rotate_key_does_not_store_device_record_in_redis(control_db) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    session_key = RedisKey.relay_session(device.device_id)
    heartbeat_key = RedisKey.relay_heartbeat(device.device_id)
    await redis.set(session_key, "stale-session-payload")
    await redis.set(heartbeat_key, "stale-heartbeat-payload")

    rotated = await registry.rotate_key(
        account_id="acct-1",
        device_id=device.device_id,
        public_key_pem=OTHER_KEYPAIR.public_key_pem,
    )

    assert rotated.public_key_pem == OTHER_KEYPAIR.public_key_pem
    assert await redis.get(RedisKey.relay_device("acct-1", device.device_id)) is None
    assert await redis.get(session_key) is None
    assert await redis.get(heartbeat_key) is None


async def test_rotate_key_does_not_clear_newer_active_target(control_db) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    first_device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    first_challenge = await registry.create_challenge("acct-1", first_device.device_id)
    first_claims = build_handshake_claims(
        device_id=first_device.device_id,
        account_id="acct-1",
        relay_session_id=first_challenge.relay_session_id,
        nonce=first_challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(first_claims))
    second_device = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    second_challenge = await registry.create_challenge(
        "acct-1", second_device.device_id
    )
    second_claims = build_handshake_claims(
        device_id=second_device.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(second_claims)
    )
    await registry.set_active_device("acct-1", second_device.device_id)

    await registry.rotate_key(
        account_id="acct-1",
        device_id=first_device.device_id,
        public_key_pem=THIRD_KEYPAIR.public_key_pem,
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(
        RelayExecutionTarget(registry, FakeStatusInvocationBroker(second_session)),
        context,
    )
    active = RelaySession.model_validate_json(
        await redis.get(RedisKey.relay_active_target("acct-1"))
    )

    assert active.relay_session_id == second_session.relay_session_id
    assert status.execution_target.target_id == second_session.execution_target_id


async def test_rotate_key_derives_fingerprint_ignoring_caller_value(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)

    rotated = await registry.rotate_key(
        account_id="acct-1",
        device_id=device.device_id,
        public_key_pem=OTHER_KEYPAIR.public_key_pem,
        fingerprint="sha256:attacker-controlled",
    )

    assert rotated.fingerprint == relay_public_key_fingerprint(
        OTHER_KEYPAIR.public_key_pem
    )


async def test_rotate_increments_key_version_and_revoke_persists_timestamp(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)

    assert device.key_version == 1
    rotated = await registry.rotate_key(
        device.account_id,
        device.device_id,
        OTHER_KEYPAIR.public_key_pem,
    )
    revoked = await registry.revoke_device(device.account_id, device.device_id)

    assert rotated.key_version == 2
    assert revoked.revoked_at is not None
    assert revoked.revoked_at.tzinfo is UTC
    persisted = await registry.get_device(device.account_id, device.device_id)
    assert persisted is not None
    assert persisted.key_version == 2
    assert persisted.revoked_at is not None
    assert persisted.revoked_at.tzinfo is UTC
    assert persisted.revoked_at == revoked.revoked_at


async def test_rotate_key_rejects_private_key_material(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)

    try:
        await registry.rotate_key(
            account_id="acct-1",
            device_id=device.device_id,
            public_key_pem=PRIVATE_KEY,
        )
    except ValueError as exc:
        assert "private key" in str(exc)
    else:
        raise AssertionError("expected private key material to be rejected")

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored == device
    assert "PRIVATE KEY" not in stored.model_dump_json()


async def test_rotate_key_preserves_revoked_state(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    revoked = await registry.revoke_device("acct-1", device.device_id)
    rotated_key = OTHER_KEYPAIR.public_key_pem

    try:
        await registry.rotate_key(
            account_id="acct-1",
            device_id=device.device_id,
            public_key_pem=rotated_key,
        )
    except ValueError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("expected revoked device rotation to be rejected")

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored == revoked
    try:
        await registry.create_challenge("acct-1", device.device_id)
    except ValueError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("expected rotated revoked device to remain revoked")


async def test_rotate_key_does_not_unrevoke_concurrent_revocation(control_db) -> None:
    redis = FakeRedis()
    registry = RevokingDuringRotateRegistry(redis, control_db)
    await _ensure_account(control_db)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    registry.arm_revocation_during_rotate(device.device_id)

    with pytest.raises(ValueError, match="revoked"):
        await registry.rotate_key(
            account_id="acct-1",
            device_id=device.device_id,
            public_key_pem=OTHER_KEYPAIR.public_key_pem,
        )

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored.revoked is True
    assert stored.public_key_pem == PUBLIC_KEY


async def test_revoke_device_marks_revoked_and_clears_active_session(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    revoked = await registry.revoke_device("acct-1", device.device_id)

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored == revoked
    assert revoked.revoked is True
    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None


async def test_unlink_device_revokes_and_clears_active_liveness(control_db) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    unlinked = await registry.unlink_device("acct-1", device.device_id)

    assert unlinked.revoked is True
    assert await registry.get_device("acct-1", device.device_id) == unlinked
    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None


async def test_revoke_device_does_not_leave_revoked_device_with_stale_liveness(
    control_db,
) -> None:
    redis = FailingSeparateDeleteRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    session_key = RedisKey.relay_session(device.device_id)
    heartbeat_key = RedisKey.relay_heartbeat(device.device_id)
    await redis.set(session_key, "session")
    await redis.set(heartbeat_key, "heartbeat")

    redis.fail_separate_delete()
    try:
        revoked = await registry.revoke_device("acct-1", device.device_id)
    except RuntimeError:
        stored = await registry.get_device("acct-1", device.device_id)
        session = await redis.get(session_key)
        heartbeat = await redis.get(heartbeat_key)
        assert not (
            stored is not None
            and stored.revoked is True
            and (session is not None or heartbeat is not None)
        )
    else:
        assert revoked.revoked is True
        assert await redis.get(session_key) is None
        assert await redis.get(heartbeat_key) is None


async def test_revoke_device_does_not_clear_newer_active_target(control_db) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    first_device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    first_challenge = await registry.create_challenge("acct-1", first_device.device_id)
    first_claims = build_handshake_claims(
        device_id=first_device.device_id,
        account_id="acct-1",
        relay_session_id=first_challenge.relay_session_id,
        nonce=first_challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(first_claims))
    second_device = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    second_challenge = await registry.create_challenge(
        "acct-1", second_device.device_id
    )
    second_claims = build_handshake_claims(
        device_id=second_device.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        OTHER_KEY_SERVICE.sign_handshake_claims(second_claims)
    )
    await registry.set_active_device("acct-1", second_device.device_id)

    await registry.revoke_device("acct-1", first_device.device_id)

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(
        RelayExecutionTarget(registry, FakeStatusInvocationBroker(second_session)),
        context,
    )
    active = RelaySession.model_validate_json(
        await redis.get(RedisKey.relay_active_target("acct-1"))
    )

    assert active.relay_session_id == second_session.relay_session_id
    assert status.execution_target.target_id == second_session.execution_target_id


async def test_disconnect_session_clears_ready_liveness(control_db) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    await registry.disconnect_session(
        "acct-1",
        device.device_id,
        session.relay_session_id,
    )

    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None


async def test_disconnect_session_does_not_clear_newer_ready_liveness(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    first_challenge = await registry.create_challenge("acct-1", device.device_id)
    first_claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=first_challenge.relay_session_id,
        nonce=first_challenge.nonce,
        version=VERSION,
    )
    first_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(first_claims)
    )
    second_challenge = await registry.create_challenge("acct-1", device.device_id)
    second_claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    await registry.disconnect_session(
        "acct-1",
        device.device_id,
        first_session.relay_session_id,
    )

    stored_session = RelaySession.model_validate_json(
        await redis.get(RedisKey.relay_session(device.device_id))
    )
    heartbeat = RelayHeartbeat.model_validate_json(
        await redis.get(RedisKey.relay_heartbeat(device.device_id))
    )
    assert stored_session.relay_session_id == second_session.relay_session_id
    assert heartbeat.relay_session_id == second_session.relay_session_id


async def test_disconnect_session_does_not_delete_newer_session_written_during_cleanup(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = InterleavingRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    first_challenge = await registry.create_challenge("acct-1", device.device_id)
    first_claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=first_challenge.relay_session_id,
        nonce=first_challenge.nonce,
        version=VERSION,
    )
    first_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(first_claims)
    )
    first_session_payload = await redis.get(RedisKey.relay_session(device.device_id))
    first_heartbeat_payload = await redis.get(
        RedisKey.relay_heartbeat(device.device_id)
    )
    first_active_payload = await redis.get(RedisKey.relay_active_target("acct-1"))
    second_challenge = await registry.create_challenge("acct-1", device.device_id)
    second_claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(second_claims)
    )
    second_session_payload = await redis.get(RedisKey.relay_session(device.device_id))
    second_heartbeat_payload = await redis.get(
        RedisKey.relay_heartbeat(device.device_id)
    )
    second_active_payload = await redis.get(RedisKey.relay_active_target("acct-1"))
    session_key = RedisKey.relay_session(device.device_id)
    heartbeat_key = RedisKey.relay_heartbeat(device.device_id)
    active_target_key = RedisKey.relay_active_target("acct-1")
    await redis.set(session_key, first_session_payload)
    await redis.set(heartbeat_key, first_heartbeat_payload)
    await redis.set(active_target_key, first_active_payload)
    redis.arm_cleanup_race(
        session_key=session_key,
        race_values={
            session_key: second_session_payload,
            heartbeat_key: second_heartbeat_payload,
            active_target_key: second_active_payload,
        },
    )

    await registry.disconnect_session(
        "acct-1",
        device.device_id,
        first_session.relay_session_id,
    )

    stored_session = RelaySession.model_validate_json(await redis.get(session_key))
    heartbeat = RelayHeartbeat.model_validate_json(await redis.get(heartbeat_key))
    active = RelaySession.model_validate_json(await redis.get(active_target_key))
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await _status_from_target(
        RelayExecutionTarget(registry, FakeStatusInvocationBroker(second_session)),
        context,
    )

    assert stored_session.relay_session_id == second_session.relay_session_id
    assert heartbeat.relay_session_id == second_session.relay_session_id
    assert active.relay_session_id == second_session.relay_session_id
    assert status.execution_target.target_id == second_session.execution_target_id


async def test_refresh_session_extends_liveness_only_for_matching_session(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    session_key = RedisKey.relay_session(device.device_id)
    heartbeat_key = RedisKey.relay_heartbeat(device.device_id)
    active_target_key = RedisKey.relay_active_target("acct-1")
    redis.ttls[session_key] = 1
    redis.ttls[heartbeat_key] = 1
    redis.ttls[active_target_key] = 1

    await registry.refresh_session("acct-1", device.device_id, "wrong-session")

    assert redis.ttls[session_key] == 1
    assert redis.ttls[heartbeat_key] == 1
    assert redis.ttls[active_target_key] == 1

    await registry.refresh_session(
        "acct-1",
        device.device_id,
        session.relay_session_id,
    )

    assert redis.ttls[session_key] == RedisTtl.RELAY_SESSION_SECONDS
    assert redis.ttls[heartbeat_key] == RedisTtl.RELAY_SESSION_SECONDS
    assert redis.ttls[active_target_key] == RedisTtl.RELAY_SESSION_SECONDS

    refreshed_version = RelayVersionMetadata(
        shipagent_core_version="1.0.1",
        registry_contract_version="registry-v2",
        ups_boundary_contract_version="ups-v2",
        capabilities=["rate_shipment", "get_shipagent_status"],
    )
    await registry.refresh_session(
        "acct-1",
        device.device_id,
        session.relay_session_id,
        version=refreshed_version,
        active_source_fingerprint="source:desktop-build-42",
    )
    refreshed_payload = await redis.get(heartbeat_key)
    assert refreshed_payload is not None
    refreshed_heartbeat = RelayHeartbeat.model_validate_json(refreshed_payload)
    assert refreshed_heartbeat.version == refreshed_version
    assert refreshed_heartbeat.active_source_fingerprint == "source:desktop-build-42"

    await redis.delete(session_key, heartbeat_key, active_target_key)
    await registry.refresh_session(
        "acct-1",
        device.device_id,
        session.relay_session_id,
    )

    assert session_key not in redis.values
    assert heartbeat_key not in redis.values
    assert active_target_key not in redis.values


async def test_liveness_cleanup_ignores_malformed_session_without_clearing_unrelated_active_target(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    session_key = RedisKey.relay_session("device-1")
    heartbeat_key = RedisKey.relay_heartbeat("device-1")
    active_target_key = RedisKey.relay_active_target("acct-1")
    unrelated_active = RelaySession(
        account_id="acct-1",
        device_id="device-2",
        relay_session_id="session-2",
        execution_target_id="relay:device-2",
        state=RelayTargetState.READY,
        version=VERSION,
    )
    await redis.set(session_key, "not-json")
    await redis.set(heartbeat_key, "heartbeat")
    await redis.set(active_target_key, unrelated_active.model_dump_json())

    await registry.refresh_session(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
    )
    await registry.disconnect_session(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
    )

    assert await redis.get(active_target_key) == unrelated_active.model_dump_json()


async def test_liveness_cleanup_ignores_scalar_json_session_without_clearing_unrelated_active_target(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    session_key = RedisKey.relay_session("device-1")
    heartbeat_key = RedisKey.relay_heartbeat("device-1")
    active_target_key = RedisKey.relay_active_target("acct-1")
    unrelated_active = RelaySession(
        account_id="acct-1",
        device_id="device-2",
        relay_session_id="session-2",
        execution_target_id="relay:device-2",
        state=RelayTargetState.READY,
        version=VERSION,
    )
    await redis.set(session_key, "123")
    await redis.set(heartbeat_key, "heartbeat")
    await redis.set(active_target_key, unrelated_active.model_dump_json())
    redis.ttls[session_key] = 1
    redis.ttls[heartbeat_key] = 1
    redis.ttls[active_target_key] = 1

    await registry.refresh_session(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
    )
    await registry.disconnect_session(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
    )

    assert await redis.get(active_target_key) == unrelated_active.model_dump_json()
    assert redis.ttls[session_key] == 1
    assert redis.ttls[heartbeat_key] == 1
    assert redis.ttls[active_target_key] == 1


async def test_refresh_and_disconnect_ignore_scalar_json_active_target(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    session = RelaySession(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
        execution_target_id="relay:device-1",
        state=RelayTargetState.READY,
        version=VERSION,
    )
    session_key = RedisKey.relay_session("device-1")
    heartbeat_key = RedisKey.relay_heartbeat("device-1")
    active_target_key = RedisKey.relay_active_target("acct-1")
    await redis.set(session_key, session.model_dump_json())
    await redis.set(heartbeat_key, "heartbeat")
    await redis.set(active_target_key, "123")
    redis.ttls[session_key] = 1
    redis.ttls[heartbeat_key] = 1
    redis.ttls[active_target_key] = 1

    await registry.refresh_session(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
    )
    await registry.disconnect_session(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
    )

    assert await redis.get(session_key) is None
    assert await redis.get(heartbeat_key) is None
    assert await redis.get(active_target_key) == "123"
    assert redis.ttls[active_target_key] == 1


async def test_rotate_and_revoke_ignore_scalar_json_active_target(control_db) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)

    rotate_device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    rotate_challenge = await registry.create_challenge(
        "acct-1", rotate_device.device_id
    )
    rotate_claims = build_handshake_claims(
        device_id=rotate_device.device_id,
        account_id="acct-1",
        relay_session_id=rotate_challenge.relay_session_id,
        nonce=rotate_challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(rotate_claims))
    active_target_key = RedisKey.relay_active_target("acct-1")
    await redis.set(active_target_key, "123")

    await registry.rotate_key(
        account_id="acct-1",
        device_id=rotate_device.device_id,
        public_key_pem=OTHER_KEYPAIR.public_key_pem,
    )

    assert await redis.get(RedisKey.relay_session(rotate_device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(rotate_device.device_id)) is None
    assert await redis.get(active_target_key) == "123"

    revoke_device = await registry.register_device(
        "acct-1",
        "Warehouse Mac",
        THIRD_KEYPAIR.public_key_pem,
    )
    revoke_challenge = await registry.create_challenge(
        "acct-1", revoke_device.device_id
    )
    revoke_claims = build_handshake_claims(
        device_id=revoke_device.device_id,
        account_id="acct-1",
        relay_session_id=revoke_challenge.relay_session_id,
        nonce=revoke_challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(
        THIRD_KEY_SERVICE.sign_handshake_claims(revoke_claims)
    )
    await redis.set(active_target_key, "123")

    await registry.revoke_device("acct-1", revoke_device.device_id)

    assert await redis.get(RedisKey.relay_session(revoke_device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(revoke_device.device_id)) is None
    assert await redis.get(active_target_key) == "123"


async def test_create_challenge_rejects_missing_device(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())

    try:
        await registry.create_challenge("acct-1", "missing-device")
    except ValueError as exc:
        assert "device not found" in str(exc)
    else:
        raise AssertionError("expected missing device to be rejected")


async def test_create_challenge_rejects_revoked_device(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    await registry.revoke_device("acct-1", device.device_id)

    try:
        await registry.create_challenge("acct-1", device.device_id)
    except ValueError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("expected revoked device to be rejected")


async def test_accept_handshake_stores_session_and_heartbeat(control_db) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )

    signed = KEY_SERVICE.sign_handshake_claims(claims)

    session = await registry.accept_handshake(signed)

    assert session.account_id == "acct-1"
    assert session.device_id == device.device_id
    assert session.relay_session_id == challenge.relay_session_id
    assert session.execution_target_id == f"relay:{device.device_id}"
    assert session.state == RelayTargetState.READY
    assert (
        redis.ttls[RedisKey.relay_session(device.device_id)]
        == RedisTtl.RELAY_SESSION_SECONDS
    )
    assert (
        redis.ttls[RedisKey.relay_heartbeat(device.device_id)]
        == RedisTtl.RELAY_SESSION_SECONDS
    )
    heartbeat = RelayHeartbeat.model_validate_json(
        await redis.get(RedisKey.relay_heartbeat(device.device_id))
    )
    assert heartbeat.relay_session_id == challenge.relay_session_id
    assert heartbeat.active_source_fingerprint is None


async def test_source_metadata_does_not_need_to_match_relay_key_fingerprint(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )

    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    handshake_heartbeat = RelayHeartbeat.model_validate_json(
        await redis.get(RedisKey.relay_heartbeat(device.device_id))
    )
    assert handshake_heartbeat.active_source_fingerprint is None

    await registry.refresh_session(
        "acct-1",
        device.device_id,
        challenge.relay_session_id,
        active_source_fingerprint="source:desktop-build-42",
    )

    active_heartbeat = await registry.get_active_heartbeat("acct-1")
    assert active_heartbeat is not None
    assert active_heartbeat.active_source_fingerprint == "source:desktop-build-42"


async def test_two_accepted_sessions_never_publish_mixed_liveness_records(
    control_db,
) -> None:
    redis = InterleavingRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    first_challenge = await registry.create_challenge("acct-1", device.device_id)
    second_challenge = await registry.create_challenge("acct-1", device.device_id)
    first_handshake = KEY_SERVICE.sign_handshake_claims(
        build_handshake_claims(
            device_id=device.device_id,
            account_id="acct-1",
            relay_session_id=first_challenge.relay_session_id,
            nonce=first_challenge.nonce,
            version=VERSION,
        )
    )
    second_handshake = KEY_SERVICE.sign_handshake_claims(
        build_handshake_claims(
            device_id=device.device_id,
            account_id="acct-1",
            relay_session_id=second_challenge.relay_session_id,
            nonce=second_challenge.nonce,
            version=VERSION,
        )
    )
    redis.arm_publish_race(RedisKey.relay_session(device.device_id))

    first_task = asyncio.create_task(
        registry.accept_handshake(first_handshake, first_challenge.relay_session_id)
    )
    await asyncio.wait_for(redis.publish_started.wait(), timeout=1)
    second_task = asyncio.create_task(
        registry.accept_handshake(
            second_handshake,
            second_challenge.relay_session_id,
        )
    )
    await asyncio.sleep(0)
    assert not second_task.done()
    redis.publish_release.set()
    first = await first_task
    second = await second_task

    session = RelaySession.model_validate_json(
        await redis.get(RedisKey.relay_session(device.device_id))
    )
    heartbeat = RelayHeartbeat.model_validate_json(
        await redis.get(RedisKey.relay_heartbeat(device.device_id))
    )
    active = RelaySession.model_validate_json(
        await redis.get(RedisKey.relay_active_target("acct-1"))
    )

    assert (
        len(
            {
                session.relay_session_id,
                heartbeat.relay_session_id,
                active.relay_session_id,
            }
        )
        == 1
    )
    assert session.relay_session_id in {
        first.relay_session_id,
        second.relay_session_id,
    }


async def test_accept_handshake_does_not_require_redis_device_record(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    assert await redis.get(RedisKey.relay_device("acct-1", device.device_id)) is None
    assert session.state == RelayTargetState.READY
    assert await redis.get(RedisKey.relay_session(device.device_id)) is not None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is not None


async def test_accept_handshake_rechecks_durable_device_before_publishing_liveness(
    control_db,
) -> None:
    await _ensure_account(control_db)
    redis = FakeRedis()
    registry = RotatingBeforePublishRegistry(redis, control_db)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    registry.arm_rotation_before_publish()

    with pytest.raises(ValueError, match="device changed"):
        await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))

    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None


async def test_accept_handshake_rejects_wrong_account(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-2",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )

    try:
        await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    except ValueError as exc:
        assert "wrong account" in str(exc)
    else:
        raise AssertionError("expected wrong account to be rejected")


async def test_accept_handshake_rejects_unsigned_claims(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )

    try:
        await registry.accept_handshake(claims)
    except ValueError as exc:
        assert "token" in str(exc)
    else:
        raise AssertionError("expected unsigned claims to be rejected")


async def test_accept_handshake_rejects_claims_signed_by_unregistered_key(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    signed = OTHER_KEY_SERVICE.sign_handshake_claims(claims)

    try:
        await registry.accept_handshake(signed)
    except ValueError as exc:
        assert "handshake token" in str(exc)
    else:
        raise AssertionError("expected unregistered signing key to be rejected")


async def test_accept_handshake_consumes_challenge_once(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    signed = KEY_SERVICE.sign_handshake_claims(claims)

    await registry.accept_handshake(signed)

    try:
        await registry.accept_handshake(signed)
    except ValueError as exc:
        assert "challenge" in str(exc)
    else:
        raise AssertionError("expected consumed challenge replay to be rejected")


async def test_accept_handshake_allows_only_one_concurrent_accept(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    signed = KEY_SERVICE.sign_handshake_claims(claims)

    results = await asyncio.gather(
        registry.accept_handshake(signed),
        registry.accept_handshake(signed),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, ValueError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert "challenge" in str(failures[0])


async def test_accept_handshake_allows_only_one_concurrent_accept_without_getdel(
    control_db,
) -> None:
    redis = NoGetDelConcurrentRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    signed = KEY_SERVICE.sign_handshake_claims(claims)
    redis.arm_concurrent_get(RedisKey.relay_challenge(challenge.relay_session_id))

    results = await asyncio.gather(
        registry.accept_handshake(signed),
        registry.accept_handshake(signed),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, ValueError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert "challenge" in str(failures[0])


async def test_accept_handshake_rejects_claims_without_stored_challenge(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id="forged-session",
        nonce="forged-nonce",
        version=VERSION,
    )
    signed = KEY_SERVICE.sign_handshake_claims(claims)

    try:
        await registry.accept_handshake(signed)
    except ValueError as exc:
        assert "challenge" in str(exc)
    else:
        raise AssertionError("expected missing stored challenge to be rejected")


async def test_accept_handshake_rejects_wrong_nonce(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce="wrong-nonce",
        version=VERSION,
    )

    try:
        await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    except ValueError as exc:
        assert "nonce" in str(exc)
    else:
        raise AssertionError("expected wrong nonce to be rejected")


async def test_accept_handshake_rejects_claims_for_different_device_than_challenge(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    challenged_device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    other_device = await registry.register_device(
        "acct-1", "Warehouse Mac", OTHER_KEYPAIR.public_key_pem
    )
    challenge = await registry.create_challenge("acct-1", challenged_device.device_id)
    claims = build_handshake_claims(
        device_id=other_device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )

    try:
        await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    except ValueError as exc:
        assert "device" in str(exc)
    else:
        raise AssertionError("expected claims for a different device to be rejected")


async def test_accept_handshake_rejects_device_revoked_after_challenge(
    control_db,
) -> None:
    registry = await _registry(control_db, FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.revoke_device("acct-1", device.device_id)

    try:
        await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    except ValueError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("expected revoked device to be rejected")


async def test_relay_execution_target_reports_unavailable_without_active_target(
    control_db,
) -> None:
    try:
        from src.control_plane.execution_targets import RelayExecutionTarget
    except ImportError as exc:
        raise AssertionError(f"relay execution target is not available: {exc}") from exc

    registry = await _registry(control_db, FakeRedis())
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(RelayExecutionTarget(registry), context)

    assert status.model_dump(mode="json", by_alias=True) == {
        "status": "offline",
        "executionTarget": {
            "state": "offline",
            "target_id": None,
            "capabilities": [],
            "message": "No active execution target connected.",
        },
    }


async def test_relay_execution_target_reports_unavailable_with_malformed_active_target(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    await redis.set(RedisKey.relay_active_target("acct-1"), "not-json")
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(RelayExecutionTarget(registry), context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_unavailable_with_malformed_active_target_bytes(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    await redis.set(RedisKey.relay_active_target("acct-1"), b"\xff")
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(RelayExecutionTarget(registry), context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_unavailable_with_malformed_session(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    active = RelaySession(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
        execution_target_id="relay:device-1",
        state=RelayTargetState.READY,
        version=VERSION,
    )
    await redis.set(RedisKey.relay_active_target("acct-1"), active.model_dump_json())
    await redis.set(RedisKey.relay_session("device-1"), "not-json")
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(RelayExecutionTarget(registry), context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_unavailable_with_malformed_heartbeat(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    active = RelaySession(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
        execution_target_id="relay:device-1",
        state=RelayTargetState.READY,
        version=VERSION,
    )
    await redis.set(RedisKey.relay_active_target("acct-1"), active.model_dump_json())
    await redis.set(RedisKey.relay_session("device-1"), active.model_dump_json())
    await redis.set(RedisKey.relay_heartbeat("device-1"), "not-json")
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(RelayExecutionTarget(registry), context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_ready_after_handshake(control_db) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    broker = FakeStatusInvocationBroker(session)
    target = RelayExecutionTarget(registry, broker)
    status = await _status_from_target(target, context)
    generic_result = await target.invoke(
        TargetToolRequest(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            tool_name="future_target_tool",
            arguments={"probe": "value"},
            correlation_id="generic-corr-1",
        )
    )

    assert status.model_dump(mode="json", by_alias=True) == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": session.execution_target_id,
            "capabilities": ["rate_shipment"],
            "message": None,
        },
    }
    assert generic_result == status.model_dump(mode="json", by_alias=True)
    assert broker.calls == [
        {
            "relay_session_id": session.relay_session_id,
            "tool_name": "get_shipagent_status",
            "arguments": {},
            "audit_correlation_id": "get_shipagent_status",
            "timeout_seconds": 2,
        },
        {
            "relay_session_id": session.relay_session_id,
            "tool_name": "future_target_tool",
            "arguments": {"probe": "value"},
            "audit_correlation_id": "generic-corr-1",
            "timeout_seconds": 2,
        },
    ]


async def test_relay_execution_target_maps_send_failure_to_offline_status(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    broker = RelayInvocationBroker()
    await broker.register(
        session.relay_session_id,
        FailingSendRelayConnection(),
        account_id=session.account_id,
        device_id=session.device_id,
    )

    status = await _status_from_target(
        RelayExecutionTarget(registry, broker),
        context,
    )

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE
    assert status.execution_target.target_id is None
    with pytest.raises(NoLiveRelaySession):
        await broker.invoke(
            relay_session_id=session.relay_session_id,
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="second-attempt",
            timeout_seconds=1,
        )


async def test_relay_execution_target_maps_busy_session_to_offline_status(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(
        RelayExecutionTarget(registry, BusyStatusInvocationBroker(session)),
        context,
    )

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE
    assert status.execution_target.target_id is None


async def test_get_active_heartbeat_rejects_revoked_durable_device(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    record = await control_db.get(RelayDeviceRecord, device.device_id)
    record.revoked = True
    await control_db.commit()

    assert await registry.get_active_heartbeat("acct-1") is None
    assert await redis.get(RedisKey.relay_session(device.device_id)) is not None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is not None


async def test_get_active_heartbeat_uses_liveness_identity_not_relay_key_fingerprint(
    control_db,
) -> None:
    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    record = await control_db.get(RelayDeviceRecord, device.device_id)
    record.public_key_pem = OTHER_KEYPAIR.public_key_pem
    record.fingerprint = relay_public_key_fingerprint(OTHER_KEYPAIR.public_key_pem)
    await control_db.commit()

    active_heartbeat = await registry.get_active_heartbeat("acct-1")
    assert active_heartbeat is not None
    assert active_heartbeat.relay_session_id == challenge.relay_session_id
    assert await redis.get(RedisKey.relay_session(device.device_id)) is not None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is not None


async def test_relay_execution_target_filters_non_public_capabilities_from_status(
    control_db,
) -> None:
    from src.control_plane.execution_targets import RelayExecutionTarget

    redis = FakeRedis()
    registry = await _registry(control_db, redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    challenge = await registry.create_challenge("acct-1", device.device_id)
    version = VERSION.model_copy(
        update={
            "capabilities": [
                "rate_shipment",
                "account_number:123456",
                "get_shipagent_status",
                "raw_ups_payload:secret",
            ]
        }
    )
    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=version,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    status = await _status_from_target(
        RelayExecutionTarget(registry, FakeStatusInvocationBroker(session)),
        context,
    )

    assert status.execution_target.capabilities == [
        "rate_shipment",
        "get_shipagent_status",
    ]
