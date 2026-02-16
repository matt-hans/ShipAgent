"""Integration tests for Data Source MCP tool execution.

Tests verify:
- CSV import and schema discovery
- Row querying and filtering
- Checksum computation and verification
- Write-back operations
"""

import pytest

from tests.helpers import MCPTestClient


@pytest.fixture
async def connected_data_mcp(data_mcp_config) -> MCPTestClient:
    """Create and start a Data MCP client."""
    client = MCPTestClient(
        command=data_mcp_config["command"],
        args=data_mcp_config["args"],
        env=data_mcp_config["env"],
    )
    await client.start()
    yield client
    await client.stop()


@pytest.mark.integration
class TestCSVImportWorkflow:
    """Tests for CSV import and query workflow."""

    @pytest.mark.asyncio
    async def test_import_csv_returns_schema(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """import_csv should return schema with column info."""
        result = await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        assert "columns" in result
        assert len(result["columns"]) >= 5
        assert result["row_count"] == 5

    @pytest.mark.asyncio
    async def test_get_schema_after_import(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """get_schema should return current source schema."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        schema = await connected_data_mcp.call_tool("get_schema", {})

        column_names = [c["name"] for c in schema["columns"]]
        assert "order_id" in column_names
        assert "recipient_name" in column_names
        assert "state" in column_names

    @pytest.mark.asyncio
    async def test_query_data_with_filter(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """query_data should filter rows by SQL WHERE clause."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("query_data", {
            "sql": "SELECT * FROM imported_data WHERE state = 'CA'",
        })

        assert len(result["rows"]) == 3  # 3 CA orders in sample data

    @pytest.mark.asyncio
    async def test_get_rows_by_filter(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """get_rows_by_filter should return matching rows."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("get_rows_by_filter", {
            "where_clause": "service_type = 'Ground'",
            "limit": 10,
        })

        assert result["total_count"] == 3  # 3 Ground orders
        assert len(result["rows"]) == 3


@pytest.mark.integration
class TestChecksumWorkflow:
    """Tests for checksum computation and verification."""

    @pytest.mark.asyncio
    async def test_compute_checksums_returns_hashes(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """compute_checksums should return SHA-256 for each row."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("compute_checksums", {})

        assert "checksums" in result
        assert len(result["checksums"]) == 5

        # Each checksum should be 64 hex chars (SHA-256)
        for checksum in result["checksums"]:
            assert len(checksum["checksum"]) == 64

    @pytest.mark.asyncio
    async def test_checksums_are_deterministic(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Same data should produce same checksums."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result1 = await connected_data_mcp.call_tool("compute_checksums", {})
        result2 = await connected_data_mcp.call_tool("compute_checksums", {})

        assert result1["checksums"] == result2["checksums"]

    @pytest.mark.asyncio
    async def test_verify_checksum_detects_match(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """verify_checksum should confirm unchanged row."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        checksums = await connected_data_mcp.call_tool("compute_checksums", {})
        first_checksum = checksums["checksums"][0]

        result = await connected_data_mcp.call_tool("verify_checksum", {
            "row_number": first_checksum["row_number"],
            "expected_checksum": first_checksum["checksum"],
        })

        assert result["matches"] is True


@pytest.mark.integration
class TestWriteBackWorkflow:
    """Tests for write-back operations."""

    @pytest.mark.asyncio
    async def test_write_back_adds_tracking_column(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """write_back should add tracking number to source."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("write_back", {
            "row_number": 1,
            "tracking_number": "1Z999AA10123456784",
        })

        assert result["success"] is True
        assert result["tracking_number"] == "1Z999AA10123456784"
