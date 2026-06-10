from dataclasses import asdict

from fastapi import Request
from fastapi.testclient import TestClient

from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService


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
    async def resolve(self, *, subject: str, client_id: str, scopes: set[str]) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
        )


def _build_app_with_routes(monkeypatch, database_url: str):
    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", database_url)
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")

    monkeypatch.setattr("src.control_plane.app.Auth0TokenVerifier", _TokenVerifier)
    monkeypatch.setattr("src.control_plane.app.AuthorizationService", _AuthorizationService)

    app = create_control_plane_app()

    @app.get("/_probe")
    async def probe(request: Request):
        authorization = getattr(request.state, "authorization", None)
        return {
            "has_context": authorization is not None,
            "authorization": asdict(authorization) if authorization is not None else None,
        }

    return app


def test_protected_resource_metadata(monkeypatch):
    app = _build_app_with_routes(monkeypatch, "sqlite+aiosqlite:///:memory:")
    with TestClient(app) as client:
        response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json()["resource"] == "https://dev-mcp.shipagent.app"
    assert response.json()["authorization_servers"] == ["https://tenant.us.auth0.com/"]


def test_missing_token_returns_bearer_challenge(monkeypatch):
    app = _build_app_with_routes(monkeypatch, "sqlite+aiosqlite:///:memory:")
    with TestClient(app) as client:
        response = client.get("/_probe")

    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_valid_token_populates_context(monkeypatch):
    app = _build_app_with_routes(monkeypatch, "sqlite+aiosqlite:///:memory:")
    with TestClient(app) as client:
        response = client.get(
            "/_probe",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_context"] is True
    assert payload["authorization"]["account_id"] == "acct-1"
    assert payload["authorization"]["provider_connection_id"] == "pc-1"
    assert payload["authorization"]["provider_surface"] == "chatgpt"
    assert payload["authorization"]["subject"] == "auth0|owner-1"
    assert payload["authorization"]["client_id"] == "chatgpt-client"
    assert set(payload["authorization"]["scopes"]) == {
        "jobs:read",
        "shipments:preview",
    }
