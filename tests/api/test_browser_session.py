"""Tests for browser API session tokens and the session exchange."""

import secrets

import pytest
from fastapi.testclient import TestClient

from src.api.browser_session import (
    BROWSER_SESSION_COOKIE,
    BROWSER_SESSION_TTL_SECONDS,
    issue_browser_session,
    verify_browser_session,
)
from src.api.middleware.auth import reset_rate_limiter


@pytest.fixture(autouse=True)
def _reset_auth_rate_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def api_key() -> str:
    return "k" * 64


def test_browser_session_token_is_valid_for_the_issuing_key(api_key: str):
    token = issue_browser_session(api_key, now=1_000)

    assert verify_browser_session(token, api_key, now=1_001) is True
    assert api_key not in token


def test_browser_session_token_is_invalid_after_key_rotation(api_key: str):
    token = issue_browser_session(api_key, now=1_000)

    assert verify_browser_session(token, "r" * 64, now=1_001) is False


def test_browser_session_token_rejects_tampering(api_key: str):
    token = issue_browser_session(api_key, now=1_000)

    assert verify_browser_session(f"{token}x", api_key, now=1_001) is False


def test_browser_session_token_rejects_expiration(api_key: str):
    token = issue_browser_session(api_key, now=1_000)

    assert (
        verify_browser_session(
            token,
            api_key,
            now=1_000 + BROWSER_SESSION_TTL_SECONDS + 1,
        )
        is False
    )


def test_browser_session_token_rejects_future_issue_time(api_key: str):
    token = issue_browser_session(api_key, now=10_000)

    assert verify_browser_session(token, api_key, now=1_000) is False


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-token",
        "v1.invalid.invalid.nonce.signature",
        "v2.1000.2000.nonce.signature",
        None,
    ],
)
def test_browser_session_token_rejects_malformed_values(
    api_key: str,
    token: str | None,
):
    assert verify_browser_session(token, api_key, now=1_001) is False


def test_session_status_reports_authentication_disabled(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {"required": False, "authenticated": True}


def test_session_status_is_public_without_disclosing_a_configured_key(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setenv("SHIPAGENT_API_KEY", secrets.token_urlsafe(48))

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {"required": True, "authenticated": False}
    assert set(response.json()) == {"required", "authenticated"}


def test_browser_session_post_requires_valid_header(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setenv("SHIPAGENT_API_KEY", secrets.token_urlsafe(48))

    response = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": "incorrect"},
    )

    assert response.status_code == 401
    assert BROWSER_SESSION_COOKIE not in response.cookies


def test_header_exchange_grants_cookie_only_settings_access(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)

    created = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )

    assert created.status_code == 200
    assert created.json() == {"required": True, "authenticated": True}
    set_cookie = created.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api" in set_cookie
    assert f"Max-Age={BROWSER_SESSION_TTL_SECONDS}" in set_cookie
    assert key not in set_cookie

    assert client.get("/api/v1/auth/session").json() == {
        "required": True,
        "authenticated": True,
    }
    settings = client.get("/api/v1/settings")
    assert settings.status_code == 200


def test_browser_session_cookie_is_secure_for_https_requests(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)

    response = client.post(
        "https://testserver/api/v1/auth/session",
        headers={"X-API-Key": key},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_tampered_browser_session_cookie_is_rejected(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    token = issue_browser_session(key)
    client.cookies.set(BROWSER_SESSION_COOKIE, f"{token}x", path="/api")

    response = client.get("/api/v1/settings")

    assert response.status_code == 401


def test_rotating_api_key_invalidates_browser_session(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    assert (
        client.post(
            "/api/v1/auth/session",
            headers={"X-API-Key": key},
        ).status_code
        == 200
    )

    monkeypatch.setenv("SHIPAGENT_API_KEY", secrets.token_urlsafe(48))

    assert client.get("/api/v1/settings").status_code == 401


def test_clearing_browser_session_restores_authentication_gate(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    assert (
        client.post(
            "/api/v1/auth/session",
            headers={"X-API-Key": key},
        ).status_code
        == 200
    )

    cleared = client.delete("/api/v1/auth/session")

    assert cleared.status_code == 200
    assert cleared.json() == {"required": True, "authenticated": False}
    assert "Max-Age=0" in cleared.headers["set-cookie"]
    assert client.get("/api/v1/settings").status_code == 401
