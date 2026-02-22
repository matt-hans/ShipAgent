"""Tests for the centralized gateway_provider module.

Verifies singleton behavior — repeated calls return the same instance
for both DataSourceMCPClient and ExternalSourcesMCPClient.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_data_gateway_returns_same_instance():
    """Provider must return the same DataSourceMCPClient on repeated calls."""
    import src.services.gateway_provider as provider

    # Reset module state
    provider._data_gateway = None

    with patch.object(provider, "DataSourceMCPClient") as MockDS:
        mock_instance = AsyncMock()
        mock_instance.is_connected = True
        MockDS.return_value = mock_instance

        gw1 = await provider.get_data_gateway()
        gw2 = await provider.get_data_gateway()
        assert gw1 is gw2, "Must return the same singleton instance"
        MockDS.assert_called_once()

    # Clean up
    provider._data_gateway = None


@pytest.mark.asyncio
async def test_get_ups_gateway_singleton():
    """Provider must return the same UPSMCPClient on repeated calls."""
    import src.services.gateway_provider as provider

    # Reset module state
    provider._ups_gateway = None

    mock_instance = AsyncMock()
    mock_instance.is_connected = True
    mock_instance.connect = AsyncMock()

    with patch.object(provider, "_build_ups_gateway", return_value=mock_instance):
        gw1 = await provider.get_ups_gateway()
        gw2 = await provider.get_ups_gateway()
        assert gw1 is gw2, "Must return the same singleton instance"

    # Clean up
    provider._ups_gateway = None


@pytest.mark.asyncio
async def test_get_external_sources_client_returns_same_instance():
    """Provider must return the same ExternalSourcesMCPClient on repeated calls."""
    import src.services.gateway_provider as provider

    # Reset module state
    provider._ext_sources_client = None

    with patch.object(provider, "ExternalSourcesMCPClient") as MockExt:
        mock_instance = AsyncMock()
        mock_instance.is_connected = True
        MockExt.return_value = mock_instance

        c1 = await provider.get_external_sources_client()
        c2 = await provider.get_external_sources_client()
        assert c1 is c2, "Must return the same singleton instance"
        MockExt.assert_called_once()

    # Clean up
    provider._ext_sources_client = None


@pytest.mark.asyncio
async def test_shutdown_gateways_invalidates_mapping_cache():
    """shutdown_gateways should always invalidate mapping cache first."""
    import src.services.gateway_provider as provider

    provider._data_gateway = None
    provider._ext_sources_client = None
    provider._ups_gateway = None

    with patch.object(provider, "invalidate_mapping_cache") as mock_invalidate:
        await provider.shutdown_gateways()
        mock_invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_check_gateway_health_all_states():
    """check_gateway_health reports correct states for each gateway."""
    import src.services.gateway_provider as provider

    # Save originals
    orig_data = provider._data_gateway
    orig_ext = provider._ext_sources_client
    orig_ups = provider._ups_gateway

    try:
        # not_initialized: ups is None
        provider._ups_gateway = None

        # disconnected: data_source has is_connected=False
        mock_disconnected = AsyncMock()
        mock_disconnected.is_connected = False
        provider._data_gateway = mock_disconnected

        # healthy: ext_sources is connected, check_health returns True
        mock_healthy = AsyncMock()
        mock_healthy.is_connected = True
        mock_healthy.check_health = AsyncMock(return_value=True)
        provider._ext_sources_client = mock_healthy

        result = await provider.check_gateway_health()

        assert result["ups"]["status"] == "not_initialized"
        assert result["data_source"]["status"] == "disconnected"
        assert result["external_sources"]["status"] == "ok"

        # unhealthy: check_health raises
        mock_unhealthy = AsyncMock()
        mock_unhealthy.is_connected = True
        mock_unhealthy.check_health = AsyncMock(side_effect=RuntimeError("dead"))
        provider._ext_sources_client = mock_unhealthy

        result2 = await provider.check_gateway_health()
        assert result2["external_sources"]["status"] == "unhealthy"

    finally:
        # Restore originals
        provider._data_gateway = orig_data
        provider._ext_sources_client = orig_ext
        provider._ups_gateway = orig_ups


class TestGatewayLockingFix:
    """Tests for B-2: gateway provider always acquires lock (CWE-362)."""

    def test_get_data_gateway_no_early_return_outside_lock(self):
        """get_data_gateway source must not return outside the lock."""
        import inspect
        import textwrap

        import src.services.gateway_provider as gp

        source = inspect.getsource(gp.get_data_gateway)
        lines = textwrap.dedent(source).strip().splitlines()
        found_lock = False
        for line in lines:
            stripped = line.strip()
            if "async with" in stripped and "_data_gateway_lock" in stripped:
                found_lock = True
            if stripped.startswith("return") and not found_lock:
                if "def " not in stripped:
                    pytest.fail("get_data_gateway has return before acquiring lock")

    def test_get_external_sources_no_early_return(self):
        """get_external_sources_client must not return outside the lock."""
        import inspect
        import textwrap

        import src.services.gateway_provider as gp

        source = inspect.getsource(gp.get_external_sources_client)
        lines = textwrap.dedent(source).strip().splitlines()
        found_lock = False
        for line in lines:
            stripped = line.strip()
            if "async with" in stripped and "_ext_sources_lock" in stripped:
                found_lock = True
            if stripped.startswith("return") and not found_lock:
                if "def " not in stripped:
                    pytest.fail("get_external_sources_client has return before lock")

    def test_get_ups_gateway_no_early_return(self):
        """get_ups_gateway must not return outside the lock."""
        import inspect
        import textwrap

        import src.services.gateway_provider as gp

        source = inspect.getsource(gp.get_ups_gateway)
        lines = textwrap.dedent(source).strip().splitlines()
        found_lock = False
        for line in lines:
            stripped = line.strip()
            if "async with" in stripped and "_ups_gateway_lock" in stripped:
                found_lock = True
            if stripped.startswith("return") and not found_lock:
                if "def " not in stripped:
                    pytest.fail("get_ups_gateway has return before acquiring lock")
