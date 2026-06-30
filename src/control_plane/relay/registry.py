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

_DISCONNECT_SESSION_SCRIPT = """
local session = redis.call("GET", KEYS[1])
if not session then
    return 0
end
local ok, payload = pcall(cjson.decode, session)
if not ok or payload["relay_session_id"] ~= ARGV[1] then
    return 0
end
local active = redis.call("GET", KEYS[3])
if active then
    local active_ok, active_payload = pcall(cjson.decode, active)
    if active_ok
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
if not ok or payload["relay_session_id"] ~= ARGV[1] then
    return 0
end
redis.call("EXPIRE", KEYS[1], tonumber(ARGV[2]))
redis.call("EXPIRE", KEYS[2], tonumber(ARGV[2]))
local active = redis.call("GET", KEYS[3])
if active then
    local active_ok, active_payload = pcall(cjson.decode, active)
    if active_ok
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

_PUBLISH_SESSION_SCRIPT = """
local device = redis.call("GET", KEYS[1])
if not device then
    return "missing"
end
local ok, payload = pcall(cjson.decode, device)
if not ok then
    return "missing"
end
if payload["revoked"] == true then
    return "revoked"
end
if payload["fingerprint"] ~= ARGV[1] or payload["public_key_pem"] ~= ARGV[2] then
    return "stale"
end
redis.call("SET", KEYS[2], ARGV[3], "EX", tonumber(ARGV[5]))
redis.call("SET", KEYS[3], ARGV[4], "EX", tonumber(ARGV[5]))
redis.call("SET", KEYS[4], ARGV[3], "EX", tonumber(ARGV[5]))
return "ok"
"""

_STORE_DEVICE_CLEAR_LIVENESS_SCRIPT = """
local function clear_current_liveness()
    local session = redis.call("GET", KEYS[2])
    if session then
        local session_ok, session_payload = pcall(cjson.decode, session)
        local active = redis.call("GET", KEYS[4])
        if session_ok and active then
            local active_ok, active_payload = pcall(cjson.decode, active)
            if active_ok
                and active_payload["device_id"] == session_payload["device_id"]
                and active_payload["relay_session_id"] == session_payload["relay_session_id"]
            then
                return redis.call("DEL", KEYS[2], KEYS[3], KEYS[4])
            end
        end
    end
    return redis.call("DEL", KEYS[2], KEYS[3])
end

local device = redis.call("GET", KEYS[1])
if not device then
    return "missing"
end
local ok, payload = pcall(cjson.decode, device)
if not ok then
    return "missing"
end
if payload["revoked"] == true then
    clear_current_liveness()
    return "revoked"
end
redis.call("SET", KEYS[1], ARGV[1])
clear_current_liveness()
return "ok"
"""

_REVOKE_DEVICE_SCRIPT = """
local function clear_current_liveness()
    local session = redis.call("GET", KEYS[2])
    if session then
        local session_ok, session_payload = pcall(cjson.decode, session)
        local active = redis.call("GET", KEYS[4])
        if session_ok and active then
            local active_ok, active_payload = pcall(cjson.decode, active)
            if active_ok
                and active_payload["device_id"] == session_payload["device_id"]
                and active_payload["relay_session_id"] == session_payload["relay_session_id"]
            then
                return redis.call("DEL", KEYS[2], KEYS[3], KEYS[4])
            end
        end
    end
    return redis.call("DEL", KEYS[2], KEYS[3])
end

local device = redis.call("GET", KEYS[1])
if not device then
    return "missing"
end
local ok, payload = pcall(cjson.decode, device)
if not ok then
    return "missing"
end
payload["revoked"] = true
local revoked = cjson.encode(payload)
redis.call("SET", KEYS[1], revoked)
clear_current_liveness()
return revoked
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
        rotate_status = await self._redis.eval(
            _STORE_DEVICE_CLEAR_LIVENESS_SCRIPT,
            4,
            RedisKey.relay_device(account_id, device_id),
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(account_id),
            rotated.model_dump_json(),
        )
        if isinstance(rotate_status, bytes):
            rotate_status = rotate_status.decode("utf-8")
        if rotate_status != "ok":
            if rotate_status == "revoked":
                raise ValueError("device revoked")
            raise ValueError("device not found")
        return rotated

    async def revoke_device(self, account_id: str, device_id: str) -> RelayDevice:
        revoked_payload = await self._redis.eval(
            _REVOKE_DEVICE_SCRIPT,
            4,
            RedisKey.relay_device(account_id, device_id),
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(account_id),
        )
        if isinstance(revoked_payload, bytes):
            revoked_payload = revoked_payload.decode("utf-8")
        if revoked_payload == "missing":
            raise ValueError("device not found")
        return RelayDevice.model_validate_json(revoked_payload)

    async def disconnect_session(self, device_id: str, relay_session_id: str) -> None:
        session = await self._get_session(device_id)
        await self._redis.eval(
            _DISCONNECT_SESSION_SCRIPT,
            3,
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(session.account_id)
            if session is not None
            else RedisKey.relay_active_target("_unknown"),
            relay_session_id,
        )

    async def refresh_session(self, device_id: str, relay_session_id: str) -> None:
        session = await self._get_session(device_id)
        await self._redis.eval(
            _REFRESH_SESSION_SCRIPT,
            3,
            RedisKey.relay_session(device_id),
            RedisKey.relay_heartbeat(device_id),
            RedisKey.relay_active_target(session.account_id)
            if session is not None
            else RedisKey.relay_active_target("_unknown"),
            relay_session_id,
            str(RedisTtl.RELAY_SESSION_SECONDS),
        )

    async def get_active_heartbeat(self, account_id: str) -> RelayHeartbeat | None:
        payload = await self._redis.get(RedisKey.relay_active_target(account_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        active = RelaySession.model_validate_json(payload)
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
        publish_status = await self._redis.eval(
            _PUBLISH_SESSION_SCRIPT,
            4,
            RedisKey.relay_device(binding.account_id, binding.device_id),
            RedisKey.relay_session(session.device_id),
            RedisKey.relay_heartbeat(session.device_id),
            RedisKey.relay_active_target(session.account_id),
            device.fingerprint,
            device.public_key_pem,
            session.model_dump_json(),
            heartbeat.model_dump_json(),
            str(RedisTtl.RELAY_SESSION_SECONDS),
        )
        if isinstance(publish_status, bytes):
            publish_status = publish_status.decode("utf-8")
        if publish_status != "ok":
            if publish_status == "revoked":
                raise ValueError("device revoked")
            if publish_status == "missing":
                raise ValueError("device not found")
            raise ValueError("device changed")
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
        await self._redis.set(
            RedisKey.relay_device(device.account_id, device.device_id),
            device.model_dump_json(),
        )

    async def _get_session(self, device_id: str) -> RelaySession | None:
        payload = await self._redis.get(RedisKey.relay_session(device_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return RelaySession.model_validate_json(payload)

    async def _get_heartbeat(self, device_id: str) -> RelayHeartbeat | None:
        payload = await self._redis.get(RedisKey.relay_heartbeat(device_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return RelayHeartbeat.model_validate_json(payload)
