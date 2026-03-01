# Amazon SP-API Full Parity Design

**Date:** 2026-02-28
**Status:** Approved

## Goal

Bring Amazon Selling Partner API integration to full parity with Shopify: order items fetching, line-item enrichment, tracking write-back via confirmShipment, env-status endpoint, and frontend DataSourcePanel visibility.

## Current State

The Amazon integration already has:
- `AmazonClient` (`clients/amazon.py`) — LWA OAuth, `fetch_orders`, `get_order`, `_normalize_order`
- `PlatformType.AMAZON` in models
- `_create_platform_client("amazon")` in MCP tools
- `amazon_activation_service.py` — full activation flow
- `resolve_amazon_credentials()` — DB + env fallback
- `connect_amazon_tool` — agent tool registered
- `POST /platforms/amazon/activate` — REST endpoint
- `AmazonConnectForm.tsx` — full credential form UI

## Gaps to Close

1. **Order items** — `getOrderItems` endpoint never called; `items: []` always empty
2. **Tracking write-back** — `update_tracking()` returns `False` (stub)
3. **Line-item enrichment** — No weight, SKU, product type data from items
4. **Env-status endpoint** — No `GET /platforms/amazon/env-status`
5. **Frontend DataSourcePanel** — Amazon not shown as a source option in sidebar
6. **Seller metadata** — No `get_shop_info()` on AmazonClient

## Design

### 1. AmazonClient Enhancements (`src/mcp/external_sources/clients/amazon.py`)

#### Order Items Fetching

New method `_fetch_order_items(order_id: str) -> list[dict]`:
- Calls `GET /orders/v0/orders/{orderId}/orderItems`
- Returns list of order item dicts
- Handles pagination via `NextToken`

Called from both `fetch_orders()` and `get_order()`. For `fetch_orders()`, items are fetched sequentially with 1-second `asyncio.sleep()` spacing between orders to respect SP-API rate limits (1 req/sec burst on getOrderItems).

#### Normalization Enrichment

`_normalize_order()` updated to accept items list and populate:
- `ExternalOrder.items` — `[{id, title, quantity, price, sku, asin}]`
- `total_weight_grams` — sum of `item.Weight.Value * quantity`, converted from item weight units to grams
- `line_item_types` — distinct product types, comma-separated
- `item_count` — sum of quantities (replaces current approximation)

#### Tracking Write-back

`update_tracking()` implemented using `PUT /orders/v0/orders/{orderId}/shipment`:

```python
{
    "marketplaceId": self._marketplace_id,
    "packageDetail": {
        "packageReferenceId": "1",
        "carrierCode": "UPS",
        "carrierName": "UPS",
        "trackingNumber": update.tracking_number,
        "shipDate": datetime.now(UTC).isoformat(),
        "orderItems": [
            {"orderItemId": item["id"], "quantity": item["quantity"]}
            for item in stored_items
        ]
    }
}
```

Items sourced from stored `ExternalOrder.items`. Fallback: if items unavailable, do a just-in-time `_fetch_order_items()` call.

#### Seller Info

New method `get_shop_info() -> dict | None`:
- Calls `GET /sellers/v1/marketplaceParticipations`
- Returns marketplace participation metadata (seller name, marketplace info)
- Used by `validate_credentials` MCP tool and env-status endpoint

### 2. API Routes (`src/api/routes/platforms.py`)

#### New Endpoint: `GET /platforms/amazon/env-status`

Mirrors Shopify's pattern:
1. Calls `resolve_amazon_credentials()` for configuration check
2. If configured, calls `ext.validate_credentials(platform="amazon", credentials={...})` (read-only)
3. Returns `AmazonEnvStatusResponse`

```python
class AmazonEnvStatusResponse(BaseModel):
    configured: bool
    valid: bool
    marketplace_id: str | None = None
    seller_name: str | None = None
    error: str | None = None
```

#### Schema Rename

`ShopifyActivateResponse` renamed to `PlatformActivateResponse` — used by both Shopify and Amazon activate endpoints.

### 3. Frontend

#### DataSourcePanel.tsx

Add Amazon as a platform source option (parallel to Shopify):
- Import `AmazonIcon` from brand-icons
- Derive `amazonConnection` from `providerConnections.filter(c => c.provider === 'amazon' && c.runtime_usable)`
- Add `handleSwitchToAmazon()` calling `activateAmazon()` API
- Add Amazon card UI with status badges (Connected, Inactive, connect prompt)
- Track `isAmazonActive` from `backendSourceType === 'amazon'`

#### api.ts

- `activateAmazon()` — `POST /platforms/amazon/activate`
- `getAmazonEnvStatus()` — `GET /platforms/amazon/env-status`

#### useExternalSources.ts

Add Amazon env-status polling alongside Shopify.

### 4. Testing

| Test File | Coverage |
|-----------|----------|
| `tests/mcp/external_sources/test_amazon_client.py` | `_fetch_order_items()`, enriched `_normalize_order()`, `update_tracking()` confirmShipment, rate limit spacing, token refresh |
| `tests/api/routes/test_platforms_amazon.py` | `GET /platforms/amazon/env-status` (configured/valid/error), `POST /platforms/amazon/activate` (success/failure) |
| `tests/services/test_amazon_activation_service.py` | Extend for items enrichment |
| Existing tool tests | `get_platform_status_tool` Amazon reporting |

### 5. Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Items fetch timing | Eager (during order fetch) | Items needed for both enrichment and tracking write-back |
| Rate limit handling | Sequential + 1s sleep | Respects SP-API limits, simpler than retry/backoff |
| Env-status endpoint | Yes | Parity with Shopify for auto-reconnect after restart |
| Schema rename | Yes | `PlatformActivateResponse` shared by both platforms |

### 6. Files Changed

| File | Change Type |
|------|-------------|
| `src/mcp/external_sources/clients/amazon.py` | Major enhancement |
| `src/api/routes/platforms.py` | New endpoint + schema |
| `frontend/src/components/sidebar/DataSourcePanel.tsx` | Add Amazon source card |
| `frontend/src/lib/api.ts` | Add API functions |
| `frontend/src/hooks/useExternalSources.ts` | Add Amazon polling |
| Tests (3+ files) | New + extended |

### 7. No New Dependencies

All work uses existing libraries (`httpx`, `asyncio`, `pydantic`).
