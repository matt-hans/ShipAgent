# tests/mcp/platforms/amazon/test_mapper.py
"""Tests for Amazon order mapper (SP-API order -> flat DuckDB row)."""
import json

import pytest

from src.mcp.platforms.amazon.mapper import AmazonMapper


@pytest.fixture
def mapper():
    """Create an AmazonMapper instance."""
    return AmazonMapper()


@pytest.fixture
def sample_amazon_order():
    """Return a sample Amazon SP-API order dict."""
    return {
        "AmazonOrderId": "111-2222222-3333333",
        "OrderStatus": "Unshipped",
        "PaymentMethod": "Other",
        "FulfillmentChannel": "MFN",
        "PurchaseDate": "2026-02-20T10:00:00Z",
        "LastUpdateDate": "2026-02-20T10:05:00Z",
        "ShippingAddress": {
            "Name": "Jane Doe",
            "AddressLine1": "123 Main St",
            "AddressLine2": "Suite 4",
            "City": "Austin",
            "StateOrRegion": "TX",
            "PostalCode": "78701",
            "CountryCode": "US",
            "Phone": "512-555-0100",
        },
        "OrderTotal": {"Amount": "49.99", "CurrencyCode": "USD"},
        "BuyerInfo": {"BuyerEmail": "jane@example.com", "BuyerName": "Jane Doe"},
        "NumberOfItemsShipped": 0,
        "NumberOfItemsUnshipped": 3,
        "ShipmentServiceLevelCategory": "Standard",
        "EarliestShipDate": "2026-02-21T00:00:00Z",
        "LatestShipDate": "2026-02-23T00:00:00Z",
        "IsBusinessOrder": False,
        "IsPrime": True,
        "MarketplaceId": "ATVPDKIKX0DER",
    }


class TestAmazonMapper:
    """Verify the AmazonMapper produces correct flat rows."""

    def test_platform_is_amazon(self, mapper, sample_amazon_order):
        """Flat row must have platform='amazon'."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["platform"] == "amazon"

    def test_external_id_is_string(self, mapper, sample_amazon_order):
        """External ID must be a string."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["external_id"] == "111-2222222-3333333"
        assert isinstance(row["external_id"], str)

    def test_canonical_hash_is_sha256(self, mapper, sample_amazon_order):
        """Canonical hash must be 64-char hex (SHA-256)."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert len(row["canonical_hash"]) == 64

    def test_canonical_hash_deterministic(self, mapper, sample_amazon_order):
        """Same input must produce the same canonical hash."""
        row1 = mapper.to_flat_row(sample_amazon_order, "primary")
        row2 = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row1["canonical_hash"] == row2["canonical_hash"]

    def test_item_count_from_shipped_and_unshipped(self, mapper, sample_amazon_order):
        """Item count should sum shipped + unshipped items."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["item_count"] == 3  # 0 shipped + 3 unshipped

    def test_price_in_cents(self, mapper, sample_amazon_order):
        """Price must be stored as integer cents."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["total_price_cents"] == 4999

    def test_mapping_version(self, mapper, sample_amazon_order):
        """Mapping version must be present and correct."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["mapping_version"] == AmazonMapper.MAPPING_VERSION
        assert row["mapping_version"] == "1.0"

    def test_shipping_address_fields(self, mapper, sample_amazon_order):
        """Shipping address fields must be mapped correctly."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["ship_to_name"] == "Jane Doe"
        assert row["ship_to_address1"] == "123 Main St"
        assert row["ship_to_address2"] == "Suite 4"
        assert row["ship_to_city"] == "Austin"
        assert row["ship_to_state"] == "TX"
        assert row["ship_to_postal"] == "78701"
        assert row["ship_to_country"] == "US"
        assert row["ship_to_phone"] == "512-555-0100"

    def test_fulfillment_channel_afn_means_amazon_fulfilled(self, mapper, sample_amazon_order):
        """AFN fulfillment channel maps to 'amazon_fulfilled'."""
        sample_amazon_order["FulfillmentChannel"] = "AFN"
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["fulfillment_status"] == "amazon_fulfilled"

    def test_fulfillment_channel_mfn_means_unfulfilled(self, mapper, sample_amazon_order):
        """MFN fulfillment channel maps to 'unfulfilled'."""
        sample_amazon_order["FulfillmentChannel"] = "MFN"
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert row["fulfillment_status"] == "unfulfilled"

    def test_prime_and_business_in_attrs(self, mapper, sample_amazon_order):
        """IsPrime and IsBusinessOrder should appear in attrs_json."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        attrs = json.loads(row["attrs_json"])
        assert attrs["is_prime"] is True
        assert attrs["is_business_order"] is False

    def test_raw_json_preserved(self, mapper, sample_amazon_order):
        """Raw JSON must be preserved in the row."""
        row = mapper.to_flat_row(sample_amazon_order, "primary")
        assert "raw_json" in row
        raw = json.loads(row["raw_json"])
        assert raw["AmazonOrderId"] == "111-2222222-3333333"

    def test_credential_ref_propagated(self, mapper, sample_amazon_order):
        """Credential ref must be propagated to the row."""
        row = mapper.to_flat_row(sample_amazon_order, "sandbox")
        assert row["credential_ref"] == "sandbox"

    def test_currency_default_usd(self, mapper):
        """Currency should default to USD when not provided."""
        order = {
            "AmazonOrderId": "111-0000000-0000000",
            "OrderTotal": {"Amount": "10.00"},
        }
        row = mapper.to_flat_row(order, "primary")
        assert row["currency"] == "USD"

    def test_country_default_us(self, mapper):
        """Country should default to US when not provided."""
        order = {
            "AmazonOrderId": "111-0000000-0000000",
            "ShippingAddress": {"Name": "Test User", "City": "Austin"},
        }
        row = mapper.to_flat_row(order, "primary")
        assert row["ship_to_country"] == "US"
