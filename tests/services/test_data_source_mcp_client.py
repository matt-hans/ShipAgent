"""Tests for DataSourceMCPClient — MCP-backed DataSourceGateway implementation.

Verifies that methods delegate correctly to the underlying MCPClient
and that response normalization works as expected.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import src.services.mapping_cache as mapping_cache
from src.services.data_source_mcp_client import DataSourceMCPClient, _get_python_command


@pytest.fixture
def mock_mcp():
    """Mock MCPClient with call_tool and connection methods."""
    mcp = MagicMock()
    mcp.call_tool = AsyncMock()
    mcp.is_connected = True
    mcp.connect = AsyncMock()
    mcp.disconnect = AsyncMock()
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
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        result = await client.import_csv("/tmp/orders.csv")
        assert result["row_count"] == 50
        mock_mcp.call_tool.assert_called_once_with(
            "import_csv", {"file_path": "/tmp/orders.csv", "delimiter": ",", "header": True}
        )
        invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_import_csv_skips_invalidation_when_fingerprint_unchanged(client, mock_mcp):
    """import_csv should preserve cache when the new fingerprint matches memory cache."""
    mapping_cache.invalidate()
    mapping_cache.get_or_compute_mapping(
        source_columns=["Name", "Address", "City", "State", "ZIP", "Country", "Weight"],
        schema_fingerprint="fp-same",
        sample_rows=[{"Name": "Alice"}],
    )
    mock_mcp.call_tool.return_value = {
        "row_count": 50,
        "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "csv",
        "signature": "fp-same",
        "warnings": [],
    }
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        await client.import_csv("/tmp/orders.csv")
        invalidate.assert_not_called()
    mapping_cache.invalidate()


@pytest.mark.asyncio
async def test_import_csv_invalidates_when_fingerprint_changes(client, mock_mcp):
    """import_csv should invalidate cache when the new fingerprint differs."""
    mapping_cache.invalidate()
    mapping_cache.get_or_compute_mapping(
        source_columns=["Name", "Address", "City", "State", "ZIP", "Country", "Weight"],
        schema_fingerprint="fp-old",
        sample_rows=[{"Name": "Alice"}],
    )
    mock_mcp.call_tool.return_value = {
        "row_count": 50,
        "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "csv",
        "signature": "fp-new",
        "warnings": [],
    }
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        await client.import_csv("/tmp/orders.csv")
        invalidate.assert_called_once_with()
    mapping_cache.invalidate()


@pytest.mark.asyncio
async def test_import_csv_invalidates_when_signature_absent(client, mock_mcp):
    """import_csv should invalidate cache when no signature is returned."""
    mapping_cache.invalidate()
    mock_mcp.call_tool.return_value = {
        "row_count": 50,
        "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "csv",
        "warnings": [],
    }
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        await client.import_csv("/tmp/orders.csv")
        invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_import_excel_invalidates_mapping_cache(client, mock_mcp):
    """import_excel should invalidate mapping cache after successful import."""
    mock_mcp.call_tool.return_value = {
        "row_count": 12, "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "excel", "warnings": [],
    }
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        result = await client.import_excel("/tmp/orders.xlsx", sheet="Sheet1")
        assert result["row_count"] == 12
        mock_mcp.call_tool.assert_called_once_with(
            "import_excel",
            {"file_path": "/tmp/orders.xlsx", "header": True, "sheet": "Sheet1"},
        )
        invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_import_database_invalidates_mapping_cache(client, mock_mcp):
    """import_database should invalidate mapping cache after successful import."""
    mock_mcp.call_tool.return_value = {
        "row_count": 22, "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "database", "warnings": [],
    }
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        result = await client.import_database(
            "postgres://u:p@localhost/db",
            "SELECT * FROM orders",
        )
        assert result["row_count"] == 22
        mock_mcp.call_tool.assert_called_once_with(
            "import_database",
            {
                "connection_string": "postgres://u:p@localhost/db",
                "query": "SELECT * FROM orders",
                "schema": "public",
            },
        )
        invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_import_database_threads_row_key_columns(client, mock_mcp):
    """import_database should pass optional row_key_columns through to MCP."""
    mock_mcp.call_tool.return_value = {
        "row_count": 22, "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "database", "warnings": [],
    }
    await client.import_database(
        "postgres://u:p@localhost/db",
        "SELECT * FROM orders",
        row_key_columns=["id"],
    )
    mock_mcp.call_tool.assert_called_once_with(
        "import_database",
        {
            "connection_string": "postgres://u:p@localhost/db",
            "query": "SELECT * FROM orders",
            "schema": "public",
            "row_key_columns": ["id"],
        },
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
async def test_get_source_info_typed_includes_determinism_metadata(client, mock_mcp):
    """Typed source info should include deterministic row-key metadata."""
    mock_mcp.call_tool.return_value = {
        "active": True,
        "source_type": "database",
        "path": None,
        "row_count": 10,
        "signature": "sig123",
        "deterministic_ready": False,
        "row_key_strategy": "none",
        "row_key_columns": [],
        "columns": [{"name": "id", "type": "INTEGER", "nullable": False}],
    }
    typed = await client.get_source_info_typed()
    assert typed is not None
    assert typed.deterministic_ready is False
    assert typed.row_key_strategy == "none"
    assert typed.row_key_columns == []


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
async def test_get_rows_with_count_preserves_authoritative_total(client, mock_mcp):
    """get_rows_with_count should preserve MCP total_count while normalizing rows."""
    mock_mcp.call_tool.return_value = {
        "rows": [
            {"row_number": 1, "data": {"id": "1", "name": "Alice"}, "checksum": "abc"},
            {"row_number": 2, "data": {"id": "2", "name": "Bob"}, "checksum": "def"},
        ],
        "total_count": 28,
    }
    result = await client.get_rows_with_count("1=1", limit=10)
    assert result["total_count"] == 28
    assert len(result["rows"]) == 2
    assert result["rows"][0]["_row_number"] == 1


@pytest.mark.asyncio
async def test_get_rows_normalizes_none_clause(client, mock_mcp):
    """None where_clause should be normalized to '1=1'."""
    mock_mcp.call_tool.return_value = {"rows": [], "total_count": 0}
    await client.get_rows_by_filter(None)
    call_args = mock_mcp.call_tool.call_args[0]
    assert call_args[1]["where_sql"] == "1=1"


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
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        await client.disconnect()
        mock_mcp.call_tool.assert_called_once_with("clear_source", {})
        invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_disconnect_always_invalidates(client, mock_mcp):
    """disconnect should invalidate unconditionally, without fingerprint checks."""
    mock_mcp.call_tool.return_value = {"status": "disconnected"}
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        should_invalidate = MagicMock(return_value=False)
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        mp.setattr(
            "src.services.data_source_mcp_client.mapping_cache_should_invalidate",
            should_invalidate,
        )
        await client.disconnect()
        invalidate.assert_called_once_with()
        should_invalidate.assert_not_called()


@pytest.mark.asyncio
async def test_import_from_records(client, mock_mcp):
    """import_from_records should delegate to MCP import_records tool."""
    mock_mcp.call_tool.return_value = {
        "row_count": 3, "source_type": "shopify", "columns": ["id", "name"],
    }
    with pytest.MonkeyPatch.context() as mp:
        invalidate = MagicMock()
        mp.setattr(
            "src.services.data_source_mcp_client.invalidate_mapping_cache",
            invalidate,
        )
        result = await client.import_from_records(
            records=[{"id": "1"}, {"id": "2"}, {"id": "3"}],
            source_label="shopify",
        )
        assert result["row_count"] == 3
        mock_mcp.call_tool.assert_called_once_with(
            "import_records", {"records": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "source_label": "shopify"}
        )
        invalidate.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_source_info_reconnects_once_on_transport_error(client, mock_mcp):
    """Transport failures should trigger one reconnect and replay."""

    class ClosedResourceError(Exception):
        pass

    async def _disconnect() -> None:
        mock_mcp.is_connected = False

    async def _connect() -> None:
        mock_mcp.is_connected = True

    mock_mcp.disconnect.side_effect = _disconnect
    mock_mcp.connect.side_effect = _connect

    mock_mcp.call_tool.side_effect = [
        ClosedResourceError("closed resource"),
        {"active": True, "source_type": "csv", "row_count": 7},
    ]

    result = await client.get_source_info()

    assert result is not None
    assert result["row_count"] == 7
    assert mock_mcp.disconnect.await_count == 1
    assert mock_mcp.connect.await_count == 1
    assert mock_mcp.call_tool.await_count == 2


def test_get_python_command_prefers_explicit_override(monkeypatch):
    """MCP_PYTHON_PATH env should take precedence over venv/system detection."""
    monkeypatch.setenv("MCP_PYTHON_PATH", "/opt/custom/python3")
    assert _get_python_command() == "/opt/custom/python3"


def test_get_python_command_ignores_blank_override(monkeypatch):
    """Blank MCP_PYTHON_PATH should fall back to normal detection."""
    monkeypatch.setenv("MCP_PYTHON_PATH", "   ")
    resolved = _get_python_command()
    assert isinstance(resolved, str)
    assert resolved != ""
