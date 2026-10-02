"""Tests for browser API session tokens and the session exchange."""

import re
import secrets

import pytest
from fastapi.testclient import TestClient

from src.api.browser_session import (
    BROWSER_CSRF_HEADER,
    BROWSER_SESSION_COOKIE,
    BROWSER_SESSION_TTL_SECONDS,
    derive_browser_csrf_token,
    issue_browser_session,
    verify_browser_csrf_token,
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


def test_browser_csrf_token_is_bounded_and_bound_to_exact_session(api_key: str):
    first_session = issue_browser_session(api_key, now=1_000)
    second_session = issue_browser_session(api_key, now=1_000)

    csrf_token = derive_browser_csrf_token(first_session, api_key)

    assert csrf_token == derive_browser_csrf_token(first_session, api_key)
    assert re.fullmatch(r"v1\.[A-Za-z0-9_-]{43}", csrf_token)
    assert len(csrf_token) <= 64
    assert api_key not in csrf_token
    assert first_session not in csrf_token
    assert verify_browser_csrf_token(csrf_token, first_session, api_key) is True
    assert verify_browser_csrf_token(csrf_token, second_session, api_key) is False
    assert verify_browser_csrf_token(csrf_token, first_session, "r" * 64) is False


@pytest.mark.parametrize(
    "candidate",
    [None, "", "not-a-token", "v2.invalid", "v1.invalid", "x" * 513],
)
def test_browser_csrf_token_rejects_malformed_values(
    api_key: str,
    candidate: str | None,
):
    session_token = issue_browser_session(api_key, now=1_000)

    assert verify_browser_csrf_token(candidate, session_token, api_key) is False


def test_session_status_reports_authentication_disabled(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "required": False,
        "authenticated": True,
        "csrf_token": None,
    }


def test_session_status_is_public_without_disclosing_a_configured_key(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setenv("SHIPAGENT_API_KEY", secrets.token_urlsafe(48))

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "required": True,
        "authenticated": False,
        "csrf_token": None,
    }
    assert set(response.json()) == {"required", "authenticated", "csrf_token"}


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


def test_browser_session_renewal_always_requires_valid_header(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    created = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )
    original_cookie = created.cookies[BROWSER_SESSION_COOKIE]

    for headers in (
        {"Origin": "http://testserver"},
        {
            "Origin": "http://testserver",
            "X-API-Key": "incorrect",
        },
    ):
        rejected = client.post("/api/v1/auth/session", headers=headers)

        assert rejected.status_code == 401
        assert BROWSER_SESSION_COOKIE not in rejected.cookies
        assert client.cookies[BROWSER_SESSION_COOKIE] == original_cookie

    renewed = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )

    assert renewed.status_code == 200
    assert renewed.cookies[BROWSER_SESSION_COOKIE] != original_cookie


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
    assert created.json()["required"] is True
    assert created.json()["authenticated"] is True
    assert isinstance(created.json()["csrf_token"], str)
    assert len(created.json()["csrf_token"]) <= 64
    set_cookie = created.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api" in set_cookie
    assert f"Max-Age={BROWSER_SESSION_TTL_SECONDS}" in set_cookie
    assert key not in set_cookie

    assert client.get("/api/v1/auth/session").json() == {
        "required": True,
        "authenticated": True,
        "csrf_token": created.json()["csrf_token"],
    }
    settings = client.get("/api/v1/settings")
    assert settings.status_code == 200


def test_cookie_authenticated_mutations_require_origin_and_session_csrf(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    exchange = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )
    csrf_token = exchange.json()["csrf_token"]

    missing_origin = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={BROWSER_CSRF_HEADER: csrf_token},
    )
    hostile_same_site = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={
            "Origin": "http://attacker.testserver",
            BROWSER_CSRF_HEADER: csrf_token,
        },
    )
    missing_csrf = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={"Origin": "http://testserver"},
    )
    invalid_csrf = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={
            "Origin": "http://testserver",
            BROWSER_CSRF_HEADER: "v1.invalid",
        },
    )

    assert missing_origin.status_code == 403
    assert hostile_same_site.status_code == 403
    assert missing_csrf.status_code == 403
    assert invalid_csrf.status_code == 403
    assert client.get("/api/v1/settings").json()["onboarding_completed"] is False

    allowed_mutation = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={
            "Origin": "http://testserver",
            BROWSER_CSRF_HEADER: csrf_token,
        },
    )

    assert allowed_mutation.status_code == 200


@pytest.mark.parametrize(
    ("origin", "configured_origins"),
    [
        ("http://testserver", None),
        ("http://localhost:4200", "http://localhost:4200"),
        ("tauri://localhost", "tauri://localhost"),
    ],
)
def test_cookie_mutation_accepts_first_party_browser_origins(
    client: TestClient,
    monkeypatch,
    origin: str,
    configured_origins: str | None,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    if configured_origins is None:
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_ORIGINS", configured_origins)
    exchange = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )

    response = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={
            "Origin": origin,
            BROWSER_CSRF_HEADER: exchange.json()["csrf_token"],
        },
    )

    assert response.status_code == 200
    assert client.get("/api/v1/settings").json()["onboarding_completed"] is True


def test_valid_api_key_header_is_exempt_from_csrf(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)

    response = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={"X-API-Key": key},
    )

    assert response.status_code == 200


def test_browser_csrf_from_previous_session_cannot_mutate(
    client: TestClient,
    monkeypatch,
):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)
    first = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )
    second = client.post(
        "/api/v1/auth/session",
        headers={"X-API-Key": key},
    )

    rejected = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={
            "Origin": "http://testserver",
            BROWSER_CSRF_HEADER: first.json()["csrf_token"],
        },
    )

    assert rejected.status_code == 403
    assert client.get("/api/v1/settings").json()["onboarding_completed"] is False

    accepted = client.post(
        "/api/v1/settings/onboarding/complete",
        headers={
            "Origin": "http://testserver",
            BROWSER_CSRF_HEADER: second.json()["csrf_token"],
        },
    )

    assert accepted.status_code == 200


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
    assert cleared.json() == {
        "required": True,
        "authenticated": False,
        "csrf_token": None,
    }
    assert "Max-Age=0" in cleared.headers["set-cookie"]
    assert client.get("/api/v1/settings").status_code == 401
