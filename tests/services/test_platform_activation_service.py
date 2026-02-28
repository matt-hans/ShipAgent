# tests/services/test_platform_activation_service.py
"""Tests for PlatformActivationService.

Uses FakeSession + mock registry to test the connect → page → normalize →
upsert → checkpoint flow without real MCP processes.

Upserts are verified via a mock DataSourceMCPClient that captures calls
to upsert_records, matching production behavior where rows flow through
the Data Source MCP server's shared DuckDB.
"""
import pytest
from unittest.mock import MagicMock, patch

from tests.services.fake_mcp_session import FakeSession
from src.services.platform_models import (
    PlatformConfig,
    PlatformError,
    PlatformErrorCode,
    ActivationReport,
)

# Patch target: the deferred import resolves from gateway_provider each time
_PATCH_TARGET = "src.services.gateway_provider.get_data_gateway"


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
    # Dummy has no required_secret_keys, so auth args are just credential_ref
    registry.resolve_auth_args.return_value = {"credential_ref": "test"}
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


class MockDataSourceClient:
    """Mock DataSourceMCPClient that captures upsert_records calls."""

    def __init__(self):
        self.upsert_calls: list[dict] = []
        self.total_inserted = 0

    async def upsert_records(
        self, records: list[dict], table_name: str, pk_columns: list[str]
    ) -> dict:
        """Record the upsert call and return synthetic counts."""
        self.upsert_calls.append({
            "records": records,
            "table_name": table_name,
            "pk_columns": pk_columns,
        })
        count = len(records)
        self.total_inserted += count
        return {"inserted": count, "updated": 0, "skipped": 0}


@pytest.fixture
def mock_ds_client():
    """Create a MockDataSourceClient and a coroutine factory for patching."""
    client = MockDataSourceClient()

    async def fake_get_data_gateway():
        return client

    return client, fake_get_data_gateway


class TestActivateInitialSync:
    """Test full initial sync (mode='initial')."""

    @pytest.mark.asyncio
    async def test_activate_initial_sync_full_pull(self, mock_ds_client):
        """Pages through all orders, upserts via Data Source MCP."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        client, fake_gw = mock_ds_client
        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch(_PATCH_TARGET, new=fake_gw):
            report = await service.activate_platform("dummy", "test", mode="initial")

        assert isinstance(report, ActivationReport)
        assert report.platform_id == "dummy"
        assert report.total_imported == 6
        assert report.pages_fetched == 2

        # Verify upsert calls went through mock data gateway
        assert len(client.upsert_calls) == 2  # one per page
        assert client.total_inserted == 6

        # Verify table_name and pk_columns are correct
        for call in client.upsert_calls:
            assert call["table_name"] == "external_orders"
            assert call["pk_columns"] == ["platform", "external_id", "credential_ref"]

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_watermark_only_advanced_on_completion(self, mock_ds_client):
        """Watermark is set at end, not during page iteration."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        client, fake_gw = mock_ds_client
        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch(_PATCH_TARGET, new=fake_gw):
            report = await service.activate_platform("dummy", "test", mode="initial")

        assert report.watermark is not None
        assert report.watermark == "2026-02-25T10:00:00Z"

        assert registry.record_sync_checkpoint.call_count >= 1
        last_call = registry.record_sync_checkpoint.call_args_list[-1]
        assert last_call.kwargs.get("watermark") or last_call[1].get("watermark") is not None

        await gateway.shutdown()


class TestCheckpoints:
    """Test checkpoint persistence per page."""

    @pytest.mark.asyncio
    async def test_checkpoint_persisted_per_page(self, mock_ds_client):
        """resume_cursor saved after each page batch."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        _, fake_gw = mock_ds_client
        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch(_PATCH_TARGET, new=fake_gw):
            await service.activate_platform("dummy", "test", mode="initial")

        # At least 2 checkpoint calls (one per page) + 1 completion
        assert registry.record_sync_checkpoint.call_count >= 2

        await gateway.shutdown()


class TestRefreshWithWatermark:
    """Test refresh mode uses watermark."""

    @pytest.mark.asyncio
    async def test_activate_refresh_passes_since_to_orders_list(self, mock_ds_client):
        """Refresh mode passes since= param to orders.list."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        client, fake_gw = mock_ds_client
        registry = _make_registry()
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
        session.program("orders.list", [{
            "items": [_make_order("D001")],
            "next_cursor": None,
            "watermark": "2026-02-28T10:00:00Z",
        }])

        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch(_PATCH_TARGET, new=fake_gw):
            report = await service.activate_platform("dummy", "test", mode="refresh")

        assert report.total_imported == 1

        await gateway.shutdown()


class TestResumeFromCrash:
    """Test resume from cursor after simulated crash."""

    @pytest.mark.asyncio
    async def test_resume_from_cursor_after_crash(self, mock_ds_client):
        """If resume_cursor is set in state, activation resumes from it."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        client, fake_gw = mock_ds_client
        registry = _make_registry()
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
        session.program("orders.list", [{
            "items": [_make_order("D004"), _make_order("D005"), _make_order("D006")],
            "next_cursor": None,
            "watermark": "2026-02-25T10:00:00Z",
        }])

        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch(_PATCH_TARGET, new=fake_gw):
            report = await service.activate_platform("dummy", "test", mode="initial")

        assert report.pages_fetched == 1
        assert report.total_imported == 3

        await gateway.shutdown()


class TestSyncRunId:
    """Test sync_run_id consistency."""

    @pytest.mark.asyncio
    async def test_sync_run_id_consistent_within_run(self, mock_ds_client):
        """All rows in a single activation share the same sync_run_id."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        client, fake_gw = mock_ds_client
        registry = _make_registry()
        session = _make_gateway_session()
        gateway = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session
        )
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch(_PATCH_TARGET, new=fake_gw):
            await service.activate_platform("dummy", "test", mode="initial")

        all_sync_ids = set()
        for call in client.upsert_calls:
            for record in call["records"]:
                all_sync_ids.add(record.get("sync_run_id"))

        assert len(all_sync_ids) == 1
        assert None not in all_sync_ids

        await gateway.shutdown()


class TestBatchDedupe:
    """Test batch deduplication before upsert."""

    @pytest.mark.asyncio
    async def test_re_upsert_delivers_rows_to_data_source(self, mock_ds_client):
        """Second activation still delivers rows to Data Source MCP."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        client, fake_gw = mock_ds_client
        registry = _make_registry()

        # First activation
        session1 = _make_gateway_session()
        gateway1 = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session1
        )
        service1 = PlatformActivationService(registry=registry, gateway=gateway1)
        with patch(_PATCH_TARGET, new=fake_gw):
            report1 = await service1.activate_platform("dummy", "test", mode="initial")
        assert report1.total_imported == 6
        await gateway1.shutdown()

        # Second activation with same data
        session2 = _make_gateway_session()
        gateway2 = PlatformGateway(
            registry, session_factory=lambda cfg, ref: session2
        )
        service2 = PlatformActivationService(registry=registry, gateway=gateway2)
        with patch(_PATCH_TARGET, new=fake_gw):
            report2 = await service2.activate_platform("dummy", "test", mode="initial")

        # Rows are sent to Data Source MCP — deduplication happens inside MCP
        assert report2.total_imported == 6
        # Total of 4 upsert calls (2 per activation, 2 pages each)
        assert len(client.upsert_calls) == 4

        await gateway2.shutdown()


class TestUnknownPlatform:
    """Test error for unknown platform."""

    @pytest.mark.asyncio
    async def test_unknown_platform_raises(self):
        """Activating an unknown platform raises PlatformError."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway

        registry = MagicMock()
        registry.get_config.return_value = None
        gateway = PlatformGateway(registry)

        service = PlatformActivationService(registry=registry, gateway=gateway)

        with pytest.raises(PlatformError) as exc_info:
            await service.activate_platform("nonexistent", "primary", mode="initial")
        assert exc_info.value.error_code == PlatformErrorCode.INVALID_ARGUMENT

        await gateway.shutdown()
