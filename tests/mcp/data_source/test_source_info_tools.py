"""Tests for source info and record import MCP tools.

Verifies get_source_info returns correct metadata, import_records
creates DuckDB table from flat dicts, and clear_source drops state.
"""

import hashlib

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_ctx_with_source():
    """Context with an active CSV source loaded."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "db": MagicMock(),
        "current_source": {
            "type": "csv",
            "path": "/tmp/orders.csv",
            "row_count": 150,
        },
        "type_overrides": {},
    }
    return ctx


@pytest.fixture
def mock_ctx_no_source():
    """Context with no active source."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "db": MagicMock(),
        "current_source": None,
        "type_overrides": {},
    }
    return ctx


@pytest.mark.asyncio
async def test_get_source_info_returns_metadata(mock_ctx_with_source):
    """get_source_info should return source_type and row_count when source active."""
    from src.mcp.data_source.tools.source_info_tools import get_source_info

    result = await get_source_info(mock_ctx_with_source)
    assert result["source_type"] == "csv"
    assert result["row_count"] == 150


@pytest.mark.asyncio
async def test_get_source_info_no_source(mock_ctx_no_source):
    """get_source_info should return active=False when no source loaded."""
    from src.mcp.data_source.tools.source_info_tools import get_source_info

    result = await get_source_info(mock_ctx_no_source)
    assert result["active"] is False


@pytest.mark.asyncio
async def test_import_records_creates_table(mock_ctx_no_source):
    """import_records should create table and return row count."""
    from src.mcp.data_source.tools.source_info_tools import import_records

    db = mock_ctx_no_source.request_context.lifespan_context["db"]
    db.execute = MagicMock()
    db.execute.return_value.fetchall = MagicMock(return_value=[(3,)])
    db.execute.return_value.fetchone = MagicMock(return_value=(3,))

    result = await import_records(
        records=[
            {"order_id": "1", "name": "Alice"},
            {"order_id": "2", "name": "Bob"},
            {"order_id": "3", "name": "Charlie"},
        ],
        source_label="shopify",
        ctx=mock_ctx_no_source,
    )
    assert result["row_count"] == 3
    assert result["source_type"] == "shopify"


@pytest.mark.asyncio
async def test_import_records_empty_list(mock_ctx_no_source):
    """import_records with empty list should return zero rows."""
    from src.mcp.data_source.tools.source_info_tools import import_records

    result = await import_records(
        records=[],
        source_label="shopify",
        ctx=mock_ctx_no_source,
    )
    assert result["row_count"] == 0


@pytest.mark.asyncio
async def test_clear_source_resets_state(mock_ctx_with_source):
    """clear_source should drop table and reset current_source and type_overrides."""
    from src.mcp.data_source.tools.source_info_tools import clear_source

    result = await clear_source(mock_ctx_with_source)
    assert result["status"] == "disconnected"

    lifespan_ctx = mock_ctx_with_source.request_context.lifespan_context
    assert lifespan_ctx["current_source"] is None
    assert lifespan_ctx["type_overrides"] == {}


@pytest.mark.asyncio
async def test_source_signature_parity_with_data_source_service(mock_ctx_with_source):
    """Signature from get_source_info must match DataSourceService.get_source_signature().

    This is a replay-safety gate: if the two diverge, job source matching
    will break during migration.
    """
    from src.mcp.data_source.tools.source_info_tools import get_source_info

    # Simulate DuckDB DESCRIBE output: (name, type, nullable_flag, ...)
    mock_schema = [
        ("order_id", "BIGINT", "NO"),
        ("customer_name", "VARCHAR", "YES"),
        ("total", "DOUBLE", "YES"),
    ]
    db = mock_ctx_with_source.request_context.lifespan_context["db"]
    db.execute.return_value.fetchall.return_value = mock_schema

    result = await get_source_info(mock_ctx_with_source)

    # Compute expected fingerprint the same way DataSourceService does
    # (src/services/data_source_service.py:442-448)
    expected_parts = [
        f"{col[0]}:{col[1]}:{int(col[2] == 'YES')}"
        for col in mock_schema
    ]
    expected_fingerprint = hashlib.sha256(
        "|".join(expected_parts).encode("utf-8"),
    ).hexdigest()

    assert result["signature"] == expected_fingerprint, (
        f"Signature mismatch — MCP tool produced {result['signature']!r}, "
        f"DataSourceService would produce {expected_fingerprint!r}"
    )

    # Also verify nullable values match real DuckDB output, not hardcoded
    assert result["columns"][0]["nullable"] is False  # BIGINT NO
    assert result["columns"][1]["nullable"] is True   # VARCHAR YES
