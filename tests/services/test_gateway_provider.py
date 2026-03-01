"""Tests for the centralized gateway_provider module.

Verifies singleton behavior — repeated calls return the same instance
for DataSourceMCPClient and UPSMCPClient.
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
async def test_shutdown_gateways_invalidates_mapping_cache():
    """shutdown_gateways should always invalidate mapping cache first."""
    import src.services.gateway_provider as provider

    provider._data_gateway = None
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
    orig_ups = provider._ups_gateway

    try:
        # not_initialized: ups is None
        provider._ups_gateway = None

        # disconnected: data_source has is_connected=False
        mock_disconnected = AsyncMock()
        mock_disconnected.is_connected = False
        provider._data_gateway = mock_disconnected

        result = await provider.check_gateway_health()

        assert result["ups"]["status"] == "not_initialized"
        assert result["data_source"]["status"] == "disconnected"

    finally:
        # Restore originals
        provider._data_gateway = orig_data
        provider._ups_gateway = orig_ups


class TestGatewayShutdownLocking:
    """Tests for H-5: shutdown_gateways acquires locks (CWE-362)."""

    def test_shutdown_acquires_all_locks(self):
        """shutdown_gateways source acquires all three locks."""
        import inspect

        import src.services.gateway_provider as gp

        source = inspect.getsource(gp.shutdown_gateways)
        assert "_data_gateway_lock" in source
        assert "_ups_gateway_lock" in source

    def test_shutdown_sets_none_inside_lock(self):
        """Each gateway is set to None inside its lock scope."""
        import inspect
        import textwrap

        import src.services.gateway_provider as gp

        source = inspect.getsource(gp.shutdown_gateways)
        lines = textwrap.dedent(source).strip().splitlines()

        # For each gateway, verify "= None" appears AFTER "async with" lock
        for lock_name, none_pattern in [
            ("_data_gateway_lock", "_data_gateway = None"),
            ("_ups_gateway_lock", "_ups_gateway = None"),
        ]:
            lock_line = None
            none_line = None
            for i, line in enumerate(lines):
                if lock_name in line and "async with" in line:
                    lock_line = i
                if none_pattern in line and lock_line is not None:
                    none_line = i
                    break
            assert lock_line is not None, f"{lock_name} not found in shutdown"
            assert none_line is not None, f"{none_pattern} not after {lock_name}"
            assert none_line > lock_line, f"{none_pattern} before {lock_name}"


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
