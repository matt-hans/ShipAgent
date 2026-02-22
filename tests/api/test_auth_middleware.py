"""Tests for optional API-key auth middleware behavior.

Includes rate limiting (F-6, CWE-307) and key strength validation.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.middleware.auth import (
    _AUTH_FAIL_MAX,
    _auth_lock,
    _get_client_ip,
    reset_rate_limiter,
    validate_api_key_strength,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset rate limiter state between tests."""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def test_api_auth_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)

    response = client.get("/api/v1/jobs")
    assert response.status_code == 200


def test_api_auth_enforced_when_key_is_set(client: TestClient, monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", "a" * 32 + "-test-key")

    response = client.get("/api/v1/jobs")
    assert response.status_code == 401

    response = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401

    response = client.get(
        "/api/v1/jobs", headers={"X-API-Key": "a" * 32 + "-test-key"}
    )
    assert response.status_code == 200


def test_health_and_readyz_are_public(client: TestClient, monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", "a" * 32 + "-test-key")

    assert client.get("/health").status_code == 200
    assert client.get("/readyz").status_code in {200, 503}


class TestApiKeyStrength:
    """Tests for API key minimum length validation (F-6)."""

    def test_short_api_key_rejected_at_startup(self, monkeypatch):
        """Keys shorter than 32 characters raise ValueError."""
        monkeypatch.setenv("SHIPAGENT_API_KEY", "too-short")
        with pytest.raises(ValueError, match="too short"):
            validate_api_key_strength()

    def test_valid_length_api_key_accepted(self, monkeypatch):
        """Keys of 32+ characters pass validation."""
        monkeypatch.setenv("SHIPAGENT_API_KEY", "a" * 32)
        validate_api_key_strength()  # Should not raise

    def test_empty_api_key_skips_validation(self, monkeypatch):
        """Empty/unset key (auth disabled) passes validation."""
        monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
        validate_api_key_strength()  # Should not raise


class TestAuthRateLimit:
    """Tests for auth failure rate limiting (F-6, CWE-307)."""

    def test_auth_rate_limit_blocks_after_max_attempts(
        self, client: TestClient, monkeypatch
    ):
        """After _AUTH_FAIL_MAX bad attempts, returns 429."""
        monkeypatch.setenv("SHIPAGENT_API_KEY", "a" * 32 + "-real-key")

        # Send _AUTH_FAIL_MAX bad requests
        for _ in range(_AUTH_FAIL_MAX):
            resp = client.get(
                "/api/v1/jobs", headers={"X-API-Key": "wrong-key"}
            )
            assert resp.status_code == 401

        # Next attempt should be rate-limited
        resp = client.get(
            "/api/v1/jobs", headers={"X-API-Key": "wrong-key"}
        )
        assert resp.status_code == 429
        assert "too many" in resp.json()["detail"].lower()

    def test_auth_rate_limit_resets_after_window(
        self, client: TestClient, monkeypatch
    ):
        """Rate limit resets after clearing the failure records."""
        monkeypatch.setenv("SHIPAGENT_API_KEY", "a" * 32 + "-real-key")

        # Fill up failures
        for _ in range(_AUTH_FAIL_MAX):
            client.get("/api/v1/jobs", headers={"X-API-Key": "wrong-key"})

        # Verify blocked
        resp = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 429

        # Reset (simulates window expiry)
        reset_rate_limiter()

        # Should work again (401, not 429)
        resp = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401


class TestRateLimiterThreadSafety:
    """Tests for B-1: thread-safe rate limiter (CWE-362)."""

    def test_auth_lock_exists(self):
        """_auth_lock is a threading.Lock instance."""
        import threading

        assert isinstance(_auth_lock, type(threading.Lock()))

    def test_rate_limiter_uses_lock(self):
        """_is_rate_limited and _record_auth_failure use _auth_lock."""
        import inspect

        from src.api.middleware.auth import _is_rate_limited, _record_auth_failure

        source_limited = inspect.getsource(_is_rate_limited)
        assert "_auth_lock" in source_limited

        source_record = inspect.getsource(_record_auth_failure)
        assert "_auth_lock" in source_record

    def test_reset_rate_limiter_uses_lock(self):
        """reset_rate_limiter also acquires _auth_lock."""
        import inspect

        source = inspect.getsource(reset_rate_limiter)
        assert "_auth_lock" in source


class TestTrustedProxyConfig:
    """Tests for H-2: X-Forwarded-For trust configuration (CWE-348)."""

    def test_get_client_ip_ignores_xff_by_default(self):
        """Without SHIPAGENT_TRUST_PROXY, X-Forwarded-For is ignored."""
        from unittest.mock import MagicMock

        import src.api.middleware.auth as auth_mod

        original = auth_mod._TRUST_PROXY
        try:
            auth_mod._TRUST_PROXY = False
            request = MagicMock()
            request.headers = {"X-Forwarded-For": "1.2.3.4"}
            request.client.host = "127.0.0.1"
            assert _get_client_ip(request) == "127.0.0.1"
        finally:
            auth_mod._TRUST_PROXY = original

    def test_get_client_ip_uses_xff_when_trusted(self):
        """With SHIPAGENT_TRUST_PROXY=true, X-Forwarded-For is used."""
        from unittest.mock import MagicMock

        import src.api.middleware.auth as auth_mod

        original = auth_mod._TRUST_PROXY
        try:
            auth_mod._TRUST_PROXY = True
            request = MagicMock()
            request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
            request.client.host = "127.0.0.1"
            assert _get_client_ip(request) == "1.2.3.4"
        finally:
            auth_mod._TRUST_PROXY = original

