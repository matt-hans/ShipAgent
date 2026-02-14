"""Tests for the centralized gateway_provider module.

Verifies singleton behavior — repeated calls return the same instance
for both DataSourceMCPClient and ExternalSourcesMCPClient.
"""

import pytest
from unittest.mock import AsyncMock, patch


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
