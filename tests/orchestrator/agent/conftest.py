"""Pytest configuration for orchestration agent tests.

Mocks the claude_agent_sdk module to allow testing agent tools without
requiring the actual SDK to be installed.
"""

import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock


def mock_sdk_module():
    """Create a mock claude_agent_sdk module.

    This allows the agent package to be imported without the actual SDK.
    All SDK classes/functions are mocked.
    """
    mock_sdk = MagicMock()

    # Mock the main classes used in client.py
    mock_sdk.AssistantMessage = MagicMock
    mock_sdk.ClaudeAgentOptions = MagicMock
    mock_sdk.ClaudeSDKClient = MagicMock
    mock_sdk.HookMatcher = MagicMock
    mock_sdk.ResultMessage = MagicMock
    mock_sdk.SdkMcpTool = MagicMock
    mock_sdk.TextBlock = MagicMock
    mock_sdk.ToolUseBlock = MagicMock
    mock_sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())

    # Mock the types submodule with StreamEvent
    mock_types = MagicMock()
    mock_types.McpStdioServerConfig = dict  # Use dict as TypedDict standin

    @dataclass
    class MockStreamEvent:
        """Mock StreamEvent for testing partial message streaming."""

        uuid: str = ""
        session_id: str = ""
        event: dict[str, Any] = None  # type: ignore[assignment]
        parent_tool_use_id: str | None = None

    mock_types.StreamEvent = MockStreamEvent
    mock_sdk.types = mock_types

    return mock_sdk


# Add mock to sys.modules BEFORE any imports
if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = mock_sdk_module()
    sys.modules["claude_agent_sdk.types"] = sys.modules["claude_agent_sdk"].types
