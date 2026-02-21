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
