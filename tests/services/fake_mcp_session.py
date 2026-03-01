# tests/services/fake_mcp_session.py
"""Fake MCP session for deterministic gateway tests."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class FakeSession:
    """Programmable fake MCP session for gateway testing.

    Supports: success responses, error responses, timeouts, call counting.
    """

    def __init__(self):
        self.call_count: dict[str, int] = defaultdict(int)
        self._responses: dict[str, list[dict | Exception]] = {}
        self._default_response: dict[str, Any] = {"success": True}
        self.closed = False

    def program(self, tool_name: str, responses: list[dict | Exception]):
        """Set responses for a tool (consumed in order, last one repeats)."""
        self._responses[tool_name] = list(responses)

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Simulate an MCP tool call."""
        self.call_count[tool_name] += 1
        responses = self._responses.get(tool_name, [self._default_response])
        response = responses.pop(0) if len(responses) > 1 else responses[0]
        if isinstance(response, asyncio.TimeoutError):
            raise response
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        """Mark session as closed."""
        self.closed = True
