"""Integration tests for external_orders data access via imported_data VIEW.

Verifies that platform orders upserted into external_orders can be queried
through the standard data tools (get_source_info, get_rows_by_filter,
get_schema) via the imported_data VIEW bridge.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import duckdb
import pytest

from src.mcp.data_source.tools.schema_migration import ensure_external_orders_table
from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb


def _make_order(
    platform: str,
    external_id: str,
    credential_ref: str = "cred_default",
    order_number: str | None = None,
    ship_to_name: str | None = None,
    ship_to_city: str | None = None,
    ship_to_state: str | None = None,
    ship_to_postal: str | None = None,
    ship_to_country: str = "US",
) -> dict:
    """Build a minimal external_orders row with canonical hash."""
    raw = {
        "platform": platform,
        "external_id": external_id,
        "credential_ref": credential_ref,
        "order_number": order_number or f"ORD-{external_id}",
        "ship_to_name": ship_to_name or f"Customer {external_id}",
        "ship_to_city": ship_to_city or "New York",
        "ship_to_state": ship_to_state or "NY",
        "ship_to_postal": ship_to_postal or "10001",
        "ship_to_country": ship_to_country,
        "total_price_cents": 2500,
        "currency": "USD",
        "item_count": 1,
        "ingested_at": datetime.now(UTC).isoformat(),
    }
    # Compute canonical hash for upsert change detection
    hash_src = "|".join(f"{k}={v}" for k, v in sorted(raw.items()) if v is not None)
    raw["canonical_hash"] = hashlib.sha256(hash_src.encode()).hexdigest()
    return raw


@pytest.fixture
def duckdb_with_orders():
    """Real DuckDB with external_orders table and sample data."""
    conn = duckdb.connect(":memory:")
    ensure_external_orders_table(conn)

    orders = [
        _make_order("shopify", "1001", ship_to_name="Alice Smith", ship_to_state="CA"),
        _make_order("shopify", "1002", ship_to_name="Bob Jones", ship_to_state="NY"),
        _make_order("amazon", "A001", ship_to_name="Charlie Lee", ship_to_state="TX"),
    ]
    upsert_records_to_duckdb(conn, orders, "external_orders", ["platform", "external_id", "credential_ref"])

    yield conn
    conn.close()


@pytest.fixture
def ctx_with_external_orders(duckdb_with_orders):
    """FastMCP-like context backed by DuckDB with external_orders."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "db": duckdb_with_orders,
        "current_source": None,
        "type_overrides": {},
    }
    return ctx


@pytest.fixture
def ctx_empty_external_orders():
    """FastMCP-like context with empty external_orders table."""
    conn = duckdb.connect(":memory:")
    ensure_external_orders_table(conn)

    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "db": conn,
        "current_source": None,
        "type_overrides": {},
    }
    return ctx


class TestGetSourceInfoAutoDetect:
    """get_source_info should auto-detect external_orders when no file source is active."""

    @pytest.mark.asyncio
    async def test_detects_external_orders_when_present(self, ctx_with_external_orders):
        """Should report external_orders as active source with correct row count."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        result = await get_source_info(ctx_with_external_orders)

        assert result["active"] is True
        assert result["source_type"] == "external_orders"
        assert result["row_count"] == 3
        assert result["deterministic_ready"] is True

    @pytest.mark.asyncio
    async def test_returns_inactive_when_external_orders_empty(self, ctx_empty_external_orders):
        """Should return active=False when external_orders has no rows."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        result = await get_source_info(ctx_empty_external_orders)
        assert result["active"] is False

    @pytest.mark.asyncio
    async def test_schema_includes_platform_columns(self, ctx_with_external_orders):
        """Schema should include platform-specific columns like ship_to_name."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        result = await get_source_info(ctx_with_external_orders)

        col_names = [c["name"] for c in result["columns"]]
        # Key columns that the agent needs to see
        assert "platform" in col_names
        assert "external_id" in col_names
        assert "ship_to_name" in col_names
        assert "ship_to_state" in col_names
        assert "ship_to_city" in col_names

    @pytest.mark.asyncio
    async def test_file_source_takes_precedence(self, ctx_with_external_orders):
        """When a file source is active, external_orders auto-detect should not trigger."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        # Simulate an active CSV source
        ctx_with_external_orders.request_context.lifespan_context["current_source"] = {
            "type": "csv",
            "path": "/tmp/orders.csv",
            "row_count": 50,
        }

        result = await get_source_info(ctx_with_external_orders)

        assert result["active"] is True
        assert result["source_type"] == "csv"
        assert result["row_count"] == 50


class TestQueryExternalOrders:
    """Query tools should work against external_orders via the imported_data VIEW."""

    @pytest.mark.asyncio
    async def test_get_rows_by_filter_queries_external_orders(self, ctx_with_external_orders):
        """get_rows_by_filter should query external_orders through the VIEW."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        # First activate the view via get_source_info
        await get_source_info(ctx_with_external_orders)

        from src.mcp.data_source.tools.query_tools import get_rows_by_filter

        result = await get_rows_by_filter(
            where_sql='"platform" = $1',
            ctx=ctx_with_external_orders,
            params=["shopify"],
        )

        assert result["total_count"] == 2
        assert len(result["rows"]) == 2

    @pytest.mark.asyncio
    async def test_get_rows_returns_all_orders(self, ctx_with_external_orders):
        """Should return all 3 orders when no filter is applied."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        await get_source_info(ctx_with_external_orders)

        from src.mcp.data_source.tools.query_tools import get_rows_by_filter

        result = await get_rows_by_filter(
            where_sql="1=1",
            ctx=ctx_with_external_orders,
        )

        assert result["total_count"] == 3

    @pytest.mark.asyncio
    async def test_get_schema_works_for_external_orders(self, ctx_with_external_orders):
        """get_schema should describe external_orders columns."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        await get_source_info(ctx_with_external_orders)

        from src.mcp.data_source.tools.schema_tools import get_schema

        result = await get_schema(ctx_with_external_orders)

        col_names = [c["name"] for c in result["columns"]]
        assert "platform" in col_names
        assert "ship_to_name" in col_names

    @pytest.mark.asyncio
    async def test_get_row_works_for_external_orders(self, ctx_with_external_orders):
        """get_row should retrieve individual rows from external_orders."""
        from src.mcp.data_source.tools.source_info_tools import get_source_info

        await get_source_info(ctx_with_external_orders)

        from src.mcp.data_source.tools.query_tools import get_row

        result = await get_row(1, ctx_with_external_orders)

        assert result["row_number"] == 1
        assert "platform" in result["data"]


class TestActivateExternalOrdersSource:
    """activate_external_orders_source MCP tool should create the VIEW."""

    @pytest.mark.asyncio
    async def test_activates_when_orders_exist(self, ctx_with_external_orders):
        """Should activate and set current_source."""
        from src.mcp.data_source.tools.source_info_tools import (
            activate_external_orders_source,
        )

        result = await activate_external_orders_source(ctx_with_external_orders)

        assert result["status"] == "activated"
        assert result["row_count"] == 3
        assert result["source_type"] == "external_orders"

        # Verify current_source was set
        cs = ctx_with_external_orders.request_context.lifespan_context["current_source"]
        assert cs is not None
        assert cs["type"] == "external_orders"

    @pytest.mark.asyncio
    async def test_returns_no_data_when_empty(self, ctx_empty_external_orders):
        """Should return no_data status when external_orders is empty."""
        from src.mcp.data_source.tools.source_info_tools import (
            activate_external_orders_source,
        )

        result = await activate_external_orders_source(ctx_empty_external_orders)

        assert result["status"] == "no_data"


class TestFileImportOverridesView:
    """File imports should correctly replace the external_orders VIEW."""

    @pytest.mark.asyncio
    async def test_csv_import_replaces_external_orders_view(self, ctx_with_external_orders):
        """Importing a CSV after external_orders activation should replace the VIEW."""
        from src.mcp.data_source.tools.source_info_tools import (
            activate_external_orders_source,
            import_records,
        )

        # First activate external_orders
        await activate_external_orders_source(ctx_with_external_orders)

        # Then import records (simulating CSV import)
        result = await import_records(
            records=[
                {"order_id": "CSV-1", "name": "Test User"},
                {"order_id": "CSV-2", "name": "Other User"},
            ],
            source_label="csv",
            ctx=ctx_with_external_orders,
        )

        assert result["row_count"] == 2
        assert result["source_type"] == "csv"

        # Verify current_source switched to CSV
        cs = ctx_with_external_orders.request_context.lifespan_context["current_source"]
        assert cs["type"] == "csv"
