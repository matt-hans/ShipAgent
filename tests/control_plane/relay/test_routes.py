from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayVersionMetadata,
    build_handshake_claims,
)
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
PRIVATE_KEY = "-----BEGIN ED25519 PRIVATE KEY-----\nsecret\n-----END ED25519 PRIVATE KEY-----\n"
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
        if numkeys == 3 and len(keys_and_args) == 4:
            device_key, session_key, heartbeat_key, device_payload = keys_and_args
            self.values[device_key] = device_payload
            await self.delete(session_key, heartbeat_key)
            return "ok"
        if numkeys == 3:
            (
                device_key,
                session_key,
                heartbeat_key,
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
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            return "ok"
        if numkeys == 2 and len(keys_and_args) == 4:
            session_key, heartbeat_key, expected_relay_session_id, ttl = keys_and_args
            payload = self.values.get(session_key)
            if payload is None or heartbeat_key not in self.values:
                return 0
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            session = json.loads(payload)
            if session.get("relay_session_id") != expected_relay_session_id:
                return 0
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            return 1
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


class _TokenVerifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def verify(self, token: str) -> TokenPrincipal:
        return TokenPrincipal(
            subject="auth0|owner-1",
            client_id="chatgpt-client",
            scopes=frozenset({"jobs:read", "shipments:preview"}),
        )


class _AuthorizationService(AuthorizationService):
    async def resolve(
        self, *, subject: str, client_id: str, scopes: set[str]
    ) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
        )


def _build_app(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr("src.control_plane.app.Auth0TokenVerifier", _TokenVerifier)
    monkeypatch.setattr(
        "src.control_plane.app.AuthorizationService", _AuthorizationService
    )
    monkeypatch.setattr("src.control_plane.app._build_redis_client", lambda _: redis)
    return create_control_plane_app(), redis


def test_register_device_returns_public_device_record(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"].startswith("relay_device_")
    assert payload["fingerprint"].startswith("sha256:")
    assert payload["revoked"] is False
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_register_device_rejects_private_key_material_with_validation_error(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 422
    assert PRIVATE_KEY not in response.text
    assert "PRIVATE KEY" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_register_device_rejects_invalid_public_key_with_validation_error(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": INVALID_PUBLIC_KEY},
        )

    assert response.status_code == 422
    assert INVALID_PUBLIC_KEY not in response.text
    assert "abc" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_register_device_rejects_extra_private_key_field_without_echoing_key_name(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)
    malicious_key = "-----BEGIN PRIVATE KEY-----"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={
                "device_name": "Dock Mac",
                "public_key_pem": PUBLIC_KEY,
                malicious_key: "attacker-controlled",
            },
        )

    assert response.status_code == 422
    assert malicious_key not in response.text
    assert "PRIVATE KEY" not in response.text
    assert "input" not in response.json()["detail"][0]
    assert "loc" not in response.json()["detail"][0]


def test_rotate_key_returns_updated_fingerprint(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)
    rotated_key = OTHER_KEYPAIR.public_key_pem

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer valid-token"},
            json={"public_key_pem": rotated_key},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"] == registered["device_id"]
    assert payload["fingerprint"] != registered["fingerprint"]
    assert payload["revoked"] is False
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_rotate_key_rejects_private_key_material_with_validation_error(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer valid-token"},
            json={"public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 422
    assert PRIVATE_KEY not in response.text
    assert "PRIVATE KEY" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_rotate_key_missing_device_returns_404(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/missing-device/rotate-key",
            headers={"Authorization": "Bearer valid-token"},
            json={"public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Relay device not found"}


def test_revoke_device_returns_revoked_record(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/revoke",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"] == registered["device_id"]
    assert payload["fingerprint"] == registered["fingerprint"]
    assert payload["revoked"] is True
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_revoke_missing_device_returns_404(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/missing-device/revoke",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Relay device not found"}


def test_register_device_requires_authorization(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 401


def test_connect_websocket_challenges_then_accepts_claims(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            accepted = websocket.receive_json()

    assert accepted == {
        "relay_session_id": challenge["relay_session_id"],
        "execution_target_id": f"relay:{registered['device_id']}",
        "state": "ready",
    }


def test_connect_websocket_disconnect_clears_ready_liveness(monkeypatch) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"

    assert RedisKey.relay_session(registered["device_id"]) not in redis.values
    assert RedisKey.relay_heartbeat(registered["device_id"]) not in redis.values


def test_connect_websocket_heartbeat_refreshes_ready_liveness(monkeypatch) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"
            session_key = RedisKey.relay_session(registered["device_id"])
            heartbeat_key = RedisKey.relay_heartbeat(registered["device_id"])
            redis.ttls[session_key] = 1
            redis.ttls[heartbeat_key] = 1

            websocket.send_text("heartbeat")
            time.sleep(0.01)

            assert redis.ttls[session_key] == RedisTtl.RELAY_SESSION_SECONDS
            assert redis.ttls[heartbeat_key] == RedisTtl.RELAY_SESSION_SECONDS


def test_connect_websocket_rejects_claims_for_different_outstanding_challenge(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as stale_websocket:
            stale_websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            stale_challenge = stale_websocket.receive_json()

        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=stale_challenge["relay_session_id"],
                nonce=stale_challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008


def test_connect_websocket_rejects_unsigned_claims(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            websocket.send_json(claims.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008


def test_connect_websocket_rejects_claims_for_different_device_than_hello(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        challenged = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        other = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Warehouse Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": challenged["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=other["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008
