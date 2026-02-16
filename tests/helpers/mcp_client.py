"""MCP subprocess test client for integration testing.

Spawns MCP servers as child processes and communicates via stdio,
enabling real integration tests without mocking MCP communication.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPTestClient:
    """Test client for MCP server subprocess communication.

    Spawns an MCP server as a child process and communicates via stdio
    using the MCP JSON-RPC protocol.

    Attributes:
        command: Executable to run (e.g., "python3" or "node")
        args: Command line arguments for the executable
        env: Environment variables for the child process
    """

    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    _process: subprocess.Popen | None = field(default=None, init=False)
    _request_id: int = field(default=0, init=False)

    @property
    def is_connected(self) -> bool:
        """Check if the MCP server process is running."""
        return self._process is not None and self._process.poll() is None

    async def start(self, timeout: float = 10.0) -> None:
        """Start the MCP server subprocess.

        Args:
            timeout: Maximum seconds to wait for server initialization

        Raises:
            TimeoutError: If server doesn't respond within timeout
            RuntimeError: If server fails to start
        """
        import os

        merged_env = {**os.environ, **self.env}

        self._process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            text=True,
            bufsize=1,
        )

        # Send initialize request
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })

    async def stop(self) -> None:
        """Stop the MCP server subprocess gracefully."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool and return the result.

        Args:
            name: Tool name to call
            arguments: Tool arguments

        Returns:
            Tool result as a dictionary

        Raises:
            RuntimeError: If not connected or tool call fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to MCP server")

        response = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if "error" in response:
            raise RuntimeError(f"Tool call failed: {response['error']}")

        result = response.get("result", {})

        # Tool-level errors (isError flag in CallToolResult)
        if result.get("isError"):
            error_text = ""
            for item in result.get("content", []):
                if item.get("type") == "text":
                    error_text = item.get("text", "")
                    break
            raise RuntimeError(f"Tool error: {error_text}")

        # Unwrap content[0].text -> JSON parse -> return dict
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, KeyError):
                    return {"raw_text": item.get("text", "")}

        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to MCP server")

        response = await self._send_request("tools/list", {})
        return response.get("result", {}).get("tools", [])

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: RPC method name
            params: Method parameters

        Returns:
            Response dictionary
        """
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError("Process not started")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        # Send request
        request_line = json.dumps(request) + "\n"
        self._process.stdin.write(request_line)
        self._process.stdin.flush()

        # Read response (blocking - should use asyncio for production)
        # Read response (blocking - should use asyncio for production)
        while True:
            response_line = self._process.stdout.readline()
            if not response_line:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise RuntimeError(f"No response from server. stderr: {stderr}")

            parsed = json.loads(response_line)
            if "id" in parsed and parsed["id"] == self._request_id:
                return parsed

    async def kill_hard(self) -> None:
        """Kill the server process immediately (for crash recovery tests)."""
        if self._process:
            self._process.kill()
            self._process = None
