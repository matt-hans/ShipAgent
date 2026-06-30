from __future__ import annotations

import asyncio
import json

from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayHeartbeat,
    RelayTargetState,
    RelayVersionMetadata,
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
        session_key, heartbeat_key, expected_relay_session_id = keys_and_args
        payload = self.values.get(session_key)
        if payload is None:
            return 0
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        session = json.loads(payload)
        if session.get("relay_session_id") != expected_relay_session_id:
            return 0
        return await self.delete(session_key, heartbeat_key)


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
        session_key = keys_and_args[0]
        if self.race_armed and session_key == self.race_session_key:
            self.values.update(self.race_values)
            self.race_armed = False
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
        key = keys_and_args[0]
        self.ttls.pop(key, None)
        return self.values.pop(key, None)


async def test_register_device_can_be_read_without_private_key_material() -> None:
    registry = RelayDeviceRegistry(FakeRedis())

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


async def test_register_device_rejects_private_key_material() -> None:
    redis = FakeRedis()
    registry = RelayDeviceRegistry(redis)

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


async def test_register_device_rejects_invalid_public_key_material() -> None:
    registry = RelayDeviceRegistry(FakeRedis())

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


async def test_register_device_derives_fingerprint_ignoring_caller_value() -> None:
    registry = RelayDeviceRegistry(FakeRedis())

    device = await registry.register_device(
        account_id="acct-1",
        device_name="Dock Mac",
        public_key_pem=PUBLIC_KEY,
        fingerprint="sha256:attacker-controlled",
    )

    assert device.fingerprint == relay_public_key_fingerprint(PUBLIC_KEY)


async def test_rotate_key_preserves_device_id_and_updates_public_key() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_rotate_key_derives_fingerprint_ignoring_caller_value() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_rotate_key_rejects_private_key_material() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_rotate_key_preserves_revoked_state() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    revoked = await registry.revoke_device("acct-1", device.device_id)
    rotated_key = OTHER_KEYPAIR.public_key_pem

    rotated = await registry.rotate_key(
        account_id="acct-1",
        device_id=device.device_id,
        public_key_pem=rotated_key,
    )

    assert rotated.revoked == revoked.revoked
    try:
        await registry.create_challenge("acct-1", device.device_id)
    except ValueError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("expected rotated revoked device to remain revoked")


async def test_revoke_device_marks_revoked_and_clears_active_session() -> None:
    redis = FakeRedis()
    registry = RelayDeviceRegistry(redis)
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    await redis.set(RedisKey.relay_session(device.device_id), "session")
    await redis.set(RedisKey.relay_heartbeat(device.device_id), "heartbeat")

    revoked = await registry.revoke_device("acct-1", device.device_id)

    stored = await registry.get_device("acct-1", device.device_id)
    assert stored == revoked
    assert revoked.revoked is True
    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None


async def test_disconnect_session_clears_ready_liveness() -> None:
    redis = FakeRedis()
    registry = RelayDeviceRegistry(redis)
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

    await registry.disconnect_session(device.device_id, session.relay_session_id)

    assert await redis.get(RedisKey.relay_session(device.device_id)) is None
    assert await redis.get(RedisKey.relay_heartbeat(device.device_id)) is None


async def test_disconnect_session_does_not_clear_newer_ready_liveness() -> None:
    redis = FakeRedis()
    registry = RelayDeviceRegistry(redis)
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


async def test_disconnect_session_does_not_delete_newer_session_written_during_cleanup() -> None:
    redis = InterleavingRedis()
    registry = RelayDeviceRegistry(redis)
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
    session_key = RedisKey.relay_session(device.device_id)
    heartbeat_key = RedisKey.relay_heartbeat(device.device_id)
    await redis.set(session_key, first_session_payload)
    await redis.set(heartbeat_key, first_heartbeat_payload)
    redis.arm_cleanup_race(
        session_key=session_key,
        race_values={
            session_key: second_session_payload,
            heartbeat_key: second_heartbeat_payload,
        },
    )

    await registry.disconnect_session(
        device.device_id,
        first_session.relay_session_id,
    )

    stored_session = RelaySession.model_validate_json(await redis.get(session_key))
    heartbeat = RelayHeartbeat.model_validate_json(await redis.get(heartbeat_key))
    assert stored_session.relay_session_id == second_session.relay_session_id
    assert heartbeat.relay_session_id == second_session.relay_session_id


async def test_create_challenge_rejects_missing_device() -> None:
    registry = RelayDeviceRegistry(FakeRedis())

    try:
        await registry.create_challenge("acct-1", "missing-device")
    except ValueError as exc:
        assert "device not found" in str(exc)
    else:
        raise AssertionError("expected missing device to be rejected")


async def test_create_challenge_rejects_revoked_device() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
    device = await registry.register_device("acct-1", "Dock Mac", PUBLIC_KEY)
    await registry.revoke_device("acct-1", device.device_id)

    try:
        await registry.create_challenge("acct-1", device.device_id)
    except ValueError as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("expected revoked device to be rejected")


async def test_accept_handshake_stores_session_and_heartbeat() -> None:
    redis = FakeRedis()
    registry = RelayDeviceRegistry(redis)
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


async def test_accept_handshake_rejects_wrong_account() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_rejects_unsigned_claims() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_rejects_claims_signed_by_unregistered_key() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_consumes_challenge_once() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_allows_only_one_concurrent_accept() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_allows_only_one_concurrent_accept_without_getdel() -> None:
    redis = NoGetDelConcurrentRedis()
    registry = RelayDeviceRegistry(redis)
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


async def test_accept_handshake_rejects_claims_without_stored_challenge() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_rejects_wrong_nonce() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_rejects_claims_for_different_device_than_challenge() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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


async def test_accept_handshake_rejects_device_revoked_after_challenge() -> None:
    registry = RelayDeviceRegistry(FakeRedis())
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
