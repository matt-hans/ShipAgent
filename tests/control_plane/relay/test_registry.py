from __future__ import annotations

import asyncio

from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayHeartbeat,
    RelayTargetState,
    RelayVersionMetadata,
    build_handshake_claims,
    relay_public_key_fingerprint,
)
from src.control_plane.relay.registry import RelayDeviceRegistry
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
