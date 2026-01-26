"""Tests for MockUPSMCPServer."""

import pytest
from tests.helpers.mock_ups_mcp import MockUPSMCPServer


class TestMockUPSMCPServer:
    """Tests for mock UPS MCP server."""

    def test_configure_response(self):
        """Should store configured responses."""
        server = MockUPSMCPServer()
        server.configure_response("shipping_create", {
            "trackingNumbers": ["1Z999"],
            "labelPaths": ["/labels/test.pdf"],
        })
        assert "shipping_create" in server._responses

    def test_configure_failure(self):
        """Should store configured failures."""
        server = MockUPSMCPServer()
        server.configure_failure("shipping_create", "UPS API Error")
        assert "shipping_create" in server._failures

    def test_get_call_history_empty(self):
        """Should return empty list initially."""
        server = MockUPSMCPServer()
        assert server.get_call_history() == []
