# tests/services/test_platform_gateway.py
"""Tests for PlatformGateway service.

Uses FakeSession for deterministic behavior — no real MCP processes spawned.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from tests.services.fake_mcp_session import FakeSession
from src.services.platform_models import PlatformError, PlatformErrorCode


@pytest.fixture
def mock_registry():
    """Mock PlatformRegistry with Shopify config."""
    from src.services.platform_models import PlatformConfig

    registry = MagicMock()
    registry.get_config.return_value = PlatformConfig(
        platform_id="shopify",
        display_name="Shopify",
        default_profile="primary",
        required_secret_keys=["ACCESS_TOKEN", "STORE_DOMAIN"],
        mcp_module="src.mcp.platforms.shopify.server",
        mcp_bundle_subcommand="mcp-shopify",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    )
    registry.update_state = MagicMock()
    return registry


class TestGatewayCallTool:
    """Test tool calling via the gateway."""

    @pytest.mark.asyncio
    async def test_call_tool_spawns_on_first_use(self, mock_registry):
        """Connection created lazily on first tool call."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 5, "max_concurrency": 3},
            "paging": {},
        }])
        session.program("orders.list", [{"items": [], "next_cursor": None}])

        gateway = PlatformGateway(mock_registry, session_factory=lambda cfg, ref: session)
        result = await gateway.call_tool("shopify", "primary", "orders.list", {})
        assert result == {"items": [], "next_cursor": None}

        # Health + capabilities + the actual call
        assert session.call_count["platform.health"] == 1
        assert session.call_count["platform.capabilities"] == 1
        assert session.call_count["orders.list"] == 1

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_call_tool_reuses_existing_connection(self, mock_registry):
        """Second call reuses existing connection (no re-spawn)."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 5, "max_concurrency": 3},
            "paging": {},
        }])

        gateway = PlatformGateway(mock_registry, session_factory=lambda cfg, ref: session)
        await gateway.call_tool("shopify", "primary", "orders.list", {})
        await gateway.call_tool("shopify", "primary", "orders.list", {})

        # Health + capabilities only called once (on first connection)
        assert session.call_count["platform.health"] == 1
        assert session.call_count["orders.list"] == 2

        await gateway.shutdown()


class TestCircuitBreaker:
    """Test circuit breaker behavior."""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_consecutive_failures(self, mock_registry):
        """5 consecutive TRANSIENT errors open the circuit."""
        from src.services.platform_gateway import PlatformGateway, CircuitOpenError

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {},
        }])
        # All calls fail with transient errors
        transient = PlatformError(
            error_code=PlatformErrorCode.TRANSIENT,
            message="timeout",
        )
        session.program("orders.list", [transient])

        gateway = PlatformGateway(
            mock_registry,
            session_factory=lambda cfg, ref: session,
            circuit_threshold=5,
        )

        # 5 failures should open the circuit
        for _ in range(5):
            with pytest.raises(PlatformError):
                await gateway.call_tool("shopify", "primary", "orders.list", {})

        # 6th call should get CircuitOpenError without calling the session
        with pytest.raises(CircuitOpenError):
            await gateway.call_tool("shopify", "primary", "orders.list", {})

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_rate_limited_does_not_trip_circuit(self, mock_registry):
        """RATE_LIMITED errors don't increment the circuit breaker."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {},
        }])
        rate_err = PlatformError(
            error_code=PlatformErrorCode.RATE_LIMITED,
            message="slow down",
            retry_after_seconds=1,
        )
        session.program("orders.list", [rate_err])

        gateway = PlatformGateway(
            mock_registry,
            session_factory=lambda cfg, ref: session,
            circuit_threshold=3,
        )

        # 5 rate-limited calls should NOT open the circuit
        for _ in range(5):
            with pytest.raises(PlatformError) as exc_info:
                await gateway.call_tool("shopify", "primary", "orders.list", {})
            assert exc_info.value.error_code == PlatformErrorCode.RATE_LIMITED

        # Circuit should still be closed — next call reaches the session
        assert session.call_count["orders.list"] == 5

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_circuit_resets_on_success(self, mock_registry):
        """Successful call resets the failure counter."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {},
        }])
        transient = PlatformError(
            error_code=PlatformErrorCode.TRANSIENT, message="timeout"
        )
        # 3 failures, then success, then 3 more failures
        session.program("orders.list", [
            transient, transient, transient,
            {"items": []},
            transient, transient, transient,
            {"items": []},
        ])

        gateway = PlatformGateway(
            mock_registry,
            session_factory=lambda cfg, ref: session,
            circuit_threshold=5,
        )

        # 3 failures
        for _ in range(3):
            with pytest.raises(PlatformError):
                await gateway.call_tool("shopify", "primary", "orders.list", {})

        # Success resets counter
        result = await gateway.call_tool("shopify", "primary", "orders.list", {})
        assert result == {"items": []}

        # 3 more failures — still under threshold (counter was reset)
        for _ in range(3):
            with pytest.raises(PlatformError):
                await gateway.call_tool("shopify", "primary", "orders.list", {})

        # Should NOT be open (only 3 consecutive, threshold is 5)
        result = await gateway.call_tool("shopify", "primary", "orders.list", {})
        assert result == {"items": []}

        await gateway.shutdown()


class TestContractVersionCheck:
    """Test contract version validation."""

    @pytest.mark.asyncio
    async def test_contract_version_mismatch_raises(self, mock_registry):
        """Wrong contract version raises a specific error."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "2.0"}])  # Mismatch!

        gateway = PlatformGateway(mock_registry, session_factory=lambda cfg, ref: session)

        with pytest.raises(PlatformError) as exc_info:
            await gateway.call_tool("shopify", "primary", "orders.list", {})
        assert "contract" in exc_info.value.message.lower() or "version" in exc_info.value.message.lower()

        await gateway.shutdown()


class TestDisconnect:
    """Test disconnect behavior."""

    @pytest.mark.asyncio
    async def test_disconnect_tears_down_and_updates_registry(self, mock_registry):
        """Clean disconnect closes session and updates registry."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 5, "max_concurrency": 3},
            "paging": {},
        }])

        gateway = PlatformGateway(mock_registry, session_factory=lambda cfg, ref: session)

        # Establish connection
        await gateway.call_tool("shopify", "primary", "orders.list", {})

        # Disconnect
        await gateway.disconnect("shopify", "primary")

        assert session.closed is True
        mock_registry.update_state.assert_called()

        await gateway.shutdown()


class TestPerCallTimeout:
    """Test per-call timeout handling."""

    @pytest.mark.asyncio
    async def test_per_call_timeout_triggers_transient(self, mock_registry):
        """Hung call raises PlatformError with TRANSIENT code."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {},
        }])
        session.program("orders.list", [asyncio.TimeoutError()])

        gateway = PlatformGateway(
            mock_registry,
            session_factory=lambda cfg, ref: session,
            call_timeout_seconds=1.0,
        )

        with pytest.raises(PlatformError) as exc_info:
            await gateway.call_tool("shopify", "primary", "orders.list", {})
        assert exc_info.value.error_code == PlatformErrorCode.TRANSIENT

        await gateway.shutdown()


class TestShutdown:
    """Test graceful shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_all_connections(self, mock_registry):
        """Shutdown closes all open sessions."""
        from src.services.platform_gateway import PlatformGateway

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 5, "max_concurrency": 3},
            "paging": {},
        }])

        gateway = PlatformGateway(mock_registry, session_factory=lambda cfg, ref: session)
        await gateway.call_tool("shopify", "primary", "orders.list", {})

        await gateway.shutdown()
        assert session.closed is True
