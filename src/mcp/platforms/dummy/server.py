# src/mcp/platforms/dummy/server.py
"""DummyPlatform MCP server for vertical slice testing.

Implements the full platform contract with fixed 2-page order data.
Used to prove the end-to-end shape before dealing with real platform quirks.

Per CONTEXT.md:
- NEVER use print() - use ctx.info() for logging
- Use FastMCP v2 with lifespan context
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

PLATFORM_ID = "dummy"
CONTRACT_VERSION = "1.0"
SERVER_VERSION = "0.1.0"

# Fixed order data: 6 orders across 2 pages
_ORDERS_PAGE_1 = [
    {
        "id": "D001",
        "order_number": "1001",
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-20T10:00:00Z",
        "updated_at": "2026-02-20T10:00:00Z",
        "total_price": "25.00",
        "currency": "USD",
        "customer_name": "Alice Test",
        "customer_email": "alice@test.com",
        "shipping_address": {
            "name": "Alice Test",
            "company": None,
            "address1": "100 First St",
            "address2": None,
            "city": "Austin",
            "state": "TX",
            "zip": "78701",
            "country_code": "US",
            "phone": "512-555-0001",
        },
        "line_items": [{"quantity": 1, "grams": 500, "title": "Widget A"}],
        "tags": "test",
    },
    {
        "id": "D002",
        "order_number": "1002",
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-21T10:00:00Z",
        "updated_at": "2026-02-21T10:00:00Z",
        "total_price": "50.00",
        "currency": "USD",
        "customer_name": "Bob Test",
        "customer_email": "bob@test.com",
        "shipping_address": {
            "name": "Bob Test",
            "company": "TestCorp",
            "address1": "200 Second St",
            "address2": "Suite 1",
            "city": "Dallas",
            "state": "TX",
            "zip": "75201",
            "country_code": "US",
            "phone": "214-555-0002",
        },
        "line_items": [
            {"quantity": 2, "grams": 300, "title": "Widget B"},
        ],
        "tags": "test,bulk",
    },
    {
        "id": "D003",
        "order_number": "1003",
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-22T10:00:00Z",
        "updated_at": "2026-02-22T10:00:00Z",
        "total_price": "15.99",
        "currency": "USD",
        "customer_name": "Carol Test",
        "customer_email": "carol@test.com",
        "shipping_address": {
            "name": "Carol Test",
            "company": None,
            "address1": "300 Third Ave",
            "address2": None,
            "city": "Houston",
            "state": "TX",
            "zip": "77001",
            "country_code": "US",
            "phone": "713-555-0003",
        },
        "line_items": [{"quantity": 1, "grams": 200, "title": "Gadget C"}],
        "tags": "test",
    },
]

_ORDERS_PAGE_2 = [
    {
        "id": "D004",
        "order_number": "1004",
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-23T10:00:00Z",
        "updated_at": "2026-02-23T10:00:00Z",
        "total_price": "75.00",
        "currency": "USD",
        "customer_name": "Dave Test",
        "customer_email": "dave@test.com",
        "shipping_address": {
            "name": "Dave Test",
            "company": None,
            "address1": "400 Fourth Blvd",
            "address2": None,
            "city": "San Antonio",
            "state": "TX",
            "zip": "78201",
            "country_code": "US",
            "phone": "210-555-0004",
        },
        "line_items": [{"quantity": 3, "grams": 400, "title": "Widget D"}],
        "tags": "test",
    },
    {
        "id": "D005",
        "order_number": "1005",
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": "fulfilled",
        "created_at": "2026-02-24T10:00:00Z",
        "updated_at": "2026-02-24T10:00:00Z",
        "total_price": "30.00",
        "currency": "USD",
        "customer_name": "Eve Test",
        "customer_email": "eve@test.com",
        "shipping_address": {
            "name": "Eve Test",
            "company": "EveCo",
            "address1": "500 Fifth Ln",
            "address2": None,
            "city": "El Paso",
            "state": "TX",
            "zip": "79901",
            "country_code": "US",
            "phone": "915-555-0005",
        },
        "line_items": [{"quantity": 1, "grams": 150, "title": "Gadget E"}],
        "tags": "test,fulfilled",
    },
    {
        "id": "D006",
        "order_number": "1006",
        "status": "open",
        "payment_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-25T10:00:00Z",
        "updated_at": "2026-02-25T10:00:00Z",
        "total_price": "99.99",
        "currency": "USD",
        "customer_name": "Frank Test",
        "customer_email": "frank@test.com",
        "shipping_address": {
            "name": "Frank Test",
            "company": None,
            "address1": "600 Sixth Dr",
            "address2": "Apt 2",
            "city": "Fort Worth",
            "state": "TX",
            "zip": "76101",
            "country_code": "US",
            "phone": "817-555-0006",
        },
        "line_items": [
            {"quantity": 1, "grams": 800, "title": "Widget F"},
            {"quantity": 2, "grams": 100, "title": "Gadget G"},
        ],
        "tags": "test,premium",
    },
]

_ALL_ORDERS = {o["id"]: o for o in _ORDERS_PAGE_1 + _ORDERS_PAGE_2}

# --- FastMCP Server ---

mcp = FastMCP("DummyPlatform")

# Process-scoped state
_connected = False
_credential_ref: str | None = None


@mcp.tool(name="platform.health")
async def health() -> dict:
    """Return health status for the DummyPlatform."""
    return {
        "ok": True,
        "platform_id": PLATFORM_ID,
        "server_version": SERVER_VERSION,
        "contract_version": CONTRACT_VERSION,
        "api_reachable": True,
        "auth_valid": _connected,
    }


@mcp.tool(name="platform.capabilities")
async def capabilities() -> dict:
    """Return capabilities for the DummyPlatform."""
    return {
        "platform_id": PLATFORM_ID,
        "contract_version": CONTRACT_VERSION,
        "supports": ["orders.list", "orders.get", "tracking.write_back"],
        "limits": {"rate_limit_per_second": 100, "max_concurrency": 10},
        "paging": {
            "strategy": "cursor",
            "default_page_size": 3,
            "max_page_size": 3,
            "overlap_seconds": 0,
        },
    }


@mcp.tool(name="auth.connect")
async def auth_connect(credential_ref: str = "test") -> dict:
    """Simulate connecting to the DummyPlatform (always succeeds)."""
    global _connected, _credential_ref
    _connected = True
    _credential_ref = credential_ref
    return {
        "ok": True,
        "platform_id": PLATFORM_ID,
        "credential_ref": credential_ref,
        "account_label": "dummy-test-store",
    }


@mcp.tool(name="auth.disconnect")
async def auth_disconnect() -> dict:
    """Simulate disconnecting from the DummyPlatform."""
    global _connected, _credential_ref
    _connected = False
    _credential_ref = None
    return {"ok": True, "platform_id": PLATFORM_ID}


@mcp.tool(name="orders.list")
async def orders_list(
    cursor: str | None = None,
    since: str | None = None,
    page_size: int = 3,
) -> dict:
    """Return a page of dummy orders.

    Page 1 (no cursor or cursor != 'page2'): 3 orders, next_cursor='page2'.
    Page 2 (cursor='page2'): 3 orders, next_cursor=None.
    """
    if cursor == "page2":
        items = _ORDERS_PAGE_2
        next_cursor = None
        watermark = "2026-02-25T10:00:00Z"
    else:
        items = _ORDERS_PAGE_1
        next_cursor = "page2"
        watermark = "2026-02-22T10:00:00Z"

    return {
        "items": items,
        "next_cursor": next_cursor,
        "watermark": watermark,
    }


@mcp.tool(name="orders.get")
async def orders_get(order_id: str) -> dict:
    """Return a single dummy order by ID."""
    order = _ALL_ORDERS.get(order_id)
    if order is None:
        return {"error": f"Order {order_id} not found"}
    return {"order": order}


@mcp.tool(name="tracking.write_back")
async def tracking_write_back(
    order_id: str,
    tracking_numbers: list[str],
    carrier: str = "UPS",
    tracking_url: str | None = None,
) -> dict:
    """Simulate writing back tracking numbers (no-op success)."""
    return {
        "ok": True,
        "order_id": order_id,
        "tracking_numbers": tracking_numbers,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
