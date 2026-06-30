from __future__ import annotations

from fastapi.testclient import TestClient

from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.relay.protocol import (
    RelayVersionMetadata,
    build_handshake_claims,
)

PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
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


def test_rotate_key_returns_updated_fingerprint(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)
    rotated_key = "-----BEGIN PUBLIC KEY-----\nrotated\n-----END PUBLIC KEY-----\n"

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
            websocket.send_json(claims.model_dump(mode="json"))
            accepted = websocket.receive_json()

    assert accepted == {
        "relay_session_id": challenge["relay_session_id"],
        "execution_target_id": f"relay:{registered['device_id']}",
        "state": "ready",
    }
