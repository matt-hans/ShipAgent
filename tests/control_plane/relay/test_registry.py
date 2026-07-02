from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.models import CloudAccount
from src.control_plane.models import RelayDevice as RelayDeviceRecord
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    RelayHeartbeat,
    RelayInvocationResultFrame,
    RelayTargetState,
    RelayVersionMetadata,
    ShipAgentStatus,
    build_handshake_claims,
    relay_public_key_fingerprint,
)
from src.control_plane.relay.registry import RelayDeviceRegistry, RelaySession
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
            type="invocation_result",
            relay_session_id=relay_session_id,
            relay_invocation_id="test-invocation",
            status="ok",
            result=status.model_dump(mode="json", by_alias=True),
        )


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
        if numkeys == 1:
            key = keys_and_args[0]
            self.ttls.pop(key, None)
            return self.values.pop(key, None)
        if numkeys == 4 and len(keys_and_args) == 5:
            device_key, session_key, heartbeat_key, active_target_key, device_payload = (
                keys_and_args
            )
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
        if numkeys == 3 and len(keys_and_args) == 5:
            session_key, heartbeat_key, active_target_key, expected_relay_session_id, ttl = (
                keys_and_args
            )
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
            if session.get("relay_session_id") != expected_relay_session_id:
                return 0
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

    def arm_cleanup_race(
        self,
        *,
        session_key: str,
        race_values: dict[str, str],
    ) -> None:
        self.race_session_key = session_key
        self.race_values = race_values
        self.race_armed = True

    async def get(self, key: str):
        value = await super().get(key)
        if self.race_armed and key == self.race_session_key:
            self.values.update(self.race_values)
            self.race_armed = False
        return value

    async def eval(self, script: str, numkeys: int, *keys_and_args: str):
        if numkeys in {2, 3}:
            session_key = keys_and_args[0]
        else:
            session_key = None
        if session_key is not None and self.race_armed and session_key == self.race_session_key:
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

    async def _clear_current_liveness(self, account_id: str, device_id: str) -> None:
        await super()._clear_current_liveness(account_id, device_id)
        if self._armed_device_id != device_id:
            return
        record = await self._db_session.get(RelayDeviceRecord, device_id)
        record.revoked = True
        await self._db_session.commit()
        self._armed_device_id = None


def test_relay_device_registry_requires_durable_store() -> None:
    with pytest.raises(ValueError, match="durable device store"):
        RelayDeviceRegistry(FakeRedis())


async def test_register_device_can_be_read_without_private_key_material(control_db) -> None:
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


async def test_list_devices_returns_account_devices_only(control_db) -> None:
    await _ensure_account(control_db, "acct-2")
    registry = await _registry(control_db, FakeRedis())
    first = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    second = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
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
    second = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)

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
    second = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
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

    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(second_claims))

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(first_session),
    ).status(context)
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
    second = await first_registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
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
        KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await RelayExecutionTarget(fresh_registry).status(context)
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
    second = await first_registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
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
        KEY_SERVICE.sign_handshake_claims(second_claims)
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await RelayExecutionTarget(
        fresh_registry,
        FakeStatusInvocationBroker(second_session),
    ).status(context)
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
    second = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
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
        KEY_SERVICE.sign_handshake_claims(second_claims)
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
    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(second_session),
    ).status(context)
    assert selected.active is True
    assert await redis.get(RedisKey.relay_session(first.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(first.device_id)) is None
    assert status.execution_target.target_id == second_session.execution_target_id


async def test_set_active_device_rejects_missing_and_revoked_devices(control_db) -> None:
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


async def test_register_device_derives_fingerprint_ignoring_caller_value(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())

    device = await registry.register_device(
        account_id="acct-1",
        device_name="Dock Mac",
        public_key_pem=PUBLIC_KEY,
        fingerprint="sha256:attacker-controlled",
    )

    assert device.fingerprint == relay_public_key_fingerprint(PUBLIC_KEY)


async def test_rotate_key_preserves_device_id_and_updates_public_key(control_db) -> None:
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


async def test_rotate_key_clears_ready_liveness_and_rejects_old_key_claims(control_db) -> None:
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
        assert "signature" in str(exc)
    else:
        raise AssertionError("expected old-key signed claims to be rejected")
    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None
    assert await redis.get(RedisKey.relay_active_target("acct-1")) is None


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
    second_device = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
    second_challenge = await registry.create_challenge("acct-1", second_device.device_id)
    second_claims = build_handshake_claims(
        device_id=second_device.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(second_claims)
    )
    await registry.set_active_device("acct-1", second_device.device_id)

    await registry.rotate_key(
        account_id="acct-1",
        device_id=first_device.device_id,
        public_key_pem=OTHER_KEYPAIR.public_key_pem,
    )

    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(second_session),
    ).status(context)
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


async def test_revoke_device_marks_revoked_and_clears_active_session(control_db) -> None:
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


async def test_revoke_device_does_not_leave_revoked_device_with_stale_liveness(control_db) -> None:
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
    second_device = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
    second_challenge = await registry.create_challenge("acct-1", second_device.device_id)
    second_claims = build_handshake_claims(
        device_id=second_device.device_id,
        account_id="acct-1",
        relay_session_id=second_challenge.relay_session_id,
        nonce=second_challenge.nonce,
        version=VERSION,
    )
    second_session = await registry.accept_handshake(
        KEY_SERVICE.sign_handshake_claims(second_claims)
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
    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(second_session),
    ).status(context)
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


async def test_disconnect_session_does_not_clear_newer_ready_liveness(control_db) -> None:
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


async def test_disconnect_session_does_not_delete_newer_session_written_during_cleanup(control_db) -> None:
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
    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(second_session),
    ).status(context)

    assert stored_session.relay_session_id == second_session.relay_session_id
    assert heartbeat.relay_session_id == second_session.relay_session_id
    assert active.relay_session_id == second_session.relay_session_id
    assert status.execution_target.target_id == second_session.execution_target_id


async def test_refresh_session_extends_liveness_only_for_matching_session(control_db) -> None:
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

    await redis.delete(session_key, heartbeat_key, active_target_key)
    await registry.refresh_session(
        "acct-1",
        device.device_id,
        session.relay_session_id,
    )

    assert session_key not in redis.values
    assert heartbeat_key not in redis.values
    assert active_target_key not in redis.values


async def test_liveness_cleanup_ignores_malformed_session_without_clearing_unrelated_active_target(control_db) -> None:
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


async def test_liveness_cleanup_ignores_scalar_json_session_without_clearing_unrelated_active_target(control_db) -> None:
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


async def test_refresh_and_disconnect_ignore_scalar_json_active_target(control_db) -> None:
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
    rotate_challenge = await registry.create_challenge("acct-1", rotate_device.device_id)
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

    revoke_device = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
    revoke_challenge = await registry.create_challenge("acct-1", revoke_device.device_id)
    revoke_claims = build_handshake_claims(
        device_id=revoke_device.device_id,
        account_id="acct-1",
        relay_session_id=revoke_challenge.relay_session_id,
        nonce=revoke_challenge.nonce,
        version=VERSION,
    )
    await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(revoke_claims))
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
    assert redis.ttls[RedisKey.relay_session(device.device_id)] == RedisTtl.RELAY_SESSION_SECONDS
    assert redis.ttls[RedisKey.relay_heartbeat(device.device_id)] == RedisTtl.RELAY_SESSION_SECONDS
    heartbeat = RelayHeartbeat.model_validate_json(
        await redis.get(RedisKey.relay_heartbeat(device.device_id))
    )
    assert heartbeat.relay_session_id == challenge.relay_session_id
    assert heartbeat.active_source_fingerprint == device.fingerprint


async def test_accept_handshake_does_not_require_redis_device_record(control_db) -> None:
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
        assert "signed" in str(exc)
    else:
        raise AssertionError("expected unsigned claims to be rejected")


async def test_accept_handshake_rejects_claims_signed_by_unregistered_key(control_db) -> None:
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
        assert "signature" in str(exc)
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


async def test_accept_handshake_allows_only_one_concurrent_accept_without_getdel(control_db) -> None:
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


async def test_accept_handshake_rejects_claims_without_stored_challenge(control_db) -> None:
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


async def test_accept_handshake_rejects_claims_for_different_device_than_challenge(control_db) -> None:
    registry = await _registry(control_db, FakeRedis())
    challenged_device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    other_device = await registry.register_device("acct-1", "Warehouse Mac", PUBLIC_KEY)
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


async def test_accept_handshake_rejects_device_revoked_after_challenge(control_db) -> None:
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


async def test_relay_execution_target_reports_unavailable_without_active_target(control_db) -> None:
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

    status = await RelayExecutionTarget(registry).status(context)

    assert status.model_dump(mode="json", by_alias=True) == {
        "status": "offline",
        "executionTarget": {
            "state": "offline",
            "target_id": None,
            "capabilities": [],
            "message": "No active execution target connected.",
        },
    }


async def test_relay_execution_target_reports_unavailable_with_malformed_active_target(control_db) -> None:
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

    status = await RelayExecutionTarget(registry).status(context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_unavailable_with_malformed_active_target_bytes(control_db) -> None:
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

    status = await RelayExecutionTarget(registry).status(context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_unavailable_with_malformed_session(control_db) -> None:
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

    status = await RelayExecutionTarget(registry).status(context)

    assert status.status == RelayTargetState.OFFLINE
    assert status.execution_target.state == RelayTargetState.OFFLINE


async def test_relay_execution_target_reports_unavailable_with_malformed_heartbeat(control_db) -> None:
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

    status = await RelayExecutionTarget(registry).status(context)

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

    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(session),
    ).status(context)

    assert status.model_dump(mode="json", by_alias=True) == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": session.execution_target_id,
            "capabilities": ["rate_shipment"],
            "message": None,
        },
    }


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


async def test_get_active_heartbeat_rejects_rotated_durable_device(
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

    assert await registry.get_active_heartbeat("acct-1") is None
    assert await redis.get(RedisKey.relay_session(device.device_id)) is not None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is not None


async def test_relay_execution_target_filters_non_public_capabilities_from_status(control_db) -> None:
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

    status = await RelayExecutionTarget(
        registry,
        FakeStatusInvocationBroker(session),
    ).status(context)

    assert status.execution_target.capabilities == [
        "rate_shipment",
        "get_shipagent_status",
    ]
