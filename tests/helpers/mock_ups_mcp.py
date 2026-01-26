"""Mock UPS MCP server for integration testing.

Provides a configurable mock that simulates UPS MCP responses
without requiring real UPS credentials or API calls.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """Record of a tool call made to the mock server."""

    tool_name: str
    arguments: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None


class MockUPSMCPServer:
    """Mock UPS MCP server for testing.

    Allows configuring responses and failures for UPS MCP tools,
    and tracks all calls made for verification.
    """

    def __init__(self) -> None:
        """Initialize the mock server."""
        self._responses: dict[str, dict[str, Any]] = {}
        self._failures: dict[str, str] = {}
        self._call_history: list[ToolCall] = []
        self._call_count: dict[str, int] = {}

        # Default successful responses
        self._default_responses = {
            "rating_quote": {
                "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
            },
            "rating_shop": {
                "rates": [
                    {"serviceCode": "03", "totalCharges": {"monetaryValue": "12.50"}},
                    {"serviceCode": "01", "totalCharges": {"monetaryValue": "45.00"}},
                ],
            },
            "shipping_create": {
                "trackingNumbers": ["1Z999AA10123456784"],
                "labelPaths": ["/labels/label_001.pdf"],
                "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
            },
            "shipping_void": {"success": True},
            "address_validate": {
                "valid": True,
                "candidates": [],
            },
        }

    def configure_response(self, tool_name: str, response: dict[str, Any]) -> None:
        """Configure a successful response for a tool.

        Args:
            tool_name: Name of the tool
            response: Response to return when tool is called
        """
        self._responses[tool_name] = response
        # Clear any configured failure
        self._failures.pop(tool_name, None)

    def configure_failure(self, tool_name: str, error: str) -> None:
        """Configure a tool to fail with an error.

        Args:
            tool_name: Name of the tool
            error: Error message to raise
        """
        self._failures[tool_name] = error
        # Clear any configured response
        self._responses.pop(tool_name, None)

    def configure_failure_on_call(
        self, tool_name: str, call_number: int, error: str
    ) -> None:
        """Configure a tool to fail on a specific call number.

        Args:
            tool_name: Name of the tool
            call_number: Which call should fail (1-indexed)
            error: Error message to raise
        """
        key = f"{tool_name}__call_{call_number}"
        self._failures[key] = error

    def get_call_history(self) -> list[ToolCall]:
        """Get the history of all tool calls.

        Returns:
            List of ToolCall records
        """
        return list(self._call_history)

    def get_call_count(self, tool_name: str) -> int:
        """Get the number of times a tool was called.

        Args:
            tool_name: Name of the tool

        Returns:
            Number of calls
        """
        return self._call_count.get(tool_name, 0)

    def reset(self) -> None:
        """Reset call history and counts."""
        self._call_history.clear()
        self._call_count.clear()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Simulate a tool call.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Configured or default response

        Raises:
            RuntimeError: If tool is configured to fail
        """
        # Track call
        self._call_count[tool_name] = self._call_count.get(tool_name, 0) + 1
        call_num = self._call_count[tool_name]

        # Check for call-specific failure
        call_specific_key = f"{tool_name}__call_{call_num}"
        if call_specific_key in self._failures:
            error = self._failures[call_specific_key]
            self._call_history.append(ToolCall(tool_name, arguments, error=error))
            raise RuntimeError(error)

        # Check for general failure
        if tool_name in self._failures:
            error = self._failures[tool_name]
            self._call_history.append(ToolCall(tool_name, arguments, error=error))
            raise RuntimeError(error)

        # Get response
        if tool_name in self._responses:
            response = self._responses[tool_name]
        elif tool_name in self._default_responses:
            response = self._default_responses[tool_name]
        else:
            response = {}

        self._call_history.append(ToolCall(tool_name, arguments, response=response))
        return response
