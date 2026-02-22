"""Tests for /readyz credential awareness (DB + env fallback).

Verifies that the readiness endpoint correctly reflects UPS credential
availability from both DB-stored connections and environment variables.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.services.connection_types import UPSCredentials


class TestReadyzCredentials:
    """Tests for UPS credential checks in the /readyz endpoint."""

    def test_readyz_configured_from_db(self, client: TestClient, monkeypatch):
        """Readyz reports 'configured' when resolver returns DB credentials."""
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ACCOUNT_NUMBER"):
            monkeypatch.delenv(var, raising=False)

        mock_creds = UPSCredentials(
            client_id="db_id", client_secret="db_sec",
            environment="production",
            base_url="https://onlinetools.ups.com",
            account_number="123456",
        )

        with patch(
            "src.services.runtime_credentials.resolve_ups_credentials",
            return_value=mock_creds,
        ):
            resp = client.get("/readyz")

        data = resp.json()
        assert data["checks"]["ups_credentials"]["status"] == "configured"
        assert data["checks"]["ups_credentials"]["environment"] == "production"

    def test_readyz_configured_from_env(self, client: TestClient, monkeypatch):
        """Readyz reports 'configured' when env vars provide UPS credentials."""
        monkeypatch.setenv("UPS_CLIENT_ID", "env_id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "env_sec")

        resp = client.get("/readyz")
        data = resp.json()
        assert data["checks"]["ups_credentials"]["status"] == "configured"

    def test_readyz_degraded_when_no_creds(self, client: TestClient, monkeypatch):
        """Readyz reports 'degraded' when no UPS credentials are available."""
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ACCOUNT_NUMBER"):
            monkeypatch.delenv(var, raising=False)

        resp = client.get("/readyz")
        data = resp.json()
        assert data["checks"]["ups_credentials"]["status"] == "degraded"
        assert data["status"] == "degraded"

    def test_readyz_degraded_on_resolver_exception(self, client: TestClient, monkeypatch):
        """Readyz reports 'degraded' when credential resolver throws."""
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            monkeypatch.delenv(var, raising=False)

        def exploding_resolver(**kwargs):
            raise RuntimeError("key file corrupt")

        with patch(
            "src.services.runtime_credentials.resolve_ups_credentials",
            exploding_resolver,
        ):
            resp = client.get("/readyz")

        data = resp.json()
        assert data["checks"]["ups_credentials"]["status"] == "degraded"
        assert "failed" in data["checks"]["ups_credentials"]["message"].lower()
