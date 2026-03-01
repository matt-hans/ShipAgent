# tests/mcp/platforms/woocommerce/test_server.py
"""WooCommerce platform MCP server contract compliance tests.

Tests all 7 required contract tools exist and return the expected shapes.
Since WooCommerce makes real HTTP calls, we mock httpx at the transport
layer and only verify contract compliance, not actual API behaviour.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp.platforms.woocommerce.mapper import WoocommerceMapper


# ---------------------------------------------------------------------------
# Helpers: mock httpx responses
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response with the given status and JSON body."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        headers=headers or {},
        request=httpx.Request("GET", "https://test.local"),
    )
    return resp


def _system_status_response() -> httpx.Response:
    """Successful system_status response for test_connection."""
    return _mock_response(
        json_data={"environment": {"version": "9.5.1"}},
    )


def _orders_page_response(
    orders: list[dict],
    total: int = 2,
    total_pages: int = 1,
) -> httpx.Response:
    """Orders list response with WooCommerce pagination headers."""
    return _mock_response(
        json_data=orders,
        headers={
            "X-WP-Total": str(total),
            "X-WP-TotalPages": str(total_pages),
        },
    )


# ---------------------------------------------------------------------------
# Sample WooCommerce order data
# ---------------------------------------------------------------------------

SAMPLE_ORDER = {
    "id": 101,
    "number": "101",
    "status": "processing",
    "date_created": "2026-02-20T10:00:00",
    "date_modified": "2026-02-20T10:05:00",
    "total": "29.99",
    "currency": "USD",
    "billing": {
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice@example.com",
        "phone": "555-0101",
    },
    "shipping": {
        "first_name": "Alice",
        "last_name": "Smith",
        "company": "",
        "address_1": "100 Main St",
        "address_2": "",
        "city": "Austin",
        "state": "TX",
        "postcode": "78701",
        "country": "US",
    },
    "line_items": [
        {"id": 1, "name": "Widget", "quantity": 2, "weight": "500", "total": "29.99"},
    ],
    "shipping_lines": [
        {"method_title": "Flat Rate", "method_id": "flat_rate"},
    ],
    "customer_note": "",
    "coupon_lines": [],
}

SAMPLE_ORDER_2 = {
    "id": 102,
    "number": "102",
    "status": "processing",
    "date_created": "2026-02-21T10:00:00",
    "date_modified": "2026-02-21T10:05:00",
    "total": "49.99",
    "currency": "USD",
    "billing": {
        "first_name": "Bob",
        "last_name": "Jones",
        "email": "bob@example.com",
        "phone": "555-0102",
    },
    "shipping": {
        "first_name": "Bob",
        "last_name": "Jones",
        "company": "TestCo",
        "address_1": "200 Second Ave",
        "address_2": "Suite 5",
        "city": "Dallas",
        "state": "TX",
        "postcode": "75201",
        "country": "US",
    },
    "line_items": [
        {"id": 2, "name": "Gadget", "quantity": 1, "weight": "300", "total": "49.99"},
    ],
    "shipping_lines": [],
    "customer_note": "Please leave at door",
    "coupon_lines": [],
}


# ---------------------------------------------------------------------------
# Contract compliance tests
# ---------------------------------------------------------------------------


class TestWooCommerceServerContract:
    """Verify the WooCommerce MCP implements the required tool contract."""

    @pytest.mark.asyncio
    async def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.woocommerce.server import mcp

        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {
            "platform.health",
            "platform.capabilities",
            "auth.connect",
            "auth.disconnect",
            "orders.list",
            "orders.get",
            "tracking.write_back",
        }
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    @pytest.mark.asyncio
    async def test_health_not_connected_returns_required_shape(self):
        """Health response must match contract shape when not connected."""
        import src.mcp.platforms.woocommerce.server as srv

        # Ensure disconnected state
        srv._client = None
        srv._credentials = None

        result = await srv.health()
        assert result["ok"] is False
        assert result["platform_id"] == "woocommerce"
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result
        assert result["auth_valid"] is False

    @pytest.mark.asyncio
    async def test_health_connected_returns_ok(self):
        """Health response returns ok=True when connected and API is reachable."""
        import src.mcp.platforms.woocommerce.server as srv
        from src.mcp.platforms.woocommerce.client import WooCommerceClient
        from src.mcp.platforms.woocommerce.models import WooCommerceCredentials

        creds = WooCommerceCredentials(
            site_url="https://test.local",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        client = WooCommerceClient(creds)
        client.test_connection = AsyncMock(return_value={"environment": {"version": "9.5.1"}})

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.health()
            assert result["ok"] is True
            assert result["api_reachable"] is True
            assert result["auth_valid"] is True
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_capabilities_returns_required_shape(self):
        """Capabilities response must match contract shape."""
        from src.mcp.platforms.woocommerce.server import capabilities

        result = await capabilities()
        assert result["platform_id"] == "woocommerce"
        assert result["contract_version"] == "1.0"
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert "orders.list" in result["supports"]
        assert result["paging"]["strategy"] == "offset"

    @pytest.mark.asyncio
    async def test_auth_connect_success(self):
        """auth.connect returns connected=True on successful connection."""
        import src.mcp.platforms.woocommerce.server as srv

        srv._client = None
        srv._credentials = None

        with patch("src.mcp.platforms.woocommerce.client.WooCommerceClient._ensure_client") as mock_ensure:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=_system_status_response())
            mock_http.is_closed = False
            mock_ensure.return_value = mock_http

            result = await srv.auth_connect(
                credential_ref="test",
                site_url="https://test.local",
                consumer_key="ck_test",
                consumer_secret="cs_test",
            )

            assert result["connected"] is True
            assert result["auth_valid"] is True
            assert result["account_id"] == "https://test.local"

        # Cleanup
        srv._client = None
        srv._credentials = None

    @pytest.mark.asyncio
    async def test_auth_disconnect(self):
        """auth.disconnect clears state and returns disconnected=True."""
        import src.mcp.platforms.woocommerce.server as srv

        srv._client = MagicMock()
        srv._client.close = AsyncMock()
        srv._credentials = MagicMock()

        result = await srv.auth_disconnect()
        assert result["disconnected"] is True
        assert srv._client is None
        assert srv._credentials is None

    @pytest.mark.asyncio
    async def test_orders_list_not_connected(self):
        """orders.list returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.woocommerce.server as srv

        srv._client = None
        result = await srv.orders_list()
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_orders_list_returns_contract_shape(self):
        """orders.list returns items, next_cursor, and watermark."""
        import src.mcp.platforms.woocommerce.server as srv
        from src.mcp.platforms.woocommerce.client import WooCommerceClient
        from src.mcp.platforms.woocommerce.models import WooCommerceCredentials

        creds = WooCommerceCredentials(
            site_url="https://test.local",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        client = WooCommerceClient(creds)
        client.fetch_orders_page = AsyncMock(return_value={
            "items": [SAMPLE_ORDER, SAMPLE_ORDER_2],
            "next_cursor": "2",
            "watermark": "2026-02-21T10:05:00",
        })

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.orders_list()
            assert "items" in result
            assert "next_cursor" in result
            assert "watermark" in result
            assert len(result["items"]) == 2
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_orders_get_not_connected(self):
        """orders.get returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.woocommerce.server as srv

        srv._client = None
        result = await srv.orders_get(order_id="101")
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_orders_get_returns_order(self):
        """orders.get returns an order dict on success."""
        import src.mcp.platforms.woocommerce.server as srv
        from src.mcp.platforms.woocommerce.client import WooCommerceClient
        from src.mcp.platforms.woocommerce.models import WooCommerceCredentials

        creds = WooCommerceCredentials(
            site_url="https://test.local",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        client = WooCommerceClient(creds)
        client.get_order = AsyncMock(return_value=SAMPLE_ORDER)

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.orders_get(order_id="101")
            assert "order" in result
            assert result["order"]["id"] == 101
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_orders_get_not_found(self):
        """orders.get returns NOT_FOUND for unknown ID."""
        import src.mcp.platforms.woocommerce.server as srv
        from src.mcp.platforms.woocommerce.client import WooCommerceClient
        from src.mcp.platforms.woocommerce.models import WooCommerceCredentials

        creds = WooCommerceCredentials(
            site_url="https://test.local",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        client = WooCommerceClient(creds)
        client.get_order = AsyncMock(return_value=None)

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.orders_get(order_id="999")
            assert result["error_code"] == "NOT_FOUND"
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_tracking_write_back_not_connected(self):
        """tracking.write_back returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.woocommerce.server as srv

        srv._client = None
        result = await srv.tracking_write_back(
            order_id="101",
            tracking_numbers=["1Z999AA10123456784"],
        )
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_tracking_write_back_success(self):
        """tracking.write_back returns success on update."""
        import src.mcp.platforms.woocommerce.server as srv
        from src.mcp.platforms.woocommerce.client import WooCommerceClient
        from src.mcp.platforms.woocommerce.models import WooCommerceCredentials

        creds = WooCommerceCredentials(
            site_url="https://test.local",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        client = WooCommerceClient(creds)
        client.update_tracking = AsyncMock(return_value={"success": True})

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.tracking_write_back(
                order_id="101",
                tracking_numbers=["1Z999AA10123456784"],
                carrier="UPS",
            )
            assert result["success"] is True
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_contract_versions_match(self):
        """Contract version must be consistent across health and capabilities."""
        import src.mcp.platforms.woocommerce.server as srv

        # Ensure disconnected state for health (still returns contract version)
        srv._client = None
        srv._credentials = None

        h = await srv.health()
        c = await srv.capabilities()
        assert h["contract_version"] == c["contract_version"]


class TestWooCommerceMapper:
    """Verify the WoocommerceMapper produces correct flat rows."""

    @pytest.fixture
    def mapper(self):
        """Create a WoocommerceMapper instance."""
        return WoocommerceMapper()

    @pytest.fixture
    def sample_order(self):
        """Return a sample WooCommerce order dict."""
        return SAMPLE_ORDER.copy()

    def test_platform_is_woocommerce(self, mapper, sample_order):
        """Flat row must have platform='woocommerce'."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["platform"] == "woocommerce"

    def test_external_id_is_string(self, mapper, sample_order):
        """External ID must be a string."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["external_id"] == "101"
        assert isinstance(row["external_id"], str)

    def test_canonical_hash_is_sha256(self, mapper, sample_order):
        """Canonical hash must be 64-char hex (SHA-256)."""
        row = mapper.to_flat_row(sample_order, "test")
        assert len(row["canonical_hash"]) == 64

    def test_canonical_hash_deterministic(self, mapper, sample_order):
        """Same input must produce the same canonical hash."""
        row1 = mapper.to_flat_row(sample_order, "test")
        row2 = mapper.to_flat_row(sample_order, "test")
        assert row1["canonical_hash"] == row2["canonical_hash"]

    def test_weight_calculation(self, mapper, sample_order):
        """Weight should be sum of (weight * quantity) for all items."""
        row = mapper.to_flat_row(sample_order, "test")
        # 500 weight * 2 quantity = 1000
        assert row["total_weight_grams"] == 1000

    def test_price_in_cents(self, mapper, sample_order):
        """Price must be stored as integer cents."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["total_price_cents"] == 2999

    def test_mapping_version(self, mapper, sample_order):
        """Mapping version must be present."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["mapping_version"] == "1.0"

    def test_shipping_address_fields(self, mapper, sample_order):
        """Shipping address fields must be mapped correctly."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["ship_to_name"] == "Alice Smith"
        assert row["ship_to_address1"] == "100 Main St"
        assert row["ship_to_city"] == "Austin"
        assert row["ship_to_state"] == "TX"
        assert row["ship_to_postal"] == "78701"
        assert row["ship_to_country"] == "US"

    def test_shipping_method_from_shipping_lines(self, mapper, sample_order):
        """Shipping method and service code from shipping_lines."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["shipping_method"] == "Flat Rate"
        assert row["service_code"] == "flat_rate"

    def test_no_shipping_lines(self, mapper):
        """Order without shipping_lines should have None shipping method."""
        row = mapper.to_flat_row(SAMPLE_ORDER_2, "test")
        assert row["shipping_method"] is None
        assert row["service_code"] is None

    def test_customer_note_in_attrs(self, mapper):
        """Customer note should appear in attrs_json."""
        import json

        order = SAMPLE_ORDER_2.copy()
        row = mapper.to_flat_row(order, "test")
        attrs = json.loads(row["attrs_json"])
        assert attrs["customer_note"] == "Please leave at door"

    def test_fallback_ship_to_name_from_billing(self, mapper):
        """If shipping name is empty, fall back to billing name."""
        order = SAMPLE_ORDER.copy()
        order["shipping"] = {
            "first_name": "",
            "last_name": "",
            "address_1": "100 Main St",
            "city": "Austin",
            "state": "TX",
            "postcode": "78701",
            "country": "US",
        }
        row = mapper.to_flat_row(order, "test")
        assert row["ship_to_name"] == "Alice Smith"

    def test_raw_json_preserved(self, mapper, sample_order):
        """Raw JSON must be preserved in the row."""
        import json

        row = mapper.to_flat_row(sample_order, "test")
        raw = json.loads(row["raw_json"])
        assert raw["id"] == 101

    def test_credential_ref_propagated(self, mapper, sample_order):
        """Credential ref must be propagated to the row."""
        row = mapper.to_flat_row(sample_order, "primary")
        assert row["credential_ref"] == "primary"
