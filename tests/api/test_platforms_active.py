# tests/api/test_platforms_active.py
"""Tests for PATCH /api/v1/platforms/active endpoint."""
import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


@dataclass
class FakePlatformSummary:
    """Lightweight stand-in for PlatformSummary used in active platform tests."""

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
    is_active: bool = False

    def __post_init__(self):
        """Set default capabilities list."""
        if self.capabilities is None:
            self.capabilities = ["orders.list", "orders.get"]


@pytest.fixture
def client():
    """Create TestClient with the FastAPI app."""
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _disable_compat_mode(monkeypatch):
    """Keep legacy active-route behavior for these baseline route tests."""
    monkeypatch.setenv("PLATFORM_ACTIVATION_COMPAT_MODE", "false")


class TestSetActivePlatformsRoute:
    """Tests for PATCH /api/v1/platforms/active."""

    def test_set_active_platforms_success(self, client):
        """Setting platforms active returns success with active platform list."""
        mock_registry = MagicMock()
        shopify_summary = FakePlatformSummary(
            platform_id="shopify", is_active=False,
        )
        amazon_summary = FakePlatformSummary(
            platform_id="amazon",
            display_name="Amazon Seller Central",
            is_active=False,
        )
        mock_registry.get_platforms_summary.return_value = [
            shopify_summary, amazon_summary,
        ]
        # After setting active, get_active_platforms returns only shopify
        active_shopify = FakePlatformSummary(
            platform_id="shopify", is_active=True,
        )
        mock_registry.get_active_platforms.return_value = [active_shopify]

        with patch(
            "src.services.gateway_provider._platform_registry",
            mock_registry,
        ):
            resp = client.patch(
                "/api/v1/platforms/active",
                json={"active_platform_ids": ["shopify"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert len(data["active_platforms"]) == 1
            assert data["active_platforms"][0]["platform_id"] == "shopify"
            assert data["active_platforms"][0]["is_active"] is True

    def test_set_active_platforms_deactivates_others(self, client):
        """Platforms not in active_platform_ids list get deactivated."""
        mock_registry = MagicMock()
        shopify_summary = FakePlatformSummary(
            platform_id="shopify", is_active=True, credential_ref="primary",
        )
        amazon_summary = FakePlatformSummary(
            platform_id="amazon",
            display_name="Amazon Seller Central",
            is_active=True,
            credential_ref="primary",
        )
        mock_registry.get_platforms_summary.return_value = [
            shopify_summary, amazon_summary,
        ]
        # After update, only amazon is active
        active_amazon = FakePlatformSummary(
            platform_id="amazon",
            display_name="Amazon Seller Central",
            is_active=True,
        )
        mock_registry.get_active_platforms.return_value = [active_amazon]

        with patch(
            "src.services.gateway_provider._platform_registry",
            mock_registry,
        ):
            resp = client.patch(
                "/api/v1/platforms/active",
                json={"active_platform_ids": ["amazon"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True

            # Verify set_platform_active was called correctly
            calls = mock_registry.set_platform_active.call_args_list
            # shopify should be deactivated, amazon should be activated
            call_map = {c.args[0]: c.args[2] for c in calls}
            assert call_map["shopify"] is False
            assert call_map["amazon"] is True

    def test_set_active_platforms_empty_deactivates_all(self, client):
        """Empty active_platform_ids list deactivates all platforms."""
        mock_registry = MagicMock()
        shopify_summary = FakePlatformSummary(
            platform_id="shopify", is_active=True,
        )
        mock_registry.get_platforms_summary.return_value = [shopify_summary]
        mock_registry.get_active_platforms.return_value = []

        with patch(
            "src.services.gateway_provider._platform_registry",
            mock_registry,
        ):
            resp = client.patch(
                "/api/v1/platforms/active",
                json={"active_platform_ids": []},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert len(data["active_platforms"]) == 0

    def test_set_active_platforms_not_initialized(self, client):
        """Returns error when platform singletons not initialized."""
        with patch(
            "src.services.gateway_provider._platform_registry",
            None,
        ):
            resp = client.patch(
                "/api/v1/platforms/active",
                json={"active_platform_ids": ["shopify"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "not initialized" in data["error"].lower()

    def test_list_platforms_includes_is_active(self, client):
        """GET /platforms/ response includes is_active field."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            FakePlatformSummary(is_active=True),
        ]

        with patch(
            "src.services.gateway_provider._platform_registry",
            mock_registry,
        ):
            resp = client.get("/api/v1/platforms/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["platforms"][0]["is_active"] is True
