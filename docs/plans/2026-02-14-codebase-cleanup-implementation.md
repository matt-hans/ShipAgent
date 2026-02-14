# Codebase Cleanup & MCP-First Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify the codebase around MCP-first architecture — single authoritative paths for external platforms and data sources, then decompose oversized modules and consolidate frontend duplication.

**Architecture:** Process-global singleton MCP clients (`ExternalSourcesMCPClient`, `DataSourceMCPClient`) as the sole interface for external platforms and data. API routes become thin HTTP-to-MCP adapters. Agent tools call shared gateway clients. Module splits reduce file sizes below 500 lines.

**Tech Stack:** Python 3.12+, FastAPI, FastMCP, MCP SDK (stdio), React, TypeScript, Tailwind CSS, shadcn/ui

---

## Phase 1A: Wire External Sources MCP Gateway

### Task 1: Complete MCP Gateway `connect_platform` Tool

**Files:**
- Modify: `src/mcp/external_sources/tools.py:62-135`
- Test: `tests/mcp/external_sources/test_tools.py` (create if needed)

**Step 1: Write failing test for connect_platform client instantiation**

```python
# tests/mcp/external_sources/test_connect_platform.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp.external_sources.tools import connect_platform


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "connections": {},
        "clients": {},
        "credentials": {},
    }
    ctx.info = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_connect_shopify_instantiates_client(mock_ctx):
    """connect_platform should authenticate and store a real client."""
    with patch(
        "src.mcp.external_sources.tools._create_platform_client"
    ) as mock_create:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_create.return_value = mock_client

        result = await connect_platform(
            platform="shopify",
            credentials={"access_token": "shpat_test"},
            ctx=mock_ctx,
            store_url="https://test.myshopify.com",
        )

    assert result["success"] is True
    assert result["status"] == "connected"
    assert mock_ctx.request_context.lifespan_context["clients"]["shopify"] is mock_client


@pytest.mark.asyncio
async def test_connect_platform_auth_failure(mock_ctx):
    """connect_platform should return error on auth failure."""
    with patch(
        "src.mcp.external_sources.tools._create_platform_client"
    ) as mock_create:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(side_effect=Exception("Invalid token"))
        mock_create.return_value = mock_client

        result = await connect_platform(
            platform="shopify",
            credentials={"access_token": "bad"},
            ctx=mock_ctx,
            store_url="https://test.myshopify.com",
        )

    assert result["success"] is False
    assert "Invalid token" in result["error"]
    assert "shopify" not in mock_ctx.request_context.lifespan_context["clients"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/external_sources/test_connect_platform.py -v`
Expected: FAIL (no `_create_platform_client` function exists)

**Step 3: Implement client instantiation in connect_platform**

Replace the "pending" stub in `src/mcp/external_sources/tools.py:109-135` with:

```python
from datetime import datetime, timezone


def _create_platform_client(platform: str):
    """Create platform client instance based on platform type.

    All platform clients use no-arg constructors. Credentials
    (including store URLs) are passed separately to authenticate().

    Args:
        platform: Platform identifier.

    Returns:
        Platform client instance (unauthenticated).

    Raises:
        ValueError: If platform is unsupported.
    """
    if platform == "shopify":
        from src.mcp.external_sources.clients.shopify import ShopifyClient
        return ShopifyClient()
    elif platform == "woocommerce":
        from src.mcp.external_sources.clients.woocommerce import WooCommerceClient
        return WooCommerceClient()
    elif platform == "sap":
        from src.mcp.external_sources.clients.sap import SAPClient
        return SAPClient()
    elif platform == "oracle":
        from src.mcp.external_sources.clients.oracle import OracleClient
        return OracleClient()
    else:
        raise ValueError(f"No client implementation for platform: {platform}")
```

Then replace the `connect_platform` body (lines 98-135) with:

```python
    await ctx.info(f"Connecting to platform: {platform}")

    if platform not in SUPPORTED_PLATFORMS:
        return {
            "success": False,
            "platform": platform,
            "error": f"Unsupported platform: {platform}. "
            f"Supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}",
        }

    lifespan_ctx = _get_lifespan_context(ctx)

    # Store credentials securely (not logged!)
    creds = lifespan_ctx.get("credentials", {})
    creds[platform] = credentials
    lifespan_ctx["credentials"] = creds

    # Instantiate and authenticate
    # All clients use no-arg __init__. store_url is merged into
    # credentials for authenticate() (e.g. Shopify expects "store_url" key).
    try:
        client = _create_platform_client(platform)
        auth_creds = dict(credentials)
        if store_url:
            auth_creds.setdefault("store_url", store_url)
        auth_ok = await client.authenticate(auth_creds)
        if not auth_ok:
            raise ValueError(
                f"Authentication returned False for {platform}. "
                "Check credentials and try again."
            )
    except Exception as e:
        connection = PlatformConnection(
            platform=platform,
            store_url=store_url,
            status="error",
            last_connected=None,
            error_message=str(e),
        )
        connections = lifespan_ctx.get("connections", {})
        connections[platform] = connection
        lifespan_ctx["connections"] = connections
        return {
            "success": False,
            "platform": platform,
            "status": "error",
            "error": str(e),
        }

    # Store authenticated client and connection
    clients = lifespan_ctx.get("clients", {})
    clients[platform] = client
    lifespan_ctx["clients"] = clients

    now = datetime.now(timezone.utc).isoformat()
    connection = PlatformConnection(
        platform=platform,
        store_url=store_url,
        status="connected",
        last_connected=now,
        error_message=None,
    )
    connections = lifespan_ctx.get("connections", {})
    connections[platform] = connection
    lifespan_ctx["connections"] = connections

    await ctx.info(f"Platform {platform} connected successfully")

    return {
        "success": True,
        "platform": platform,
        "status": "connected",
    }
```

**Step 4: Add disconnect_platform MCP tool**

Add to `src/mcp/external_sources/tools.py` after `connect_platform`:

```python
@mcp.tool()
async def disconnect_platform(platform: str, ctx: Context) -> dict:
    """Disconnect from a platform, removing client and connection state.

    Args:
        platform: Platform identifier to disconnect.

    Returns:
        Dict with success status.
    """
    lifespan_ctx = _get_lifespan_context(ctx)
    clients = lifespan_ctx.get("clients", {})
    connections = lifespan_ctx.get("connections", {})
    credentials = lifespan_ctx.get("credentials", {})

    client = clients.pop(platform, None)
    connections.pop(platform, None)
    credentials.pop(platform, None)

    if client is not None and hasattr(client, "close"):
        try:
            await client.close()
        except Exception:
            pass

    await ctx.info(f"Platform {platform} disconnected")
    return {"success": True, "platform": platform, "status": "disconnected"}
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/mcp/external_sources/test_connect_platform.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/mcp/external_sources/tools.py tests/mcp/external_sources/test_connect_platform.py
git commit -m "feat: complete connect_platform and disconnect_platform MCP tools"
```

---

### Task 2: Create ExternalSourcesMCPClient (Process-Global Singleton)

**Files:**
- Create: `src/services/external_sources_mcp_client.py`
- Test: `tests/services/test_external_sources_mcp_client.py`

**Step 1: Write failing test**

```python
# tests/services/test_external_sources_mcp_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.external_sources_mcp_client import ExternalSourcesMCPClient


@pytest.mark.asyncio
async def test_connect_calls_mcp_tool():
    """ExternalSourcesMCPClient.connect_platform should call MCP connect_platform tool."""
    client = ExternalSourcesMCPClient.__new__(ExternalSourcesMCPClient)
    client._mcp = MagicMock()
    client._mcp.call_tool = AsyncMock(return_value={
        "success": True,
        "platform": "shopify",
        "status": "connected",
    })
    client._mcp.is_connected = True

    result = await client.connect_platform(
        platform="shopify",
        credentials={"access_token": "test"},
        store_url="https://test.myshopify.com",
    )

    assert result["success"] is True
    client._mcp.call_tool.assert_called_once_with(
        "connect_platform",
        {
            "platform": "shopify",
            "credentials": {"access_token": "test"},
            "store_url": "https://test.myshopify.com",
        },
    )


@pytest.mark.asyncio
async def test_list_connections():
    """list_connections should call MCP list_connections tool."""
    client = ExternalSourcesMCPClient.__new__(ExternalSourcesMCPClient)
    client._mcp = MagicMock()
    client._mcp.call_tool = AsyncMock(return_value={
        "connections": [],
        "count": 0,
    })
    client._mcp.is_connected = True

    result = await client.list_connections()
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_fetch_orders():
    """fetch_orders should call MCP list_orders tool."""
    client = ExternalSourcesMCPClient.__new__(ExternalSourcesMCPClient)
    client._mcp = MagicMock()
    client._mcp.call_tool = AsyncMock(return_value={
        "success": True,
        "orders": [{"order_id": "1"}],
        "count": 1,
    })
    client._mcp.is_connected = True

    result = await client.fetch_orders("shopify")
    assert result["count"] == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_external_sources_mcp_client.py -v`
Expected: FAIL (module does not exist)

**Step 3: Implement ExternalSourcesMCPClient**

```python
# src/services/external_sources_mcp_client.py
"""Process-global async MCP client for External Sources Gateway.

Provides a singleton interface for connecting to and interacting with
external platforms (Shopify, WooCommerce, SAP, Oracle) via the External
Sources MCP server over stdio.

Mirrors the UPSMCPClient pattern: one process-global instance, long-lived
stdio connection, cached across requests.
"""

import logging
import os
from typing import Any

from mcp import StdioServerParameters

from src.services.mcp_client import MCPClient, MCPToolError

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")


class ExternalSourcesMCPClient:
    """Process-global async MCP client for external platform operations.

    Wraps the generic MCPClient with External Sources MCP-specific
    methods. Designed as a singleton — one instance shared by API routes
    and agent tools.

    Attributes:
        _mcp: Underlying generic MCPClient instance.
    """

    def __init__(self) -> None:
        """Initialize External Sources MCP client."""
        self._mcp = MCPClient(
            server_params=self._build_server_params(),
            max_retries=2,
            base_delay=0.5,
        )

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the External Sources MCP server.

        Returns:
            Configured StdioServerParameters.
        """
        return StdioServerParameters(
            command=_VENV_PYTHON,
            args=["-m", "src.mcp.external_sources.server"],
            env={
                "PYTHONPATH": _PROJECT_ROOT,
                "PATH": os.environ.get("PATH", ""),
            },
        )

    async def connect(self) -> None:
        """Connect to External Sources MCP server if not already connected."""
        if self._mcp.is_connected:
            return
        await self._mcp.connect()
        logger.info("External Sources MCP client connected")

    async def disconnect(self) -> None:
        """Disconnect from External Sources MCP server."""
        await self._mcp.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the MCP session is connected."""
        return self._mcp.is_connected

    async def connect_platform(
        self,
        platform: str,
        credentials: dict[str, Any],
        store_url: str | None = None,
    ) -> dict[str, Any]:
        """Connect to a platform via MCP gateway.

        Args:
            platform: Platform identifier (shopify, woocommerce, sap, oracle).
            credentials: Platform-specific credentials.
            store_url: Store/instance URL.

        Returns:
            Dict with success, platform, status.

        Raises:
            MCPToolError: On MCP tool error.
        """
        return await self._mcp.call_tool(
            "connect_platform",
            {
                "platform": platform,
                "credentials": credentials,
                "store_url": store_url,
            },
        )

    async def disconnect_platform(self, platform: str) -> dict[str, Any]:
        """Disconnect a platform via MCP gateway.

        Calls the disconnect_platform MCP tool which removes the client
        from the server's lifespan context and calls client.close().

        Args:
            platform: Platform identifier.

        Returns:
            Dict with success status.
        """
        return await self._mcp.call_tool(
            "disconnect_platform", {"platform": platform}
        )

    async def list_connections(self) -> dict[str, Any]:
        """List all platform connections.

        Returns:
            Dict with connections list and count.
        """
        return await self._mcp.call_tool("list_connections", {})

    async def fetch_orders(
        self,
        platform: str,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch orders from a connected platform.

        Args:
            platform: Platform identifier.
            status: Optional order status filter.
            limit: Max orders to return.

        Returns:
            Dict with orders list and count.
        """
        args: dict[str, Any] = {"platform": platform, "limit": limit}
        if status:
            args["status"] = status
        return await self._mcp.call_tool("list_orders", args)

    async def get_order(
        self, platform: str, order_id: str
    ) -> dict[str, Any]:
        """Get a single order by ID.

        Args:
            platform: Platform identifier.
            order_id: Platform order ID.

        Returns:
            Dict with order data.
        """
        return await self._mcp.call_tool(
            "get_order", {"platform": platform, "order_id": order_id}
        )

    async def update_tracking(
        self,
        platform: str,
        order_id: str,
        tracking_number: str,
        carrier: str = "UPS",
    ) -> dict[str, Any]:
        """Update tracking info for an order.

        Args:
            platform: Platform identifier.
            order_id: Platform order ID.
            tracking_number: Carrier tracking number.
            carrier: Carrier name.

        Returns:
            Dict with success status.
        """
        return await self._mcp.call_tool(
            "update_tracking",
            {
                "platform": platform,
                "order_id": order_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
            },
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_external_sources_mcp_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/external_sources_mcp_client.py tests/services/test_external_sources_mcp_client.py
git commit -m "feat: add ExternalSourcesMCPClient — process-global MCP client for platforms"
```

---

### Task 3: Replace PlatformStateManager with MCP Client Adapter

**Files:**
- Modify: `src/api/routes/platforms.py:125-261` (replace PlatformStateManager)
- Test: `tests/api/routes/test_platforms.py` (update existing)

**Step 1: Write failing test for MCP-backed platforms route**

```python
# tests/api/routes/test_platforms_mcp.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_connect_route_uses_mcp_client():
    """Connect route should call ExternalSourcesMCPClient, not direct client."""
    from src.api.routes.platforms import _get_external_sources_client

    with patch(
        "src.api.routes.platforms._get_external_sources_client"
    ) as mock_get:
        mock_client = AsyncMock()
        mock_client.connect_platform = AsyncMock(return_value={
            "success": True, "platform": "shopify", "status": "connected"
        })
        mock_get.return_value = mock_client

        # Verify PlatformStateManager class has been removed
        import src.api.routes.platforms as platforms_mod
        assert not hasattr(platforms_mod, "PlatformStateManager"), \
            "PlatformStateManager should be removed — routes must use ExternalSourcesMCPClient"

        # Verify the route calls ExternalSourcesMCPClient
        mock_client.connect_platform.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/routes/test_platforms_mcp.py -v`
Expected: FAIL (PlatformStateManager still exists)

**Step 3: Refactor platforms.py**

Replace the `PlatformStateManager` class (lines 125-261) and all direct client imports with a module-level singleton accessor and thin route adapters. The routes should call `ExternalSourcesMCPClient` methods.

Key changes:
- Add `_ext_client: ExternalSourcesMCPClient | None = None` module global
- Add `_ext_client_lock = asyncio.Lock()` for lazy init
- Add `async def _get_external_sources_client() -> ExternalSourcesMCPClient`
- Replace each route handler to call `_get_external_sources_client()` then delegate
- Remove all `from src.mcp.external_sources.clients.*` imports
- Remove `PlatformStateManager` class entirely

**Step 4: Run existing platform tests + new test**

Run: `pytest tests/api/routes/test_platforms*.py -v`
Expected: PASS (may need test updates for new patterns)

**Step 5: Commit**

```bash
git add src/api/routes/platforms.py tests/api/routes/
git commit -m "refactor: replace PlatformStateManager with ExternalSourcesMCPClient adapter"
```

---

### Task 4: Delete Stale Shopify MCP Config + Tests

**Files:**
- Modify: `src/orchestrator/agent/config.py:87-131` (delete get_shopify_mcp_config)
- Modify: `src/orchestrator/agent/config.py:235` (remove "shopify" key)
- Modify: `tests/orchestrator/agent/test_config.py` (delete 6 stale tests)

**Step 1: Identify and remove stale config**

Delete `get_shopify_mcp_config()` function (lines 87-131 in config.py).
Remove `"shopify": get_shopify_mcp_config()` from `create_mcp_servers_config()` return dict (line 235).

**Step 2: Delete stale tests**

Remove from `tests/orchestrator/agent/test_config.py`:
- `TestShopifyMCPConfig` class (all methods ~lines 85-146)
- `test_shopify_uses_npx` (~line 288)
- `test_shopify_config_is_valid` (~line 306)

**Step 3: Run remaining config tests**

Run: `pytest tests/orchestrator/agent/test_config.py -v`
Expected: PASS (remaining tests cover data, external, ups configs)

**Step 4: Commit**

```bash
git add src/orchestrator/agent/config.py tests/orchestrator/agent/test_config.py
git commit -m "chore: remove stale Shopify MCP config and dead-path tests"
```

---

## Phase 1B: DataSourceGateway (MCP Data Source Authoritative)

### Task 5: Add `get_source_info` and `import_records` MCP Data Source Tools

**Files:**
- Create: `src/mcp/data_source/tools/source_info_tools.py`
- Modify: `src/mcp/data_source/server.py:64-111` (register new tools)
- Test: `tests/mcp/data_source/test_source_info_tools.py`

**Step 1: Write failing test**

```python
# tests/mcp/data_source/test_source_info_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_ctx_with_source():
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "db": MagicMock(),
        "current_source": {
            "type": "csv",
            "path": "/tmp/orders.csv",
            "row_count": 150,
        },
        "type_overrides": {},
    }
    return ctx


@pytest.fixture
def mock_ctx_no_source():
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "db": MagicMock(),
        "current_source": None,
        "type_overrides": {},
    }
    return ctx


@pytest.mark.asyncio
async def test_get_source_info_returns_metadata(mock_ctx_with_source):
    from src.mcp.data_source.tools.source_info_tools import get_source_info

    result = await get_source_info(mock_ctx_with_source)
    assert result["source_type"] == "csv"
    assert result["row_count"] == 150


@pytest.mark.asyncio
async def test_get_source_info_no_source(mock_ctx_no_source):
    from src.mcp.data_source.tools.source_info_tools import get_source_info

    result = await get_source_info(mock_ctx_no_source)
    assert result["active"] is False


@pytest.mark.asyncio
async def test_import_records_creates_table(mock_ctx_no_source):
    from src.mcp.data_source.tools.source_info_tools import import_records

    db = mock_ctx_no_source.request_context.lifespan_context["db"]
    db.execute = MagicMock()
    db.execute.return_value.fetchall = MagicMock(return_value=[(3,)])
    db.execute.return_value.fetchone = MagicMock(return_value=(3,))

    result = await import_records(
        records=[
            {"order_id": "1", "name": "Alice"},
            {"order_id": "2", "name": "Bob"},
            {"order_id": "3", "name": "Charlie"},
        ],
        source_label="shopify",
        ctx=mock_ctx_no_source,
    )
    assert result["row_count"] == 3
    assert result["source_type"] == "shopify"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/data_source/test_source_info_tools.py -v`
Expected: FAIL (module does not exist)

**Step 3: Implement source_info_tools.py**

```python
# src/mcp/data_source/tools/source_info_tools.py
"""Source info and record import tools for Data Source MCP."""

import hashlib
import json
from typing import Any

from fastmcp import Context


async def get_source_info(ctx: Context) -> dict:
    """Get metadata about the currently active data source.

    Returns:
        Dictionary with active flag, source_type, path, row_count,
        and source_signature (schema fingerprint).
    """
    current_source = ctx.request_context.lifespan_context.get("current_source")

    if current_source is None:
        return {"active": False}

    await ctx.info("Retrieving source info")

    # Build signature from schema if available
    db = ctx.request_context.lifespan_context["db"]
    signature = None
    columns = []
    try:
        schema_rows = db.execute("DESCRIBE imported_data").fetchall()
        columns = [{"name": col[0], "type": col[1]} for col in schema_rows]
        sig_input = json.dumps(
            [(c["name"], c["type"]) for c in columns], sort_keys=True
        )
        signature = hashlib.sha256(sig_input.encode()).hexdigest()[:16]
    except Exception:
        pass

    return {
        "active": True,
        "source_type": current_source.get("type", "unknown"),
        "path": current_source.get("path"),
        "sheet": current_source.get("sheet"),
        "query": current_source.get("query"),
        "row_count": current_source.get("row_count", 0),
        "columns": columns,
        "signature": signature,
    }


async def import_records(
    records: list[dict[str, Any]],
    source_label: str,
    ctx: Context,
) -> dict:
    """Import a list of flat dictionaries as a data source.

    Replaces any existing source. Used by agent tools to import
    fetched external platform data (e.g., Shopify orders).

    Args:
        records: List of flat dicts to import as rows.
        source_label: Label for the source (e.g., 'shopify').

    Returns:
        Dictionary with row_count, columns, and source_type.
    """
    db = ctx.request_context.lifespan_context["db"]

    if not records:
        return {"row_count": 0, "source_type": source_label, "columns": []}

    await ctx.info(f"Importing {len(records)} records as '{source_label}' source")

    # Drop existing table
    db.execute("DROP TABLE IF EXISTS imported_data")

    # Build CREATE TABLE from first record's keys
    columns = list(records[0].keys())
    col_defs = ", ".join(f'"{col}" VARCHAR' for col in columns)
    db.execute(f"CREATE TABLE imported_data ({col_defs})")

    # Insert records
    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(f'"{c}"' for c in columns)
    insert_sql = f"INSERT INTO imported_data ({col_names}) VALUES ({placeholders})"

    for record in records:
        values = [str(record.get(col, "")) if record.get(col) is not None else None for col in columns]
        db.execute(insert_sql, values)

    row_count = db.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    # Update current source
    ctx.request_context.lifespan_context["current_source"] = {
        "type": source_label,
        "row_count": row_count,
    }

    await ctx.info(f"Imported {row_count} records with {len(columns)} columns")

    return {
        "row_count": row_count,
        "source_type": source_label,
        "columns": columns,
    }
```

**Step 4: Register new tools in server.py**

Add to `src/mcp/data_source/server.py` after existing imports (~line 85):

```python
from src.mcp.data_source.tools.source_info_tools import (
    get_source_info,
    import_records,
)
```

Add registrations after line 111:

```python
mcp.tool()(get_source_info)
mcp.tool()(import_records)
```

**Step 5: Run tests**

Run: `pytest tests/mcp/data_source/test_source_info_tools.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/mcp/data_source/tools/source_info_tools.py src/mcp/data_source/server.py tests/mcp/data_source/test_source_info_tools.py
git commit -m "feat: add get_source_info and import_records MCP data source tools"
```

---

### Task 6: Create DataSourceGateway Protocol

**Files:**
- Create: `src/services/data_source_gateway.py`
- Test: (protocol has no implementation to test — tested via Task 7)

**Step 1: Write the protocol**

```python
# src/services/data_source_gateway.py
"""DataSourceGateway protocol — single interface for all data source access.

All external callers (API routes, agent tools, conversation processing)
use this protocol. The MCP-backed implementation is the production default.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataSourceGateway(Protocol):
    """Protocol for data source access.

    Implementors provide data import, query, schema, and write-back
    operations. The authoritative implementation routes through the
    Data Source MCP server.
    """

    async def import_csv(
        self, file_path: str, delimiter: str = ",", header: bool = True
    ) -> dict[str, Any]:
        """Import CSV file as active data source."""
        ...

    async def import_excel(
        self, file_path: str, sheet: str | None = None, header: bool = True
    ) -> dict[str, Any]:
        """Import Excel sheet as active data source."""
        ...

    async def import_database(
        self, connection_string: str, query: str, schema: str = "public"
    ) -> dict[str, Any]:
        """Import database query results as active data source."""
        ...

    async def import_from_records(
        self, records: list[dict[str, Any]], source_label: str
    ) -> dict[str, Any]:
        """Import flat dicts as active data source."""
        ...

    async def get_source_info(self) -> dict[str, Any] | None:
        """Get metadata about the active data source. None if no source."""
        ...

    async def get_source_signature(self) -> dict[str, Any] | None:
        """Get stable source signature for replay safety checks.

        Returns dict matching DataSourceService.get_source_signature() contract:
        {"source_type": str, "source_ref": str, "schema_fingerprint": str}
        or None if no source is active.
        """
        ...

    async def get_rows_by_filter(
        self, where_clause: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get rows matching a SQL WHERE clause as flat dicts.

        Args:
            where_clause: SQL WHERE condition, or None for all rows.
                Gateway normalizes None → "1=1" before calling MCP tool.
        """
        ...

    async def query_data(self, sql: str) -> dict[str, Any]:
        """Execute a SELECT query against active data source."""
        ...

    async def write_back_batch(
        self, updates: dict[int, dict[str, str]]
    ) -> dict[str, Any]:
        """Write tracking numbers back to source for multiple rows.

        Args:
            updates: {row_number: {"tracking_number": "...", "shipped_at": "..."}}

        Returns:
            Dict with success count, failure count.
        """
        ...

    async def disconnect(self) -> None:
        """Disconnect/clear active data source."""
        ...

    async def get_schema(self) -> dict[str, Any]:
        """Get column schema of active data source."""
        ...

    async def list_sheets(self, file_path: str) -> dict[str, Any]:
        """List sheets in an Excel file."""
        ...

    async def list_tables(
        self, connection_string: str, schema: str = "public"
    ) -> dict[str, Any]:
        """List tables in a database."""
        ...
```

**Step 2: Commit**

```bash
git add src/services/data_source_gateway.py
git commit -m "feat: add DataSourceGateway protocol for unified data access"
```

---

### Task 7: Create DataSourceMCPClient (Gateway Implementation)

**Files:**
- Create: `src/services/data_source_mcp_client.py`
- Test: `tests/services/test_data_source_mcp_client.py`

**Step 1: Write failing tests**

```python
# tests/services/test_data_source_mcp_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.data_source_mcp_client import DataSourceMCPClient


@pytest.fixture
def mock_mcp():
    mcp = MagicMock()
    mcp.call_tool = AsyncMock()
    mcp.is_connected = True
    mcp.connect = AsyncMock()
    return mcp


@pytest.mark.asyncio
async def test_import_csv(mock_mcp):
    mock_mcp.call_tool.return_value = {
        "row_count": 50, "columns": [{"name": "id", "type": "INTEGER"}],
        "source_type": "csv", "warnings": [],
    }
    client = DataSourceMCPClient.__new__(DataSourceMCPClient)
    client._mcp = mock_mcp
    result = await client.import_csv("/tmp/orders.csv")
    assert result["row_count"] == 50
    mock_mcp.call_tool.assert_called_once_with(
        "import_csv", {"file_path": "/tmp/orders.csv", "delimiter": ",", "header": True}
    )


@pytest.mark.asyncio
async def test_get_source_info_returns_none_when_inactive(mock_mcp):
    mock_mcp.call_tool.return_value = {"active": False}
    client = DataSourceMCPClient.__new__(DataSourceMCPClient)
    client._mcp = mock_mcp
    result = await client.get_source_info()
    assert result is None


@pytest.mark.asyncio
async def test_get_rows_normalizes_shape(mock_mcp):
    """MCP returns {rows:[{row_number,data,checksum}]} — gateway returns flat dicts."""
    mock_mcp.call_tool.return_value = {
        "rows": [
            {"row_number": 1, "data": {"id": "1", "name": "Alice"}, "checksum": "abc"},
            {"row_number": 2, "data": {"id": "2", "name": "Bob"}, "checksum": "def"},
        ],
        "total_count": 2,
    }
    client = DataSourceMCPClient.__new__(DataSourceMCPClient)
    client._mcp = mock_mcp
    result = await client.get_rows_by_filter("1=1")
    assert len(result) == 2
    assert result[0] == {"id": "1", "name": "Alice", "_row_number": 1, "_checksum": "abc"}


@pytest.mark.asyncio
async def test_write_back_batch_iterates(mock_mcp):
    mock_mcp.call_tool.return_value = {"success": True}
    client = DataSourceMCPClient.__new__(DataSourceMCPClient)
    client._mcp = mock_mcp
    result = await client.write_back_batch({
        1: {"tracking_number": "1Z001", "shipped_at": "2026-01-01"},
        2: {"tracking_number": "1Z002", "shipped_at": "2026-01-01"},
    })
    assert result["success_count"] == 2
    assert mock_mcp.call_tool.call_count == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_data_source_mcp_client.py -v`
Expected: FAIL (module does not exist)

**Step 3: Implement DataSourceMCPClient**

```python
# src/services/data_source_mcp_client.py
"""MCP-backed implementation of DataSourceGateway.

Routes all data source operations through the Data Source MCP server
via a process-global, long-lived stdio connection.
"""

import logging
import os
from typing import Any

from mcp import StdioServerParameters

from src.services.mcp_client import MCPClient

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")


class DataSourceMCPClient:
    """MCP-backed DataSourceGateway implementation.

    Process-global singleton. All data access routes through the
    Data Source MCP server over stdio.
    """

    def __init__(self) -> None:
        """Initialize Data Source MCP client."""
        self._mcp = MCPClient(
            server_params=self._build_server_params(),
            max_retries=1,
            base_delay=0.5,
        )

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the Data Source MCP server."""
        return StdioServerParameters(
            command=_VENV_PYTHON,
            args=["-m", "src.mcp.data_source.server"],
            env={
                "PYTHONPATH": _PROJECT_ROOT,
                "PATH": os.environ.get("PATH", ""),
            },
        )

    async def connect(self) -> None:
        """Connect to Data Source MCP server if not already connected."""
        if self._mcp.is_connected:
            return
        await self._mcp.connect()
        logger.info("Data Source MCP client connected")

    async def disconnect_mcp(self) -> None:
        """Disconnect from Data Source MCP server."""
        await self._mcp.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the MCP session is connected."""
        return self._mcp.is_connected

    async def _ensure_connected(self) -> None:
        """Ensure MCP connection is active before making calls."""
        if not self._mcp.is_connected:
            await self.connect()

    # ── Import operations ──────────────────────────────────────────

    async def import_csv(
        self, file_path: str, delimiter: str = ",", header: bool = True
    ) -> dict[str, Any]:
        """Import CSV file as active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("import_csv", {
            "file_path": file_path, "delimiter": delimiter, "header": header,
        })

    async def import_excel(
        self, file_path: str, sheet: str | None = None, header: bool = True
    ) -> dict[str, Any]:
        """Import Excel sheet as active data source."""
        await self._ensure_connected()
        args: dict[str, Any] = {"file_path": file_path, "header": header}
        if sheet:
            args["sheet"] = sheet
        return await self._mcp.call_tool("import_excel", args)

    async def import_database(
        self, connection_string: str, query: str, schema: str = "public"
    ) -> dict[str, Any]:
        """Import database query results as active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("import_database", {
            "connection_string": connection_string,
            "query": query,
            "schema": schema,
        })

    async def import_from_records(
        self, records: list[dict[str, Any]], source_label: str
    ) -> dict[str, Any]:
        """Import flat dicts as active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("import_records", {
            "records": records,
            "source_label": source_label,
        })

    # ── Query operations ───────────────────────────────────────────

    async def get_source_info(self) -> dict[str, Any] | None:
        """Get metadata about the active data source.

        Returns None if no source is active.
        """
        await self._ensure_connected()
        result = await self._mcp.call_tool("get_source_info", {})
        if not result.get("active", False):
            return None
        return result

    async def get_source_signature(self) -> dict[str, Any] | None:
        """Get stable source signature matching DataSourceService contract.

        Returns:
            {"source_type": str, "source_ref": str, "schema_fingerprint": str}
            or None if no source is active.
        """
        info = await self.get_source_info()
        if info is None:
            return None
        return {
            "source_type": info.get("source_type", "unknown"),
            "source_ref": info.get("path") or info.get("query") or "",
            "schema_fingerprint": info.get("signature", ""),
        }

    async def get_schema(self) -> dict[str, Any]:
        """Get column schema of active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("get_schema", {})

    async def get_rows_by_filter(
        self, where_clause: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get rows matching a WHERE clause, normalized to flat dicts.

        MCP tool requires a non-None where_clause string for its SQL
        template. Gateway normalizes None → "1=1" (all rows).

        MCP returns {rows:[{row_number, data, checksum}]}.
        This method normalizes to flat dicts with _row_number and _checksum.
        """
        await self._ensure_connected()
        # Normalize None/empty → "1=1" so the MCP tool's
        # "WHERE {where_clause}" template doesn't break.
        effective_clause = where_clause if where_clause and where_clause.strip() else "1=1"
        result = await self._mcp.call_tool("get_rows_by_filter", {
            "where_clause": effective_clause,
            "limit": limit,
            "offset": offset,
        })
        return self._normalize_rows(result.get("rows", []))

    async def query_data(self, sql: str) -> dict[str, Any]:
        """Execute a SELECT query against active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("query_data", {"sql": sql})

    # ── Write-back ─────────────────────────────────────────────────

    async def write_back_batch(
        self, updates: dict[int, dict[str, str]]
    ) -> dict[str, Any]:
        """Write tracking numbers back to source for multiple rows.

        Iterates over individual write_back MCP tool calls.
        Atomicity tradeoff: individual rows are atomic, batch is not.

        Args:
            updates: {row_number: {"tracking_number": "...", "shipped_at": "..."}}
        """
        await self._ensure_connected()
        success_count = 0
        failure_count = 0
        errors: list[dict[str, Any]] = []

        for row_number, data in updates.items():
            try:
                await self._mcp.call_tool("write_back", {
                    "row_number": row_number,
                    "tracking_number": data["tracking_number"],
                    "shipped_at": data.get("shipped_at"),
                })
                success_count += 1
            except Exception as e:
                failure_count += 1
                errors.append({"row_number": row_number, "error": str(e)})

        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "errors": errors,
        }

    # ── Data source lifecycle ──────────────────────────────────────

    async def disconnect(self) -> None:
        """Clear active data source (not the MCP connection)."""
        # Data Source MCP does not have a disconnect tool.
        # Importing a new source replaces the previous one.
        pass

    async def list_sheets(self, file_path: str) -> dict[str, Any]:
        """List sheets in an Excel file."""
        await self._ensure_connected()
        return await self._mcp.call_tool("list_sheets", {"file_path": file_path})

    async def list_tables(
        self, connection_string: str, schema: str = "public"
    ) -> dict[str, Any]:
        """List tables in a database."""
        await self._ensure_connected()
        return await self._mcp.call_tool("list_tables", {
            "connection_string": connection_string, "schema": schema,
        })

    # ── Internal helpers ───────────────────────────────────────────

    @staticmethod
    def _normalize_rows(
        raw_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize MCP row format to flat dicts.

        Input:  [{row_number: 1, data: {col: val}, checksum: "abc"}, ...]
        Output: [{col: val, _row_number: 1, _checksum: "abc"}, ...]
        """
        normalized = []
        for row in raw_rows:
            flat = dict(row.get("data", {}))
            flat["_row_number"] = row.get("row_number")
            flat["_checksum"] = row.get("checksum")
            normalized.append(flat)
        return normalized
```

**Step 4: Run tests**

Run: `pytest tests/services/test_data_source_mcp_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/data_source_mcp_client.py tests/services/test_data_source_mcp_client.py
git commit -m "feat: add DataSourceMCPClient — MCP-backed DataSourceGateway implementation"
```

---

### Task 8: Create Centralized Gateway Provider Module

**Files:**
- Create: `src/services/gateway_provider.py`
- Test: `tests/services/test_gateway_provider.py`

This task creates a **single provider module** that owns both process-global
MCP gateway singletons. All callers (API routes, agent tools, conversation
processing) import from this one module. This prevents the split-brain
problem of multiple files each creating their own singleton.

**Step 1: Write failing test**

```python
# tests/services/test_gateway_provider.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_get_data_gateway_returns_same_instance():
    """Provider must return the same DataSourceMCPClient on repeated calls."""
    import src.services.gateway_provider as provider
    # Reset module state
    provider._data_gateway = None
    provider._ext_sources_client = None

    with patch.object(provider, "DataSourceMCPClient") as MockDS:
        mock_instance = AsyncMock()
        mock_instance.is_connected = True
        MockDS.return_value = mock_instance

        gw1 = await provider.get_data_gateway()
        gw2 = await provider.get_data_gateway()
        assert gw1 is gw2, "Must return the same singleton instance"
        MockDS.assert_called_once()


@pytest.mark.asyncio
async def test_get_external_sources_client_returns_same_instance():
    """Provider must return the same ExternalSourcesMCPClient on repeated calls."""
    import src.services.gateway_provider as provider
    provider._data_gateway = None
    provider._ext_sources_client = None

    with patch.object(provider, "ExternalSourcesMCPClient") as MockExt:
        mock_instance = AsyncMock()
        mock_instance.is_connected = True
        MockExt.return_value = mock_instance

        c1 = await provider.get_external_sources_client()
        c2 = await provider.get_external_sources_client()
        assert c1 is c2, "Must return the same singleton instance"
        MockExt.assert_called_once()
```

**Step 2: Implement the provider module**

```python
# src/services/gateway_provider.py
"""Centralized MCP gateway provider — single owner of process-global singletons.

All callers (API routes, agent tools, conversation processing) import
gateway accessors from HERE. This module owns the singleton lifecycle.
Never instantiate DataSourceMCPClient or ExternalSourcesMCPClient elsewhere.
"""

import asyncio
import logging

from src.services.data_source_mcp_client import DataSourceMCPClient
from src.services.external_sources_mcp_client import ExternalSourcesMCPClient

logger = logging.getLogger(__name__)

# ── DataSourceMCPClient singleton ──────────────────────────────────
_data_gateway: DataSourceMCPClient | None = None
_data_gateway_lock = asyncio.Lock()


async def get_data_gateway() -> DataSourceMCPClient:
    """Get or create the process-global DataSourceMCPClient.

    Thread-safe via double-checked locking.

    Returns:
        The shared DataSourceMCPClient instance.
    """
    global _data_gateway
    if _data_gateway is not None:
        return _data_gateway
    async with _data_gateway_lock:
        if _data_gateway is None:
            _data_gateway = DataSourceMCPClient()
            await _data_gateway.connect()
            logger.info("DataSourceMCPClient singleton initialized")
    return _data_gateway


# ── ExternalSourcesMCPClient singleton ─────────────────────────────
_ext_sources_client: ExternalSourcesMCPClient | None = None
_ext_sources_lock = asyncio.Lock()


async def get_external_sources_client() -> ExternalSourcesMCPClient:
    """Get or create the process-global ExternalSourcesMCPClient.

    Returns:
        The shared ExternalSourcesMCPClient instance.
    """
    global _ext_sources_client
    if _ext_sources_client is not None:
        return _ext_sources_client
    async with _ext_sources_lock:
        if _ext_sources_client is None:
            _ext_sources_client = ExternalSourcesMCPClient()
            await _ext_sources_client.connect()
            logger.info("ExternalSourcesMCPClient singleton initialized")
    return _ext_sources_client


async def shutdown_gateways() -> None:
    """Shutdown hook — disconnect all gateway clients. Call from FastAPI lifespan."""
    global _data_gateway, _ext_sources_client
    if _data_gateway is not None:
        try:
            await _data_gateway.disconnect_mcp()
        except Exception as e:
            logger.warning("Failed to disconnect DataSourceMCPClient: %s", e)
        _data_gateway = None
    if _ext_sources_client is not None:
        try:
            await _ext_sources_client.disconnect()
        except Exception as e:
            logger.warning("Failed to disconnect ExternalSourcesMCPClient: %s", e)
        _ext_sources_client = None
```

**Step 3: Run tests**

Run: `pytest tests/services/test_gateway_provider.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/services/gateway_provider.py tests/services/test_gateway_provider.py
git commit -m "feat: add centralized gateway_provider for MCP client singletons"
```

---

### Task 8b: Wire API Routes to DataSourceGateway

**Files:**
- Modify: `src/api/routes/data_sources.py` (replace DataSourceService.get_instance() with gateway)
- Modify: `src/api/main.py` (call shutdown_gateways in lifespan)
- Test: existing `tests/api/routes/test_data_sources.py`

**Step 1: Wire main.py to gateway provider shutdown**

In `src/api/main.py` lifespan, add:

```python
from src.services.gateway_provider import shutdown_gateways

# In the shutdown phase of the lifespan context manager:
await shutdown_gateways()
```

**Step 2: Update data_sources.py routes**

Replace `DataSourceService.get_instance()` calls (lines 46, 177, 227, 258, 273) with:

```python
from src.services.gateway_provider import get_data_gateway

# In each route handler:
gw = await get_data_gateway()
```

Route methods become thin adapters — no direct DataSourceService imports.

**Step 3: Run existing tests**

Run: `pytest tests/api/routes/test_data_sources.py -v`
Expected: PASS (may need mock updates to patch `gateway_provider.get_data_gateway`)

**Step 4: Commit**

```bash
git add src/api/routes/data_sources.py src/api/main.py
git commit -m "refactor: wire data source routes to DataSourceMCPClient via gateway_provider"
```

---

### Task 9: Wire Agent Tools to DataSourceGateway

**Files:**
- Modify: `src/orchestrator/agent/tools_v2.py` (replace DataSourceService calls)
- Modify: `src/orchestrator/agent/client.py` (remove mcp__data__* from agent)
- Test: existing `tests/orchestrator/agent/test_tools_v2.py`

**Step 1: Replace _get_data_source_service() with gateway_provider import**

In `tools_v2.py`, replace `_get_data_source_service()` (lines 142-149) with:

```python
from src.services.gateway_provider import get_data_gateway, get_external_sources_client
```

No local singleton. All gateway access goes through `gateway_provider.py`.

**Step 2: Update tool implementations**

Replace every `svc = _get_data_source_service()` with `gw = await get_data_gateway()`:

- `get_schema_tool()` (line 386): Replace `svc.get_source_info()` with `gw.get_source_info()` + `gw.get_schema()`
- `fetch_rows_tool()` (line 416): Replace `svc.get_rows_by_filter()` with `gw.get_rows_by_filter()`
- `ship_command_pipeline()` (line 715): Replace `source_service.get_rows_by_filter()` with `gw.get_rows_by_filter()`
- `_persist_job_source_signature()` (line 153): Replace `DataSourceService.get_instance().get_source_signature()` with `(await get_data_gateway()).get_source_signature()`

Note: `_persist_job_source_signature` becomes async since `get_data_gateway()` is async.

**Step 3: Remove mcp__data__* from agent client**

In `src/orchestrator/agent/client.py`:
- Remove data MCP server from `mcp_servers` dict (~line 196)
- Remove `"mcp__data__*"` from `allowed_tools` list (~line 212)

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream and not sse"`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools_v2.py src/orchestrator/agent/client.py
git commit -m "refactor: agent tools use DataSourceGateway, remove mcp__data__ from agent"
```

---

### Task 10: Wire conversations.py to DataSourceGateway

**Files:**
- Modify: `src/api/routes/conversations.py` (replace DataSourceService, remove auto-import)

**Step 1: Replace source checks**

Replace `DataSourceService.get_instance()` calls (~line 291-293) with:

```python
from src.services.gateway_provider import get_data_gateway

gw = await get_data_gateway()
source_info = await gw.get_source_info()
```

**Step 2: Delete _try_auto_import_shopify entirely**

Delete the function (lines 64-136) and ALL references in one atomic step:
- Remove `from src.mcp.external_sources.clients.shopify import ShopifyClient` import
- Remove the auto-import call at ~line 297-299
- Remove `auto_import_used` variable and all references
- Remove all direct `DataSourceService` imports

Do NOT comment-out — delete in one step. The connect_shopify agent tool (Task 11) is the replacement.

**Step 3: Run conversation tests**

Run: `pytest tests/api/routes/test_conversations.py -v -k "not stream and not sse"`
Expected: PASS

**Step 4: Commit**

```bash
git add src/api/routes/conversations.py
git commit -m "refactor: conversations use gateway_provider, remove auto-import"
```

---

## Phase 2: Auto-Import Migration + Dead Code Removal

### Task 11: Add connect_shopify Agent Tool

**Files:**
- Modify: `src/orchestrator/agent/tools_v2.py` (add connect_shopify tool)
- Modify: `src/orchestrator/agent/system_prompt.py` (add Shopify auto-connect instruction)
- Test: `tests/orchestrator/agent/test_connect_shopify.py`

**Step 1: Write failing test**

```python
# tests/orchestrator/agent/test_connect_shopify.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_connect_shopify_fetches_and_imports():
    """connect_shopify tool should connect platform, fetch orders, import via gateway."""
    with patch("src.orchestrator.agent.tools_v2.get_external_sources_client") as mock_ext, \
         patch("src.orchestrator.agent.tools_v2.get_data_gateway") as mock_gw, \
         patch.dict("os.environ", {
             "SHOPIFY_ACCESS_TOKEN": "shpat_test",
             "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
         }):
        ext_client = AsyncMock()
        ext_client.connect_platform.return_value = {"success": True}
        ext_client.fetch_orders.return_value = {
            "success": True,
            "orders": [{"order_id": "1", "customer_name": "Alice"}],
            "count": 1,
        }
        mock_ext.return_value = ext_client

        gw = AsyncMock()
        gw.import_from_records.return_value = {"row_count": 1}
        mock_gw.return_value = gw

        from src.orchestrator.agent.tools_v2 import connect_shopify_tool
        # Handler signature matches _bind_bridge contract:
        # args: dict[str, Any], bridge: EventEmitterBridge | None = None
        result = await connect_shopify_tool(
            args={},
            bridge=MagicMock(),
        )

    # Strict behavioral assertions
    ext_client.connect_platform.assert_called_once_with(
        platform="shopify",
        credentials={"access_token": "shpat_test"},
        store_url="https://test.myshopify.com",
    )
    ext_client.fetch_orders.assert_called_once_with("shopify", limit=250)
    gw.import_from_records.assert_called_once()
    assert "1" in result and "order" in result.lower()
```

**Step 2: Implement connect_shopify tool handler**

Add to `tools_v2.py` after the existing tool handlers.

**Important:** The handler signature MUST match the `_bind_bridge` contract:
`_bind_bridge` wraps handlers by calling `await handler(args, bridge=bridge)`.
So the handler takes `args: dict[str, Any]` as first param and
`bridge: EventEmitterBridge | None = None` as keyword param.

```python
async def connect_shopify_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> str:
    """Connect to Shopify and import orders as active data source.

    Reads SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN from env.
    Calls ExternalSourcesMCPClient to connect + fetch, then
    DataSourceGateway to import records.

    Args:
        args: Empty dict (credentials read from env).
        bridge: Optional event emitter bridge.

    Returns:
        Human-readable result string.
    """
    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    if not access_token or not store_domain:
        return _err("Shopify credentials not configured. Set SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN environment variables.")

    ext = await get_external_sources_client()

    # Connect
    connect_result = await ext.connect_platform(
        platform="shopify",
        credentials={"access_token": access_token},
        store_url=f"https://{store_domain}",
    )
    if not connect_result.get("success"):
        return _err(f"Failed to connect to Shopify: {connect_result.get('error', 'Unknown error')}")

    # Fetch orders
    orders_result = await ext.fetch_orders("shopify", limit=250)
    if not orders_result.get("success"):
        return _err(f"Failed to fetch Shopify orders: {orders_result.get('error', 'Unknown error')}")

    orders = orders_result.get("orders", [])
    if not orders:
        return _err("No orders found in Shopify store.")

    # Flatten orders for import (exclude nested objects)
    flat_orders = []
    for o in orders:
        flat = {k: v for k, v in o.items() if k not in ("items", "raw_data") and v is not None}
        flat_orders.append(flat)

    # Import via gateway
    gw = await get_data_gateway()
    import_result = await gw.import_from_records(flat_orders, "shopify")

    count = import_result.get("row_count", len(flat_orders))
    return _ok(f"Connected to Shopify and imported {count} orders as active data source.")
```

**Step 3: Add tool definition to get_all_tool_definitions()**

Add `connect_shopify` to the `definitions` list in `get_all_tool_definitions()`:

```python
{
    "name": "connect_shopify",
    "description": (
        "Connect to Shopify using env credentials, fetch orders, "
        "and import them as the active data source. Call this when "
        "no data source is active and Shopify env vars are configured."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
    "handler": _bind_bridge(connect_shopify_tool, bridge),
},
```

**Step 4: Update system prompt**

In `system_prompt.py`, add to the batch-mode workflow section:

```
If no data source is currently active and SHOPIFY_ACCESS_TOKEN is configured,
call the connect_shopify tool to import Shopify orders before processing
shipping commands.
```

**Step 5: Run tests**

Run: `pytest tests/orchestrator/agent/test_connect_shopify.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/orchestrator/agent/tools_v2.py src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_connect_shopify.py
git commit -m "feat: add connect_shopify agent tool — replaces auto-import side effect"
```

---

### Task 12: Delete Orphaned Assets + Verify Dead Code Removal

**Files:**
- Delete: `frontend/src/assets/react.svg`
- Verify: `src/api/routes/conversations.py` has no `_try_auto_import_shopify` (deleted in Task 10)

Note: `_try_auto_import_shopify` was already deleted atomically in Task 10 (not
commented out). This task handles remaining dead code.

**Step 1: Delete orphaned asset**

```bash
rm frontend/src/assets/react.svg
```

**Step 2: Verify no auto-import references remain**

```bash
grep -r "_try_auto_import_shopify\|auto_import_used" src/ --include="*.py"
```
Expected: No matches.

**Step 3: Commit**

```bash
git rm frontend/src/assets/react.svg
git commit -m "chore: remove orphaned react.svg"
```

---

### Task 13: Standardize Frontend Platform Hook

**Files:**
- Modify: `frontend/src/components/sidebar/panels.tsx` (use useExternalSources consistently)

**Step 1: Remove direct API imports**

In `panels.tsx`, remove direct `connectPlatform`/`disconnectPlatform` imports from `@/lib/api`.
Replace with `useExternalSources()` hook's `connect()`/`disconnect()`/`test()` methods.

**Step 2: Verify no direct API calls remain**

Search `panels.tsx` for any remaining `api.connect`, `api.disconnect`, `connectPlatform`, `disconnectPlatform` calls. Remove all.

**Step 3: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/components/sidebar/panels.tsx
git commit -m "refactor: standardize panels.tsx on useExternalSources hook"
```

---

## Phase 3: Module Decomposition + Frontend Consolidation

### Task 14: Create Shared Icon Libraries

**Files:**
- Create: `frontend/src/components/ui/icons.tsx`
- Create: `frontend/src/components/ui/brand-icons.tsx`
- Modify: All files with duplicated icons

**Step 1: Extract all generic icons to icons.tsx**

Create `frontend/src/components/ui/icons.tsx` with every unique generic icon:
SearchIcon, TrashIcon, PrinterIcon, DownloadIcon, CheckIcon, XIcon, ChevronDownIcon, EditIcon, MapPinIcon, FilterIcon, PlusIcon, RefreshIcon, CloseIcon, PackageIcon, TruckIcon, AlertIcon, WarningIcon, etc.

Copy the canonical version of each (from `presentation.tsx` or `panels.tsx` where they're exported).

**Step 2: Extract brand icons to brand-icons.tsx**

Create `frontend/src/components/ui/brand-icons.tsx` with Shopify, WooCommerce, SAP, Oracle brand glyphs.

**Step 3: Update all consuming files**

Replace local icon definitions in:
- `presentation.tsx` → import from `@/components/ui/icons`
- `panels.tsx` → import from `@/components/ui/icons` and `@/components/ui/brand-icons`
- `JobDetailPanel.tsx` → import from `@/components/ui/icons`
- `LabelPreview.tsx` → import from `@/components/ui/icons`
- `RecentSourcesModal.tsx` → import from `@/components/ui/icons`

Delete all local icon component definitions from these files.

**Step 4: Run type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/components/ui/icons.tsx frontend/src/components/ui/brand-icons.tsx frontend/src/components/
git commit -m "refactor: consolidate 16+ duplicated icons into shared icon libraries"
```

---

### Task 15: Extract formatTimeAgo to utils.ts

**Files:**
- Modify: `frontend/src/lib/utils.ts`
- Modify: `frontend/src/components/sidebar/panels.tsx` (~line 783)
- Modify: `frontend/src/components/RecentSourcesModal.tsx` (~line 78)

**Step 1: Add to utils.ts**

```typescript
export function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'Just now';
}
```

**Step 2: Replace local copies**

In `panels.tsx` and `RecentSourcesModal.tsx`, delete local `formatTimeAgo` function and import from `@/lib/utils`.

**Step 3: Type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/lib/utils.ts frontend/src/components/sidebar/panels.tsx frontend/src/components/RecentSourcesModal.tsx
git commit -m "refactor: extract formatTimeAgo to shared utils"
```

---

### Task 16: Split presentation.tsx

**Files:**
- Create: `frontend/src/components/command-center/PreviewCard.tsx`
- Create: `frontend/src/components/command-center/ProgressDisplay.tsx`
- Create: `frontend/src/components/command-center/CompletionArtifact.tsx`
- Create: `frontend/src/components/command-center/ToolCallChip.tsx`
- Create: `frontend/src/components/command-center/messages.tsx`
- Modify: `frontend/src/components/command-center/presentation.tsx` (temporary barrel)

**Step 1: Run regression baseline**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: PASS — establishes baseline

**Step 2: Extract each component**

Move each component to its own file. Each file imports its dependencies (icons from `@/components/ui/icons`, types from `@/types/api`, etc.).

**Step 3: Make presentation.tsx a temporary barrel**

```typescript
// frontend/src/components/command-center/presentation.tsx
// TEMPORARY BARREL — removal target: 2026-03-14
// All new imports should use individual component files directly.
// After this date, update all consumers and delete this file.

export { PreviewCard } from './PreviewCard';
export { ProgressDisplay } from './ProgressDisplay';
export { CompletionArtifact } from './CompletionArtifact';
export { ToolCallChip } from './ToolCallChip';
export { ActiveSourceBanner, WelcomeMessage } from './messages';
// Re-export any other consumed names...
```

**Step 4: Run regression check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: PASS — no behavior change

**Step 5: Commit**

```bash
git add frontend/src/components/command-center/
git commit -m "refactor: split presentation.tsx into focused component modules"
```

---

### Task 17: Split panels.tsx

**Files:**
- Create: `frontend/src/components/sidebar/DataSourcePanel.tsx`
- Create: `frontend/src/components/sidebar/JobHistoryPanel.tsx`
- Modify: `frontend/src/components/sidebar/panels.tsx` (temporary barrel)

**Step 1: Run regression baseline**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: PASS

**Step 2: Extract DataSourcePanel and JobHistoryPanel**

Move `DataSourceSection` component to `DataSourcePanel.tsx`.
Move `JobHistorySection` component to `JobHistoryPanel.tsx`.
Each imports icons from `@/components/ui/icons` and `@/components/ui/brand-icons`.

**Step 3: Make panels.tsx a temporary barrel**

```typescript
// frontend/src/components/sidebar/panels.tsx
// TEMPORARY BARREL — removal target: 2026-03-14
// After this date, update all consumers and delete this file.

export { DataSourceSection } from './DataSourcePanel';
export { JobHistorySection } from './JobHistoryPanel';
```

**Step 4: Run regression check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/components/sidebar/
git commit -m "refactor: split panels.tsx into DataSourcePanel + JobHistoryPanel"
```

---

### Task 18: Extract Backend Tool Shared Internals

**Files:**
- Create: `src/orchestrator/agent/tools/core.py`
- Create: `src/orchestrator/agent/tools/__init__.py`
- Modify: `src/orchestrator/agent/tools_v2.py` (import from tools/core)

**Step 1: Run regression baseline**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream and not sse" --tb=short`
Expected: PASS — establishes baseline

**Step 2: Extract shared internals to core.py**

Move from `tools_v2.py` to `src/orchestrator/agent/tools/core.py`:
- `EventEmitterBridge` class (lines 49-75)
- `_emit_event()` (lines 77-85)
- `_store_fetched_rows()` (lines 87-95)
- `_consume_fetched_rows()` (lines 97-105)
- `_ok()` (lines 112-124)
- `_err()` (lines 127-139)
- `_bind_bridge()` (lines 1243-1252)
- UPS client cache globals + functions (lines 284-344)

Note: Data gateway accessors are NOT moved here — they live in
`gateway_provider.py` (Task 8). `core.py` re-exports them for convenience:

```python
# Re-export gateway accessors for tool handler convenience
from src.services.gateway_provider import get_data_gateway, get_external_sources_client
```

**Step 3: Create __init__.py**

```python
# src/orchestrator/agent/tools/__init__.py
"""Agent tool registration — canonical entrypoint.

All tool definitions are registered here. Submodules export
handler functions only.
"""

# Re-export from tools_v2 during migration
from src.orchestrator.agent.tools_v2 import get_all_tool_definitions

__all__ = ["get_all_tool_definitions"]
```

**Step 4: Update tools_v2.py imports**

Replace local definitions with imports from `tools.core`:

```python
from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _emit_event,
    _store_fetched_rows,
    _consume_fetched_rows,
    _ok,
    _err,
    _get_ups_client,
    _reset_ups_client,
    shutdown_cached_ups_client,
    _bind_bridge,
)
# Gateway accessors already imported from gateway_provider in Task 9
from src.services.gateway_provider import get_data_gateway, get_external_sources_client
```

**Step 5: Run regression check**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream and not sse" --tb=short`
Expected: PASS — no behavior change

**Step 6: Commit**

```bash
git add src/orchestrator/agent/tools/ src/orchestrator/agent/tools_v2.py
git commit -m "refactor: extract shared tool internals to tools/core.py"
```

---

### Task 19: Split Tool Handlers

**Files:**
- Create: `src/orchestrator/agent/tools/pipeline.py`
- Create: `src/orchestrator/agent/tools/data.py`
- Create: `src/orchestrator/agent/tools/interactive.py`
- Modify: `src/orchestrator/agent/tools/__init__.py` (own get_all_tool_definitions)
- Modify: `src/orchestrator/agent/tools_v2.py` (temporary barrel)

**Step 1: Move pipeline tools**

Move to `tools/pipeline.py` (use actual function names from tools_v2.py):
- `ship_command_pipeline_tool()` — the fast pipeline handler
- `batch_preview_tool()` — rate all rows for a job
- `batch_execute_tool()` — execute confirmed batch
- `create_job_tool()` — create job record
- `add_rows_to_job_tool()` — add fetched rows to a job
- `get_job_status_tool()` — get job summary/progress
- Related helpers (rate/execute row helpers)

**Step 2: Move data tools**

Move to `tools/data.py` (use actual function names from tools_v2.py):
- `get_source_info_tool()` — get source metadata
- `get_schema_tool()` — get column schema
- `fetch_rows_tool()` — fetch rows with filter
- `validate_filter_syntax_tool()` — validate WHERE clause
- `connect_shopify_tool()` — connect Shopify + import (from Task 11)
- `get_platform_status_tool()` — check platform connections

**Step 3: Move interactive tools**

Move to `tools/interactive.py` (use actual function names from tools_v2.py):
- `preview_interactive_shipment_tool()` — preview single interactive shipment
- `_normalize_ship_from()` — normalize ship-from address
- `_mask_account()` — mask account numbers for display

**Step 4: Move get_all_tool_definitions to __init__.py**

`tools/__init__.py` becomes the canonical registration entrypoint. It imports handlers from submodules and assembles tool definition lists.

**Step 5: Make tools_v2.py a temporary barrel**

```python
# src/orchestrator/agent/tools_v2.py
# TEMPORARY BARREL — removal target: 2026-03-14
# Import from src.orchestrator.agent.tools instead.
# After this date, update all consumers and delete this file.

from src.orchestrator.agent.tools import get_all_tool_definitions
from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    shutdown_cached_ups_client,
    _bind_bridge,
)

__all__ = [
    "get_all_tool_definitions",
    "EventEmitterBridge",
    "shutdown_cached_ups_client",
    "_bind_bridge",
]
```

**Step 6: Run regression check**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream and not sse" --tb=short`
Expected: PASS

Run: `pytest -k "not stream and not sse and not edi" --tb=short`
Expected: PASS — full suite regression gate

**Step 7: Commit**

```bash
git add src/orchestrator/agent/tools/ src/orchestrator/agent/tools_v2.py
git commit -m "refactor: split tools_v2.py into pipeline/data/interactive modules"
```

---

### Task 20: Final Regression Gate + Documentation Update

**Files:**
- Modify: `CLAUDE.md` (update source structure, remove outdated references)
- Run: Full test suite

**Step 1: Run full regression suite**

```bash
pytest -k "not stream and not sse and not edi" --tb=short -q
```
Expected: PASS with same or more tests passing as baseline

**Step 2: Run frontend checks**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: PASS

**Step 3: Update CLAUDE.md**

Update the Source Structure section to reflect:
- New files: `services/external_sources_mcp_client.py`, `services/data_source_gateway.py`, `services/data_source_mcp_client.py`
- New directories: `orchestrator/agent/tools/` (core, pipeline, data, interactive)
- New frontend files: `ui/icons.tsx`, `ui/brand-icons.tsx`, split command-center and sidebar modules
- Removed: `PlatformStateManager`, `get_shopify_mcp_config()`, auto-import side effect
- Updated architecture: DataSourceGateway as authoritative data path

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for MCP-first architecture cleanup"
```

---

## Summary

| Phase | Tasks | Key Deliverables |
|-------|-------|------------------|
| **1A** | 1-4 | External Sources MCP gateway wired (connect + disconnect tools), ExternalSourcesMCPClient singleton, PlatformStateManager deleted, stale config removed |
| **1B** | 5-10 | DataSourceGateway protocol, DataSourceMCPClient implementation, centralized gateway_provider, routes + agent tools wired, mcp__data__ removed from agent, auto-import deleted |
| **2** | 11-13 | connect_shopify agent tool (correct _bind_bridge signature), orphaned assets deleted, frontend hook standardized |
| **3** | 14-20 | Icons consolidated, formatTimeAgo extracted, presentation.tsx split (5 files), panels.tsx split (2 files), tools_v2.py split (4 files), regression validated |

**Total commits:** ~21 atomic commits
**Risk mitigation:** Each task has explicit regression gates. Temporary barrel files preserve backward compatibility during migration with explicit removal dates (2026-03-14).

### Key Architectural Invariants

1. **Single provider module** — `gateway_provider.py` owns both MCP client singletons. No other file may create `DataSourceMCPClient` or `ExternalSourcesMCPClient` instances.
2. **No-arg client constructors** — All platform clients use `__init__(self)` with no args. Credentials (including URLs) pass through `authenticate(credentials: dict) -> bool`.
3. **Auth return check** — Every `authenticate()` call checks the boolean return value.
4. **Handler signature contract** — All tool handlers use `(args: dict[str, Any], bridge: EventEmitterBridge | None = None)` to match `_bind_bridge` wrapping.
5. **Structured source signature** — `get_source_signature()` returns `dict[str, Any]` with `source_type`, `source_ref`, `schema_fingerprint` — NOT a truncated string.
6. **None-safe where_clause** — Gateway normalizes `None` → `"1=1"` before passing to MCP tool.
