"""Tests for Shopify _normalize_order field extraction.

Validates that the 6 new fields (financial_status, fulfillment_status,
tags, total_weight_grams, shipping_method, item_count) are correctly
extracted from raw Shopify API data.
"""

from src.mcp.external_sources.clients.shopify import ShopifyClient


class TestNormalizeOrderNewFields:
    """Tests for new field extraction in _normalize_order."""

    def _make_raw_order(self, **overrides) -> dict:
        """Build a minimal raw Shopify order dict with required fields.

        Args:
            **overrides: Key-value pairs to override or add to the base order.

        Returns:
            Raw Shopify order dict suitable for _normalize_order().
        """
        base = {
            "id": 123456789,
            "order_number": 1001,
            "created_at": "2025-01-20T10:30:00-05:00",
            "financial_status": "paid",
            "fulfillment_status": None,
            "total_price": "59.98",
            "tags": "VIP, wholesale",
            "customer": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
            },
            "shipping_address": {
                "first_name": "John",
                "last_name": "Doe",
                "company": None,
                "address1": "123 Main St",
                "address2": None,
                "city": "San Francisco",
                "province_code": "CA",
                "zip": "94102",
                "country_code": "US",
                "phone": "415-555-1234",
            },
            "line_items": [
                {
                    "id": 1,
                    "title": "Widget",
                    "quantity": 2,
                    "price": "10.00",
                    "sku": "W-001",
                    "grams": 500,
                },
                {
                    "id": 2,
                    "title": "Gadget",
                    "quantity": 1,
                    "price": "20.00",
                    "sku": "G-001",
                    "grams": 1000,
                },
            ],
            "shipping_lines": [
                {"title": "Standard Shipping"},
            ],
        }
        base.update(overrides)
        return base

    def test_financial_status_extracted(self):
        """financial_status is extracted from raw order."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())
        assert order.financial_status == "paid"

    def test_fulfillment_status_extracted_null_as_unfulfilled(self):
        """fulfillment_status None is normalized to 'unfulfilled'."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order(fulfillment_status=None))
        assert order.fulfillment_status == "unfulfilled"

    def test_fulfillment_status_extracted_when_set(self):
        """fulfillment_status is extracted when explicitly set."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order(fulfillment_status="fulfilled"))
        assert order.fulfillment_status == "fulfilled"

    def test_tags_extracted(self):
        """Tags are extracted as comma-separated string."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())
        assert order.tags == "VIP, wholesale"

    def test_tags_none_when_empty(self):
        """Tags are None when empty string or missing."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order(tags=""))
        assert order.tags is None

    def test_total_weight_grams_computed(self):
        """total_weight_grams is computed from line items (grams * quantity)."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())
        # Widget: 500g * 2 = 1000g, Gadget: 1000g * 1 = 1000g, total = 2000g
        assert order.total_weight_grams == 2000.0

    def test_total_weight_grams_none_when_no_grams(self):
        """total_weight_grams is None when line items have no grams."""
        client = ShopifyClient()
        raw = self._make_raw_order()
        for item in raw["line_items"]:
            item["grams"] = 0
        order = client._normalize_order(raw)
        assert order.total_weight_grams is None

    def test_shipping_method_extracted(self):
        """shipping_method is extracted from first shipping line."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())
        assert order.shipping_method == "Standard Shipping"

    def test_shipping_method_none_when_no_shipping_lines(self):
        """shipping_method is None when no shipping lines."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order(shipping_lines=[]))
        assert order.shipping_method is None

    def test_item_count_computed(self):
        """item_count is computed from line item quantities."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())
        # Widget: quantity 2, Gadget: quantity 1, total = 3
        assert order.item_count == 3

    def test_item_count_none_when_no_items(self):
        """item_count is None when no line items."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order(line_items=[]))
        assert order.item_count is None

    def test_all_new_fields_together(self):
        """All 6 new fields are correctly extracted from a single order."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())

        assert order.financial_status == "paid"
        assert order.fulfillment_status == "unfulfilled"
        assert order.tags == "VIP, wholesale"
        assert order.total_weight_grams == 2000.0
        assert order.shipping_method == "Standard Shipping"
        assert order.item_count == 3

    def test_existing_fields_unchanged(self):
        """Existing fields remain correct after new field additions."""
        client = ShopifyClient()
        order = client._normalize_order(self._make_raw_order())

        assert order.platform == "shopify"
        assert order.order_id == "123456789"
        assert order.order_number == "1001"
        assert order.status == "paid/unfulfilled"
        assert order.customer_name == "John Doe"
        assert order.ship_to_name == "John Doe"
        assert order.ship_to_city == "San Francisco"
        assert order.ship_to_state == "CA"
        assert order.ship_to_postal_code == "94102"
        assert order.ship_to_country == "US"
        assert order.total_price == "59.98"


class TestShopifyNewFieldsExpanded:
    """Verify Shopify client populates new ExternalOrder fields (Task 9)."""

    def _make_raw_order(self, **overrides) -> dict:
        """Build minimal raw Shopify order with extended fields."""
        base = {
            "id": 99999,
            "order_number": 2001,
            "created_at": "2026-02-01T10:00:00-05:00",
            "financial_status": "paid",
            "fulfillment_status": None,
            "total_price": "49.99",
            "tags": "",
            "customer": {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "orders_count": 5,
                "total_spent": "249.95",
            },
            "shipping_address": {
                "first_name": "Jane",
                "last_name": "Doe",
                "address1": "123 Main St",
                "city": "New York",
                "province_code": "NY",
                "zip": "10001",
                "country_code": "US",
            },
            "line_items": [
                {"id": 1, "title": "Widget", "quantity": 1, "price": "49.99",
                 "sku": "WDG-001", "grams": 500},
            ],
            "shipping_lines": [],
            "note": None,
            "note_attributes": [],
            "discount_codes": [],
            "risk": [],
        }
        base.update(overrides)
        return base

    def test_customer_tags_populated(self):
        """customer_tags extracted from customer.tags."""
        raw = self._make_raw_order(
            customer={"first_name": "Jane", "last_name": "Doe", "tags": "VIP, wholesale"},
        )
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.customer_tags == "VIP, wholesale"

    def test_customer_tags_none_when_absent(self):
        """customer_tags is None when customer has no tags."""
        raw = self._make_raw_order()
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.customer_tags is None

    def test_customer_order_count_populated(self):
        """customer_order_count extracted from customer.orders_count."""
        raw = self._make_raw_order()
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.customer_order_count == 5

    def test_customer_total_spent_populated(self):
        """customer_total_spent extracted from customer.total_spent."""
        raw = self._make_raw_order()
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.customer_total_spent == "249.95"

    def test_order_note_populated(self):
        """order_note extracted from note field."""
        raw = self._make_raw_order(note="Please ship priority")
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.order_note == "Please ship priority"

    def test_order_note_none_when_empty(self):
        """order_note is None when note is empty."""
        raw = self._make_raw_order(note="")
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.order_note is None

    def test_shipping_rate_code_from_shipping_lines(self):
        """shipping_rate_code from shipping_lines[0].code."""
        raw = self._make_raw_order(
            shipping_lines=[{"code": "STANDARD", "title": "Standard Shipping"}],
        )
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.shipping_rate_code == "STANDARD"

    def test_shipping_rate_code_none_when_no_lines(self):
        """shipping_rate_code is None when no shipping lines."""
        raw = self._make_raw_order(shipping_lines=[])
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.shipping_rate_code is None

    def test_custom_attributes_from_note_attributes(self):
        """custom_attributes populated from note_attributes."""
        raw = self._make_raw_order(
            note_attributes=[
                {"name": "gift_message", "value": "Happy Birthday"},
                {"name": "priority_flag", "value": "true"},
            ],
        )
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.custom_attributes["gift_message"] == "Happy Birthday"
        assert order.custom_attributes["priority_flag"] == "true"

    def test_discount_codes_populated(self):
        """discount_codes from discount_codes array."""
        raw = self._make_raw_order(
            discount_codes=[{"code": "SAVE10"}, {"code": "FREESHIP"}],
        )
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert "SAVE10" in order.discount_codes
        assert "FREESHIP" in order.discount_codes

    def test_discount_codes_none_when_empty(self):
        """discount_codes is None when no codes."""
        raw = self._make_raw_order(discount_codes=[])
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.discount_codes is None

    def test_line_item_types_populated(self):
        """line_item_types from distinct product_type values."""
        raw = self._make_raw_order(
            line_items=[
                {"id": 1, "title": "A", "quantity": 1, "price": "10",
                 "grams": 100, "product_type": "Apparel"},
                {"id": 2, "title": "B", "quantity": 1, "price": "20",
                 "grams": 200, "product_type": "Electronics"},
                {"id": 3, "title": "C", "quantity": 1, "price": "5",
                 "grams": 50, "product_type": "Apparel"},
            ],
        )
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.line_item_types == "Apparel, Electronics"

    def test_risk_level_high(self):
        """risk_level HIGH when recommendation contains cancel."""
        raw = self._make_raw_order(risk=[{"recommendation": "cancel"}])
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.risk_level == "HIGH"

    def test_risk_level_medium(self):
        """risk_level MEDIUM when recommendation is investigate."""
        raw = self._make_raw_order(risk=[{"recommendation": "investigate"}])
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.risk_level == "MEDIUM"

    def test_risk_level_low(self):
        """risk_level LOW for accept recommendation."""
        raw = self._make_raw_order(risk=[{"recommendation": "accept"}])
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.risk_level == "LOW"

    def test_risk_level_none_when_no_assessments(self):
        """risk_level is None when no risk assessments."""
        raw = self._make_raw_order(risk=[])
        client = ShopifyClient()
        order = client._normalize_order(raw)
        assert order.risk_level is None
