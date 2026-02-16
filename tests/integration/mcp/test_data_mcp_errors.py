"""Integration tests for Data Source MCP error handling.

Tests verify:
- Invalid file paths return structured errors
- Malformed CSV files handled gracefully
- SQL injection attempts rejected
- Missing source operations fail cleanly
"""

import os
import tempfile
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
class TestFileErrors:
    """Tests for file-related error handling."""

    @pytest.mark.asyncio
    async def test_import_nonexistent_file(self, connected_data_mcp):
        """Importing nonexistent file should return error."""
        with pytest.raises(RuntimeError, match="error|not found|exist"):
            await connected_data_mcp.call_tool("import_csv", {
                "file_path": "/nonexistent/path/file.csv",
            })

    @pytest.mark.asyncio
    async def test_import_directory_instead_of_file(self, connected_data_mcp):
        """Importing a directory should return error."""
        with pytest.raises(RuntimeError):
            await connected_data_mcp.call_tool("import_csv", {
                "file_path": "/tmp",
            })

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, connected_data_mcp):
        """Path traversal attempts should be blocked."""
        with pytest.raises(RuntimeError):
            await connected_data_mcp.call_tool("import_csv", {
                "file_path": "../../../etc/passwd",
            })


@pytest.mark.integration
class TestMalformedDataErrors:
    """Tests for malformed data handling."""

    @pytest.mark.asyncio
    async def test_empty_csv_file(self, connected_data_mcp):
        """Empty CSV should be handled gracefully."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            result = await connected_data_mcp.call_tool("import_csv", {
                "file_path": path,
            })
            # Should either return empty result or raise clear error
            assert result.get("row_count", 0) == 0 or "error" in str(result).lower()
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_csv_with_only_headers(self, connected_data_mcp):
        """CSV with only headers should return 0 rows."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, 'w') as f:
            f.write("col1,col2,col3\n")
        try:
            result = await connected_data_mcp.call_tool("import_csv", {
                "file_path": path,
            })
            assert result["row_count"] == 0
        finally:
            os.unlink(path)


@pytest.mark.integration
class TestQueryErrors:
    """Tests for query error handling."""

    @pytest.mark.asyncio
    async def test_query_without_import_fails(self, connected_data_mcp):
        """Querying without importing data should fail."""
        with pytest.raises(RuntimeError, match="no.*source|import"):
            await connected_data_mcp.call_tool("query_data", {
                "sql": "SELECT * FROM imported_data",
            })

    @pytest.mark.asyncio
    async def test_sql_injection_rejected(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """SQL injection attempts should be rejected or sanitized."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        # Attempt DROP TABLE injection
        with pytest.raises(RuntimeError):
            await connected_data_mcp.call_tool("query_data", {
                "sql": "SELECT * FROM imported_data; DROP TABLE imported_data;--",
            })

    @pytest.mark.asyncio
    async def test_invalid_sql_syntax(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Invalid SQL syntax should return clear error."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        with pytest.raises(RuntimeError, match="syntax|parse|invalid"):
            await connected_data_mcp.call_tool("query_data", {
                "sql": "SELECTT * FROMM imported_data",
            })


@pytest.mark.integration
class TestChecksumErrors:
    """Tests for checksum error handling."""

    @pytest.mark.asyncio
    async def test_verify_invalid_row_number(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Verifying nonexistent row should fail."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        with pytest.raises(RuntimeError, match="row|not found|invalid"):
            await connected_data_mcp.call_tool("verify_checksum", {
                "row_number": 9999,
                "expected_checksum": "abc123",
            })

    @pytest.mark.asyncio
    async def test_verify_mismatched_checksum(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Mismatched checksum should be detected."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("verify_checksum", {
            "row_number": 1,
            "expected_checksum": "0000000000000000000000000000000000000000000000000000000000000000",
        })

        assert result["matches"] is False
