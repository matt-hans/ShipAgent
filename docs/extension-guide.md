# ShipAgent Extension Guide

**How to Add New Data Sources, Platforms, and Agent Tools**

This document provides a complete architectural reference for extending ShipAgent with new integrations. It identifies every file involved in each extension path and describes exactly what must be created or modified.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Adding a New Data Source Adapter](#2-adding-a-new-data-source-adapter)
3. [Adding a New Platform Integration](#3-adding-a-new-platform-integration)
4. [Adding a New Agent Tool](#4-adding-a-new-agent-tool)
5. [Frontend Changes](#5-frontend-changes)
6. [System Prompt Updates](#6-system-prompt-updates)
7. [Testing Requirements](#7-testing-requirements)
8. [Quick Reference: File Checklist](#8-quick-reference-file-checklist)
9. [Expansion Roadmap](#9-expansion-roadmap)

---

## 1. Architecture Overview

ShipAgent uses a layered architecture with three distinct extension paths:

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                       │
│   types/api.ts → hooks → components → icons/CSS             │
├─────────────────────────────────────────────────────────────┤
│                    FastAPI REST Routes                       │
│   routes/data_sources.py    routes/platforms.py              │
├─────────────────────────────────────────────────────────────┤
│                  Gateway / MCP Clients                       │
│   DataSourceMCPClient    ExternalSourcesMCPClient            │
├─────────────────────────────────────────────────────────────┤
│                    MCP Servers (stdio)                       │
│   data_source/server.py    external_sources/server.py        │
├─────────────────────────────────────────────────────────────┤
│              Adapters / Platform Clients                     │
│   adapters/csv_adapter.py    clients/shopify.py              │
├─────────────────────────────────────────────────────────────┤
│                  Orchestration Agent                         │
│   tools/__init__.py → system_prompt.py → client.py           │
└─────────────────────────────────────────────────────────────┘
```

### Extension Path A — Data Source Adapters

For local/file-based data (CSV, Excel, databases, EDI, Google Sheets, etc.). Data is imported into DuckDB and queried via SQL. The agent generates WHERE clauses against the imported schema.

### Extension Path B — Platform Integrations

For external e-commerce/ERP platforms (Shopify, Amazon, WooCommerce, SAP, Oracle, etc.). Orders are fetched via platform APIs, normalized to a common schema, and imported as a data source.

### Extension Path C — Agent Tools

For new deterministic capabilities the agent can invoke during conversation (address validation, rate comparison, customs declaration, etc.).

---

## 2. Adding a New Data Source Adapter

Data source adapters handle importing external data into DuckDB so the agent can query it via SQL. The current adapters are CSV, Excel, Database (PostgreSQL/MySQL), and EDI.

### 2.1 The Base Class Contract

**File:** `src/mcp/data_source/adapters/base.py`

Every adapter must inherit from `BaseSourceAdapter` and implement three members:

```python
class BaseSourceAdapter(ABC):

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return identifier: 'csv', 'excel', 'google_sheets', etc."""

    @abstractmethod
    def import_data(self, conn: DuckDBPyConnection, **kwargs) -> ImportResult:
        """Read source data into the 'imported_data' table in DuckDB."""

    @abstractmethod
    def get_metadata(self, conn: DuckDBPyConnection) -> dict:
        """Return non-sensitive metadata about the imported data."""
```

**`import_data()` responsibilities:**

1. Validate inputs (file exists, credentials valid, etc.)
2. Read data from the external source
3. Create or replace the `imported_data` table in DuckDB
4. Discover schema via `DESCRIBE imported_data`
5. Return an `ImportResult` with columns, row count, and warnings

**`ImportResult` model** (from `src/mcp/data_source/models.py`):

```python
class ImportResult(BaseModel):
    row_count: int
    columns: list[SchemaColumn]
    warnings: list[str]
    source_type: str

class SchemaColumn(BaseModel):
    name: str          # Column name
    type: str          # DuckDB type (VARCHAR, INTEGER, DATE, etc.)
    nullable: bool
    warnings: list[str]
```

### 2.2 Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `src/mcp/data_source/adapters/{name}_adapter.py` | Adapter class implementing `BaseSourceAdapter` |

### 2.3 Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `src/mcp/data_source/adapters/__init__.py` | Export new adapter class |
| 2 | `src/mcp/data_source/tools/import_tools.py` | Add `import_{name}()` MCP tool function |
| 3 | `src/mcp/data_source/server.py` | Register new tool: `mcp.tool()(import_{name})` |
| 4 | `src/services/data_source_gateway.py` | Add method to `DataSourceGateway` protocol |
| 5 | `src/services/data_source_mcp_client.py` | Implement gateway method (calls MCP tool) |
| 6 | `src/api/routes/data_sources.py` | Add route handler for new source type |
| 7 | `src/api/schemas.py` | Add Pydantic request/response fields if needed |
| 8 | `src/services/data_source_service.py` | Update `DataSourceInfo` if new metadata fields needed |

### 2.4 Step-by-Step Example: Google Sheets Adapter

**Step 1 — Create the adapter:**

```python
# src/mcp/data_source/adapters/google_sheets_adapter.py

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult, SchemaColumn

class GoogleSheetsAdapter(BaseSourceAdapter):

    @property
    def source_type(self) -> str:
        return "google_sheets"

    def import_data(self, conn, **kwargs) -> ImportResult:
        spreadsheet_id = kwargs["spreadsheet_id"]
        sheet_name = kwargs.get("sheet")
        credentials_json = kwargs.get("credentials_json")

        # 1. Authenticate with Google Sheets API
        # 2. Fetch sheet data as rows
        # 3. Load into DuckDB
        conn.execute("CREATE OR REPLACE TABLE imported_data AS SELECT ...")

        # 4. Discover schema
        schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
        columns = [
            SchemaColumn(name=r[0], type=r[1], nullable=r[2] == "YES", warnings=[])
            for r in schema_rows
        ]
        row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

        return ImportResult(
            row_count=row_count,
            columns=columns,
            warnings=[],
            source_type="google_sheets",
        )

    def get_metadata(self, conn) -> dict:
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
            cols = conn.execute("DESCRIBE imported_data").fetchall()
            return {"row_count": row_count, "column_count": len(cols), "source_type": "google_sheets"}
        except Exception:
            return {"error": "No data imported"}
```

**Step 2 — Export in `__init__.py`:**

```python
# src/mcp/data_source/adapters/__init__.py
from src.mcp.data_source.adapters.google_sheets_adapter import GoogleSheetsAdapter
__all__ = [..., "GoogleSheetsAdapter"]
```

**Step 3 — Create the MCP import tool:**

```python
# Add to src/mcp/data_source/tools/import_tools.py

async def import_google_sheets(
    spreadsheet_id: str,
    ctx: Context,
    sheet: str | None = None,
    credentials_json: str | None = None,
) -> dict:
    """Import Google Sheets spreadsheet and discover schema."""
    db = ctx.request_context.lifespan_context["db"]
    adapter = GoogleSheetsAdapter()
    result = adapter.import_data(
        conn=db,
        spreadsheet_id=spreadsheet_id,
        sheet=sheet,
        credentials_json=credentials_json,
    )
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "google_sheets",
        "spreadsheet_id": spreadsheet_id,
        "sheet": sheet,
        "row_count": result.row_count,
    }
    return result.model_dump()
```

**Step 4 — Register in MCP server:**

```python
# src/mcp/data_source/server.py
from src.mcp.data_source.tools.import_tools import import_google_sheets
mcp.tool()(import_google_sheets)
```

**Step 5 — Add gateway method:**

```python
# src/services/data_source_gateway.py — add to Protocol
async def import_google_sheets(
    self, spreadsheet_id: str, sheet: str | None = None, credentials_json: str | None = None
) -> dict[str, Any]: ...

# src/services/data_source_mcp_client.py — implement
async def import_google_sheets(self, spreadsheet_id: str, **kwargs) -> dict[str, Any]:
    await self._ensure_connected()
    result = await self._mcp.call_tool("import_google_sheets", {
        "spreadsheet_id": spreadsheet_id, **kwargs
    })
    return result
```

**Step 6 — Add API route handler:**

```python
# src/api/routes/data_sources.py — extend import_data_source()
elif payload.type == "google_sheets":
    result = await gw.import_google_sheets(
        spreadsheet_id=payload.spreadsheet_id,
        sheet=payload.sheet,
    )
```

### 2.5 Write-Back Support

If the new source supports write-back (writing tracking numbers back to the source), update:

| File | Change |
|------|--------|
| `src/mcp/data_source/tools/writeback_tools.py` | Add write-back case for new source type |
| `src/services/write_back_utils.py` | Add atomic write utility if file-based |

The write-back tool dispatches by `current_source["type"]`:

```python
# writeback_tools.py
if current_source["type"] == "google_sheets":
    await write_to_google_sheets(spreadsheet_id, row_number, tracking_number)
```

### 2.6 Saved Source Support

For one-click reconnection, update:

| File | Change |
|------|--------|
| `src/services/saved_data_source_service.py` | Add `save_or_update_google_sheets()` method |
| `src/services/data_source_mcp_client.py` | Add `_auto_save_google_sheets()` in import method |
| `src/db/models.py` | Extend `SavedDataSource` model fields if needed |

### 2.7 Design Rules

- **One source at a time.** Importing replaces any previous source (shared `imported_data` table).
- **Never store credentials.** Only save display metadata for reconnection (spreadsheet name, ID — not API keys).
- **Graceful degradation.** Import all rows, flag invalid ones in warnings. Never fail on bad rows.
- **VARCHAR fallback.** When type inference is ambiguous, default to VARCHAR.

---

## 3. Adding a New Platform Integration

Platform integrations connect to external e-commerce/ERP systems, fetch orders, normalize them to a common schema, and optionally write tracking numbers back. The current platforms are Shopify, WooCommerce, SAP, and Oracle.

### 3.1 The Base Class Contract

**File:** `src/mcp/external_sources/clients/base.py`

Every platform client must inherit from `PlatformClient` and implement six members:

```python
class PlatformClient(ABC):

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return identifier: 'shopify', 'amazon', etc."""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate with platform. Return True if successful."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Health check — is the connection still alive?"""

    @abstractmethod
    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        """Fetch orders with optional filters."""

    @abstractmethod
    async def get_order(self, order_id: str) -> ExternalOrder | None:
        """Get a single order by ID."""

    @abstractmethod
    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Write tracking number back to the platform."""
```

**`ExternalOrder` model** (from `src/mcp/external_sources/models.py`) — the normalization target:

```python
class ExternalOrder(BaseModel):
    platform: str
    order_id: str
    order_number: str | None
    status: str
    created_at: str
    customer_name: str
    customer_email: str | None
    ship_to_name: str
    ship_to_company: str | None
    ship_to_address1: str
    ship_to_address2: str | None
    ship_to_city: str
    ship_to_state: str
    ship_to_postal_code: str
    ship_to_country: str
    ship_to_phone: str | None
    total_price: float | None
    financial_status: str | None
    fulfillment_status: str | None
    tags: str | None
    total_weight_grams: int | None
    item_count: int | None
    items: list[dict] | None
    raw_data: dict | None
```

Every platform must normalize its native order format into this schema via a `_normalize_order()` method. This enables uniform SQL querying and batch processing regardless of the source platform.

### 3.2 Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `src/mcp/external_sources/clients/{platform}.py` | Client class implementing `PlatformClient` |

### 3.3 Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `src/mcp/external_sources/models.py` | Add value to `PlatformType` enum |
| 2 | `src/mcp/external_sources/tools.py` | Add case to `_create_platform_client()` factory |
| 3 | `src/mcp/external_sources/tools.py` | Add entry to `_URL_KEY_MAP` if platform uses a URL |
| 4 | `src/mcp/external_sources/clients/__init__.py` | Export new client class |

**No changes needed to:** `server.py`, `external_sources_mcp_client.py`, `gateway_provider.py`, or `routes/platforms.py`. These layers are fully generic — they dispatch by the `platform` string parameter.

### 3.4 Step-by-Step Example: Amazon Seller Central

**Step 1 — Create the client:**

```python
# src/mcp/external_sources/clients/amazon.py

import httpx
from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import ExternalOrder, OrderFilters, TrackingUpdate

class AmazonClient(PlatformClient):

    def __init__(self) -> None:
        self._authenticated = False
        self._access_key: str | None = None
        self._secret_key: str | None = None
        self._marketplace_id: str | None = None
        self._endpoint: str | None = None

    @property
    def platform_name(self) -> str:
        return "amazon"

    async def authenticate(self, credentials: dict) -> bool:
        self._access_key = credentials.get("access_key")
        self._secret_key = credentials.get("secret_key")
        self._marketplace_id = credentials.get("marketplace_id", "ATVPDKIKX0DER")
        self._endpoint = credentials.get("endpoint", "https://sellingpartnerapi-na.amazon.com")
        try:
            # Exchange credentials for SP-API access token
            # Test with GET /orders/v0/orders?MaxResultsPerPage=1
            self._authenticated = True
            return True
        except Exception:
            self._authenticated = False
            return False

    async def test_connection(self) -> bool:
        if not self._authenticated:
            return False
        # Quick health check against SP-API
        return True

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        if not self._authenticated:
            return []
        # Call SP-API GET /orders/v0/orders
        # Apply filters: CreatedAfter, CreatedBefore, OrderStatuses, MaxResultsPerPage
        raw_orders = []  # ... API call ...
        return [self._normalize_order(o) for o in raw_orders]

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        if not self._authenticated:
            return None
        # Call SP-API GET /orders/v0/orders/{orderId}
        return None  # ... normalize and return ...

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        if not self._authenticated:
            return False
        # Call SP-API POST /feeds/v0/feeds (POST_ORDER_FULFILLMENT_DATA)
        return True

    def _normalize_order(self, raw: dict) -> ExternalOrder:
        """Map Amazon order JSON to ExternalOrder."""
        shipping = raw.get("ShippingAddress", {})
        return ExternalOrder(
            platform="amazon",
            order_id=raw.get("AmazonOrderId", ""),
            order_number=raw.get("AmazonOrderId"),
            status=raw.get("OrderStatus", "unknown"),
            created_at=raw.get("PurchaseDate", ""),
            customer_name=raw.get("BuyerInfo", {}).get("BuyerName", ""),
            customer_email=raw.get("BuyerInfo", {}).get("BuyerEmail"),
            ship_to_name=shipping.get("Name", ""),
            ship_to_address1=shipping.get("AddressLine1", ""),
            ship_to_address2=shipping.get("AddressLine2"),
            ship_to_city=shipping.get("City", ""),
            ship_to_state=shipping.get("StateOrRegion", ""),
            ship_to_postal_code=shipping.get("PostalCode", ""),
            ship_to_country=shipping.get("CountryCode", "US"),
            ship_to_phone=shipping.get("Phone"),
            total_price=float(raw.get("OrderTotal", {}).get("Amount", 0)),
            financial_status=raw.get("PaymentMethodDetails", [None])[0],
            fulfillment_status=raw.get("FulfillmentChannel"),
            total_weight_grams=None,
            item_count=raw.get("NumberOfItemsUnshipped", 0),
            items=raw.get("OrderItems", []),
            raw_data=raw,
        )

    async def close(self) -> None:
        """Cleanup resources."""
        self._authenticated = False
```

**Step 2 — Add to PlatformType enum:**

```python
# src/mcp/external_sources/models.py
class PlatformType(str, Enum):
    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"
    SAP = "sap"
    ORACLE = "oracle"
    AMAZON = "amazon"          # ← Add this
```

**Step 3 — Add to client factory:**

```python
# src/mcp/external_sources/tools.py — in _create_platform_client()
elif platform == "amazon":
    from src.mcp.external_sources.clients.amazon import AmazonClient
    return AmazonClient()
```

**Step 4 — Add URL key mapping (if applicable):**

```python
# src/mcp/external_sources/tools.py
_URL_KEY_MAP = {
    "shopify": "store_url",
    "woocommerce": "site_url",
    "sap": "base_url",
    "amazon": "endpoint",     # ← Add if platform uses a base URL
}
```

**Step 5 — Export in `__init__.py`:**

```python
# src/mcp/external_sources/clients/__init__.py
from src.mcp.external_sources.clients.amazon import AmazonClient
__all__ = [..., "AmazonClient"]
```

That's it for the backend. The MCP server, MCP client, gateway provider, and API routes are all generic and will automatically route requests to the new client.

### 3.5 How Platform Data Becomes Queryable

Platforms don't use the data source adapter path directly. Instead, the agent uses the `connect_shopify` tool pattern:

1. Agent calls `connect_{platform}` tool
2. Tool authenticates via `ExternalSourcesMCPClient.connect_platform()`
3. Tool fetches orders via `ExternalSourcesMCPClient.fetch_orders()`
4. Orders are flattened to dicts (excluding nested arrays)
5. Flattened records imported via `DataSourceGateway.import_from_records()`
6. Data is now in DuckDB and queryable via SQL

To replicate this for a new platform, add an agent tool (see [Section 4](#4-adding-a-new-agent-tool)) that follows this same pattern. Reference `connect_shopify_tool` in `src/orchestrator/agent/tools/data.py`.

### 3.6 Authentication Patterns

| Platform | Auth Method | Credentials Keys |
|----------|------------|-----------------|
| Shopify | Bearer token | `store_url`, `access_token` |
| WooCommerce | HTTP Basic (consumer key/secret) | `site_url`, `consumer_key`, `consumer_secret` |
| SAP | HTTP Basic + SAP client | `base_url`, `username`, `password`, `client` |
| Oracle | Connection string / DSN | `connection_string` or `host`/`port`/`service_name`/`user`/`password` |
| Amazon (example) | SP-API OAuth | `access_key`, `secret_key`, `marketplace_id` |

### 3.7 Design Rules

- **Normalize everything.** Every platform must produce `ExternalOrder` objects — no platform-specific schemas leak upstream.
- **Never log credentials.** The lifespan context stores credentials in memory only. They are never written to logs or disk.
- **Stateless gateway.** The `ExternalSourcesMCPClient` is stateless; all state lives in the MCP server's lifespan context.
- **Async throughout.** All client methods must be `async` for non-blocking I/O.
- **Graceful auth failure.** `authenticate()` returns `False` on failure — never raises.

---

## 4. Adding a New Agent Tool

Agent tools are deterministic functions the LLM can invoke during conversation. They are defined as dicts with a name, description, input schema, and async handler.

### 4.1 Tool Definition Structure

```python
{
    "name": "tool_name",              # snake_case identifier
    "description": "What this tool does — LLM reads this to decide when to call it",
    "input_schema": {
        "type": "object",
        "properties": {
            "param_name": {
                "type": "string",
                "description": "What this parameter controls",
            },
        },
        "required": ["param_name"],
    },
    "handler": tool_handler_function,  # async callable
}
```

### 4.2 Tool Handler Pattern

All handlers follow this signature and use `_ok()`/`_err()` response helpers from `core.py`:

```python
async def my_tool_handler(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,  # Optional — only if emitting SSE events
) -> dict[str, Any]:
    """Handler docstring."""
    param = args.get("param_name")
    if not param:
        return _err("param_name is required")

    try:
        result = await some_service.do_work(param)
        return _ok({"status": "success", "data": result})
    except Exception as e:
        logger.error("my_tool failed: %s", e)
        return _err(f"Operation failed: {e}")
```

**Response format** (MCP-compatible):

```python
# Success
{"isError": False, "content": [{"type": "text", "text": "{\"key\": \"value\"}"}]}

# Error
{"isError": True, "content": [{"type": "text", "text": "Error message"}]}
```

### 4.3 Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `src/orchestrator/agent/tools/{module}.py` | Add handler function (choose: `data.py`, `pipeline.py`, `interactive.py`, or new file) |
| 2 | `src/orchestrator/agent/tools/__init__.py` | Import handler + add definition to `get_all_tool_definitions()` |
| 3 | `src/orchestrator/agent/system_prompt.py` | Add tool usage guidance to agent's system prompt (if non-obvious) |

### 4.4 Tool Module Organization

| Module | Concern | Example Tools |
|--------|---------|---------------|
| `data.py` | Data source queries, platform status | `get_source_info`, `fetch_rows`, `connect_shopify` |
| `pipeline.py` | Job lifecycle, batch processing | `ship_command_pipeline`, `batch_preview`, `create_job` |
| `interactive.py` | Single-shipment creation | `preview_interactive_shipment` |
| `core.py` | Shared utilities only (not tools) | `_ok()`, `_err()`, `EventEmitterBridge`, `_get_ups_client()` |

### 4.5 Step-by-Step Example: Rate Comparison Tool

```python
# 1. Add handler to src/orchestrator/agent/tools/data.py

async def compare_rates_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Compare shipping rates across multiple UPS services for a destination.

    Args:
        args: Dict with ship_to_zip, weight_lbs, and optional services list.
        bridge: Optional event emitter for SSE.

    Returns:
        Rate comparison table sorted by cost.
    """
    zip_code = args.get("ship_to_zip")
    weight = args.get("weight_lbs", 1.0)
    services = args.get("services")  # Optional: subset of service codes

    if not zip_code:
        return _err("ship_to_zip is required")

    try:
        ups = await _get_ups_client()
        # Rate against multiple services
        rates = []
        for code in (services or ["03", "02", "01", "12", "13"]):
            rate = await ups.get_rate(ship_to_zip=zip_code, weight=weight, service_code=code)
            rates.append({"service_code": code, "cost_cents": rate["cost_cents"]})

        rates.sort(key=lambda r: r["cost_cents"])
        return _ok({"rates": rates, "cheapest": rates[0], "destination_zip": zip_code})
    except Exception as e:
        logger.error("compare_rates_tool failed: %s", e)
        return _err(f"Rate comparison failed: {e}")
```

```python
# 2. Register in src/orchestrator/agent/tools/__init__.py

from src.orchestrator.agent.tools.data import compare_rates_tool

# Inside get_all_tool_definitions():
definitions.append({
    "name": "compare_rates",
    "description": "Compare shipping rates across multiple UPS services for a given destination ZIP and weight. Returns rates sorted by cost.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ship_to_zip": {
                "type": "string",
                "description": "Destination ZIP code",
            },
            "weight_lbs": {
                "type": "number",
                "description": "Package weight in pounds (default 1.0)",
                "default": 1.0,
            },
            "services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of service codes to compare (default: all)",
            },
        },
        "required": ["ship_to_zip"],
    },
    "handler": _bind_bridge(compare_rates_tool, bridge),
})
```

```python
# 3. Update system prompt in src/orchestrator/agent/system_prompt.py (if needed)
# Add to tool_usage_section:
tool_usage_section += """
- Use `compare_rates` when the user asks to compare shipping costs across services.
"""
```

### 4.6 Bridge Binding

If a tool needs to emit real-time events to the frontend (progress updates, preview cards, etc.), it accepts a `bridge` parameter and uses `_bind_bridge()`:

```python
# Handler accepts bridge
async def my_tool(args, bridge=None):
    if bridge:
        bridge.emit("my_event", {"data": "value"})

# Registration uses _bind_bridge
"handler": _bind_bridge(my_tool, bridge)
```

If a tool does NOT need event emission, bind it directly without the bridge wrapper:

```python
"handler": my_tool  # No bridge binding needed
```

### 4.7 Mode-Aware Tools

Tools can be restricted to specific modes:

```python
# In get_all_tool_definitions():
if interactive_shipping:
    # Only include these tools in interactive mode
    interactive_allowed = {"get_job_status", "get_platform_status", "preview_interactive_shipment"}
    return [d for d in definitions if d["name"] in interactive_allowed]
else:
    # Batch mode gets all tools
    return definitions
```

### 4.8 Design Rules

- **Always async.** Required by Claude Agent SDK.
- **Always return `_ok()` or `_err()`.** Never raise exceptions from handlers.
- **Validate inputs first.** Check required params before doing work.
- **Log errors to logger.** Frontend sees the `_err()` message; backend sees the stack trace.
- **Keep tool descriptions precise.** The LLM uses the description to decide when to call the tool.

---

## 5. Frontend Changes

### 5.1 For a New Data Source Type

| # | File | Change |
|---|------|--------|
| 1 | `frontend/src/types/api.ts` | Add to `DataSourceType` union type |
| 2 | `frontend/src/types/api.ts` | Add config interface if source has unique parameters |
| 3 | `frontend/src/lib/api.ts` | Update `importDataSource()` and request types if needed |
| 4 | `frontend/src/components/sidebar/DataSourcePanel.tsx` | Add import button + connection form |
| 5 | `frontend/src/hooks/useAppState.tsx` | Update `CachedLocalConfig` type if needed |
| 6 | `frontend/src/components/ui/icons.tsx` | Add icon component |

### 5.2 For a New Platform

| # | File | Change |
|---|------|--------|
| 1 | `frontend/src/types/api.ts` | Add to `PlatformType` union + credentials interface |
| 2 | `frontend/src/hooks/useExternalSources.ts` | Add to `ALL_PLATFORMS` and `INITIAL_PLATFORMS` |
| 3 | `frontend/src/components/ui/brand-icons.tsx` | Add platform brand icon |
| 4 | `frontend/src/index.css` | Add platform color token (light + dark mode) |
| 5 | `frontend/src/index.css` | Add `.platform-card--{name}` CSS class |

The platform hook (`useExternalSources.ts`) and API client (`api.ts`) are fully generic — they work with any `PlatformType` value via the `{platform}` path parameter. No changes needed to API endpoint functions.

### 5.3 Icon Conventions

- **Data source icons** go in `frontend/src/components/ui/icons.tsx` (functional SVGs)
- **Platform brand icons** go in `frontend/src/components/ui/brand-icons.tsx` (brand-aware SVGs)
- All icons accept `{ className?: string }` props
- Use `currentColor` fill for theme compatibility

### 5.4 CSS Platform Colors

```css
/* frontend/src/index.css — light mode */
--color-{platform}: oklch(0.45 0.2 130);

/* Dark mode override */
--color-{platform}: oklch(0.5 0.22 130);

/* Platform card accent */
.platform-card--{platform}::before {
  background: oklch(0.45 0.2 130);
}
```

---

## 6. System Prompt Updates

**File:** `src/orchestrator/agent/system_prompt.py`

The system prompt dynamically informs the agent about available capabilities. When adding new features, consider updating these sections:

| Section | When to Update |
|---------|---------------|
| **Service Codes table** | Adding new carriers or service types |
| **Data Source section** | Auto-detection of new platform credentials in environment |
| **Filter Generation Rules** | New column types, naming conventions, or query patterns |
| **Workflow section** | New tool call sequences or decision trees |
| **Safety Rules** | New confirmation gates or restrictions |
| **Tool Usage section** | Guidance on when/how to use new tools |

### Example: Adding Auto-Detection for Amazon

```python
# In build_system_prompt(), extend the no-source-connected logic:
amazon_configured = bool(
    os.environ.get("AMAZON_ACCESS_KEY")
    and os.environ.get("AMAZON_SECRET_KEY")
)
if amazon_configured:
    data_section = (
        "No data source imported yet, but Amazon Seller credentials are configured. "
        "You MUST call the connect_amazon tool FIRST to import Amazon orders."
    )
```

---

## 7. Testing Requirements

### 7.1 Data Source Adapter Tests

```
tests/mcp/data_source/adapters/test_{name}_adapter.py
```

Required test cases:
- Import with valid source → correct row count, schema, types
- Import with invalid source → appropriate error
- Import with empty data → 0 rows, no crash
- Import with mixed types → VARCHAR fallback, warnings
- `get_metadata()` after import → correct counts
- `get_metadata()` before import → error dict

### 7.2 Platform Client Tests

```
tests/mcp/external_sources/test_{platform}.py
```

Required test cases:
- Authentication success and failure
- `test_connection()` when connected and disconnected
- `fetch_orders()` with and without filters
- `get_order()` for existing and non-existing orders
- `update_tracking()` success and failure
- Order normalization → all `ExternalOrder` fields populated correctly

### 7.3 Agent Tool Tests

```
tests/orchestrator/agent/tools/test_{module}.py
```

Required test cases:
- Handler returns `_ok()` on success
- Handler returns `_err()` on missing required params
- Handler returns `_err()` on service failure
- Bridge events emitted correctly (if applicable)
- Tool registered in `get_all_tool_definitions()` output

### 7.4 Running Tests

```bash
# All tests
pytest

# Specific adapter
pytest tests/mcp/data_source/adapters/test_google_sheets_adapter.py -v

# Specific platform
pytest tests/mcp/external_sources/test_amazon.py -v

# Agent tools
pytest tests/orchestrator/agent/tools/ -v

# Skip known hanging tests
pytest -k "not stream and not sse and not progress"
```

---

## 8. Quick Reference: File Checklist

### Adding a Data Source Adapter

```
CREATE:
  [ ] src/mcp/data_source/adapters/{name}_adapter.py
  [ ] tests/mcp/data_source/adapters/test_{name}_adapter.py

MODIFY:
  [ ] src/mcp/data_source/adapters/__init__.py          — export
  [ ] src/mcp/data_source/tools/import_tools.py          — import tool
  [ ] src/mcp/data_source/server.py                      — register tool
  [ ] src/services/data_source_gateway.py                 — protocol method
  [ ] src/services/data_source_mcp_client.py              — implement method
  [ ] src/api/routes/data_sources.py                      — route handler
  [ ] frontend/src/types/api.ts                           — DataSourceType union
  [ ] frontend/src/components/sidebar/DataSourcePanel.tsx  — UI button/form
  [ ] frontend/src/components/ui/icons.tsx                 — icon (optional)
```

### Adding a Platform Integration

```
CREATE:
  [ ] src/mcp/external_sources/clients/{platform}.py
  [ ] tests/mcp/external_sources/test_{platform}.py

MODIFY:
  [ ] src/mcp/external_sources/models.py                  — PlatformType enum
  [ ] src/mcp/external_sources/tools.py                   — factory + URL map
  [ ] src/mcp/external_sources/clients/__init__.py        — export
  [ ] frontend/src/types/api.ts                           — PlatformType union
  [ ] frontend/src/hooks/useExternalSources.ts            — ALL_PLATFORMS
  [ ] frontend/src/components/ui/brand-icons.tsx          — brand icon
  [ ] frontend/src/index.css                              — colors + card class
```

### Adding an Agent Tool

```
MODIFY:
  [ ] src/orchestrator/agent/tools/{module}.py            — handler function
  [ ] src/orchestrator/agent/tools/__init__.py            — import + definition
  [ ] src/orchestrator/agent/system_prompt.py             — usage guidance (if needed)
  [ ] tests/orchestrator/agent/tools/test_{module}.py     — tests
```

---

## 9. Expansion Roadmap

The following integrations would extend ShipAgent to cover the full shipping ecosystem. Each entry lists the extension path and key implementation considerations.

### 9.1 Data Source Expansions

| Integration | Extension Path | Key Considerations |
|-------------|---------------|-------------------|
| **Google Sheets** | Adapter | OAuth2 flow for authentication; Google Sheets API v4; real-time sync vs snapshot import; shared spreadsheet permissions |
| **Airtable** | Adapter | API key auth; paginated record fetching; formula fields as computed columns; linked records require denormalization |
| **JSON/JSONL** | Adapter | Schema inference from nested objects; array flattening strategy; large file streaming |
| **XML** | Adapter | XPath for element extraction; namespace handling; attribute vs element mapping |
| **Google BigQuery** | Adapter | Service account auth; query cost estimation; result size limits; DuckDB can query BigQuery via extension |
| **Snowflake** | Adapter | Key-pair or SSO auth; warehouse/database/schema selection; DuckDB has no native extension — use Python connector |
| **REST API (Generic)** | Adapter | Configurable endpoint, auth (Bearer/API key/Basic), response path extraction, pagination strategy |

### 9.2 Platform Expansions

| Integration | Extension Path | Key Considerations |
|-------------|---------------|-------------------|
| **Amazon Seller Central** | Platform client | SP-API with LWA OAuth; marketplace-specific endpoints; FBA vs MFN fulfillment channels; rate limiting (1 req/sec burst) |
| **eBay** | Platform client | REST API with OAuth 2.0; order API v2; fulfillment API for tracking; sandbox vs production environments |
| **Etsy** | Platform client | OAuth 2.0; Shop API v3; receipt-based order model; shipping profiles |
| **BigCommerce** | Platform client | API token auth; V2 orders API; webhook-based tracking updates |
| **Magento / Adobe Commerce** | Platform client | REST API with token auth; complex order status model; configurable attributes |
| **Square** | Platform client | OAuth 2.0; Orders API; fulfillment objects for tracking; location-based inventory |
| **NetSuite** | Platform client | SuiteTalk SOAP or REST; SuiteQL for queries; complex auth (TBA); saved searches |
| **Dynamics 365** | Platform client | Azure AD OAuth; OData v4 queries; Business Central vs Supply Chain Management |
| **ShipStation** | Platform client (or Adapter) | API key auth; already has normalized order model; useful as an aggregator source |
| **Pirate Ship** | Platform client | API access varies; could import from CSV exports initially |

### 9.3 Carrier Expansions

Adding new carriers requires a different extension path — creating a new MCP server similar to `ups-mcp`:

| Carrier | Implementation Notes |
|---------|---------------------|
| **FedEx** | REST API (OAuth 2.0); rate, ship, track, address validation; similar tool surface to UPS |
| **USPS** | Web Tools API (XML) or new REST API; limited to domestic; stamps.com integration common |
| **DHL** | DHL Express API; XML-heavy; international focus; customs declarations required |
| **Canada Post** | REST API; metric units; bilingual labels (EN/FR) |
| **Royal Mail** | Shipping API; UK domestic; customs for international |

**Carrier expansion pattern:**

1. Create or find an MCP server for the carrier (like `ups-mcp`)
2. Add it as a stdio MCP server in the agent configuration (`client.py`)
3. Create a `{Carrier}MCPClient` wrapper for batch execution (like `UPSMCPClient`)
4. Update `BatchEngine` to dispatch to the correct carrier client
5. Update `UPSPayloadBuilder` → `PayloadBuilder` to support carrier-specific payloads
6. Add carrier service codes to the system prompt
7. Update agent tools to accept carrier selection

### 9.4 Agent Tool Expansions

| Tool | Purpose | Implementation Notes |
|------|---------|---------------------|
| **compare_rates** | Rate comparison across services/carriers | Multi-service rating in parallel; present as sorted table |
| **validate_address_batch** | Bulk address validation before shipping | Pre-flight check; flag invalid addresses in preview |
| **customs_declaration** | Generate customs forms for international | Requires HS codes, declared values, country of origin |
| **schedule_pickup** | Schedule carrier pickup | Carrier-specific pickup APIs; time window selection |
| **void_batch** | Cancel multiple shipments at once | Iterate tracking numbers; partial failure handling |
| **analytics_query** | Query shipping history for insights | Aggregate across completed jobs; cost trends, volume by state |
| **connect_amazon** | Import Amazon orders as data source | Follow `connect_shopify` pattern; SP-API OAuth flow |

### 9.5 Priority Recommendation

For maximum impact with minimal effort, prioritize in this order:

1. **Amazon Seller Central** (Platform) — Largest e-commerce platform; high demand
2. **FedEx** (Carrier) — Most requested second carrier
3. **Google Sheets** (Adapter) — Zero-install data source; broad appeal
4. **eBay** (Platform) — Second-largest marketplace
5. **Rate Comparison Tool** (Agent Tool) — High-value feature for cost optimization
6. **USPS** (Carrier) — Essential for lightweight/domestic shipments
7. **ShipStation** (Platform/Adapter) — Aggregator that covers many smaller platforms at once
