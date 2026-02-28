# tests/mcp/platforms/dummy/test_vertical_slice.py
"""End-to-end vertical slice: DummyPlatform server contract + mapper + upsert.

Tests the full contract compliance and data flow from DummyPlatform orders
through mapper to DuckDB upsert.
"""
import pytest
import duckdb

from src.mcp.platforms.dummy.mapper import DummyMapper
from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
from src.mcp.data_source.tools.schema_migration import ensure_external_orders_table


class TestDummyServerContract:
    """Verify the DummyPlatform MCP implements the required tool contract."""

    @pytest.mark.asyncio
    async def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.dummy.server import mcp
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {
            "platform.health", "platform.capabilities", "auth.connect",
            "auth.disconnect", "orders.list", "orders.get", "tracking.write_back",
        }
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    @pytest.mark.asyncio
    async def test_health_returns_required_shape(self):
        """Health response must match contract shape."""
        from src.mcp.platforms.dummy.server import health
        result = await health()
        assert result["ok"] is True
        assert result["platform_id"] == "dummy"
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result

    @pytest.mark.asyncio
    async def test_capabilities_returns_required_shape(self):
        """Capabilities response must match contract shape."""
        from src.mcp.platforms.dummy.server import capabilities
        result = await capabilities()
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert result["contract_version"] == "1.0"
        assert "orders.list" in result["supports"]

    @pytest.mark.asyncio
    async def test_orders_list_pages_correctly(self):
        """orders.list returns 2 pages of 3 orders each."""
        from src.mcp.platforms.dummy.server import orders_list

        # Page 1
        page1 = await orders_list()
        assert len(page1["items"]) == 3
        assert page1["next_cursor"] == "page2"
        assert page1["watermark"] is not None

        # Page 2
        page2 = await orders_list(cursor="page2")
        assert len(page2["items"]) == 3
        assert page2["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_orders_get_returns_order(self):
        """orders.get returns a matching order."""
        from src.mcp.platforms.dummy.server import orders_get
        result = await orders_get(order_id="D001")
        assert "order" in result
        assert result["order"]["id"] == "D001"

    @pytest.mark.asyncio
    async def test_orders_get_not_found(self):
        """orders.get returns error for unknown ID."""
        from src.mcp.platforms.dummy.server import orders_get
        result = await orders_get(order_id="NONEXISTENT")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_auth_connect_disconnect(self):
        """auth.connect and auth.disconnect cycle."""
        from src.mcp.platforms.dummy.server import auth_connect, auth_disconnect, health

        connect_result = await auth_connect(credential_ref="test")
        assert connect_result["ok"] is True
        assert connect_result["platform_id"] == "dummy"

        h = await health()
        assert h["auth_valid"] is True

        disconnect_result = await auth_disconnect()
        assert disconnect_result["ok"] is True

    @pytest.mark.asyncio
    async def test_tracking_write_back(self):
        """tracking.write_back is a no-op success."""
        from src.mcp.platforms.dummy.server import tracking_write_back
        result = await tracking_write_back(
            order_id="D001",
            tracking_numbers=["1Z999AA10123456784"],
        )
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_contract_versions_match(self):
        """Contract version must be consistent across health and capabilities."""
        from src.mcp.platforms.dummy.server import health, capabilities
        h = await health()
        c = await capabilities()
        assert h["contract_version"] == c["contract_version"]


class TestDummyMapper:
    """Verify the DummyMapper produces correct flat rows."""

    @pytest.fixture
    def mapper(self):
        return DummyMapper()

    @pytest.fixture
    def sample_order(self):
        return {
            "id": "D001",
            "order_number": "1001",
            "status": "open",
            "payment_status": "paid",
            "fulfillment_status": None,
            "created_at": "2026-02-20T10:00:00Z",
            "updated_at": "2026-02-20T10:00:00Z",
            "total_price": "25.00",
            "currency": "USD",
            "customer_name": "Alice Test",
            "customer_email": "alice@test.com",
            "shipping_address": {
                "name": "Alice Test",
                "address1": "100 First St",
                "city": "Austin",
                "state": "TX",
                "zip": "78701",
                "country_code": "US",
            },
            "line_items": [{"quantity": 1, "grams": 500, "title": "Widget A"}],
            "tags": "test",
        }

    def test_platform_is_dummy(self, mapper, sample_order):
        row = mapper.to_flat_row(sample_order, "test")
        assert row["platform"] == "dummy"

    def test_external_id_is_string(self, mapper, sample_order):
        row = mapper.to_flat_row(sample_order, "test")
        assert row["external_id"] == "D001"
        assert isinstance(row["external_id"], str)

    def test_canonical_hash_is_sha256(self, mapper, sample_order):
        row = mapper.to_flat_row(sample_order, "test")
        assert len(row["canonical_hash"]) == 64

    def test_canonical_hash_deterministic(self, mapper, sample_order):
        row1 = mapper.to_flat_row(sample_order, "test")
        row2 = mapper.to_flat_row(sample_order, "test")
        assert row1["canonical_hash"] == row2["canonical_hash"]

    def test_weight_calculation(self, mapper, sample_order):
        row = mapper.to_flat_row(sample_order, "test")
        assert row["total_weight_grams"] == 500

    def test_price_in_cents(self, mapper, sample_order):
        row = mapper.to_flat_row(sample_order, "test")
        assert row["total_price_cents"] == 2500

    def test_mapping_version(self, mapper, sample_order):
        row = mapper.to_flat_row(sample_order, "test")
        assert row["mapping_version"] == "1.0"


class TestDummyFullDataFlow:
    """Prove the full chain: DummyPlatform orders -> mapper -> DuckDB upsert."""

    @pytest.fixture
    def db(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        yield conn
        conn.close()

    @pytest.mark.asyncio
    async def test_full_page_through_and_upsert(self, db):
        """Page through all DummyPlatform orders, map, and upsert to DuckDB."""
        from src.mcp.platforms.dummy.server import orders_list

        mapper = DummyMapper()
        all_rows = []

        # Page 1
        page1 = await orders_list()
        for order in page1["items"]:
            all_rows.append(mapper.to_flat_row(order, "test"))

        # Page 2
        page2 = await orders_list(cursor=page1["next_cursor"])
        for order in page2["items"]:
            all_rows.append(mapper.to_flat_row(order, "test"))

        assert len(all_rows) == 6

        # Upsert all rows
        result = upsert_records_to_duckdb(
            db, all_rows, "external_orders",
            ["platform", "external_id", "credential_ref"],
        )
        assert result["inserted"] == 6
        assert result["updated"] == 0
        assert result["skipped"] == 0

        # Verify in DuckDB
        count = db.execute("SELECT COUNT(*) FROM external_orders WHERE platform='dummy'").fetchone()[0]
        assert count == 6

    @pytest.mark.asyncio
    async def test_re_upsert_skips_unchanged(self, db):
        """Second upsert of same data should skip all records."""
        from src.mcp.platforms.dummy.server import orders_list

        mapper = DummyMapper()
        rows = []
        page = await orders_list()
        for order in page["items"]:
            rows.append(mapper.to_flat_row(order, "test"))

        # First upsert
        upsert_records_to_duckdb(
            db, rows, "external_orders",
            ["platform", "external_id", "credential_ref"],
        )

        # Re-map with same data (canonical_hash should be same)
        rows2 = []
        page = await orders_list()
        for order in page["items"]:
            rows2.append(mapper.to_flat_row(order, "test"))

        result = upsert_records_to_duckdb(
            db, rows2, "external_orders",
            ["platform", "external_id", "credential_ref"],
        )
        assert result["skipped"] == 3
        assert result["inserted"] == 0
        assert result["updated"] == 0

    @pytest.mark.asyncio
    async def test_cross_platform_isolation(self, db):
        """Dummy and shopify orders don't collide on external_id."""
        mapper = DummyMapper()
        dummy_row = mapper.to_flat_row(
            {"id": "1", "order_number": "1", "line_items": []}, "test"
        )

        # Manually create a "shopify" row with same external_id
        shopify_row = dict(dummy_row)
        shopify_row["platform"] = "shopify"
        shopify_row["canonical_hash"] = "different_hash"

        result = upsert_records_to_duckdb(
            db, [dummy_row, shopify_row], "external_orders",
            ["platform", "external_id", "credential_ref"],
        )
        assert result["inserted"] == 2


class TestDummyVerticalSliceIntegration:
    """Full activation integration tests using PlatformGateway + ActivationService."""

    @pytest.fixture
    def db(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        yield conn
        conn.close()

    def _make_gateway_session(self):
        """Build a FakeSession with DummyPlatform responses."""
        from tests.services.fake_mcp_session import FakeSession

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
        return session

    def _make_registry(self):
        """Build a mock registry with dummy config."""
        from unittest.mock import MagicMock
        from src.services.platform_models import PlatformConfig

        config = PlatformConfig(
            platform_id="dummy",
            display_name="Dummy (Test)",
            default_profile="test",
            required_secret_keys=[],
            mcp_module="src.mcp.platforms.dummy.server",
            mcp_bundle_subcommand="mcp-dummy",
            contract_version="1.0",
            default_sync_overlap_seconds=0,
            enabled=True,
        )
        registry = MagicMock()
        registry.get_config.return_value = config
        registry.get_state.return_value = None
        registry.update_state = MagicMock()
        registry.record_sync_checkpoint = MagicMock()
        registry.record_capabilities = MagicMock()
        registry.record_health_check = MagicMock()
        registry.resolve_auth_args.return_value = {"credential_ref": "test"}
        return registry

    def _mock_data_gateway(self, db):
        """Build a mock DataSourceMCPClient that upserts to the local DuckDB."""
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb

        class LocalDSClient:
            async def upsert_records(self, records, table_name, pk_columns):
                return upsert_records_to_duckdb(db, records, table_name, pk_columns)

        client = LocalDSClient()

        async def fake_get():
            return client

        return fake_get

    @pytest.mark.asyncio
    async def test_full_activation_imports_all_pages(self, db):
        """Activate dummy platform -> 2 pages -> 6 orders in DuckDB."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway
        from src.mcp.platforms.dummy.server import orders_list as dummy_orders_list
        from unittest.mock import patch

        registry = self._make_registry()
        session = self._make_gateway_session()

        # Program page responses matching the dummy server's fixed data
        page1 = await dummy_orders_list()
        page2 = await dummy_orders_list(cursor="page2")
        session.program("orders.list", [page1, page2])

        gateway = PlatformGateway(registry, session_factory=lambda cfg, ref: session)
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch("src.services.gateway_provider.get_data_gateway", new=self._mock_data_gateway(db)):
            report = await service.activate_platform("dummy", "test", mode="initial")

        assert report.total_imported == 6
        assert report.pages_fetched == 2

        count = db.execute("SELECT COUNT(*) FROM external_orders WHERE platform='dummy'").fetchone()[0]
        assert count == 6

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_refresh_with_watermark(self, db):
        """Second activation with mode=refresh passes since= to orders.list."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway
        from unittest.mock import MagicMock, patch

        registry = self._make_registry()
        mock_state = MagicMock()
        mock_state.last_completed_watermark = "2026-02-20T10:00:00Z"
        mock_state.resume_cursor = None
        registry.get_state.return_value = mock_state

        session = self._make_gateway_session()
        session.program("orders.list", [{
            "items": [{"id": "D001", "order_number": "1001", "status": "open",
                       "line_items": [{"quantity": 1, "grams": 500}],
                       "total_price": "25.00", "currency": "USD"}],
            "next_cursor": None,
            "watermark": "2026-02-28T10:00:00Z",
        }])

        gateway = PlatformGateway(registry, session_factory=lambda cfg, ref: session)
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch("src.services.gateway_provider.get_data_gateway", new=self._mock_data_gateway(db)):
            report = await service.activate_platform("dummy", "test", mode="refresh")

        assert report.total_imported == 1
        assert report.watermark == "2026-02-28T10:00:00Z"

        await gateway.shutdown()

    @pytest.mark.asyncio
    async def test_resume_after_simulated_crash(self, db):
        """Set resume_cursor in registry, verify activation resumes from cursor."""
        from src.services.platform_activation_service import PlatformActivationService
        from src.services.platform_gateway import PlatformGateway
        from unittest.mock import MagicMock, patch

        registry = self._make_registry()
        mock_state = MagicMock()
        mock_state.last_completed_watermark = None
        mock_state.resume_cursor = "page2"
        registry.get_state.return_value = mock_state

        session = self._make_gateway_session()
        session.program("orders.list", [{
            "items": [
                {"id": "D004", "order_number": "1004", "status": "open",
                 "line_items": [{"quantity": 1, "grams": 400}],
                 "total_price": "75.00", "currency": "USD"},
            ],
            "next_cursor": None,
            "watermark": "2026-02-25T10:00:00Z",
        }])

        gateway = PlatformGateway(registry, session_factory=lambda cfg, ref: session)
        service = PlatformActivationService(registry=registry, gateway=gateway)

        with patch("src.services.gateway_provider.get_data_gateway", new=self._mock_data_gateway(db)):
            report = await service.activate_platform("dummy", "test", mode="initial")

        assert report.pages_fetched == 1
        assert report.total_imported == 1

        await gateway.shutdown()
