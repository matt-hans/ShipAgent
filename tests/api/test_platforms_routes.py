# tests/api/test_platforms_routes.py
"""Tests for generic platform API routes (federated architecture)."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from dataclasses import dataclass


@dataclass
class FakePlatformSummary:
    """Lightweight stand-in for PlatformSummary."""

    platform_id: str = "shopify"
    display_name: str = "Shopify"
    credential_ref: str = "primary"
    connection_status: str = "connected"
    enabled: bool = True
    has_credentials: bool = True
    health_ok: bool = True
    last_error: str | None = None
    last_sync_completed_at: str | None = "2026-02-28T12:00:00Z"
    last_sync_row_count: int | None = 150
    capabilities: list | None = None
    account_label: str | None = "my-store.myshopify.com"
    contract_version_ok: bool = True
    capabilities_stale: bool = False

    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = ["orders.list", "orders.get"]


@dataclass
class FakeActivationReport:
    """Lightweight stand-in for ActivationReport."""

    platform_id: str = "shopify"
    credential_ref: str = "primary"
    mode: str = "initial"
    total_imported: int = 50
    pages_fetched: int = 3
    watermark: str | None = "2026-02-28T12:00:00Z"
    duration_seconds: float = 2.5
    warnings: list | None = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@pytest.fixture
def client():
    """Create TestClient with the FastAPI app."""
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


class TestListPlatformsRoute:
    """Test GET /api/v1/platforms/."""

    def test_returns_platforms(self, client):
        """Returns list of registered platforms."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [FakePlatformSummary()]

        with patch(
            "src.services.gateway_provider.get_platform_registry",
            return_value=mock_registry,
        ):
            resp = client.get("/api/v1/platforms/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total"] == 1
            assert data["platforms"][0]["platform_id"] == "shopify"

    def test_returns_empty_when_not_initialized(self, client):
        """Returns empty list when platform singletons not initialized."""
        with patch(
            "src.services.gateway_provider._platform_registry",
            None,
        ):
            resp = client.get("/api/v1/platforms/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total"] == 0


class TestActivatePlatformRoute:
    """Test POST /api/v1/platforms/activate."""

    def test_activate_returns_report(self, client):
        """Successful activation returns import stats."""
        mock_service = AsyncMock()
        mock_service.activate_platform.return_value = FakeActivationReport()

        with patch(
            "src.services.gateway_provider._activation_service",
            mock_service,
        ):
            resp = client.post(
                "/api/v1/platforms/activate",
                json={"platform_id": "shopify"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total_imported"] == 50
            assert data["mode"] == "initial"

    def test_activate_returns_error_on_failure(self, client):
        """Failed activation returns error message."""
        mock_service = AsyncMock()
        mock_service.activate_platform.side_effect = ValueError("Bad platform")

        with patch(
            "src.services.gateway_provider._activation_service",
            mock_service,
        ):
            resp = client.post(
                "/api/v1/platforms/activate",
                json={"platform_id": "nonexistent"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "Bad platform" in data["error"]


class TestRefreshPlatformRoute:
    """Test POST /api/v1/platforms/refresh."""

    def test_refresh_returns_report(self, client):
        """Successful refresh returns import stats."""
        mock_service = AsyncMock()
        mock_service.activate_platform.return_value = FakeActivationReport(mode="refresh")

        with patch(
            "src.services.gateway_provider._activation_service",
            mock_service,
        ):
            resp = client.post(
                "/api/v1/platforms/refresh",
                json={"platform_id": "shopify"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["mode"] == "refresh"


class TestDisconnectPlatformRoute:
    """Test POST /api/v1/platforms/disconnect-platform."""

    def test_disconnect_succeeds(self, client):
        """Successful disconnect returns status."""
        mock_gateway = AsyncMock()

        with patch(
            "src.services.gateway_provider._platform_gateway",
            mock_gateway,
        ):
            resp = client.post(
                "/api/v1/platforms/disconnect-platform",
                json={"platform_id": "shopify"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["status"] == "disconnected"


class TestPlatformStatusRoute:
    """Test GET /api/v1/platforms/status/{platform_id}."""

    def test_returns_platform_status(self, client):
        """Returns detailed status for a platform."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [FakePlatformSummary()]

        with patch(
            "src.services.gateway_provider._platform_registry",
            mock_registry,
        ):
            resp = client.get("/api/v1/platforms/status/shopify")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["platform_id"] == "shopify"
            assert data["display_name"] == "Shopify"

    def test_returns_error_for_unknown_platform(self, client):
        """Returns error for unknown platform."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = []

        with patch(
            "src.services.gateway_provider._platform_registry",
            mock_registry,
        ):
            resp = client.get("/api/v1/platforms/status/nonexistent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "not found" in data["error"].lower()
