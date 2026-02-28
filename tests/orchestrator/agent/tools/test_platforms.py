# tests/orchestrator/agent/tools/test_platforms.py
"""Tests for meta-platform agent tools."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


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
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class TestListPlatformsTool:
    """Test list_platforms tool."""

    @pytest.mark.asyncio
    async def test_returns_platform_summaries(self):
        """Returns structured summary of all platforms."""
        from src.orchestrator.agent.tools.platforms import list_platforms_tool

        mock_summary = MagicMock()
        mock_summary.platform_id = "shopify"
        mock_summary.display_name = "Shopify"
        mock_summary.credential_ref = "primary"
        mock_summary.connection_status = "connected"
        mock_summary.enabled = True
        mock_summary.has_credentials = True
        mock_summary.health_ok = True
        mock_summary.last_error = None
        mock_summary.last_sync_completed_at = "2026-02-28T12:00:00Z"
        mock_summary.last_sync_row_count = 150
        mock_summary.capabilities = ["orders.list", "orders.get"]
        mock_summary.contract_version_ok = True
        mock_summary.capabilities_stale = False
        mock_summary.account_label = "my-store.myshopify.com"

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get:
            mock_registry = MagicMock()
            mock_registry.get_platforms_summary.return_value = [mock_summary]
            mock_get.return_value = mock_registry

            result = await list_platforms_tool({})
            assert result["success"] is True
            assert result["data"]["total"] == 1
            assert result["data"]["platforms"][0]["platform_id"] == "shopify"


class TestActivatePlatformTool:
    """Test activate_platform tool."""

    @pytest.mark.asyncio
    async def test_validates_platform_id(self):
        """Unknown platform returns error."""
        from src.orchestrator.agent.tools.platforms import activate_platform_tool

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get:
            mock_registry = MagicMock()
            mock_registry.get_config.return_value = None
            mock_get.return_value = mock_registry

            result = await activate_platform_tool({"platform_id": "nonexistent"})
            assert result["success"] is False
            assert "unknown" in result["error"].lower() or "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_delegates_to_activation_service(self):
        """Valid platform delegates to PlatformActivationService."""
        from src.orchestrator.agent.tools.platforms import activate_platform_tool

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get_reg:
            mock_registry = MagicMock()
            mock_registry.get_config.return_value = MagicMock(
                enabled=True, default_profile="primary"
            )
            mock_get_reg.return_value = mock_registry

            with patch("src.orchestrator.agent.tools.platforms.get_activation_service") as mock_get_svc:
                mock_svc = AsyncMock()
                mock_svc.activate_platform.return_value = FakeActivationReport()
                mock_get_svc.return_value = mock_svc

                result = await activate_platform_tool({
                    "platform_id": "shopify",
                    "credential_ref": "primary",
                })
                assert result["success"] is True
                mock_svc.activate_platform.assert_called_once()


class TestRefreshPlatformTool:
    """Test refresh_platform tool."""

    @pytest.mark.asyncio
    async def test_delegates_with_refresh_mode(self):
        """Refresh calls activation service with mode='refresh'."""
        from src.orchestrator.agent.tools.platforms import refresh_platform_tool

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get_reg:
            mock_registry = MagicMock()
            mock_registry.get_config.return_value = MagicMock(
                enabled=True, default_profile="primary"
            )
            mock_get_reg.return_value = mock_registry

            with patch("src.orchestrator.agent.tools.platforms.get_activation_service") as mock_get_svc:
                mock_svc = AsyncMock()
                mock_svc.activate_platform.return_value = FakeActivationReport(mode="refresh")
                mock_get_svc.return_value = mock_svc

                result = await refresh_platform_tool({"platform_id": "shopify"})
                assert result["success"] is True
                call_kwargs = mock_svc.activate_platform.call_args
                assert call_kwargs.kwargs.get("mode") == "refresh" or \
                    (len(call_kwargs.args) > 2 and call_kwargs.args[2] == "refresh")


class TestDisconnectPlatformTool:
    """Test disconnect_platform tool."""

    @pytest.mark.asyncio
    async def test_disconnects_via_gateway(self):
        """Disconnect calls gateway.disconnect()."""
        from src.orchestrator.agent.tools.platforms import disconnect_platform_tool

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get_reg:
            mock_registry = MagicMock()
            mock_registry.get_config.return_value = MagicMock(
                enabled=True, default_profile="primary"
            )
            mock_get_reg.return_value = mock_registry

            with patch("src.orchestrator.agent.tools.platforms.get_platform_gateway") as mock_get_gw:
                mock_gw = AsyncMock()
                mock_get_gw.return_value = mock_gw

                result = await disconnect_platform_tool({"platform_id": "shopify"})
                assert result["success"] is True
                mock_gw.disconnect.assert_called_once()


class TestGetPlatformCapabilitiesTool:
    """Test get_platform_capabilities tool."""

    @pytest.mark.asyncio
    async def test_returns_capabilities(self):
        """Returns capabilities from gateway."""
        from src.orchestrator.agent.tools.platforms import get_platform_capabilities_tool

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get_reg:
            mock_registry = MagicMock()
            mock_registry.get_config.return_value = MagicMock(
                enabled=True, default_profile="primary"
            )
            mock_get_reg.return_value = mock_registry

            with patch("src.orchestrator.agent.tools.platforms.get_platform_gateway") as mock_get_gw:
                mock_gw = AsyncMock()
                mock_gw.call_tool.return_value = {
                    "supports": ["orders.list", "orders.get"],
                    "limits": {"rate_limit_per_second": 5},
                    "paging": {"default_page_size": 50},
                }
                mock_get_gw.return_value = mock_gw

                result = await get_platform_capabilities_tool({"platform_id": "shopify"})
                assert result["success"] is True
                assert "orders.list" in result["data"]["supports"]
