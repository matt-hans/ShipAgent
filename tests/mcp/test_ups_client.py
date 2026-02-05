"""Tests for UPS MCP Python client."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.ups_client import UpsMcpClient, UpsMcpError


class TestUpsMcpError:
    """Test UpsMcpError exception class."""

    def test_error_with_code_and_message(self):
        """Test error can be created with code and message."""
        error = UpsMcpError(
            code="E-3005",
            message="UPS returned an error",
        )
        assert error.code == "E-3005"
        assert error.message == "UPS returned an error"
        assert error.details is None

    def test_error_with_details(self):
        """Test error can include additional details."""
        error = UpsMcpError(
            code="E-5001",
            message="Authentication failed",
            details={"reason": "Invalid credentials"},
        )
        assert error.details == {"reason": "Invalid credentials"}

    def test_error_string_representation(self):
        """Test error __str__ includes code and message."""
        error = UpsMcpError(
            code="E-4001",
            message="System error",
        )
        assert str(error) == "[E-4001] System error"


class TestUpsMcpClientInit:
    """Test UpsMcpClient initialization."""

    def test_client_can_instantiate(self):
        """Test that client can be created."""
        client = UpsMcpClient()
        assert client is not None
        assert client._process is None
        assert client._initialized is False

    def test_client_has_request_counter(self):
        """Test client initializes request ID counter."""
        client = UpsMcpClient()
        assert client._request_id == 0


class TestUpsMcpClientEnv:
    """Test environment variable handling."""

    def test_get_env_passes_ups_credentials(self):
        """Test that UPS credentials are passed to child process."""
        client = UpsMcpClient()

        with patch.dict(
            "os.environ",
            {
                "UPS_CLIENT_ID": "test_client_id",
                "UPS_CLIENT_SECRET": "test_secret",
                "UPS_ACCOUNT_NUMBER": "123456",
                "PATH": "/usr/bin",
            },
        ):
            env = client._get_env()

        assert env["UPS_CLIENT_ID"] == "test_client_id"
        assert env["UPS_CLIENT_SECRET"] == "test_secret"
        assert env["UPS_ACCOUNT_NUMBER"] == "123456"
        assert env["PATH"] == "/usr/bin"

    def test_get_env_uses_default_labels_dir(self):
        """Test default labels directory is set."""
        client = UpsMcpClient()

        with patch.dict("os.environ", {}, clear=True):
            env = client._get_env()

        assert "UPS_LABELS_OUTPUT_DIR" in env
        assert "labels" in env["UPS_LABELS_OUTPUT_DIR"]

    def test_get_env_uses_custom_labels_dir(self):
        """Test custom labels directory is used when set."""
        client = UpsMcpClient()

        with patch.dict(
            "os.environ",
            {"UPS_LABELS_OUTPUT_DIR": "/custom/labels"},
        ):
            env = client._get_env()

        assert env["UPS_LABELS_OUTPUT_DIR"] == "/custom/labels"


class TestUpsMcpClientStartServer:
    """Test server startup functionality."""

    @pytest.mark.asyncio
    async def test_start_server_raises_if_mcp_not_built(self):
        """Test error is raised if UPS MCP dist not found."""
        client = UpsMcpClient()

        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(UpsMcpError) as exc_info:
                await client._start_server()

        assert exc_info.value.code == "E-4001"
        assert "not built" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_start_server_raises_if_node_not_found(self):
        """Test error is raised if Node.js not in PATH."""
        client = UpsMcpClient()

        with patch("pathlib.Path.exists", return_value=True):
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("node not found"),
            ):
                with pytest.raises(UpsMcpError) as exc_info:
                    await client._start_server()

        assert exc_info.value.code == "E-4001"
        assert "Node.js not found" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_start_server_success(self):
        """Test successful server startup."""
        client = UpsMcpClient()

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()

        with patch("pathlib.Path.exists", return_value=True):
            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_process,
            ):
                await client._start_server()

        assert client._process is not None
        assert client._process.pid == 12345


class TestUpsMcpClientSendRequest:
    """Test JSON-RPC request sending."""

    @pytest.mark.asyncio
    async def test_send_request_raises_if_not_running(self):
        """Test error is raised if server not running."""
        client = UpsMcpClient()
        client._process = None

        with pytest.raises(UpsMcpError) as exc_info:
            await client._send_request("test_method")

        assert exc_info.value.code == "E-4001"
        assert "not running" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_send_request_increments_id(self):
        """Test request ID increments on each call."""
        client = UpsMcpClient()

        # Set up mock process
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(
            return_value=b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'
        )

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = None

        client._process = mock_process

        await client._send_request("method1")
        await client._send_request("method2")

        assert client._request_id == 2

    @pytest.mark.asyncio
    async def test_send_request_handles_json_rpc_error(self):
        """Test JSON-RPC error in response is converted to UpsMcpError."""
        client = UpsMcpClient()

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(
            return_value=b'{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}\n'
        )

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = None

        client._process = mock_process

        with pytest.raises(UpsMcpError) as exc_info:
            await client._send_request("test_method")

        assert exc_info.value.code == "E-3005"
        assert "Invalid Request" in exc_info.value.message


class TestUpsMcpClientCallTool:
    """Test tool calling functionality."""

    @pytest.mark.asyncio
    async def test_call_tool_raises_if_not_initialized(self):
        """Test error is raised if session not initialized."""
        client = UpsMcpClient()
        client._initialized = False

        with pytest.raises(UpsMcpError) as exc_info:
            await client.call_tool("shipping_create", {})

        assert exc_info.value.code == "E-4001"
        assert "not initialized" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_call_tool_parses_text_content(self):
        """Test tool response text content is parsed as JSON."""
        client = UpsMcpClient()
        client._initialized = True

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        # Mock response with text content containing JSON
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "success": True,
                            "trackingNumbers": ["1Z999AA10123456784"],
                            "labelPaths": ["/labels/1Z999AA10123456784.pdf"],
                            "totalCharges": {
                                "currencyCode": "USD",
                                "monetaryValue": "15.50",
                            },
                        }),
                    }
                ]
            },
        }

        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(
            return_value=(json.dumps(response) + "\n").encode()
        )

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = None

        client._process = mock_process

        result = await client.call_tool(
            "shipping_create",
            {"shipper": {}, "shipTo": {}, "packages": []},
        )

        assert result["success"] is True
        assert result["trackingNumbers"] == ["1Z999AA10123456784"]
        assert result["totalCharges"]["monetaryValue"] == "15.50"

    @pytest.mark.asyncio
    async def test_call_tool_raises_on_empty_content(self):
        """Test error is raised if response has no content."""
        client = UpsMcpClient()
        client._initialized = True

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": []},
        }

        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(
            return_value=(json.dumps(response) + "\n").encode()
        )

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = None

        client._process = mock_process

        with pytest.raises(UpsMcpError) as exc_info:
            await client.call_tool("shipping_create", {})

        assert exc_info.value.code == "E-3005"
        assert "Empty response" in exc_info.value.message


class TestUpsMcpClientShutdown:
    """Test client shutdown functionality."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_stdin(self):
        """Test shutdown closes stdin to signal process exit."""
        client = UpsMcpClient()

        mock_stdin = MagicMock()
        mock_stdin.close = MagicMock()

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.wait = AsyncMock()

        client._process = mock_process
        client._initialized = True

        await client._shutdown()

        mock_stdin.close.assert_called_once()
        assert client._process is None
        assert client._initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_kills_on_timeout(self):
        """Test process is killed if it doesn't exit gracefully."""
        client = UpsMcpClient()

        mock_stdin = MagicMock()
        mock_stdin.close = MagicMock()

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_process.kill = MagicMock()

        client._process = mock_process
        client._initialized = True

        await client._shutdown()

        mock_process.kill.assert_called_once()


class TestUpsMcpClientContextManager:
    """Test async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_starts_and_stops_server(self):
        """Test context manager handles server lifecycle."""
        with patch.object(UpsMcpClient, "_start_server", new_callable=AsyncMock) as mock_start, \
             patch.object(UpsMcpClient, "_initialize_session", new_callable=AsyncMock) as mock_init, \
             patch.object(UpsMcpClient, "_shutdown", new_callable=AsyncMock) as mock_shutdown:

            async with UpsMcpClient() as client:
                assert client is not None

            mock_start.assert_called_once()
            mock_init.assert_called_once()
            mock_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_shuts_down_on_error(self):
        """Test context manager shuts down even if error occurs."""
        with patch.object(UpsMcpClient, "_start_server", new_callable=AsyncMock), \
             patch.object(UpsMcpClient, "_initialize_session", new_callable=AsyncMock), \
             patch.object(UpsMcpClient, "_shutdown", new_callable=AsyncMock) as mock_shutdown:

            try:
                async with UpsMcpClient() as client:
                    raise ValueError("Test error")
            except ValueError:
                pass

            mock_shutdown.assert_called_once()


class TestUpsMcpClientListTools:
    """Test tool listing functionality."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_definitions(self):
        """Test list_tools returns array of tool definitions."""
        client = UpsMcpClient()
        client._initialized = True

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "shipping_create", "description": "Create shipment"},
                    {"name": "rating_quote", "description": "Get rate quote"},
                ]
            },
        }

        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(
            return_value=(json.dumps(response) + "\n").encode()
        )

        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = None

        client._process = mock_process

        tools = await client.list_tools()

        assert len(tools) == 2
        assert tools[0]["name"] == "shipping_create"
        assert tools[1]["name"] == "rating_quote"
