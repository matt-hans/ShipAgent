"""Integration tests for Data Source MCP server lifecycle.

Tests verify:
- Server starts successfully as subprocess
- Server responds to MCP initialize handshake
- Server lists all expected tools
- Server shuts down cleanly
- Server handles unexpected termination
"""

import pytest

from tests.helpers import MCPTestClient


@pytest.fixture
def data_mcp_client(data_mcp_config) -> MCPTestClient:
    """Create MCPTestClient configured for Data MCP."""
    return MCPTestClient(
        command=data_mcp_config["command"],
        args=data_mcp_config["args"],
        env=data_mcp_config["env"],
    )


@pytest.mark.integration
class TestDataMCPLifecycle:
    """Tests for Data MCP server lifecycle management."""

    @pytest.mark.asyncio
    async def test_server_starts_successfully(self, data_mcp_client):
        """Server should start and respond to initialize."""
        await data_mcp_client.start(timeout=10.0)
        assert data_mcp_client.is_connected
        await data_mcp_client.stop()

    @pytest.mark.asyncio
    async def test_server_lists_all_tools(self, data_mcp_client):
        """Server should list all 13 expected tools."""
        await data_mcp_client.start()
        try:
            tools = await data_mcp_client.list_tools()
            tool_names = [t["name"] for t in tools]

            expected_tools = [
                "import_csv", "import_excel", "import_database",
                "list_sheets", "list_tables",
                "get_schema", "override_column_type",
                "get_row", "get_rows_by_filter", "query_data",
                "compute_checksums", "verify_checksum",
                "write_back",
            ]

            for expected in expected_tools:
                assert expected in tool_names, f"Missing tool: {expected}"

            assert len(tools) == 13
        finally:
            await data_mcp_client.stop()

    @pytest.mark.asyncio
    async def test_server_shuts_down_cleanly(self, data_mcp_client):
        """Server should shut down without errors."""
        await data_mcp_client.start()
        await data_mcp_client.stop()
        assert not data_mcp_client.is_connected

    @pytest.mark.asyncio
    async def test_server_handles_kill(self, data_mcp_client):
        """Client should handle server being killed."""
        await data_mcp_client.start()
        await data_mcp_client.kill_hard()
        assert not data_mcp_client.is_connected

    @pytest.mark.asyncio
    async def test_server_can_restart_after_kill(self, data_mcp_client):
        """Server should be restartable after being killed."""
        await data_mcp_client.start()
        await data_mcp_client.kill_hard()

        # Should be able to start again
        await data_mcp_client.start()
        assert data_mcp_client.is_connected
        await data_mcp_client.stop()
