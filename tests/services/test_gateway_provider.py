"""Tests for the centralized gateway_provider module.

Verifies singleton behavior — repeated calls return the same instance.
"""

import pytest
from unittest.mock import AsyncMock, patch


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
