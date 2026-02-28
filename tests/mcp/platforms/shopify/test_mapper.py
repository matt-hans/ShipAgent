# tests/mcp/platforms/shopify/test_mapper.py
"""Tests for Shopify order mapper (provider order -> flat DuckDB row)."""
import pytest
from src.mcp.platforms.shopify.mapper import ShopifyMapper


@pytest.fixture
def mapper():
    return ShopifyMapper()


@pytest.fixture
def sample_shopify_order():
    return {
        "id": 5678901234,
        "order_number": 1042,
        "financial_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-28T10:30:00-05:00",
        "updated_at": "2026-02-28T11:00:00-05:00",
        "shipping_address": {
            "name": "Jane Doe",
            "company": "Acme Corp",
            "address1": "123 Main St",
            "address2": "Suite 4",
            "city": "Austin",
            "province_code": "TX",
            "zip": "78701",
            "country_code": "US",
            "phone": "512-555-0100",
        },
        "total_price": "49.99",
        "currency": "USD",
        "customer": {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
        "line_items": [
            {"quantity": 2, "grams": 500, "title": "Widget"},
            {"quantity": 1, "grams": 200, "title": "Gadget"},
        ],
        "tags": "vip, wholesale",
        "note": "Handle with care",
        "shipping_lines": [{"title": "Standard Shipping", "code": "STANDARD"}],
    }


class TestShopifyMapper:
    def test_platform_column(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["platform"] == "shopify"

    def test_credential_ref(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "sandbox")
        assert row["credential_ref"] == "sandbox"

    def test_external_id_is_string(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["external_id"] == "5678901234"
        assert isinstance(row["external_id"], str)

    def test_ship_to_fields(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["ship_to_name"] == "Jane Doe"
        assert row["ship_to_company"] == "Acme Corp"
        assert row["ship_to_city"] == "Austin"
        assert row["ship_to_state"] == "TX"
        assert row["ship_to_postal"] == "78701"
        assert row["ship_to_country"] == "US"

    def test_weight_is_integer_grams(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["total_weight_grams"] == 1200  # (2*500)+(1*200)
        assert isinstance(row["total_weight_grams"], int)

    def test_price_in_cents(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["total_price_cents"] == 4999

    def test_item_count(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["item_count"] == 3  # 2 + 1

    def test_canonical_hash_present(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert "canonical_hash" in row
        assert len(row["canonical_hash"]) == 64  # SHA256 hex

    def test_canonical_hash_deterministic(self, mapper, sample_shopify_order):
        row1 = mapper.to_flat_row(sample_shopify_order, "primary")
        row2 = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row1["canonical_hash"] == row2["canonical_hash"]

    def test_canonical_hash_changes_on_status_change(self, mapper, sample_shopify_order):
        row1 = mapper.to_flat_row(sample_shopify_order, "primary")
        sample_shopify_order["fulfillment_status"] = "fulfilled"
        row2 = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row1["canonical_hash"] != row2["canonical_hash"]

    def test_raw_json_preserved(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert "raw_json" in row
        assert "5678901234" in row["raw_json"]

    def test_attrs_json_contains_non_core_fields(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        import json
        attrs = json.loads(row["attrs_json"])
        assert "note" in attrs

    def test_mapping_version(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["mapping_version"] == ShopifyMapper.MAPPING_VERSION

    def test_missing_shipping_address(self, mapper):
        order = {"id": 999, "order_number": 1, "line_items": []}
        row = mapper.to_flat_row(order, "primary")
        assert row["ship_to_name"] is None
        assert row["ship_to_state"] is None

    def test_fulfillment_status_defaults_to_unfulfilled(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["fulfillment_status"] == "unfulfilled"
