"""Tests for MCPTestClient helper."""

import pytest
from tests.helpers.mcp_client import MCPTestClient


class TestMCPTestClientInit:
    """Tests for MCPTestClient initialization."""

    def test_client_accepts_server_config(self):
        """Client should accept server command and args."""
        client = MCPTestClient(
            command="python3",
            args=["-m", "src.mcp.data_source.server"],
            env={"PYTHONPATH": "."},
        )
        assert client.command == "python3"
        assert "-m" in client.args

    def test_client_not_connected_initially(self):
        """Client should not be connected before start()."""
        client = MCPTestClient(
            command="python3",
            args=["-m", "src.mcp.data_source.server"],
            env={"PYTHONPATH": "."},
        )
        assert client.is_connected is False
