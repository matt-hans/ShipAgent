"""Tests for DataSourceMCPClient — MCP-backed DataSourceGateway implementation.

Verifies that methods delegate correctly to the underlying MCPClient
and that response normalization works as expected.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.data_source_mcp_client import DataSourceMCPClient


@pytest.fixture
def mock_mcp():
    """Mock MCPClient with call_tool and connection methods."""
    mcp = MagicMock()
    mcp.call_tool = AsyncMock()
    mcp.is_connected = True
    mcp.connect = AsyncMock()
    return mcp


@pytest.fixture
def client(mock_mcp):
    """DataSourceMCPClient with injected mock MCPClient."""
    c = DataSourceMCPClient.__new__(DataSourceMCPClient)
    c._mcp = mock_mcp
    return c


@pytest.mark.asyncio
async def test_import_csv(client, mock_mcp):
    """import_csv should delegate to MCP import_csv tool."""
    mock_mcp.call_tool.return_value = {
        "row_count": 50, "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "csv", "warnings": [],
    }
    result = await client.import_csv("/tmp/orders.csv")
    assert result["row_count"] == 50
    mock_mcp.call_tool.assert_called_once_with(
        "import_csv", {"file_path": "/tmp/orders.csv", "delimiter": ",", "header": True}
    )


@pytest.mark.asyncio
async def test_get_source_info_returns_none_when_inactive(client, mock_mcp):
    """get_source_info should return None when no source is active."""
    mock_mcp.call_tool.return_value = {"active": False}
    result = await client.get_source_info()
    assert result is None


@pytest.mark.asyncio
async def test_get_source_info_returns_dict_when_active(client, mock_mcp):
    """get_source_info should return the full dict when source is active."""
    mock_mcp.call_tool.return_value = {
        "active": True, "source_type": "csv", "row_count": 10,
    }
    result = await client.get_source_info()
    assert result["source_type"] == "csv"
    assert result["row_count"] == 10


@pytest.mark.asyncio
async def test_get_rows_normalizes_shape(client, mock_mcp):
    """MCP returns {rows:[{row_number,data,checksum}]} — gateway returns flat dicts."""
    mock_mcp.call_tool.return_value = {
        "rows": [
            {"row_number": 1, "data": {"id": "1", "name": "Alice"}, "checksum": "abc"},
            {"row_number": 2, "data": {"id": "2", "name": "Bob"}, "checksum": "def"},
        ],
        "total_count": 2,
    }
    result = await client.get_rows_by_filter("1=1")
    assert len(result) == 2
    assert result[0] == {"id": "1", "name": "Alice", "_row_number": 1, "_checksum": "abc"}


@pytest.mark.asyncio
async def test_get_rows_normalizes_none_clause(client, mock_mcp):
    """None where_clause should be normalized to '1=1'."""
    mock_mcp.call_tool.return_value = {"rows": [], "total_count": 0}
    await client.get_rows_by_filter(None)
    call_args = mock_mcp.call_tool.call_args[0]
    assert call_args[1]["where_clause"] == "1=1"


@pytest.mark.asyncio
async def test_write_back_batch_iterates(client, mock_mcp):
    """write_back_batch should call write_back per row."""
    mock_mcp.call_tool.return_value = {"success": True}
    result = await client.write_back_batch({
        1: {"tracking_number": "1Z001", "shipped_at": "2026-01-01"},
        2: {"tracking_number": "1Z002", "shipped_at": "2026-01-01"},
    })
    assert result["success_count"] == 2
    assert mock_mcp.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_get_source_signature(client, mock_mcp):
    """get_source_signature should transform get_source_info into service contract format."""
    mock_mcp.call_tool.return_value = {
        "active": True,
        "source_type": "csv",
        "path": "/tmp/orders.csv",
        "signature": "abc123",
    }
    result = await client.get_source_signature()
    assert result == {
        "source_type": "csv",
        "source_ref": "/tmp/orders.csv",
        "schema_fingerprint": "abc123",
    }


@pytest.mark.asyncio
async def test_disconnect_calls_clear_source(client, mock_mcp):
    """disconnect should call the clear_source MCP tool."""
    mock_mcp.call_tool.return_value = {"status": "disconnected"}
    await client.disconnect()
    mock_mcp.call_tool.assert_called_once_with("clear_source", {})


@pytest.mark.asyncio
async def test_import_from_records(client, mock_mcp):
    """import_from_records should delegate to MCP import_records tool."""
    mock_mcp.call_tool.return_value = {
        "row_count": 3, "source_type": "shopify", "columns": ["id", "name"],
    }
    result = await client.import_from_records(
        records=[{"id": "1"}, {"id": "2"}, {"id": "3"}],
        source_label="shopify",
    )
    assert result["row_count"] == 3
    mock_mcp.call_tool.assert_called_once_with(
        "import_records", {"records": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "source_label": "shopify"}
    )
