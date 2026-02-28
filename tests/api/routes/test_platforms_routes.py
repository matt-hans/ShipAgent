# tests/api/routes/test_platforms_routes.py
"""Tests for platform API routes — activation guardrails."""
import pytest
from unittest.mock import MagicMock, patch

from src.api.routes.platforms import set_active_platforms, SetActivePlatformsRequest
from src.services.platform_models import PlatformSummary


def _make_summary(
    platform_id: str,
    connection_status: str = "connected",
    has_credentials: bool = True,
    is_active: bool = False,
    enabled: bool = True,
) -> PlatformSummary:
    """Build a minimal PlatformSummary for testing."""
    return PlatformSummary(
        platform_id=platform_id,
        display_name=platform_id.capitalize(),
        credential_ref="primary",
        enabled=enabled,
        connection_status=connection_status,
        account_label=None,
        last_sync_completed_at=None,
        last_sync_row_count=None,
        capabilities=None,
        has_credentials=has_credentials,
        health_ok=True if connection_status == "connected" else None,
        last_error=None,
        contract_version_ok=True,
        capabilities_stale=True,
        is_active=is_active,
    )


class TestSetActivePlatformsGuardrails:
    """PATCH /platforms/active enforcement: only connected platforms can activate."""

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_rejects_disconnected_platform_without_credentials(
        self, mock_get_registry,
    ):
        """Disconnected platform without credentials is rejected."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary("shopify", connection_status="disconnected", has_credentials=False),
            _make_summary("amazon", connection_status="connected", has_credentials=True),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is False
        assert "shopify" in response.error
        assert "not connected" in response.error
        # set_platform_active should NOT have been called
        mock_registry.set_platform_active.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_accepts_connected_platform(self, mock_get_registry):
        """Connected platform with credentials is activated."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary("shopify", connection_status="connected", has_credentials=True),
        ]
        mock_registry.get_active_platforms.return_value = [
            _make_summary("shopify", connection_status="connected", is_active=True),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is True
        assert len(response.active_platforms) == 1
        mock_registry.set_platform_active.assert_called()

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_accepts_disconnected_with_credentials(self, mock_get_registry):
        """Disconnected platform WITH credentials is allowed (can auto-connect)."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary("shopify", connection_status="disconnected", has_credentials=True),
        ]
        mock_registry.get_active_platforms.return_value = [
            _make_summary("shopify", connection_status="disconnected", is_active=True),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is True
        mock_registry.set_platform_active.assert_called()

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_rejects_unknown_platform(self, mock_get_registry):
        """Unknown platform ID is rejected."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary("shopify", connection_status="connected"),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["nonexistent"])
        response = await set_active_platforms(request)

        assert response.success is False
        assert "nonexistent" in response.error
        assert "unknown" in response.error

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_deactivate_all_succeeds(self, mock_get_registry):
        """Empty list deactivates all — always succeeds."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary("shopify", connection_status="connected", is_active=True),
        ]
        mock_registry.get_active_platforms.return_value = []
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=[])
        response = await set_active_platforms(request)

        assert response.success is True
        assert len(response.active_platforms) == 0
