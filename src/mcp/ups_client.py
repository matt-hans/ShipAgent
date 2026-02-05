"""UPS MCP Python client.

Lightweight async client that spawns and communicates with the UPS MCP
Node.js server via stdio transport using the MCP protocol.

This client enables the Python-based batch execution to call UPS MCP tools
(shipping_create, rating_quote, etc.) without direct UPS API integration.

Example:
    async with UpsMcpClient() as client:
        result = await client.call_tool("shipping_create", {
            "shipper": {...},
            "shipTo": {...},
            "packages": [...],
            "serviceCode": "03"
        })
        tracking_number = result["trackingNumbers"][0]
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Project root is parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class UpsMcpError(Exception):
    """Error from UPS MCP tool call.

    Attributes:
        code: Error code (e.g., "E-3005", "E-5001")
        message: Human-readable error message
        details: Additional error details from UPS API
    """

    code: str
    message: str
    details: dict | None = None

    def __str__(self) -> str:
        """Return formatted error message."""
        return f"[{self.code}] {self.message}"


class UpsMcpClient:
    """Async client for calling UPS MCP tools via stdio.

    Spawns the UPS MCP Node.js server as a child process and communicates
    using JSON-RPC over stdio (the MCP transport protocol).

    Attributes:
        _process: Subprocess running the UPS MCP server
        _request_id: Counter for JSON-RPC request IDs
        _initialized: Whether the MCP session is initialized
    """

    def __init__(self) -> None:
        """Initialize client with default settings."""
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._initialized = False
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "UpsMcpClient":
        """Start the UPS MCP server and initialize session.

        Returns:
            Self for use in async with statement.

        Raises:
            UpsMcpError: If server fails to start or initialize.
        """
        await self._start_server()
        await self._initialize_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Shutdown the MCP server gracefully."""
        await self._shutdown()

    def _get_env(self) -> dict[str, str]:
        """Build environment variables for UPS MCP server.

        Returns:
            Dict of environment variables including UPS credentials.
        """
        env: dict[str, str] = {}

        # Pass through UPS credentials
        if client_id := os.environ.get("UPS_CLIENT_ID"):
            env["UPS_CLIENT_ID"] = client_id
        if client_secret := os.environ.get("UPS_CLIENT_SECRET"):
            env["UPS_CLIENT_SECRET"] = client_secret
        if account_number := os.environ.get("UPS_ACCOUNT_NUMBER"):
            env["UPS_ACCOUNT_NUMBER"] = account_number

        # Labels output directory
        labels_dir = os.environ.get(
            "UPS_LABELS_OUTPUT_DIR", str(PROJECT_ROOT / "labels")
        )
        env["UPS_LABELS_OUTPUT_DIR"] = labels_dir

        # Node.js needs PATH to find node binary
        if path := os.environ.get("PATH"):
            env["PATH"] = path

        return env

    async def _start_server(self) -> None:
        """Start the UPS MCP Node.js server as subprocess.

        Raises:
            UpsMcpError: If server fails to start.
        """
        ups_mcp_path = PROJECT_ROOT / "packages" / "ups-mcp" / "dist" / "index.js"

        if not ups_mcp_path.exists():
            raise UpsMcpError(
                code="E-4001",
                message=f"UPS MCP not built. Run 'npm run build' in packages/ups-mcp",
                details={"path": str(ups_mcp_path)},
            )

        try:
            self._process = await asyncio.create_subprocess_exec(
                "node",
                str(ups_mcp_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._get_env(),
            )
            logger.info("Started UPS MCP server (PID: %s)", self._process.pid)
        except FileNotFoundError as e:
            raise UpsMcpError(
                code="E-4001",
                message="Node.js not found. Ensure node is installed and in PATH.",
                details={"error": str(e)},
            )
        except Exception as e:
            raise UpsMcpError(
                code="E-4001",
                message=f"Failed to start UPS MCP server: {e}",
                details={"error": str(e)},
            )

    async def _send_request(self, method: str, params: dict | None = None) -> dict:
        """Send JSON-RPC request and wait for response.

        Args:
            method: JSON-RPC method name
            params: Optional parameters for the method

        Returns:
            Response result dict

        Raises:
            UpsMcpError: If request fails or server returns error
        """
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise UpsMcpError(
                code="E-4001",
                message="UPS MCP server not running",
            )

        async with self._lock:
            self._request_id += 1
            request_id = self._request_id

            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params:
                request["params"] = params

            # Send request as newline-delimited JSON
            request_json = json.dumps(request) + "\n"
            self._process.stdin.write(request_json.encode())
            await self._process.stdin.drain()

            logger.debug("Sent MCP request: %s", method)

            # Read response line
            response_line = await self._process.stdout.readline()
            if not response_line:
                # Check stderr for error details
                stderr_data = b""
                if self._process.stderr:
                    try:
                        stderr_data = await asyncio.wait_for(
                            self._process.stderr.read(1024),
                            timeout=0.1,
                        )
                    except asyncio.TimeoutError:
                        pass

                raise UpsMcpError(
                    code="E-4001",
                    message="UPS MCP server closed unexpectedly",
                    details={"stderr": stderr_data.decode(errors="replace")},
                )

            try:
                response = json.loads(response_line.decode())
            except json.JSONDecodeError as e:
                raise UpsMcpError(
                    code="E-4001",
                    message=f"Invalid JSON response from UPS MCP: {e}",
                    details={"response": response_line.decode(errors="replace")},
                )

            # Check for JSON-RPC error
            if "error" in response:
                error = response["error"]
                raise UpsMcpError(
                    code="E-3005",
                    message=error.get("message", "Unknown UPS MCP error"),
                    details=error.get("data"),
                )

            return response.get("result", {})

    async def _send_notification(self, method: str, params: dict | None = None) -> None:
        """Send JSON-RPC notification (no response expected).

        Per JSON-RPC 2.0 spec, notifications do NOT have an 'id' field
        and servers MUST NOT respond to them.

        Args:
            method: JSON-RPC method name
            params: Optional parameters for the method

        Raises:
            UpsMcpError: If server connection is lost
        """
        if not self._process or not self._process.stdin:
            raise UpsMcpError(
                code="E-4001",
                message="UPS MCP server not running",
            )

        async with self._lock:
            # Notifications have no 'id' field per JSON-RPC 2.0 spec
            notification: dict[str, Any] = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if params:
                notification["params"] = params

            # Send notification as newline-delimited JSON
            notification_json = json.dumps(notification) + "\n"
            self._process.stdin.write(notification_json.encode())
            await self._process.stdin.drain()

            logger.debug("Sent MCP notification: %s", method)

    async def _initialize_session(self) -> None:
        """Initialize MCP session with handshake.

        Raises:
            UpsMcpError: If initialization fails.
        """
        # Send initialize request
        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "shipagent-batch",
                    "version": "1.0.0",
                },
            },
        )

        logger.info(
            "MCP session initialized: %s",
            result.get("serverInfo", {}).get("name", "unknown"),
        )

        # Send initialized notification (no response expected per MCP protocol)
        await self._send_notification("notifications/initialized")
        self._initialized = True

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a UPS MCP tool.

        Args:
            name: Tool name (e.g., "shipping_create", "rating_quote")
            arguments: Tool arguments dict

        Returns:
            Tool result dict parsed from JSON response

        Raises:
            UpsMcpError: If tool call fails
        """
        if not self._initialized:
            raise UpsMcpError(
                code="E-4001",
                message="MCP session not initialized. Use 'async with' context manager.",
            )

        result = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

        # Extract text content from MCP response
        content = result.get("content", [])
        if not content:
            raise UpsMcpError(
                code="E-3005",
                message="Empty response from UPS MCP tool",
                details={"tool": name},
            )

        # Parse first text content as JSON
        for item in content:
            if item.get("type") == "text":
                try:
                    return json.loads(item.get("text", "{}"))
                except json.JSONDecodeError as e:
                    raise UpsMcpError(
                        code="E-3005",
                        message=f"Invalid JSON in tool response: {e}",
                        details={"text": item.get("text", "")[:200]},
                    )

        raise UpsMcpError(
            code="E-3005",
            message="No text content in UPS MCP tool response",
            details={"content": content},
        )

    async def _shutdown(self) -> None:
        """Gracefully shutdown the MCP server."""
        if self._process:
            try:
                # Close stdin to signal shutdown
                if self._process.stdin:
                    self._process.stdin.close()

                # Wait for process to exit (with timeout)
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("UPS MCP server did not exit gracefully, killing")
                    self._process.kill()
                    await self._process.wait()

                logger.info("UPS MCP server shutdown complete")
            except Exception as e:
                logger.error("Error shutting down UPS MCP server: %s", e)
            finally:
                self._process = None
                self._initialized = False

    async def list_tools(self) -> list[dict]:
        """List available tools from UPS MCP.

        Returns:
            List of tool definitions with name, description, and schema.
        """
        result = await self._send_request("tools/list")
        return result.get("tools", [])
