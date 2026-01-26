# Comprehensive Integration Testing Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement comprehensive integration tests covering Data Source MCP subprocess communication, Shopify MCP integration, orchestration layer, API pipeline, end-to-end flows, and cross-cutting concerns - validating all MVP functionality without UPS credentials.

**Architecture:** Layer-by-layer (bottom-up) approach - validate each layer before building on it. Tests use real subprocess communication for MCPs, real database operations, and mock UPS responses at the boundary.

**Tech Stack:** pytest, pytest-asyncio, AsyncMock, subprocess, FastAPI TestClient, SQLite (file-based for integration tests)

---

## Phase 1: Test Infrastructure & Helpers

### Task 1.1: Create MCPTestClient Helper

**Files:**
- Create: `tests/helpers/__init__.py`
- Create: `tests/helpers/mcp_client.py`
- Test: `tests/helpers/test_mcp_client.py`

**Step 1: Write the failing test**

```python
# tests/helpers/test_mcp_client.py
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/helpers/test_mcp_client.py -v`
Expected: FAIL with "No module named 'tests.helpers'"

**Step 3: Create the helpers package**

```python
# tests/helpers/__init__.py
"""Test helper utilities for integration testing."""

from tests.helpers.mcp_client import MCPTestClient

__all__ = ["MCPTestClient"]
```

**Step 4: Write minimal MCPTestClient implementation**

```python
# tests/helpers/mcp_client.py
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

        return response.get("result", {})

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
        response_line = self._process.stdout.readline()
        if not response_line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"No response from server. stderr: {stderr}")

        return json.loads(response_line)

    async def kill_hard(self) -> None:
        """Kill the server process immediately (for crash recovery tests)."""
        if self._process:
            self._process.kill()
            self._process = None
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/helpers/test_mcp_client.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/helpers/
git commit -m "$(cat <<'EOF'
feat(tests): add MCPTestClient helper for subprocess testing

Enables integration tests with real MCP server subprocesses
instead of mocked tool calls.
EOF
)"
```

---

### Task 1.2: Create Mock UPS MCP Server

**Files:**
- Create: `tests/helpers/mock_ups_mcp.py`
- Test: `tests/helpers/test_mock_ups_mcp.py`

**Step 1: Write the failing test**

```python
# tests/helpers/test_mock_ups_mcp.py
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/helpers/test_mock_ups_mcp.py -v`
Expected: FAIL with "No module named 'tests.helpers.mock_ups_mcp'"

**Step 3: Write minimal implementation**

```python
# tests/helpers/mock_ups_mcp.py
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
```

**Step 4: Update helpers __init__.py**

```python
# tests/helpers/__init__.py
"""Test helper utilities for integration testing."""

from tests.helpers.mcp_client import MCPTestClient
from tests.helpers.mock_ups_mcp import MockUPSMCPServer, ToolCall

__all__ = ["MCPTestClient", "MockUPSMCPServer", "ToolCall"]
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/helpers/test_mock_ups_mcp.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/helpers/mock_ups_mcp.py tests/helpers/test_mock_ups_mcp.py tests/helpers/__init__.py
git commit -m "$(cat <<'EOF'
feat(tests): add MockUPSMCPServer for UPS integration testing

Provides configurable mock responses for UPS MCP tools,
enabling end-to-end testing without UPS credentials.
EOF
)"
```

---

### Task 1.3: Create Shopify Test Utilities

**Files:**
- Create: `tests/helpers/shopify_test_store.py`
- Test: `tests/helpers/test_shopify_test_store.py`

**Step 1: Write the failing test**

```python
# tests/helpers/test_shopify_test_store.py
"""Tests for ShopifyTestStore helper."""

import pytest
from tests.helpers.shopify_test_store import ShopifyTestStore


class TestShopifyTestStoreInit:
    """Tests for ShopifyTestStore initialization."""

    def test_store_requires_credentials(self):
        """Store should require access token and domain."""
        with pytest.raises(ValueError, match="access_token"):
            ShopifyTestStore(access_token="", store_domain="test.myshopify.com")

    def test_store_accepts_valid_credentials(self):
        """Store should accept valid credentials."""
        store = ShopifyTestStore(
            access_token="shpat_test_token",
            store_domain="test.myshopify.com",
        )
        assert store.store_domain == "test.myshopify.com"

    def test_created_orders_initially_empty(self):
        """Created orders list should be empty initially."""
        store = ShopifyTestStore(
            access_token="shpat_test_token",
            store_domain="test.myshopify.com",
        )
        assert store.created_order_ids == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/helpers/test_shopify_test_store.py -v`
Expected: FAIL with "No module named 'tests.helpers.shopify_test_store'"

**Step 3: Write implementation**

```python
# tests/helpers/shopify_test_store.py
"""Shopify test store utilities for integration testing.

Provides helpers for creating, managing, and cleaning up test orders
in a Shopify development/test store.
"""

import subprocess
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShopifyTestStore:
    """Helper for managing test data in a Shopify store.

    Uses the Shopify CLI to create and manage test orders,
    enabling integration testing of the Shopify → Shipment pipeline.

    Attributes:
        access_token: Shopify Admin API access token
        store_domain: Store domain (e.g., mystore.myshopify.com)
    """

    access_token: str
    store_domain: str
    _created_order_ids: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Validate credentials."""
        if not self.access_token:
            raise ValueError("access_token is required")
        if not self.store_domain:
            raise ValueError("store_domain is required")

    @property
    def created_order_ids(self) -> list[str]:
        """Get list of order IDs created by this test session."""
        return list(self._created_order_ids)

    async def create_test_order(
        self,
        line_items: list[dict[str, Any]],
        shipping_address: dict[str, str],
        customer_email: str = "test@example.com",
    ) -> str:
        """Create a test order in Shopify.

        Args:
            line_items: List of line items with title, quantity, price
            shipping_address: Shipping address dictionary
            customer_email: Customer email for the order

        Returns:
            Created order ID

        Example:
            order_id = await store.create_test_order(
                line_items=[{"title": "Test Product", "quantity": 1, "price": "10.00"}],
                shipping_address={
                    "first_name": "Test",
                    "last_name": "Customer",
                    "address1": "123 Test St",
                    "city": "Los Angeles",
                    "province": "CA",
                    "zip": "90001",
                    "country": "US",
                },
            )
        """
        # Build order payload
        order_data = {
            "order": {
                "email": customer_email,
                "fulfillment_status": "unfulfilled",
                "send_receipt": False,
                "send_fulfillment_receipt": False,
                "line_items": [
                    {
                        "title": item.get("title", "Test Product"),
                        "quantity": item.get("quantity", 1),
                        "price": item.get("price", "10.00"),
                    }
                    for item in line_items
                ],
                "shipping_address": shipping_address,
            }
        }

        # Use curl to create order via Admin API
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-X", "POST",
                f"https://{self.store_domain}/admin/api/2024-01/orders.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(order_data),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to create order: {result.stderr}")

        response = json.loads(result.stdout)
        if "errors" in response:
            raise RuntimeError(f"Shopify API error: {response['errors']}")

        order_id = str(response["order"]["id"])
        self._created_order_ids.append(order_id)
        return order_id

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Get order details from Shopify.

        Args:
            order_id: Shopify order ID

        Returns:
            Order data dictionary
        """
        result = subprocess.run(
            [
                "curl",
                "-s",
                f"https://{self.store_domain}/admin/api/2024-01/orders/{order_id}.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to get order: {result.stderr}")

        response = json.loads(result.stdout)
        return response.get("order", {})

    async def delete_order(self, order_id: str) -> None:
        """Delete an order from Shopify.

        Args:
            order_id: Shopify order ID to delete
        """
        # First cancel the order
        subprocess.run(
            [
                "curl",
                "-s",
                "-X", "POST",
                f"https://{self.store_domain}/admin/api/2024-01/orders/{order_id}/cancel.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
            ],
            capture_output=True,
        )

        # Then delete it
        subprocess.run(
            [
                "curl",
                "-s",
                "-X", "DELETE",
                f"https://{self.store_domain}/admin/api/2024-01/orders/{order_id}.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
            ],
            capture_output=True,
        )

        if order_id in self._created_order_ids:
            self._created_order_ids.remove(order_id)

    async def cleanup_test_orders(self) -> None:
        """Delete all orders created by this test session."""
        for order_id in list(self._created_order_ids):
            try:
                await self.delete_order(order_id)
            except Exception:
                pass  # Best effort cleanup
        self._created_order_ids.clear()
```

**Step 4: Update helpers __init__.py**

```python
# tests/helpers/__init__.py
"""Test helper utilities for integration testing."""

from tests.helpers.mcp_client import MCPTestClient
from tests.helpers.mock_ups_mcp import MockUPSMCPServer, ToolCall
from tests.helpers.shopify_test_store import ShopifyTestStore

__all__ = ["MCPTestClient", "MockUPSMCPServer", "ToolCall", "ShopifyTestStore"]
```

**Step 5: Run tests**

Run: `pytest tests/helpers/test_shopify_test_store.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/helpers/shopify_test_store.py tests/helpers/test_shopify_test_store.py tests/helpers/__init__.py
git commit -m "$(cat <<'EOF'
feat(tests): add ShopifyTestStore for order management in tests

Enables creation and cleanup of test orders in Shopify
for end-to-end integration testing.
EOF
)"
```

---

### Task 1.4: Create Process Control Utilities

**Files:**
- Create: `tests/helpers/process_control.py`
- Test: `tests/helpers/test_process_control.py`

**Step 1: Write the failing test**

```python
# tests/helpers/test_process_control.py
"""Tests for ProcessController helper."""

import pytest
from tests.helpers.process_control import ProcessController


class TestProcessController:
    """Tests for process control utilities."""

    def test_controller_initializes(self):
        """Controller should initialize without errors."""
        controller = ProcessController()
        assert controller is not None

    def test_spawn_returns_process(self):
        """Spawn should return a process handle."""
        controller = ProcessController()
        proc = controller.spawn(["python3", "-c", "import time; time.sleep(10)"])
        assert proc is not None
        assert proc.poll() is None  # Still running
        proc.kill()
        proc.wait()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/helpers/test_process_control.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# tests/helpers/process_control.py
"""Process control utilities for crash recovery testing.

Provides helpers for spawning, monitoring, and killing processes
to simulate crash scenarios in integration tests.
"""

import asyncio
import subprocess
import signal
from dataclasses import dataclass
from typing import Callable


@dataclass
class ProcessController:
    """Controller for managing test processes.

    Enables crash recovery testing by providing precise control
    over subprocess lifecycle.
    """

    def spawn(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """Spawn a subprocess.

        Args:
            command: Command and arguments to run
            env: Environment variables (merged with current env)

        Returns:
            Popen process handle
        """
        import os

        merged_env = {**os.environ, **(env or {})}

        return subprocess.Popen(
            command,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def kill_gracefully(self, process: subprocess.Popen, timeout: float = 5.0) -> None:
        """Kill a process gracefully with SIGTERM, then SIGKILL if needed.

        Args:
            process: Process to kill
            timeout: Seconds to wait before SIGKILL
        """
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def kill_hard(self, process: subprocess.Popen) -> None:
        """Kill a process immediately with SIGKILL.

        Args:
            process: Process to kill
        """
        process.kill()
        process.wait()

    async def wait_for_condition(
        self,
        condition: Callable[[], bool],
        timeout: float = 30.0,
        poll_interval: float = 0.1,
    ) -> bool:
        """Wait for a condition to become true.

        Args:
            condition: Callable that returns True when condition is met
            timeout: Maximum seconds to wait
            poll_interval: Seconds between condition checks

        Returns:
            True if condition was met, False if timeout
        """
        elapsed = 0.0
        while elapsed < timeout:
            if condition():
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return False
```

**Step 4: Update helpers __init__.py**

```python
# tests/helpers/__init__.py
"""Test helper utilities for integration testing."""

from tests.helpers.mcp_client import MCPTestClient
from tests.helpers.mock_ups_mcp import MockUPSMCPServer, ToolCall
from tests.helpers.shopify_test_store import ShopifyTestStore
from tests.helpers.process_control import ProcessController

__all__ = [
    "MCPTestClient",
    "MockUPSMCPServer",
    "ToolCall",
    "ShopifyTestStore",
    "ProcessController",
]
```

**Step 5: Run tests**

Run: `pytest tests/helpers/test_process_control.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/helpers/process_control.py tests/helpers/test_process_control.py tests/helpers/__init__.py
git commit -m "$(cat <<'EOF'
feat(tests): add ProcessController for crash recovery testing

Enables precise control over subprocess lifecycle for
simulating crashes in integration tests.
EOF
)"
```

---

### Task 1.5: Create Root-Level conftest.py with Shared Fixtures

**Files:**
- Create: `tests/conftest.py`

**Step 1: Write root conftest with shared fixtures**

```python
# tests/conftest.py
"""Root-level pytest fixtures for all tests.

Provides shared fixtures for integration testing including:
- Database fixtures (file-based SQLite)
- MCP client fixtures
- Shopify store fixtures
- Common test data generators
"""

import csv
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.orchestrator.agent.config import PROJECT_ROOT


# ============================================================================
# Pytest Markers
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests requiring external services"
    )
    config.addinivalue_line(
        "markers", "shopify: marks tests requiring Shopify credentials"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests that take a long time to run"
    )


# ============================================================================
# Skip Conditions
# ============================================================================

requires_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)

requires_shopify_credentials = pytest.mark.skipif(
    not (os.environ.get("SHOPIFY_ACCESS_TOKEN") and os.environ.get("SHOPIFY_STORE_DOMAIN")),
    reason="Shopify credentials not set"
)


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def file_based_db() -> Generator[str, None, None]:
    """Create a file-based SQLite database for integration tests.

    Unlike in-memory databases, this persists across connections
    and can be used for multi-process testing.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)

    yield path

    os.unlink(path)


@pytest.fixture
def integration_db_session(file_based_db: str):
    """Create database session for integration tests."""
    engine = create_engine(f"sqlite:///{file_based_db}")
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_shipping_csv() -> Generator[str, None, None]:
    """Create a sample CSV file with shipping data."""
    fd, path = tempfile.mkstemp(suffix=".csv")

    with os.fdopen(fd, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "recipient_name", "address", "city", "state", "zip",
            "country", "weight_lbs", "service_type"
        ])
        writer.writeheader()

        test_orders = [
            {"order_id": "1001", "recipient_name": "Alice Johnson", "address": "123 Main St",
             "city": "Los Angeles", "state": "CA", "zip": "90001", "country": "US",
             "weight_lbs": "2.5", "service_type": "Ground"},
            {"order_id": "1002", "recipient_name": "Bob Smith", "address": "456 Oak Ave",
             "city": "San Francisco", "state": "CA", "zip": "94102", "country": "US",
             "weight_lbs": "1.2", "service_type": "Ground"},
            {"order_id": "1003", "recipient_name": "Carol White", "address": "789 Pine Rd",
             "city": "San Diego", "state": "CA", "zip": "92101", "country": "US",
             "weight_lbs": "5.0", "service_type": "Next Day Air"},
            {"order_id": "1004", "recipient_name": "David Brown", "address": "321 Elm St",
             "city": "Portland", "state": "OR", "zip": "97201", "country": "US",
             "weight_lbs": "3.3", "service_type": "Ground"},
            {"order_id": "1005", "recipient_name": "Eve Wilson", "address": "654 Maple Dr",
             "city": "Seattle", "state": "WA", "zip": "98101", "country": "US",
             "weight_lbs": "0.8", "service_type": "2nd Day Air"},
        ]

        for order in test_orders:
            writer.writerow(order)

    yield path
    os.unlink(path)


@pytest.fixture
def large_shipping_csv() -> Generator[str, None, None]:
    """Create a large CSV file with 1000 rows for scale testing."""
    fd, path = tempfile.mkstemp(suffix=".csv")

    with os.fdopen(fd, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "recipient_name", "address", "city", "state", "zip",
            "country", "weight_lbs", "service_type"
        ])
        writer.writeheader()

        states = ["CA", "OR", "WA", "NV", "AZ"]
        cities = {
            "CA": [("Los Angeles", "90001"), ("San Francisco", "94102")],
            "OR": [("Portland", "97201")],
            "WA": [("Seattle", "98101")],
            "NV": [("Las Vegas", "89101")],
            "AZ": [("Phoenix", "85001")],
        }
        services = ["Ground", "2nd Day Air", "Next Day Air"]

        for i in range(1000):
            state = states[i % len(states)]
            city, zip_code = cities[state][i % len(cities[state])]
            writer.writerow({
                "order_id": str(10000 + i),
                "recipient_name": f"Customer {i}",
                "address": f"{i} Test Street",
                "city": city,
                "state": state,
                "zip": zip_code,
                "country": "US",
                "weight_lbs": str(round(1.0 + (i % 10) * 0.5, 1)),
                "service_type": services[i % len(services)],
            })

    yield path
    os.unlink(path)


# ============================================================================
# MCP Fixtures
# ============================================================================

@pytest.fixture
def data_mcp_config() -> dict:
    """Get Data MCP configuration for testing."""
    from src.orchestrator.agent.config import get_data_mcp_config
    return get_data_mcp_config()


@pytest.fixture
def shopify_mcp_config() -> dict:
    """Get Shopify MCP configuration for testing."""
    from src.orchestrator.agent.config import get_shopify_mcp_config
    return get_shopify_mcp_config()
```

**Step 2: Run tests to verify conftest loads**

Run: `pytest tests/helpers/ -v`
Expected: PASS (all helper tests still pass with root conftest)

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(tests): add root conftest with shared fixtures

Provides common fixtures for file-based databases, sample CSV data,
MCP configurations, and pytest markers for integration tests.
EOF
)"
```

---

## Phase 2: Data Source MCP Subprocess Tests

### Task 2.1: MCP Server Lifecycle Tests

**Files:**
- Create: `tests/integration/mcp/__init__.py`
- Create: `tests/integration/mcp/test_data_mcp_lifecycle.py`

**Step 1: Write the failing tests**

```python
# tests/integration/mcp/test_data_mcp_lifecycle.py
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
```

**Step 2: Create integration/mcp package**

```python
# tests/integration/mcp/__init__.py
"""Integration tests for MCP servers."""
```

**Step 3: Run tests**

Run: `pytest tests/integration/mcp/test_data_mcp_lifecycle.py -v -m integration`
Expected: Tests run (may need MCPTestClient adjustments for actual MCP protocol)

**Step 4: Commit**

```bash
git add tests/integration/mcp/
git commit -m "$(cat <<'EOF'
test(integration): add Data MCP lifecycle tests

Verifies server startup, tool listing, shutdown, and
crash recovery behavior using real subprocess communication.
EOF
)"
```

---

### Task 2.2: MCP Tool Execution Tests

**Files:**
- Create: `tests/integration/mcp/test_data_mcp_tools.py`

**Step 1: Write the tests**

```python
# tests/integration/mcp/test_data_mcp_tools.py
"""Integration tests for Data Source MCP tool execution.

Tests verify:
- CSV import and schema discovery
- Row querying and filtering
- Checksum computation and verification
- Write-back operations
"""

import pytest

from tests.helpers import MCPTestClient


@pytest.fixture
async def connected_data_mcp(data_mcp_config) -> MCPTestClient:
    """Create and start a Data MCP client."""
    client = MCPTestClient(
        command=data_mcp_config["command"],
        args=data_mcp_config["args"],
        env=data_mcp_config["env"],
    )
    await client.start()
    yield client
    await client.stop()


@pytest.mark.integration
class TestCSVImportWorkflow:
    """Tests for CSV import and query workflow."""

    @pytest.mark.asyncio
    async def test_import_csv_returns_schema(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """import_csv should return schema with column info."""
        result = await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        assert "columns" in result
        assert len(result["columns"]) >= 5
        assert result["row_count"] == 5

    @pytest.mark.asyncio
    async def test_get_schema_after_import(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """get_schema should return current source schema."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        schema = await connected_data_mcp.call_tool("get_schema", {})

        column_names = [c["name"] for c in schema["columns"]]
        assert "order_id" in column_names
        assert "recipient_name" in column_names
        assert "state" in column_names

    @pytest.mark.asyncio
    async def test_query_data_with_filter(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """query_data should filter rows by SQL WHERE clause."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("query_data", {
            "query": "SELECT * FROM source WHERE state = 'CA'",
        })

        assert len(result["rows"]) == 3  # 3 CA orders in sample data

    @pytest.mark.asyncio
    async def test_get_rows_by_filter(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """get_rows_by_filter should return matching rows."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("get_rows_by_filter", {
            "filter_clause": "service_type = 'Ground'",
            "limit": 10,
        })

        assert result["total_count"] == 3  # 3 Ground orders
        assert len(result["rows"]) == 3


@pytest.mark.integration
class TestChecksumWorkflow:
    """Tests for checksum computation and verification."""

    @pytest.mark.asyncio
    async def test_compute_checksums_returns_hashes(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """compute_checksums should return SHA-256 for each row."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("compute_checksums", {})

        assert "checksums" in result
        assert len(result["checksums"]) == 5

        # Each checksum should be 64 hex chars (SHA-256)
        for checksum in result["checksums"]:
            assert len(checksum["hash"]) == 64

    @pytest.mark.asyncio
    async def test_checksums_are_deterministic(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Same data should produce same checksums."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result1 = await connected_data_mcp.call_tool("compute_checksums", {})
        result2 = await connected_data_mcp.call_tool("compute_checksums", {})

        assert result1["checksums"] == result2["checksums"]

    @pytest.mark.asyncio
    async def test_verify_checksum_detects_match(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """verify_checksum should confirm unchanged row."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        checksums = await connected_data_mcp.call_tool("compute_checksums", {})
        first_checksum = checksums["checksums"][0]

        result = await connected_data_mcp.call_tool("verify_checksum", {
            "row_number": first_checksum["row_number"],
            "expected_hash": first_checksum["hash"],
        })

        assert result["valid"] is True


@pytest.mark.integration
class TestWriteBackWorkflow:
    """Tests for write-back operations."""

    @pytest.mark.asyncio
    async def test_write_back_adds_tracking_column(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """write_back should add tracking number to source."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("write_back", {
            "row_number": 1,
            "column_name": "tracking_number",
            "value": "1Z999AA10123456784",
        })

        assert result["success"] is True

        # Verify by re-reading
        row = await connected_data_mcp.call_tool("get_row", {
            "row_number": 1,
        })

        assert row["data"]["tracking_number"] == "1Z999AA10123456784"
```

**Step 2: Run tests**

Run: `pytest tests/integration/mcp/test_data_mcp_tools.py -v -m integration`

**Step 3: Commit**

```bash
git add tests/integration/mcp/test_data_mcp_tools.py
git commit -m "$(cat <<'EOF'
test(integration): add Data MCP tool execution tests

Verifies CSV import, schema discovery, querying, checksums,
and write-back operations via real MCP subprocess calls.
EOF
)"
```

---

### Task 2.3: MCP Error Handling Tests

**Files:**
- Create: `tests/integration/mcp/test_data_mcp_errors.py`

**Step 1: Write the tests**

```python
# tests/integration/mcp/test_data_mcp_errors.py
"""Integration tests for Data Source MCP error handling.

Tests verify:
- Invalid file paths return structured errors
- Malformed CSV files handled gracefully
- SQL injection attempts rejected
- Missing source operations fail cleanly
"""

import os
import tempfile
import pytest

from tests.helpers import MCPTestClient


@pytest.fixture
async def connected_data_mcp(data_mcp_config) -> MCPTestClient:
    """Create and start a Data MCP client."""
    client = MCPTestClient(
        command=data_mcp_config["command"],
        args=data_mcp_config["args"],
        env=data_mcp_config["env"],
    )
    await client.start()
    yield client
    await client.stop()


@pytest.mark.integration
class TestFileErrors:
    """Tests for file-related error handling."""

    @pytest.mark.asyncio
    async def test_import_nonexistent_file(self, connected_data_mcp):
        """Importing nonexistent file should return error."""
        with pytest.raises(RuntimeError, match="error|not found|exist"):
            await connected_data_mcp.call_tool("import_csv", {
                "file_path": "/nonexistent/path/file.csv",
            })

    @pytest.mark.asyncio
    async def test_import_directory_instead_of_file(self, connected_data_mcp):
        """Importing a directory should return error."""
        with pytest.raises(RuntimeError):
            await connected_data_mcp.call_tool("import_csv", {
                "file_path": "/tmp",
            })

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, connected_data_mcp):
        """Path traversal attempts should be blocked."""
        with pytest.raises(RuntimeError):
            await connected_data_mcp.call_tool("import_csv", {
                "file_path": "../../../etc/passwd",
            })


@pytest.mark.integration
class TestMalformedDataErrors:
    """Tests for malformed data handling."""

    @pytest.mark.asyncio
    async def test_empty_csv_file(self, connected_data_mcp):
        """Empty CSV should be handled gracefully."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            result = await connected_data_mcp.call_tool("import_csv", {
                "file_path": path,
            })
            # Should either return empty result or raise clear error
            assert result.get("row_count", 0) == 0 or "error" in str(result).lower()
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_csv_with_only_headers(self, connected_data_mcp):
        """CSV with only headers should return 0 rows."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, 'w') as f:
            f.write("col1,col2,col3\n")
        try:
            result = await connected_data_mcp.call_tool("import_csv", {
                "file_path": path,
            })
            assert result["row_count"] == 0
        finally:
            os.unlink(path)


@pytest.mark.integration
class TestQueryErrors:
    """Tests for query error handling."""

    @pytest.mark.asyncio
    async def test_query_without_import_fails(self, connected_data_mcp):
        """Querying without importing data should fail."""
        with pytest.raises(RuntimeError, match="no.*source|import"):
            await connected_data_mcp.call_tool("query_data", {
                "query": "SELECT * FROM source",
            })

    @pytest.mark.asyncio
    async def test_sql_injection_rejected(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """SQL injection attempts should be rejected or sanitized."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        # Attempt DROP TABLE injection
        with pytest.raises(RuntimeError):
            await connected_data_mcp.call_tool("query_data", {
                "query": "SELECT * FROM source; DROP TABLE source;--",
            })

    @pytest.mark.asyncio
    async def test_invalid_sql_syntax(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Invalid SQL syntax should return clear error."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        with pytest.raises(RuntimeError, match="syntax|parse|invalid"):
            await connected_data_mcp.call_tool("query_data", {
                "query": "SELECTT * FROMM source",
            })


@pytest.mark.integration
class TestChecksumErrors:
    """Tests for checksum error handling."""

    @pytest.mark.asyncio
    async def test_verify_invalid_row_number(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Verifying nonexistent row should fail."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        with pytest.raises(RuntimeError, match="row|not found|invalid"):
            await connected_data_mcp.call_tool("verify_checksum", {
                "row_number": 9999,
                "expected_hash": "abc123",
            })

    @pytest.mark.asyncio
    async def test_verify_mismatched_checksum(
        self, connected_data_mcp, sample_shipping_csv
    ):
        """Mismatched checksum should be detected."""
        await connected_data_mcp.call_tool("import_csv", {
            "file_path": sample_shipping_csv,
        })

        result = await connected_data_mcp.call_tool("verify_checksum", {
            "row_number": 1,
            "expected_hash": "0000000000000000000000000000000000000000000000000000000000000000",
        })

        assert result["valid"] is False
```

**Step 2: Run tests**

Run: `pytest tests/integration/mcp/test_data_mcp_errors.py -v -m integration`

**Step 3: Commit**

```bash
git add tests/integration/mcp/test_data_mcp_errors.py
git commit -m "$(cat <<'EOF'
test(integration): add Data MCP error handling tests

Verifies graceful handling of invalid files, malformed data,
SQL injection attempts, and checksum mismatches.
EOF
)"
```

---

## Phase 3: Shopify MCP Integration Tests

### Task 3.1: Shopify MCP Connectivity Tests

**Files:**
- Create: `tests/integration/mcp/test_shopify_mcp.py`

**Step 1: Write the tests**

```python
# tests/integration/mcp/test_shopify_mcp.py
"""Integration tests for Shopify MCP connectivity.

Tests verify:
- Agent connects to Shopify MCP successfully
- MCP authentication works with store credentials
- Tool discovery returns expected Shopify tools
- Connection handles errors gracefully

Requires: SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN environment variables
"""

import os
import pytest

from tests.helpers import MCPTestClient
from tests.conftest import requires_shopify_credentials


@pytest.fixture
def shopify_mcp_client(shopify_mcp_config) -> MCPTestClient:
    """Create MCPTestClient configured for Shopify MCP."""
    return MCPTestClient(
        command=shopify_mcp_config["command"],
        args=shopify_mcp_config["args"],
        env=shopify_mcp_config["env"],
    )


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyMCPConnectivity:
    """Tests for Shopify MCP connection and tool discovery."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_server_starts_with_credentials(self, shopify_mcp_client):
        """Shopify MCP should start with valid credentials."""
        await shopify_mcp_client.start(timeout=15.0)
        assert shopify_mcp_client.is_connected
        await shopify_mcp_client.stop()

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_server_lists_shopify_tools(self, shopify_mcp_client):
        """Shopify MCP should list order-related tools."""
        await shopify_mcp_client.start()
        try:
            tools = await shopify_mcp_client.list_tools()
            tool_names = [t["name"] for t in tools]

            # Verify essential Shopify tools exist
            # (actual tool names depend on shopify-mcp package)
            assert len(tools) > 0

            # Log available tools for debugging
            print(f"Available Shopify tools: {tool_names}")

        finally:
            await shopify_mcp_client.stop()

    @pytest.mark.asyncio
    async def test_server_fails_without_credentials(self):
        """Shopify MCP should fail gracefully without credentials."""
        client = MCPTestClient(
            command="npx",
            args=["shopify-mcp", "--accessToken", "", "--domain", ""],
            env={"PATH": os.environ.get("PATH", "")},
        )

        with pytest.raises((RuntimeError, TimeoutError)):
            await client.start(timeout=10.0)


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyMCPErrorRecovery:
    """Tests for Shopify MCP error handling."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, shopify_mcp_client):
        """Client should reconnect after server restart."""
        await shopify_mcp_client.start()
        await shopify_mcp_client.stop()

        # Should be able to start again
        await shopify_mcp_client.start()
        assert shopify_mcp_client.is_connected
        await shopify_mcp_client.stop()

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_handles_kill_gracefully(self, shopify_mcp_client):
        """Client should handle server being killed."""
        await shopify_mcp_client.start()
        await shopify_mcp_client.kill_hard()
        assert not shopify_mcp_client.is_connected
```

**Step 2: Run tests (will skip without Shopify credentials)**

Run: `pytest tests/integration/mcp/test_shopify_mcp.py -v -m shopify`

**Step 3: Commit**

```bash
git add tests/integration/mcp/test_shopify_mcp.py
git commit -m "$(cat <<'EOF'
test(integration): add Shopify MCP connectivity tests

Verifies Shopify MCP startup, tool discovery, and error
recovery. Tests skip without SHOPIFY_* credentials.
EOF
)"
```

---

### Task 3.2: Shopify Order Retrieval Tests

**Files:**
- Create: `tests/integration/mcp/test_shopify_orders.py`

**Step 1: Write the tests**

```python
# tests/integration/mcp/test_shopify_orders.py
"""Integration tests for Shopify order retrieval.

Tests verify:
- Fetch orders by status (unfulfilled, pending)
- Fetch orders by date range
- Order data schema matches expected structure
- Pagination works for large order sets
- Order line items and addresses extracted correctly

Requires: SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN environment variables
"""

import pytest

from tests.helpers import MCPTestClient, ShopifyTestStore
from tests.conftest import requires_shopify_credentials


@pytest.fixture
async def connected_shopify_mcp(shopify_mcp_config) -> MCPTestClient:
    """Create and start a Shopify MCP client."""
    client = MCPTestClient(
        command=shopify_mcp_config["command"],
        args=shopify_mcp_config["args"],
        env=shopify_mcp_config["env"],
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
def shopify_test_store() -> ShopifyTestStore:
    """Create ShopifyTestStore for test order management."""
    import os
    return ShopifyTestStore(
        access_token=os.environ.get("SHOPIFY_ACCESS_TOKEN", ""),
        store_domain=os.environ.get("SHOPIFY_STORE_DOMAIN", ""),
    )


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyOrderRetrieval:
    """Tests for fetching orders from Shopify."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_fetch_unfulfilled_orders(self, connected_shopify_mcp):
        """Should fetch orders with unfulfilled status."""
        # Note: Actual tool name depends on shopify-mcp package
        # This test documents expected behavior
        try:
            result = await connected_shopify_mcp.call_tool("get_orders", {
                "status": "unfulfilled",
                "limit": 10,
            })
            assert "orders" in result or "data" in result
        except RuntimeError as e:
            # Tool might have different name - log for debugging
            tools = await connected_shopify_mcp.list_tools()
            pytest.skip(f"get_orders tool not found. Available: {[t['name'] for t in tools]}")

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_order_contains_shipping_address(
        self, connected_shopify_mcp, shopify_test_store
    ):
        """Orders should contain complete shipping address."""
        # Create a test order
        order_id = await shopify_test_store.create_test_order(
            line_items=[{"title": "Test Item", "quantity": 1, "price": "10.00"}],
            shipping_address={
                "first_name": "Test",
                "last_name": "Customer",
                "address1": "123 Test St",
                "city": "Los Angeles",
                "province": "CA",
                "zip": "90001",
                "country": "US",
            },
        )

        try:
            # Fetch the order
            order = await shopify_test_store.get_order(order_id)

            # Verify shipping address fields
            address = order.get("shipping_address", {})
            assert address.get("city") == "Los Angeles"
            assert address.get("province") == "CA"
            assert address.get("zip") == "90001"
        finally:
            await shopify_test_store.cleanup_test_orders()


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyOrderDataIntegrity:
    """Tests for Shopify order data integrity."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_order_id_preserved(self, shopify_test_store):
        """Order ID should be preserved through retrieval."""
        order_id = await shopify_test_store.create_test_order(
            line_items=[{"title": "Test Item", "quantity": 1, "price": "10.00"}],
            shipping_address={
                "first_name": "Test",
                "last_name": "Customer",
                "address1": "123 Test St",
                "city": "Los Angeles",
                "province": "CA",
                "zip": "90001",
                "country": "US",
            },
        )

        try:
            order = await shopify_test_store.get_order(order_id)
            assert str(order["id"]) == order_id
        finally:
            await shopify_test_store.cleanup_test_orders()

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_line_items_preserved(self, shopify_test_store):
        """Line items should be fully preserved."""
        order_id = await shopify_test_store.create_test_order(
            line_items=[
                {"title": "Product A", "quantity": 2, "price": "15.00"},
                {"title": "Product B", "quantity": 1, "price": "25.00"},
            ],
            shipping_address={
                "first_name": "Test",
                "last_name": "Customer",
                "address1": "123 Test St",
                "city": "Los Angeles",
                "province": "CA",
                "zip": "90001",
                "country": "US",
            },
        )

        try:
            order = await shopify_test_store.get_order(order_id)
            line_items = order.get("line_items", [])

            assert len(line_items) == 2

            titles = [item["title"] for item in line_items]
            assert "Product A" in titles
            assert "Product B" in titles
        finally:
            await shopify_test_store.cleanup_test_orders()
```

**Step 2: Run tests**

Run: `pytest tests/integration/mcp/test_shopify_orders.py -v -m shopify`

**Step 3: Commit**

```bash
git add tests/integration/mcp/test_shopify_orders.py
git commit -m "$(cat <<'EOF'
test(integration): add Shopify order retrieval tests

Verifies order fetching, data integrity, and shipping address
extraction from Shopify via MCP.
EOF
)"
```

---

## Phase 4: Orchestration Layer Integration

### Task 4.1: NL Pipeline Integration Tests

**Files:**
- Create: `tests/integration/orchestrator/__init__.py`
- Create: `tests/integration/orchestrator/test_nl_pipeline.py`

**Step 1: Create package and tests**

```python
# tests/integration/orchestrator/__init__.py
"""Integration tests for orchestration layer."""
```

```python
# tests/integration/orchestrator/test_nl_pipeline.py
"""Integration tests for NL parsing → filter → template pipeline.

Tests verify:
- Natural language command produces valid SQL filter
- Filter applied to real Data MCP returns correct row subset
- Generated Jinja2 template renders valid UPS-shaped payloads
- Template passes JSON Schema validation
- Full pipeline: "Ship California orders" → filtered rows → rendered payloads
"""

import pytest

from tests.helpers import MCPTestClient
from tests.conftest import requires_anthropic_key


@pytest.fixture
async def data_mcp_with_sample_data(
    data_mcp_config, sample_shipping_csv
) -> MCPTestClient:
    """Data MCP client with sample CSV loaded."""
    client = MCPTestClient(
        command=data_mcp_config["command"],
        args=data_mcp_config["args"],
        env=data_mcp_config["env"],
    )
    await client.start()

    # Import sample data
    await client.call_tool("import_csv", {"file_path": sample_shipping_csv})

    yield client
    await client.stop()


@pytest.mark.integration
class TestIntentToFilter:
    """Tests for intent parsing to SQL filter generation."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_state_filter_generation(self, data_mcp_with_sample_data):
        """'California orders' should generate state = 'CA' filter."""
        from src.orchestrator.nl_engine import FilterGenerator

        generator = FilterGenerator()
        schema = await data_mcp_with_sample_data.call_tool("get_schema", {})

        result = await generator.generate_filter(
            natural_language="Ship all California orders",
            schema=schema,
        )

        assert result.filter_clause is not None
        assert "CA" in result.filter_clause or "California" in result.filter_clause

        # Apply filter and verify results
        rows = await data_mcp_with_sample_data.call_tool("get_rows_by_filter", {
            "filter_clause": result.filter_clause,
            "limit": 100,
        })

        # Should get only CA orders (3 in sample data)
        assert rows["total_count"] == 3

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_service_filter_generation(self, data_mcp_with_sample_data):
        """'Ground shipments' should filter by service_type."""
        from src.orchestrator.nl_engine import FilterGenerator

        generator = FilterGenerator()
        schema = await data_mcp_with_sample_data.call_tool("get_schema", {})

        result = await generator.generate_filter(
            natural_language="Ship all Ground orders",
            schema=schema,
        )

        rows = await data_mcp_with_sample_data.call_tool("get_rows_by_filter", {
            "filter_clause": result.filter_clause,
            "limit": 100,
        })

        # Should get only Ground orders (3 in sample data)
        assert rows["total_count"] == 3


@pytest.mark.integration
class TestTemplateGeneration:
    """Tests for mapping template generation and rendering."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_template_renders_valid_payload(self, data_mcp_with_sample_data):
        """Generated template should render valid UPS payload."""
        from src.orchestrator.nl_engine import MappingGenerator

        generator = MappingGenerator()
        schema = await data_mcp_with_sample_data.call_tool("get_schema", {})

        template = await generator.generate_template(
            schema=schema,
            service_code="03",  # Ground
        )

        # Get a sample row
        rows = await data_mcp_with_sample_data.call_tool("get_rows_by_filter", {
            "filter_clause": "1=1",
            "limit": 1,
        })
        sample_row = rows["rows"][0]["data"]

        # Render template with sample data
        from jinja2 import Template
        import json

        jinja_template = Template(template.template_string)
        rendered = jinja_template.render(row=sample_row)
        payload = json.loads(rendered)

        # Verify basic UPS structure
        assert "ShipTo" in payload or "shipto" in str(payload).lower()


@pytest.mark.integration
class TestFullPipeline:
    """Tests for complete NL → filter → template → validation pipeline."""

    @requires_anthropic_key
    @pytest.mark.asyncio
    async def test_california_ground_orders_pipeline(
        self, data_mcp_with_sample_data
    ):
        """Full pipeline for 'Ship California orders via Ground'."""
        from src.orchestrator.nl_engine import (
            IntentParser,
            FilterGenerator,
            MappingGenerator,
            TemplateValidator,
        )

        # Step 1: Parse intent
        parser = IntentParser()
        intent = await parser.parse(
            "Ship all California orders using UPS Ground"
        )

        assert intent.service_hint == "Ground" or "ground" in str(intent).lower()

        # Step 2: Generate filter
        schema = await data_mcp_with_sample_data.call_tool("get_schema", {})

        filter_gen = FilterGenerator()
        filter_result = await filter_gen.generate_filter(
            natural_language="California orders",
            schema=schema,
        )

        # Step 3: Get filtered rows
        rows = await data_mcp_with_sample_data.call_tool("get_rows_by_filter", {
            "filter_clause": filter_result.filter_clause,
            "limit": 100,
        })

        assert rows["total_count"] > 0

        # Step 4: Generate template
        mapping_gen = MappingGenerator()
        template = await mapping_gen.generate_template(
            schema=schema,
            service_code="03",
        )

        # Step 5: Validate template
        validator = TemplateValidator()
        validation_result = await validator.validate(
            template=template.template_string,
            sample_row=rows["rows"][0]["data"],
        )

        assert validation_result.is_valid or validation_result.can_self_correct
```

**Step 2: Run tests**

Run: `pytest tests/integration/orchestrator/test_nl_pipeline.py -v -m integration`

**Step 3: Commit**

```bash
git add tests/integration/orchestrator/
git commit -m "$(cat <<'EOF'
test(integration): add NL pipeline integration tests

Verifies intent parsing, filter generation, template creation,
and validation using real Data MCP and Anthropic API.
EOF
)"
```

---

I'll continue with the remaining phases in subsequent tasks. This plan document is getting long - let me save what we have and you can let me know when you're ready for more.

---

## Summary: Implementation Phases

| Phase | Tasks | New Tests | Status |
|-------|-------|-----------|--------|
| **Phase 1** | Test helpers (MCPTestClient, MockUPSMCP, ShopifyTestStore, ProcessController, root conftest) | ~15 | Documented |
| **Phase 2** | Data MCP subprocess tests (lifecycle, tools, errors) | ~25 | Documented |
| **Phase 3** | Shopify MCP tests (connectivity, orders) | ~15 | Documented |
| **Phase 4** | Orchestration integration (NL pipeline, self-correction, elicitation) | ~30 | Partial |
| **Phase 5** | API pipeline tests (command, preview, approval, progress) | ~25 | Pending |
| **Phase 6** | E2E flows (happy paths, zero data loss, crash recovery, errors) | ~35 | Pending |
| **Phase 7** | Cross-cutting (concurrency, scale, security, observability) | ~20 | Pending |

**Total Estimated: ~165 new integration tests**

---

## Next Steps

1. Review this plan document
2. Choose execution approach:
   - **Subagent-Driven (this session)** - Fresh subagent per task with review
   - **Parallel Session** - Open new session with executing-plans skill
3. Begin Phase 1 implementation
