"""Tests for generic MCPClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.mcp_client import (
    MCPClient,
    MCPConnectionError,
    MCPToolError,
    _default_is_retryable,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_content(text: str) -> MagicMock:
    """Create a mock TextContent with the given text."""
    from mcp.types import TextContent
    content = MagicMock(spec=TextContent)
    content.text = text
    # Make isinstance check work
    content.__class__ = TextContent
    return content


def _make_call_result(text: str, is_error: bool = False) -> MagicMock:
    """Create a mock CallToolResult."""
    content = _make_text_content(text)
    result = MagicMock()
    result.isError = is_error
    result.content = [content]
    return result


def _make_server_params() -> MagicMock:
    """Create mock StdioServerParameters."""
    from mcp import StdioServerParameters
    return StdioServerParameters(command="test-cmd", args=["--test"])


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestMCPClientLifecycle:
    """Test connection lifecycle (aenter/aexit)."""

    @pytest.mark.asyncio
    async def test_aenter_initializes_session(self):
        """Entering context spawns MCP server and initializes session."""
        mock_session = AsyncMock()
        mock_read = MagicMock()
        mock_write = MagicMock()

        with patch("src.services.mcp_client.stdio_client") as mock_stdio, \
             patch("src.services.mcp_client.ClientSession") as MockSession:

            # stdio_client is an async context manager
            mock_stdio_ctx = AsyncMock()
            mock_stdio_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
            mock_stdio_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_stdio.return_value = mock_stdio_ctx

            # ClientSession is also an async context manager
            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session_ctx

            params = _make_server_params()
            client = MCPClient(params)

            async with client:
                pass

            mock_session.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aenter_spawn_failure_raises_connection_error(self):
        """Spawn failure raises MCPConnectionError."""
        with patch("src.services.mcp_client.stdio_client") as mock_stdio:
            mock_stdio_ctx = AsyncMock()
            mock_stdio_ctx.__aenter__ = AsyncMock(side_effect=OSError("spawn failed"))
            mock_stdio_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_stdio.return_value = mock_stdio_ctx

            params = _make_server_params()
            client = MCPClient(params)

            with pytest.raises(MCPConnectionError) as exc_info:
                async with client:
                    pass

            assert "spawn failed" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_aexit_cleans_up(self):
        """Exiting context shuts down session and stdio."""
        mock_session = AsyncMock()
        mock_read = MagicMock()
        mock_write = MagicMock()

        with patch("src.services.mcp_client.stdio_client") as mock_stdio, \
             patch("src.services.mcp_client.ClientSession") as MockSession:

            mock_stdio_ctx = AsyncMock()
            mock_stdio_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
            mock_stdio_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_stdio.return_value = mock_stdio_ctx

            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session_ctx

            params = _make_server_params()
            client = MCPClient(params)

            async with client:
                pass

            mock_session_ctx.__aexit__.assert_awaited_once()
            mock_stdio_ctx.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# call_tool tests
# ---------------------------------------------------------------------------


class TestMCPClientCallTool:
    """Test call_tool() with JSON parsing and retry."""

    @pytest.mark.asyncio
    async def test_parses_json_from_text_content(self):
        """Successful call returns parsed JSON dict."""
        expected = {"success": True, "value": 42}
        mock_result = _make_call_result(json.dumps(expected))

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        params = _make_server_params()
        client = MCPClient(params, max_retries=0)
        client._session = mock_session

        result = await client.call_tool("test_tool", {"arg": "val"})

        assert result == expected
        mock_session.call_tool.assert_awaited_once_with("test_tool", {"arg": "val"})

    @pytest.mark.asyncio
    async def test_raises_on_no_session(self):
        """call_tool without context raises MCPConnectionError."""
        params = _make_server_params()
        client = MCPClient(params)

        with pytest.raises(MCPConnectionError):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_raises_value_error_on_invalid_json(self):
        """Non-JSON response raises ValueError."""
        mock_result = _make_call_result("not json at all")

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        params = _make_server_params()
        client = MCPClient(params, max_retries=0)
        client._session = mock_session

        with pytest.raises(ValueError, match="invalid JSON"):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        """Retries on retryable error, succeeds on third attempt."""
        error_result = _make_call_result("503 Service Unavailable", is_error=True)
        success_result = _make_call_result(json.dumps({"ok": True}))

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(
            side_effect=[error_result, error_result, success_result],
        )

        params = _make_server_params()
        client = MCPClient(params, max_retries=3, base_delay=0.01)
        client._session = mock_session

        result = await client.call_tool("test_tool", {})

        assert result == {"ok": True}
        assert mock_session.call_tool.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_error(self):
        """Non-retryable errors raise immediately without retry."""
        error_result = _make_call_result(
            '{"code": "120100", "message": "Invalid address"}',
            is_error=True,
        )

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=error_result)

        params = _make_server_params()
        client = MCPClient(params, max_retries=3, base_delay=0.01)
        client._session = mock_session

        with pytest.raises(MCPToolError) as exc_info:
            await client.call_tool("test_tool", {})

        assert mock_session.call_tool.call_count == 1
        assert "Invalid address" in exc_info.value.error_text

    @pytest.mark.asyncio
    async def test_raises_after_retries_exhausted(self):
        """Raises MCPToolError after all retries are exhausted."""
        error_result = _make_call_result("429 Too Many Requests", is_error=True)

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=error_result)

        params = _make_server_params()
        client = MCPClient(params, max_retries=2, base_delay=0.01)
        client._session = mock_session

        with pytest.raises(MCPToolError) as exc_info:
            await client.call_tool("test_tool", {})

        # 1 initial + 2 retries = 3 total
        assert mock_session.call_tool.call_count == 3
        assert exc_info.value.tool_name == "test_tool"

    @pytest.mark.asyncio
    async def test_custom_is_retryable(self):
        """Custom is_retryable callback controls retry behavior."""
        error_result = _make_call_result("custom-retryable-error", is_error=True)
        success_result = _make_call_result(json.dumps({"ok": True}))

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(
            side_effect=[error_result, success_result],
        )

        def custom_retryable(text: str) -> bool:
            """Retry only on our custom pattern."""
            return "custom-retryable" in text

        params = _make_server_params()
        client = MCPClient(params, max_retries=3, base_delay=0.01, is_retryable=custom_retryable)
        client._session = mock_session

        result = await client.call_tool("test_tool", {})
        assert result == {"ok": True}
        assert mock_session.call_tool.call_count == 2


# ---------------------------------------------------------------------------
# Default retryable classifier
# ---------------------------------------------------------------------------


class TestDefaultIsRetryable:
    """Test _default_is_retryable patterns."""

    @pytest.mark.parametrize("text", [
        "429 Too Many Requests",
        "503 Service Unavailable",
        "502 Bad Gateway",
        "rate limit exceeded",
        "connection refused",
        "timeout after 30s",
    ])
    def test_retryable_patterns(self, text: str):
        """Known transient error patterns are classified as retryable."""
        assert _default_is_retryable(text) is True

    @pytest.mark.parametrize("text", [
        "Invalid address line 1",
        "Missing required field: weight",
        "Authentication failed",
        "400 Bad Request",
    ])
    def test_non_retryable_patterns(self, text: str):
        """Validation and auth errors are not retryable."""
        assert _default_is_retryable(text) is False
