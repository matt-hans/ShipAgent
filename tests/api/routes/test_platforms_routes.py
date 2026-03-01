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
    credential_ref: str = "primary",
) -> PlatformSummary:
    """Build a minimal PlatformSummary for testing."""
    return PlatformSummary(
        platform_id=platform_id,
        display_name=platform_id.capitalize(),
        credential_ref=credential_ref,
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

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_multi_profile_accepts_when_one_profile_connected(
        self, mock_get_registry,
    ):
        """Multi-profile: accepted if at least one profile is activatable."""
        mock_registry = MagicMock()
        # Shopify has two profiles: one disconnected/no creds, one connected
        mock_registry.get_platforms_summary.return_value = [
            _make_summary(
                "shopify", credential_ref="primary",
                connection_status="disconnected", has_credentials=False,
            ),
            _make_summary(
                "shopify", credential_ref="secondary",
                connection_status="connected", has_credentials=True,
            ),
        ]
        mock_registry.get_active_platforms.return_value = [
            _make_summary(
                "shopify", credential_ref="secondary",
                connection_status="connected", is_active=True,
            ),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is True
        # set_platform_active called for both profiles
        assert mock_registry.set_platform_active.call_count == 2

        # Verify: disconnected/no-creds profile NOT activated,
        # connected profile IS activated
        calls = mock_registry.set_platform_active.call_args_list
        call_map = {(c.args[0], c.args[1]): c.args[2] for c in calls}
        assert call_map[("shopify", "primary")] is False  # not activatable
        assert call_map[("shopify", "secondary")] is True

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_multi_profile_rejects_when_all_profiles_fail(
        self, mock_get_registry,
    ):
        """Multi-profile: rejected if ALL profiles are disconnected/no-creds."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary(
                "shopify", credential_ref="primary",
                connection_status="disconnected", has_credentials=False,
            ),
            _make_summary(
                "shopify", credential_ref="secondary",
                connection_status="disconnected", has_credentials=False,
            ),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is False
        assert "shopify" in response.error
        mock_registry.set_platform_active.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_multi_profile_order_independent(self, mock_get_registry):
        """Validation does not depend on summary list order."""
        mock_registry = MagicMock()
        # Reversed order from test above: connected first, disconnected second
        mock_registry.get_platforms_summary.return_value = [
            _make_summary(
                "shopify", credential_ref="secondary",
                connection_status="connected", has_credentials=True,
            ),
            _make_summary(
                "shopify", credential_ref="primary",
                connection_status="disconnected", has_credentials=False,
            ),
        ]
        mock_registry.get_active_platforms.return_value = [
            _make_summary(
                "shopify", credential_ref="secondary",
                connection_status="connected", is_active=True,
            ),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is True
        # Same result regardless of order
        calls = mock_registry.set_platform_active.call_args_list
        call_map = {(c.args[0], c.args[1]): c.args[2] for c in calls}
        assert call_map[("shopify", "primary")] is False
        assert call_map[("shopify", "secondary")] is True

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_degraded_status_is_activatable(self, mock_get_registry):
        """Degraded connection status is directly activatable without credentials."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary(
                "shopify", connection_status="degraded", has_credentials=False,
            ),
        ]
        mock_registry.get_active_platforms.return_value = [
            _make_summary("shopify", connection_status="degraded", is_active=True),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is True

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_auth_expired_with_credentials_is_activatable(
        self, mock_get_registry,
    ):
        """auth_expired with credentials can be activated (will re-auth)."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary(
                "shopify", connection_status="auth_expired", has_credentials=True,
            ),
        ]
        mock_registry.get_active_platforms.return_value = [
            _make_summary("shopify", connection_status="auth_expired", is_active=True),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is True

    @pytest.mark.asyncio
    @patch("src.services.gateway_provider.get_platform_registry")
    async def test_auth_expired_without_credentials_is_rejected(
        self, mock_get_registry,
    ):
        """auth_expired without credentials cannot be activated."""
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [
            _make_summary(
                "shopify", connection_status="auth_expired", has_credentials=False,
            ),
        ]
        mock_get_registry.return_value = mock_registry

        request = SetActivePlatformsRequest(active_platform_ids=["shopify"])
        response = await set_active_platforms(request)

        assert response.success is False
        assert "shopify" in response.error
        mock_registry.set_platform_active.assert_not_called()
