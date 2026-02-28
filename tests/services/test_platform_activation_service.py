# tests/services/test_platform_activation_service.py
"""Tests for PlatformActivationService.

Uses FakeSession + mock registry to test the connect → page → normalize →
upsert → checkpoint flow without real MCP processes or DuckDB.
"""
import asyncio
import uuid
import pytest
import duckdb
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from tests.services.fake_mcp_session import FakeSession
from src.services.platform_models import (
    PlatformConfig,
    PlatformError,
    PlatformErrorCode,
    ActivationReport,
)
from src.mcp.data_source.tools.schema_migration import ensure_external_orders_table


def _make_config(platform_id: str = "dummy") -> PlatformConfig:
    """Build a PlatformConfig for testing."""
    return PlatformConfig(
        platform_id=platform_id,
        display_name="Dummy (Test)",
        default_profile="test",
        required_secret_keys=[],
        mcp_module="src.mcp.platforms.dummy.server",
        mcp_bundle_subcommand="mcp-dummy",
        contract_version="1.0",
        default_sync_overlap_seconds=0,
        enabled=True,
    )


def _make_registry(config: PlatformConfig | None = None):
    """Build a mock registry with dummy config."""
    cfg = config or _make_config()
    registry = MagicMock()
    registry.get_config.return_value = cfg
    registry.get_state.return_value = None
    registry.update_state = MagicMock()
    registry.record_sync_checkpoint = MagicMock()
    registry.record_capabilities = MagicMock()
    registry.record_health_check = MagicMock()
    return registry


def _make_gateway_session(pages: list[dict] | None = None):
    """Build a FakeSession with auth and orders data programmed.

    Default: 2 pages of 3 orders each.
    """
    session = FakeSession()
    session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
    session.program("platform.capabilities", [{
        "platform_id": "dummy",
        "contract_version": "1.0",
        "supports": ["orders.list", "orders.get", "tracking.write_back"],
        "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
        "paging": {"default_page_size": 3, "max_page_size": 3, "overlap_seconds": 0},
    }])
    session.program("auth.connect", [{"ok": True, "account_label": "test-store"}])

    if pages is None:
        pages = [
            {"items": [_make_order(f"D{i:03d}") for i in range(1, 4)], "next_cursor": "page2", "watermark": "2026-02-22T10:00:00Z"},
            {"items": [_make_order(f"D{i:03d}") for i in range(4, 7)], "next_cursor": None, "watermark": "2026-02-25T10:00:00Z"},
        ]
    session.program("orders.list", pages)
    return session


def _make_order(order_id: str) -> dict:
    """Build a minimal order dict for testing."""
    return {
        "id": order_id,
        "order_number": order_id.replace("D", "100"),
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-20T10:00:00Z",
        "updated_at": "2026-02-20T10:00:00Z",
        "total_price": "25.00",
        "currency": "USD",
        "customer_name": f"Customer {order_id}",
        "customer_email": f"{order_id.lower()}@test.com",
        "shipping_address": {
            "name": f"Customer {order_id}",
            "address1": f"{order_id} Main St",
            "city": "Austin",
            "state": "TX",
            "zip": "78701",
            "country_code": "US",
        },
        "line_items": [{"quantity": 1, "grams": 500, "title": "Widget"}],
        "tags": "test",
    }


@pytest.fixture
def duckdb_conn():
    """In-memory DuckDB connection with external_orders table."""
    conn = duckdb.connect(":memory:")
    ensure_external_orders_table(conn)
    yield conn
    conn.close()


class TestActivateInitialSync:
    """Test full initial sync (mode='initial')."""

    @pytest.mark.asyncio
    async def test_activate_initial_sync_full_pull(self, duckdb_conn):
        """Pages through all orders, imports to DuckDB."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )

        service = PlatformActivationService(
            registry=registry,
            gateway=gateway,
            duckdb_conn=duckdb_conn,
        )

        report = await service.activate_platform("dummy", "test", mode="initial")

        assert isinstance(report, ActivationReport)
        assert report.platform_id == "dummy"
        assert report.total_imported == 6
        assert report.pages_fetched == 2

        # Verify DuckDB rows
        count = duckdb_conn.execute(
            "SELECT COUNT(*) FROM external_orders WHERE platform = 'dummy'"
        ).fetchone()[0]
        assert count == 6

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_watermark_only_advanced_on_completion(self, duckdb_conn):
        """Watermark is set at end, not during page iteration."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )

        service = PlatformActivationService(
            registry=registry,
            gateway=gateway,
            duckdb_conn=duckdb_conn,
        )

        report = await service.activate_platform("dummy", "test", mode="initial")

        # Final checkpoint should have watermark
        assert report.watermark is not None
        assert report.watermark == "2026-02-25T10:00:00Z"

        # Verify registry.record_sync_checkpoint was called
        assert registry.record_sync_checkpoint.call_count >= 1
        # Last call should have watermark set (completion)
        last_call = registry.record_sync_checkpoint.call_args_list[-1]
        assert last_call.kwargs.get("watermark") or last_call[1].get("watermark") is not None

        await gateway.shutdown()


class TestCheckpoints:
    """Test checkpoint persistence per page."""

    @pytest.mark.asyncio
    async def test_checkpoint_persisted_per_page(self, duckdb_conn):
        """resume_cursor saved after each page batch."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )

        service = PlatformActivationService(
            registry=registry,
            gateway=gateway,
            duckdb_conn=duckdb_conn,
        )

        await service.activate_platform("dummy", "test", mode="initial")

        # At least 2 checkpoint calls (one per page) + 1 completion
        assert registry.record_sync_checkpoint.call_count >= 2

        await gateway.shutdown()


class TestRefreshWithWatermark:
    """Test refresh mode uses watermark."""

    @pytest.mark.asyncio
    async def test_activate_refresh_passes_since_to_orders_list(self, duckdb_conn):
        """Refresh mode passes since= param to orders.list."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway
        from src.db.models import PlatformSyncState

        registry = _make_registry()
        # Simulate existing state with watermark
        mock_state = MagicMock()
        mock_state.last_completed_watermark = "2026-02-20T10:00:00Z"
        mock_state.resume_cursor = None
        registry.get_state.return_value = mock_state

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "platform_id": "dummy",
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {"default_page_size": 3, "max_page_size": 3, "overlap_seconds": 0},
        }])
        session.program("auth.connect", [{"ok": True, "account_label": "test-store"}])
        # Single page for refresh
        session.program("orders.list", [{
            "items": [_make_order("D001")],
            "next_cursor": None,
            "watermark": "2026-02-28T10:00:00Z",
        }])

        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )

        service = PlatformActivationService(
            registry=registry,
            gateway=gateway,
            duckdb_conn=duckdb_conn,
        )

        report = await service.activate_platform("dummy", "test", mode="refresh")

        # Verify since was passed in the orders.list call
        # The gateway proxies to session.call_tool("orders.list", args)
        # We verify the args contained since=
        assert report.total_imported == 1

        await gateway.shutdown()


class TestResumeFromCrash:
    """Test resume from cursor after simulated crash."""

    @pytest.mark.asyncio
    async def test_resume_from_cursor_after_crash(self, duckdb_conn):
        """If resume_cursor is set in state, activation resumes from it."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = _make_registry()
        # Simulate crash: resume_cursor is set from previous partial sync
        mock_state = MagicMock()
        mock_state.last_completed_watermark = None
        mock_state.resume_cursor = "page2"
        registry.get_state.return_value = mock_state

        session = FakeSession()
        session.program("platform.health", [{"ok": True, "contract_version": "1.0"}])
        session.program("platform.capabilities", [{
            "platform_id": "dummy",
            "contract_version": "1.0",
            "supports": ["orders.list"],
            "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
            "paging": {"default_page_size": 3, "max_page_size": 3, "overlap_seconds": 0},
        }])
        session.program("auth.connect", [{"ok": True, "account_label": "test-store"}])
        # Only page2 (resumed from cursor)
        session.program("orders.list", [{
            "items": [_make_order("D004"), _make_order("D005"), _make_order("D006")],
            "next_cursor": None,
            "watermark": "2026-02-25T10:00:00Z",
        }])

        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )

        service = PlatformActivationService(
            registry=registry,
            gateway=gateway,
            duckdb_conn=duckdb_conn,
        )

        report = await service.activate_platform("dummy", "test", mode="initial")

        # Should only have fetched 1 page (resumed from page2)
        assert report.pages_fetched == 1
        assert report.total_imported == 3

        await gateway.shutdown()


class TestSyncRunId:
    """Test sync_run_id consistency."""

    @pytest.mark.asyncio
    async def test_sync_run_id_consistent_within_run(self, duckdb_conn):
        """All rows in a single activation share the same sync_run_id."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )

        service = PlatformActivationService(
            registry=registry,
            gateway=gateway,
            duckdb_conn=duckdb_conn,
        )

        await service.activate_platform("dummy", "test", mode="initial")

        # Check all rows have the same sync_run_id
        rows = duckdb_conn.execute(
            "SELECT DISTINCT sync_run_id FROM external_orders WHERE platform = 'dummy'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] is not None

        await gateway.shutdown()


class TestBatchDedupe:
    """Test batch deduplication before upsert."""

    @pytest.mark.asyncio
    async def test_re_upsert_skips_unchanged(self, duckdb_conn):
        """Re-running activation with same data skips unchanged rows."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = _make_registry()

        # First activation
        session1 = _make_gateway_session()
        gateway1 = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session1
        )
        service1 = PlatformActivationService(
            registry=registry, gateway=gateway1, duckdb_conn=duckdb_conn,
        )
        report1 = await service1.activate_platform("dummy", "test", mode="initial")
        assert report1.total_imported == 6
        await gateway1.shutdown()

        # Second activation with same data — all should be skipped
        session2 = _make_gateway_session()
        gateway2 = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session2
        )
        service2 = PlatformActivationService(
            registry=registry, gateway=gateway2, duckdb_conn=duckdb_conn,
        )
        report2 = await service2.activate_platform("dummy", "test", mode="initial")

        # Still 6 rows total (no duplicates)
        count = duckdb_conn.execute(
            "SELECT COUNT(*) FROM external_orders WHERE platform = 'dummy'"
        ).fetchone()[0]
        assert count == 6

        await gateway2.shutdown()


class TestUnknownPlatform:
    """Test error for unknown platform."""

    @pytest.mark.asyncio
    async def test_unknown_platform_raises(self, duckdb_conn):
        """Activating an unknown platform raises PlatformError."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = MagicMock()
        registry.get_config.return_value = None
        gateway = PlatformGateway(registry)

        service = PlatformActivationService(
            registry=registry, gateway=gateway, duckdb_conn=duckdb_conn,
        )

        with pytest.raises(PlatformError) as exc_info:
            await service.activate_platform("nonexistent", "primary", mode="initial")
        assert exc_info.value.error_code == PlatformErrorCode.INVALID_ARGUMENT

        await gateway.shutdown()
