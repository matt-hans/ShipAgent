# Amazon SP-API Full Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring Amazon Selling Partner API integration to full parity with Shopify — order items fetching, line-item enrichment, tracking write-back via confirmShipment, env-status endpoint, and frontend DataSourcePanel visibility.

**Architecture:** Extend the existing `AmazonClient` (PlatformClient subclass) with `_fetch_order_items()` for per-order item enrichment, `update_tracking()` via SP-API `confirmShipment`, and `get_shop_info()` for seller metadata. Add `GET /platforms/amazon/env-status` API route. Add Amazon card to frontend `DataSourcePanel` sidebar with activate/status UI.

**Tech Stack:** Python 3.12 (httpx, asyncio, pydantic), FastAPI, React/TypeScript, SP-API Orders v0 + Sellers v1

**Design Doc:** `docs/plans/2026-02-28-amazon-spapi-full-parity-design.md`

---

### Task 1: AmazonClient — Order Items Fetching

**Files:**
- Modify: `src/mcp/external_sources/clients/amazon.py`
- Test: `tests/mcp/external_sources/test_amazon_client.py` (create)

**Step 1: Write the failing test for `_fetch_order_items`**

Create `tests/mcp/external_sources/test_amazon_client.py`:

```python
"""Test Amazon SP-API client implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp.external_sources.clients.amazon import AmazonClient
from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import ExternalOrder, OrderFilters


class TestAmazonClientInit:
    """Test AmazonClient initialization."""

    def test_extends_platform_client(self):
        assert issubclass(AmazonClient, PlatformClient)

    def test_platform_name(self):
        client = AmazonClient()
        assert client.platform_name == "amazon"


class TestFetchOrderItems:
    """Test _fetch_order_items method."""

    @pytest.mark.asyncio
    async def test_fetch_order_items_success(self):
        """Fetches items from SP-API and returns list of item dicts."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "payload": {
                "OrderItems": [
                    {
                        "OrderItemId": "item-1",
                        "Title": "Widget A",
                        "QuantityOrdered": 2,
                        "ItemPrice": {"Amount": "19.99", "CurrencyCode": "USD"},
                        "SellerSKU": "SKU-001",
                        "ASIN": "B00TEST123",
                        "ProductInfo": {"NumberOfItems": "1"},
                    },
                    {
                        "OrderItemId": "item-2",
                        "Title": "Widget B",
                        "QuantityOrdered": 1,
                        "ItemPrice": {"Amount": "9.99", "CurrencyCode": "USD"},
                        "SellerSKU": "SKU-002",
                        "ASIN": "B00TEST456",
                    },
                ]
            }
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            items = await client._fetch_order_items("ORDER-123")

        assert len(items) == 2
        assert items[0]["OrderItemId"] == "item-1"
        assert items[1]["SellerSKU"] == "SKU-002"

    @pytest.mark.asyncio
    async def test_fetch_order_items_not_authenticated(self):
        """Returns empty list when not authenticated."""
        client = AmazonClient()
        client._authenticated = False

        items = await client._fetch_order_items("ORDER-123")
        assert items == []

    @pytest.mark.asyncio
    async def test_fetch_order_items_api_error(self):
        """Returns empty list on API error."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0

        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            items = await client._fetch_order_items("ORDER-123")

        assert items == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestFetchOrderItems -v`
Expected: FAIL with `AttributeError: 'AmazonClient' object has no attribute '_fetch_order_items'`

**Step 3: Implement `_fetch_order_items` in AmazonClient**

In `src/mcp/external_sources/clients/amazon.py`, add after `_get_access_token`:

```python
async def _fetch_order_items(self, order_id: str) -> list[dict[str, Any]]:
    """Fetch order items from SP-API getOrderItems endpoint.

    Args:
        order_id: Amazon order ID.

    Returns:
        List of raw order item dicts from SP-API. Empty on failure.
    """
    if not self._authenticated:
        return []

    token = await self._get_access_token()
    if not token:
        return []

    headers = {
        "x-amz-access-token": token,
        "content-type": "application/json",
    }

    all_items: list[dict[str, Any]] = []
    next_token: str | None = None

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                params: dict[str, str] = {}
                if next_token:
                    params["NextToken"] = next_token

                response = await client.get(
                    f"{self._base_url()}/orders/v0/orders/{order_id}/orderItems",
                    headers=headers,
                    params=params,
                )

                if response.status_code != 200:
                    break

                payload = response.json().get("payload", {})
                items = payload.get("OrderItems", [])
                all_items.extend(items)

                next_token = payload.get("NextToken")
                if not next_token:
                    break
    except Exception:
        return []

    return all_items
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestFetchOrderItems -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add tests/mcp/external_sources/test_amazon_client.py src/mcp/external_sources/clients/amazon.py
git commit -m "feat(amazon): add _fetch_order_items for SP-API order item retrieval"
```

---

### Task 2: AmazonClient — Enriched Order Normalization

**Files:**
- Modify: `src/mcp/external_sources/clients/amazon.py`
- Modify: `tests/mcp/external_sources/test_amazon_client.py`

**Step 1: Write the failing test for enriched normalization**

Append to `tests/mcp/external_sources/test_amazon_client.py`:

```python
class TestNormalizeOrderWithItems:
    """Test _normalize_order with item enrichment."""

    def test_normalize_with_items_populates_fields(self):
        """Items are normalized into ExternalOrder.items with enrichment."""
        client = AmazonClient()
        client._marketplace_id = "ATVPDKIKX0DER"

        order = {
            "AmazonOrderId": "111-1234567-1234567",
            "PurchaseDate": "2026-02-28T10:00:00Z",
            "OrderStatus": "Unshipped",
            "OrderTotal": {"Amount": "49.97", "CurrencyCode": "USD"},
            "FulfillmentChannel": "MFN",
            "ShippingAddress": {
                "Name": "Jane Doe",
                "AddressLine1": "123 Main St",
                "City": "Springfield",
                "StateOrRegion": "IL",
                "PostalCode": "62701",
                "CountryCode": "US",
            },
            "BuyerInfo": {"BuyerEmail": "jane@example.com"},
            "ShipmentServiceLevelCategory": "Standard",
            "NumberOfItemsShipped": 0,
            "NumberOfItemsUnshipped": 3,
        }

        items = [
            {
                "OrderItemId": "item-1",
                "Title": "Widget A",
                "QuantityOrdered": 2,
                "ItemPrice": {"Amount": "19.99", "CurrencyCode": "USD"},
                "SellerSKU": "SKU-001",
                "ASIN": "B00TEST123",
                "ItemWeight": {"Value": "200", "Unit": "Grams"},
                "ProductInfo": {"NumberOfItems": "1"},
            },
            {
                "OrderItemId": "item-2",
                "Title": "Widget B",
                "QuantityOrdered": 1,
                "ItemPrice": {"Amount": "9.99", "CurrencyCode": "USD"},
                "SellerSKU": "SKU-002",
                "ASIN": "B00TEST456",
                "ItemWeight": {"Value": "0.5", "Unit": "Pounds"},
            },
        ]

        result = client._normalize_order(order, items)

        assert isinstance(result, ExternalOrder)
        assert result.platform == "amazon"
        assert result.order_id == "111-1234567-1234567"
        assert len(result.items) == 2
        assert result.items[0]["id"] == "item-1"
        assert result.items[0]["sku"] == "SKU-001"
        assert result.items[0]["asin"] == "B00TEST123"
        assert result.items[0]["quantity"] == 2
        assert result.item_count == 3  # 2 + 1
        # Weight: (200g * 2) + (0.5 lb * 453.592 * 1) = 400 + 226.796 = ~626.8
        assert result.total_weight_grams is not None
        assert abs(result.total_weight_grams - 626.796) < 1.0

    def test_normalize_without_items_backward_compatible(self):
        """Passing no items preserves existing behavior."""
        client = AmazonClient()
        client._marketplace_id = "ATVPDKIKX0DER"

        order = {
            "AmazonOrderId": "222-1234567-1234567",
            "PurchaseDate": "2026-02-28T10:00:00Z",
            "OrderStatus": "Shipped",
            "FulfillmentChannel": "AFN",
            "ShippingAddress": {"Name": "Test", "AddressLine1": "456 Elm", "City": "Austin", "StateOrRegion": "TX", "PostalCode": "73301", "CountryCode": "US"},
            "BuyerInfo": {},
            "NumberOfItemsShipped": 2,
            "NumberOfItemsUnshipped": 0,
        }

        result = client._normalize_order(order)
        assert result.items == []
        assert result.item_count == 2  # fallback to shipped + unshipped
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestNormalizeOrderWithItems -v`
Expected: FAIL (signature mismatch — `_normalize_order` doesn't accept items param)

**Step 3: Update `_normalize_order` signature and implementation**

In `src/mcp/external_sources/clients/amazon.py`, update `_normalize_order`:

```python
# Weight unit conversion factors to grams
_WEIGHT_TO_GRAMS: dict[str, float] = {
    "grams": 1.0,
    "g": 1.0,
    "kilograms": 1000.0,
    "kg": 1000.0,
    "ounces": 28.3495,
    "oz": 28.3495,
    "pounds": 453.592,
    "lb": 453.592,
    "lbs": 453.592,
}

def _normalize_order(
    self, order: dict[str, Any], items: list[dict[str, Any]] | None = None
) -> ExternalOrder:
```

Inside the method body, replace the `items=[]` and enrichment section with:

```python
    # Normalize line items when available
    normalized_items: list[dict[str, Any]] = []
    total_weight_grams: float | None = None
    item_count: int | None = None

    if items:
        weight_sum = 0.0
        has_weight = False
        qty_sum = 0

        for item in items:
            qty = int(item.get("QuantityOrdered") or 1)
            qty_sum += qty
            price_info = item.get("ItemPrice") or {}

            normalized_items.append({
                "id": str(item.get("OrderItemId", "")),
                "title": item.get("Title", ""),
                "quantity": qty,
                "price": str(price_info.get("Amount", "0.00")),
                "sku": item.get("SellerSKU", ""),
                "asin": item.get("ASIN", ""),
            })

            # Weight conversion
            weight_info = item.get("ItemWeight") or {}
            weight_val = weight_info.get("Value")
            weight_unit = str(weight_info.get("Unit", "")).lower().strip()
            if weight_val is not None and weight_unit:
                try:
                    factor = _WEIGHT_TO_GRAMS.get(weight_unit, 1.0)
                    weight_sum += float(weight_val) * factor * qty
                    has_weight = True
                except (ValueError, TypeError):
                    pass

        item_count = qty_sum if qty_sum > 0 else None
        total_weight_grams = weight_sum if has_weight else None
    else:
        # Fallback: approximate item count from order-level fields
        shipped = order.get("NumberOfItemsShipped") or 0
        unshipped = order.get("NumberOfItemsUnshipped") or 0
        item_count = (shipped + unshipped) or None
```

Then in the `ExternalOrder(...)` constructor, replace `items=[]`, `total_weight_grams=None`, and the old `item_count` with:

```python
    items=normalized_items,
    total_weight_grams=total_weight_grams,
    item_count=item_count,
```

Also update all existing callers of `_normalize_order` that don't pass items (they'll use the default `None`).

**Step 4: Run test to verify it passes**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestNormalizeOrderWithItems -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add src/mcp/external_sources/clients/amazon.py tests/mcp/external_sources/test_amazon_client.py
git commit -m "feat(amazon): enrich _normalize_order with item data, weights, and SKUs"
```

---

### Task 3: AmazonClient — Wire Item Fetching into fetch_orders and get_order

**Files:**
- Modify: `src/mcp/external_sources/clients/amazon.py`
- Modify: `tests/mcp/external_sources/test_amazon_client.py`

**Step 1: Write the failing test**

Append to `tests/mcp/external_sources/test_amazon_client.py`:

```python
import asyncio


class TestFetchOrdersWithItems:
    """Test that fetch_orders calls _fetch_order_items for each order."""

    @pytest.mark.asyncio
    async def test_fetch_orders_populates_items(self):
        """fetch_orders fetches items per-order and enriches ExternalOrder."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"
        client._sandbox = False

        orders_response = MagicMock()
        orders_response.status_code = 200
        orders_response.json.return_value = {
            "payload": {
                "Orders": [
                    {
                        "AmazonOrderId": "111-0000001-0000001",
                        "PurchaseDate": "2026-02-28T10:00:00Z",
                        "OrderStatus": "Unshipped",
                        "FulfillmentChannel": "MFN",
                        "ShippingAddress": {
                            "Name": "Test User",
                            "AddressLine1": "1 Main St",
                            "City": "NY",
                            "StateOrRegion": "NY",
                            "PostalCode": "10001",
                            "CountryCode": "US",
                        },
                        "BuyerInfo": {},
                    },
                ],
            }
        }

        mock_items = [
            {"OrderItemId": "i-1", "Title": "Gadget", "QuantityOrdered": 1,
             "SellerSKU": "G-001", "ASIN": "B001"},
        ]

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = orders_response
            with patch.object(
                client, "_fetch_order_items", new_callable=AsyncMock
            ) as mock_fetch_items:
                mock_fetch_items.return_value = mock_items
                # Patch asyncio.sleep to avoid real delay
                with patch("src.mcp.external_sources.clients.amazon.asyncio.sleep", new_callable=AsyncMock):
                    orders = await client.fetch_orders(OrderFilters(limit=10))

        assert len(orders) == 1
        assert orders[0].items[0]["id"] == "i-1"
        assert orders[0].items[0]["sku"] == "G-001"
        mock_fetch_items.assert_called_once_with("111-0000001-0000001")


class TestGetOrderWithItems:
    """Test that get_order calls _fetch_order_items."""

    @pytest.mark.asyncio
    async def test_get_order_populates_items(self):
        """get_order fetches items and enriches the ExternalOrder."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        order_response = MagicMock()
        order_response.status_code = 200
        order_response.json.return_value = {
            "payload": {
                "AmazonOrderId": "222-0000001-0000001",
                "PurchaseDate": "2026-02-28T10:00:00Z",
                "OrderStatus": "Shipped",
                "FulfillmentChannel": "MFN",
                "ShippingAddress": {
                    "Name": "Test",
                    "AddressLine1": "2 Elm St",
                    "City": "LA",
                    "StateOrRegion": "CA",
                    "PostalCode": "90001",
                    "CountryCode": "US",
                },
                "BuyerInfo": {},
            }
        }

        mock_items = [
            {"OrderItemId": "i-99", "Title": "Thing", "QuantityOrdered": 3,
             "SellerSKU": "T-001", "ASIN": "B099"},
        ]

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = order_response
            with patch.object(
                client, "_fetch_order_items", new_callable=AsyncMock
            ) as mock_fetch_items:
                mock_fetch_items.return_value = mock_items
                order = await client.get_order("222-0000001-0000001")

        assert order is not None
        assert order.items[0]["id"] == "i-99"
        assert order.item_count == 3
        mock_fetch_items.assert_called_once_with("222-0000001-0000001")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestFetchOrdersWithItems -v`
Expected: FAIL (fetch_orders doesn't call _fetch_order_items yet)

**Step 3: Wire item fetching into fetch_orders and get_order**

In `src/mcp/external_sources/clients/amazon.py`, add at top:

```python
import asyncio
```

In `fetch_orders()`, after `normalized_orders.append(self._normalize_order(order))`, change to:

```python
                    for order in orders:
                        if filters.status and str(order.get("OrderStatus", "")).lower() != str(filters.status).lower():
                            continue
                        order_id = str(order.get("AmazonOrderId", ""))
                        items = await self._fetch_order_items(order_id)
                        normalized_orders.append(self._normalize_order(order, items))
                        if len(normalized_orders) >= max_results:
                            break
                        # Rate limit: 1 req/sec for getOrderItems
                        await asyncio.sleep(1.0)
```

In `get_order()`, after `return self._normalize_order(payload)`, change to:

```python
            order_id = str(payload.get("AmazonOrderId", ""))
            items = await self._fetch_order_items(order_id)
            return self._normalize_order(payload, items)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py -v`
Expected: All PASSED

**Step 5: Commit**

```bash
git add src/mcp/external_sources/clients/amazon.py tests/mcp/external_sources/test_amazon_client.py
git commit -m "feat(amazon): wire _fetch_order_items into fetch_orders and get_order"
```

---

### Task 4: AmazonClient — Tracking Write-Back via confirmShipment

**Files:**
- Modify: `src/mcp/external_sources/clients/amazon.py`
- Modify: `tests/mcp/external_sources/test_amazon_client.py`

**Step 1: Write the failing test**

Append to `tests/mcp/external_sources/test_amazon_client.py`:

```python
from src.mcp.external_sources.models import TrackingUpdate


class TestUpdateTracking:
    """Test tracking write-back via confirmShipment."""

    @pytest.mark.asyncio
    async def test_update_tracking_with_stored_items(self):
        """Confirms shipment using stored items for orderItems payload."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        # Pre-store items (simulating eager fetch)
        client._order_items_cache = {
            "ORDER-100": [
                {"OrderItemId": "oi-1", "QuantityOrdered": 2},
                {"OrderItemId": "oi-2", "QuantityOrdered": 1},
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"payload": {}}

        update = TrackingUpdate(
            order_id="ORDER-100",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response
            result = await client.update_tracking(update)

        assert result is True
        # Verify the payload sent
        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["marketplaceId"] == "ATVPDKIKX0DER"
        assert body["packageDetail"]["carrierCode"] == "UPS"
        assert body["packageDetail"]["trackingNumber"] == "1Z999AA10123456784"
        assert len(body["packageDetail"]["orderItems"]) == 2

    @pytest.mark.asyncio
    async def test_update_tracking_fallback_fetches_items(self):
        """Falls back to _fetch_order_items when cache misses."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"
        client._order_items_cache = {}  # empty cache

        mock_items = [{"OrderItemId": "oi-9", "QuantityOrdered": 1}]

        mock_response = MagicMock()
        mock_response.status_code = 200

        update = TrackingUpdate(
            order_id="ORDER-200",
            tracking_number="1Z111BB20123456784",
            carrier="UPS",
        )

        with patch.object(
            client, "_fetch_order_items", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = mock_items
            with patch.object(
                httpx.AsyncClient, "post", new_callable=AsyncMock
            ) as mock_post:
                mock_post.return_value = mock_response
                result = await client.update_tracking(update)

        assert result is True
        mock_fetch.assert_called_once_with("ORDER-200")

    @pytest.mark.asyncio
    async def test_update_tracking_not_authenticated(self):
        """Returns False when not authenticated."""
        client = AmazonClient()
        client._authenticated = False

        update = TrackingUpdate(
            order_id="ORDER-300",
            tracking_number="1Z999CC30123456784",
            carrier="UPS",
        )

        result = await client.update_tracking(update)
        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestUpdateTracking -v`
Expected: FAIL (update_tracking still returns False)

**Step 3: Implement update_tracking with confirmShipment**

In `src/mcp/external_sources/clients/amazon.py`, add `_order_items_cache` to `__init__`:

```python
self._order_items_cache: dict[str, list[dict[str, Any]]] = {}
```

In `fetch_orders` and `get_order`, after fetching items, cache them:

```python
# In fetch_orders, after items = await self._fetch_order_items(order_id):
if items:
    self._order_items_cache[order_id] = items

# In get_order, after items = await self._fetch_order_items(order_id):
if items:
    self._order_items_cache[order_id] = items
```

Replace the stub `update_tracking` with:

```python
async def update_tracking(self, update: TrackingUpdate) -> bool:
    """Write tracking number back to Amazon via confirmShipment.

    Uses cached order items when available, falls back to
    _fetch_order_items for a just-in-time retrieval.

    Args:
        update: Tracking update with order_id, tracking_number, carrier.

    Returns:
        True if Amazon accepted the shipment confirmation.
    """
    if not self._authenticated:
        return False

    token = await self._get_access_token()
    if not token:
        return False

    # Resolve order items — cache first, JIT fallback
    raw_items = self._order_items_cache.get(update.order_id)
    if not raw_items:
        raw_items = await self._fetch_order_items(update.order_id)

    if not raw_items:
        return False

    order_items = [
        {
            "orderItemId": str(item.get("OrderItemId", "")),
            "quantity": int(item.get("QuantityOrdered") or 1),
        }
        for item in raw_items
    ]

    from datetime import UTC, datetime

    payload = {
        "marketplaceId": self._marketplace_id,
        "packageDetail": {
            "packageReferenceId": "1",
            "carrierCode": update.carrier,
            "carrierName": update.carrier,
            "trackingNumber": update.tracking_number,
            "shipDate": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orderItems": order_items,
        },
    }

    headers = {
        "x-amz-access-token": token,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self._base_url()}/orders/v0/orders/{update.order_id}/shipment",
                headers=headers,
                json=payload,
            )
        return response.status_code in (200, 204)
    except Exception:
        return False
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py -v`
Expected: All PASSED

**Step 5: Commit**

```bash
git add src/mcp/external_sources/clients/amazon.py tests/mcp/external_sources/test_amazon_client.py
git commit -m "feat(amazon): implement tracking write-back via confirmShipment"
```

---

### Task 5: AmazonClient — get_shop_info (Seller Metadata)

**Files:**
- Modify: `src/mcp/external_sources/clients/amazon.py`
- Modify: `tests/mcp/external_sources/test_amazon_client.py`

**Step 1: Write the failing test**

Append to `tests/mcp/external_sources/test_amazon_client.py`:

```python
class TestGetShopInfo:
    """Test get_shop_info for seller metadata."""

    @pytest.mark.asyncio
    async def test_get_shop_info_returns_marketplace_data(self):
        """Returns marketplace participation metadata."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "payload": [
                {
                    "marketplace": {
                        "id": "ATVPDKIKX0DER",
                        "name": "Amazon.com",
                        "countryCode": "US",
                    },
                    "participation": {
                        "isParticipating": True,
                    },
                },
            ]
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.get_shop_info()

        assert result is not None
        assert result["name"] == "Amazon.com"
        assert result["marketplace_id"] == "ATVPDKIKX0DER"

    @pytest.mark.asyncio
    async def test_get_shop_info_not_authenticated(self):
        """Returns None when not authenticated."""
        client = AmazonClient()
        client._authenticated = False

        result = await client.get_shop_info()
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py::TestGetShopInfo -v`
Expected: FAIL (no `get_shop_info` method)

**Step 3: Implement get_shop_info**

Add to `AmazonClient`:

```python
async def get_shop_info(self) -> dict[str, Any] | None:
    """Fetch seller marketplace participation metadata.

    Returns:
        Dict with name, marketplace_id, country_code, or None on failure.
    """
    if not self._authenticated:
        return None

    token = await self._get_access_token()
    if not token:
        return None

    headers = {
        "x-amz-access-token": token,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self._base_url()}/sellers/v1/marketplaceParticipations",
                headers=headers,
            )

        if response.status_code != 200:
            return None

        participations = response.json().get("payload", [])
        if not participations:
            return None

        # Find matching marketplace or use first
        for p in participations:
            marketplace = p.get("marketplace", {})
            if marketplace.get("id") == self._marketplace_id:
                return {
                    "name": marketplace.get("name", "Amazon Seller"),
                    "marketplace_id": marketplace.get("id", ""),
                    "country_code": marketplace.get("countryCode", ""),
                }

        # Fallback to first participation
        first = participations[0].get("marketplace", {})
        return {
            "name": first.get("name", "Amazon Seller"),
            "marketplace_id": first.get("id", ""),
            "country_code": first.get("countryCode", ""),
        }
    except Exception:
        return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp/external_sources/test_amazon_client.py -v`
Expected: All PASSED

**Step 5: Commit**

```bash
git add src/mcp/external_sources/clients/amazon.py tests/mcp/external_sources/test_amazon_client.py
git commit -m "feat(amazon): add get_shop_info for seller marketplace metadata"
```

---

### Task 6: API Route — Amazon env-status Endpoint

**Files:**
- Modify: `src/api/routes/platforms.py`
- Modify: `tests/api/routes/test_platforms_mcp.py`

**Step 1: Write the failing test**

Append to `tests/api/routes/test_platforms_mcp.py`:

```python
class TestAmazonEnvStatus:
    """Tests for GET /platforms/amazon/env-status."""

    @patch("src.api.routes.platforms.resolve_amazon_credentials")
    def test_env_status_not_configured(self, mock_resolve):
        """Returns configured=False when no credentials found."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        mock_resolve.return_value = None

        client = TestClient(app)
        response = client.get("/api/v1/platforms/amazon/env-status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["valid"] is False

    @patch("src.api.routes.platforms.get_external_sources_client")
    @patch("src.api.routes.platforms.resolve_amazon_credentials")
    @pytest.mark.asyncio
    async def test_env_status_configured_and_valid(self, mock_resolve, mock_get_ext):
        """Returns configured=True, valid=True when credentials work."""
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.services.runtime_credentials import AmazonSPAPICredentials

        mock_resolve.return_value = AmazonSPAPICredentials(
            client_id="test-id",
            client_secret="test-secret",
            refresh_token="test-token",
            marketplace_id="ATVPDKIKX0DER",
            sandbox=False,
        )

        mock_ext = AsyncMock()
        mock_ext.validate_credentials = AsyncMock(return_value={
            "valid": True,
            "platform": "amazon",
            "shop": {"name": "Amazon.com", "marketplace_id": "ATVPDKIKX0DER"},
        })
        mock_get_ext.return_value = mock_ext

        client = TestClient(app)
        response = client.get("/api/v1/platforms/amazon/env-status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["seller_name"] == "Amazon.com"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/routes/test_platforms_mcp.py::TestAmazonEnvStatus -v`
Expected: FAIL (404 — endpoint doesn't exist yet)

**Step 3: Add the endpoint and schema**

In `src/api/routes/platforms.py`, add the import (near existing imports):

```python
from src.services.runtime_credentials import resolve_amazon_credentials
```

Add the response schema after `ShopifyEnvStatusResponse`:

```python
class AmazonEnvStatusResponse(BaseModel):
    """Response from Amazon environment status check."""

    configured: bool = Field(
        ..., description="True if Amazon SP-API credentials are configured"
    )
    valid: bool = Field(..., description="True if credentials validated against Amazon API")
    marketplace_id: str | None = Field(None, description="Amazon marketplace ID")
    seller_name: str | None = Field(None, description="Seller/marketplace name from Amazon")
    error: str | None = Field(None, description="Error message if validation failed")
```

Rename `ShopifyActivateResponse` to `PlatformActivateResponse` and update references (both `activate_shopify` and `activate_amazon` routes).

Add the endpoint after the existing `get_shopify_env_status` route:

```python
@router.get("/amazon/env-status", response_model=AmazonEnvStatusResponse)
async def get_amazon_env_status() -> AmazonEnvStatusResponse:
    """Check Amazon credentials via runtime_credentials adapter.

    Resolves Amazon credentials (DB priority, env fallback) and validates
    via the gateway's read-only validate_credentials tool.

    Returns:
        Status indicating whether credentials are configured and valid.
    """
    amazon_creds = resolve_amazon_credentials()
    if amazon_creds is None:
        return AmazonEnvStatusResponse(
            configured=False,
            valid=False,
            marketplace_id=None,
            seller_name=None,
            error="No Amazon credentials configured. Connect Amazon in Settings.",
        )

    try:
        ext = await get_external_sources_client()
        result = await ext.validate_credentials(
            platform="amazon",
            credentials={
                "client_id": amazon_creds.client_id,
                "client_secret": amazon_creds.client_secret,
                "refresh_token": amazon_creds.refresh_token,
                "marketplace_id": amazon_creds.marketplace_id,
                "sandbox": amazon_creds.sandbox,
            },
        )

        if not result.get("valid"):
            return AmazonEnvStatusResponse(
                configured=True,
                valid=False,
                marketplace_id=amazon_creds.marketplace_id,
                seller_name=None,
                error=result.get("error", "Authentication failed - check credentials"),
            )

        shop = result.get("shop") or {}
        seller_name = shop.get("name") if isinstance(shop, dict) else None

        return AmazonEnvStatusResponse(
            configured=True,
            valid=True,
            marketplace_id=amazon_creds.marketplace_id,
            seller_name=seller_name,
            error=None,
        )

    except Exception as e:
        return AmazonEnvStatusResponse(
            configured=True,
            valid=False,
            marketplace_id=amazon_creds.marketplace_id,
            seller_name=None,
            error=str(e),
        )
```

**Important ordering note:** The `GET /amazon/env-status` route must be defined BEFORE the parameterized `GET /{platform}/orders` route, otherwise FastAPI will match `amazon` as a platform parameter to the wrong handler.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/api/routes/test_platforms_mcp.py -v`
Expected: All PASSED

**Step 5: Commit**

```bash
git add src/api/routes/platforms.py tests/api/routes/test_platforms_mcp.py
git commit -m "feat(api): add GET /platforms/amazon/env-status endpoint"
```

---

### Task 7: Frontend — TypeScript Types and API Client

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add `'amazon'` to `PlatformType` union**

In `frontend/src/types/api.ts` line 451, change:

```typescript
export type PlatformType = 'shopify' | 'amazon' | 'woocommerce' | 'sap' | 'oracle';
```

Add `AmazonEnvStatus` interface after `ShopifyEnvStatus` (around line 718):

```typescript
/** Amazon environment status response. */
export interface AmazonEnvStatus {
  /** True if Amazon SP-API credentials are configured */
  configured: boolean;
  /** True if credentials validated against Amazon API */
  valid: boolean;
  /** Amazon marketplace ID */
  marketplace_id: string | null;
  /** Seller/marketplace name from Amazon */
  seller_name: string | null;
  /** Error message if validation failed */
  error: string | null;
}
```

**Step 2: Add API functions**

In `frontend/src/lib/api.ts`, after the `activateShopify` function, add:

```typescript
/**
 * Activate Amazon as the active data source.
 *
 * Performs backend connect + fetch + import in a single call.
 *
 * @returns Activation result with row count and column info.
 */
export async function activateAmazon(): Promise<{
  success: boolean;
  row_count: number;
  source_type: string | null;
  columns: Array<Record<string, unknown>>;
  error: string | null;
}> {
  const response = await fetch(`${getApiBase()}/platforms/amazon/activate`, {
    method: 'POST',
  });
  return parseResponse(response);
}
```

After `getShopifyEnvStatus`, add:

```typescript
/**
 * Check Amazon credentials from environment/DB.
 *
 * Validates SP-API credentials and returns configuration status.
 *
 * @returns Status indicating whether credentials are configured and valid.
 */
export async function getAmazonEnvStatus(): Promise<AmazonEnvStatus> {
  const response = await fetch(`${getApiBase()}/platforms/amazon/env-status`);
  return parseResponse<AmazonEnvStatus>(response);
}
```

Add the import for `AmazonEnvStatus` at the top of api.ts where other types are imported.

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): add Amazon types, activateAmazon, getAmazonEnvStatus API functions"
```

---

### Task 8: Frontend — useExternalSources Amazon Polling

**Files:**
- Modify: `frontend/src/hooks/useExternalSources.ts`

**Step 1: Add `'amazon'` to ALL_PLATFORMS**

In `frontend/src/hooks/useExternalSources.ts` line 102:

```typescript
const ALL_PLATFORMS: PlatformType[] = ['shopify', 'amazon', 'woocommerce', 'sap', 'oracle'];
```

**Step 2: Add amazon to INITIAL_PLATFORMS in refresh()**

In the `refresh` callback (~line 183), add `amazon`:

```typescript
const newPlatforms: Record<PlatformType, PlatformState> = {
  shopify: { ...initialPlatformState },
  amazon: { ...initialPlatformState },
  woocommerce: { ...initialPlatformState },
  sap: { ...initialPlatformState },
  oracle: { ...initialPlatformState },
};
```

**Step 3: Add Amazon env-status state and check**

Add to `ExternalSourcesState` interface:

```typescript
/** Amazon environment status (auto-detected credentials). */
amazonEnvStatus: AmazonEnvStatus | null;
/** True while checking Amazon environment status. */
isCheckingAmazonEnv: boolean;
```

Add to `UseExternalSourcesReturn` interface:

```typescript
/** Check Amazon environment status. */
checkAmazonEnv: () => Promise<AmazonEnvStatus | null>;
```

Import `getAmazonEnvStatus` and `AmazonEnvStatus` type.

Initialize state with `amazonEnvStatus: null, isCheckingAmazonEnv: false`.

Add `checkAmazonEnv` callback (mirror `checkShopifyEnv` pattern):

```typescript
const checkAmazonEnv = useCallback(async (): Promise<AmazonEnvStatus | null> => {
  setState((prev) => ({ ...prev, isCheckingAmazonEnv: true }));

  try {
    const status = await getAmazonEnvStatus();
    setState((prev) => ({
      ...prev,
      amazonEnvStatus: status,
      isCheckingAmazonEnv: false,
    }));

    if (status.valid) {
      updatePlatformState('amazon', {
        connection: {
          platform: 'amazon',
          store_url: null,
          status: 'connected',
          last_connected: new Date().toISOString(),
          error_message: null,
        },
      });
    }

    return status;
  } catch (err) {
    setState((prev) => ({
      ...prev,
      amazonEnvStatus: {
        configured: false,
        valid: false,
        marketplace_id: null,
        seller_name: null,
        error: err instanceof Error ? err.message : 'Failed to check Amazon env',
      },
      isCheckingAmazonEnv: false,
    }));
    return null;
  }
}, [updatePlatformState]);
```

Add `useEffect` to check on mount (same as Shopify):

```typescript
useEffect(() => {
  checkAmazonEnv();
}, [checkAmazonEnv]);
```

Add `checkAmazonEnv` to the return object.

**Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/hooks/useExternalSources.ts
git commit -m "feat(frontend): add Amazon env-status polling to useExternalSources"
```

---

### Task 9: Frontend — DataSourcePanel Amazon Card

**Files:**
- Modify: `frontend/src/components/sidebar/DataSourcePanel.tsx`

**Step 1: Add Amazon imports and state**

At top of file, add import:

```typescript
import { AmazonIcon } from '@/components/ui/brand-icons';
import {
  disconnectDataSource,
  importDataSource,
  uploadDataSource,
  getSavedDataSources,
  reconnectSavedSource,
  getDataSourceStatus,
  activateShopify,
  activateAmazon,
} from '@/lib/api';
```

After the Shopify availability section (~line 69), add Amazon availability:

```typescript
// Amazon availability derived from provider connections
const amazonConnection = providerConnections.find(
  (c) => c.provider === 'amazon' && c.runtime_usable
);
const amazonAvailable = !!amazonConnection;

const amazonEnvStatus = externalState.amazonEnvStatus;
const isCheckingAmazonEnv = externalState.isCheckingAmazonEnv;
const amazonEnvConnected = amazonEnvStatus?.valid === true;
const amazonSellerName = amazonConnection?.display_name
  || amazonEnvStatus?.seller_name
  || (amazonEnvStatus?.marketplace_id ? `Marketplace ${amazonEnvStatus.marketplace_id}` : null);
```

**Step 2: Update derived source effect**

In the `useEffect` that derives active source (~line 122), add Amazon:

```typescript
} else if (backendSourceType === 'amazon') {
  setActiveSourceType('amazon');
  setActiveSourceInfo({
    type: 'amazon',
    label: 'Amazon',
    detail: amazonSellerName || 'Connected',
    sourceKind: 'amazon',
  });
}
```

Add `amazonSellerName` to the dependency array.

**Step 3: Add handleSwitchToAmazon handler**

After `handleSwitchToShopify`:

```typescript
/** Switch to Amazon: activate Amazon first, then clear local source on success. */
const handleSwitchToAmazon = async () => {
  setImportError(null);
  setIsConnecting(true);
  try {
    const result = await activateAmazon();
    if (!result.success) {
      setImportError(result.error || 'Failed to activate Amazon');
      return;
    }
    if (dataSource) {
      setCachedLocalConfig({
        type: dataSource.type as 'csv' | 'excel' | 'database',
        file_path: dataSource.csv_path || dataSource.excel_path,
      });
    }
    setDataSource(null);
    setBackendSourceType('amazon');
  } catch (err) {
    setImportError(err instanceof Error ? err.message : 'Failed to activate Amazon');
  } finally {
    setIsConnecting(false);
  }
};

const isAmazonActive = activeSourceType === 'amazon';
```

**Step 4: Add Amazon card JSX**

After the Shopify card closing `)}` and before the Local Data Source Card, add the Amazon card. Follow the exact same pattern as the Shopify card, using `AmazonIcon`, `#FF9900` color, `amazonAvailable || amazonEnvConnected`, `isAmazonActive`, `amazonSellerName`, `handleSwitchToAmazon`, and `isCheckingAmazonEnv`.

```tsx
{/* === AMAZON CARD === */}
{(amazonAvailable || amazonEnvConnected) ? (
  <div className={cn(
    'rounded-lg border overflow-hidden transition-colors',
    isAmazonActive && interactiveShipping
      ? 'border-l-4 border-l-slate-500 border-slate-600/30 bg-slate-800/20'
      : isAmazonActive
        ? 'border-l-4 border-l-[#FF9900] border-[#FF9900]/30 bg-[#FF9900]/5'
        : 'border-slate-800'
  )}>
    <div className="flex items-center justify-between p-2.5 bg-slate-800/30">
      <div className="flex items-center gap-2">
        <AmazonIcon className="w-5 h-5 text-[#FF9900]" />
        <span className="text-xs font-medium text-slate-200">Amazon</span>
      </div>
      <div className="flex items-center gap-2">
        {isCheckingAmazonEnv ? (
          <span className="text-[10px] font-mono text-slate-500">Checking...</span>
        ) : isAmazonActive && interactiveShipping ? (
          <span className="badge badge-neutral text-[9px]">STANDBY</span>
        ) : isAmazonActive ? (
          <span className="badge badge-success text-[9px]">ACTIVE</span>
        ) : (
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
            <span className="text-[10px] font-mono text-slate-500">Available</span>
          </span>
        )}
      </div>
    </div>

    {isAmazonActive && (
      <div className={cn('p-2.5 border-t', interactiveShipping ? 'border-slate-700' : 'border-[#FF9900]/20')}>
        <p className="text-xs text-slate-300">
          {amazonSellerName}
        </p>
        <p className="text-[10px] font-mono text-slate-500 mt-0.5">
          {interactiveShipping ? 'Available in batch mode' : 'Connected'}
        </p>
      </div>
    )}

    {!isAmazonActive && (
      <div className="p-2.5 border-t border-slate-800">
        <p className="text-[10px] text-slate-500 mb-2">
          {amazonSellerName}
        </p>
        <button
          onClick={handleSwitchToAmazon}
          disabled={isConnecting}
          className="w-full py-1.5 text-xs font-medium rounded border border-[#FF9900]/40 text-[#FF9900] hover:bg-[#FF9900]/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isConnecting ? 'Activating...' : 'Use Amazon'}
        </button>
      </div>
    )}
  </div>
) : (
  <div className="rounded-lg border border-slate-800 overflow-hidden">
    <div className="flex items-center justify-between p-2.5 bg-slate-800/30">
      <div className="flex items-center gap-2">
        <AmazonIcon className="w-5 h-5 text-[#FF9900]/50" />
        <span className="text-xs font-medium text-slate-400">Amazon</span>
      </div>
      <span className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
        <span className="text-[10px] font-mono text-slate-500">Not configured</span>
      </span>
    </div>
    <div className="p-2.5 border-t border-slate-800">
      <button
        onClick={() => setSettingsFlyoutOpen(true)}
        className="text-[10px] font-medium text-[#FF9900] hover:underline"
      >
        Connect Amazon in Settings →
      </button>
    </div>
  </div>
)}
```

**Step 5: Verify TypeScript compiles and dev server renders**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 6: Commit**

```bash
git add frontend/src/components/sidebar/DataSourcePanel.tsx
git commit -m "feat(frontend): add Amazon card to DataSourcePanel sidebar"
```

---

### Task 10: Run Full Test Suite and Fix Any Regressions

**Files:**
- All modified files

**Step 1: Run backend tests**

Run: `pytest tests/mcp/external_sources/ -v`
Expected: All PASSED (including new Amazon tests)

**Step 2: Run platform route tests**

Run: `pytest tests/api/routes/test_platforms_mcp.py -v`
Expected: All PASSED

**Step 3: Run agent tool tests**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream"`
Expected: All PASSED (connect_amazon_tool and get_platform_status unchanged)

**Step 4: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Run full test suite (excluding known hanging tests)**

Run: `pytest -k "not test_stream_endpoint_exists and not stream and not sse and not progress" --tb=short -q`
Expected: All PASSED (may see known EDI collection errors)

**Step 6: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: resolve test regressions from Amazon parity changes"
```
