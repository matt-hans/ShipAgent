# tests/mcp/platforms/amazon/test_sandbox_integration.py
"""Live sandbox integration test — exercises the full Amazon SP-API pipeline.

Requires real sandbox credentials in .env:
  AMAZON_SP_API_CLIENT_ID, AMAZON_SP_API_CLIENT_SECRET,
  AMAZON_SP_API_REFRESH_TOKEN, AMAZON_MARKETPLACE_ID, AMAZON_SP_API_SANDBOX=true

Marked with @pytest.mark.sandbox — skipped unless AMAZON_SP_API_SANDBOX=true.
Run explicitly with: pytest -m sandbox -v
"""
from __future__ import annotations

import os

import pytest

from src.mcp.platforms.amazon.client import AmazonClient
from src.mcp.platforms.amazon.mapper import AmazonMapper
from src.mcp.platforms.amazon.models import AmazonCredentials

# Skip entire module when sandbox credentials are not configured
_sandbox_enabled = os.environ.get("AMAZON_SP_API_SANDBOX", "").lower() in ("1", "true", "yes")
_has_creds = all(
    os.environ.get(k, "").strip()
    for k in ("AMAZON_SP_API_CLIENT_ID", "AMAZON_SP_API_CLIENT_SECRET", "AMAZON_SP_API_REFRESH_TOKEN")
)

pytestmark = pytest.mark.skipif(
    not (_sandbox_enabled and _has_creds),
    reason="Requires AMAZON_SP_API_SANDBOX=true and sandbox credentials in env",
)


@pytest.fixture
def sandbox_credentials() -> AmazonCredentials:
    """Build AmazonCredentials from env vars with sandbox=True."""
    return AmazonCredentials(
        client_id=os.environ["AMAZON_SP_API_CLIENT_ID"].strip(),
        client_secret=os.environ["AMAZON_SP_API_CLIENT_SECRET"].strip(),
        refresh_token=os.environ["AMAZON_SP_API_REFRESH_TOKEN"].strip(),
        marketplace_id=os.environ.get("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER").strip(),
        sandbox=True,
    )


@pytest.fixture
def sandbox_client(sandbox_credentials: AmazonCredentials) -> AmazonClient:
    """Create an AmazonClient pointed at the sandbox."""
    return AmazonClient(sandbox_credentials)


@pytest.fixture
def mapper() -> AmazonMapper:
    """Create an AmazonMapper instance."""
    return AmazonMapper()


class TestSandboxConnectivity:
    """Verify basic auth and API connectivity against the live sandbox."""

    async def test_lwa_token_exchange(self, sandbox_client: AmazonClient) -> None:
        """LWA refresh token exchange returns a valid access token."""
        token = await sandbox_client._get_access_token()
        assert token is not None
        assert token.startswith("Atza|")

    async def test_connection_health(self, sandbox_client: AmazonClient) -> None:
        """test_connection() succeeds against sandbox getOrders endpoint."""
        result = await sandbox_client.test_connection()
        assert "payload" in result
        assert "Orders" in result["payload"]

    async def test_sandbox_base_url(self, sandbox_credentials: AmazonCredentials) -> None:
        """Sandbox credentials produce sandbox base URL."""
        assert "sandbox" in sandbox_credentials.base_url
        assert sandbox_credentials.sandbox is True


class TestSandboxOrderFetch:
    """Verify order fetching against the live sandbox."""

    async def test_fetch_orders_returns_items(self, sandbox_client: AmazonClient) -> None:
        """fetch_orders_page returns orders from the static sandbox."""
        result = await sandbox_client.fetch_orders_page(
            since="TEST_CASE_200",
        )
        assert "items" in result
        assert len(result["items"]) > 0, "Sandbox should return at least 1 static order"

    async def test_sandbox_orders_have_required_fields(self, sandbox_client: AmazonClient) -> None:
        """Sandbox orders have the fields our mapper expects."""
        result = await sandbox_client.fetch_orders_page(since="TEST_CASE_200")
        order = result["items"][0]

        # Fields required by AmazonMapper.to_flat_row
        assert "AmazonOrderId" in order
        assert "OrderStatus" in order
        assert "FulfillmentChannel" in order
        assert "OrderTotal" in order
        assert "NumberOfItemsShipped" in order or "NumberOfItemsUnshipped" in order

    async def test_sandbox_order_address(self, sandbox_client: AmazonClient) -> None:
        """Sandbox orders include a ShipFrom address (ship-to may require separate call)."""
        result = await sandbox_client.fetch_orders_page(since="TEST_CASE_200")
        order = result["items"][0]

        # The static sandbox includes DefaultShipFromLocationAddress
        assert "DefaultShipFromLocationAddress" in order
        addr = order["DefaultShipFromLocationAddress"]
        assert addr.get("City")
        assert addr.get("StateOrRegion")
        assert addr.get("PostalCode")
        assert addr.get("CountryCode")


class TestSandboxMapperIntegration:
    """Verify AmazonMapper handles real sandbox data correctly."""

    async def test_mapper_produces_valid_flat_row(
        self, sandbox_client: AmazonClient, mapper: AmazonMapper,
    ) -> None:
        """Mapper converts live sandbox orders to valid flat rows."""
        result = await sandbox_client.fetch_orders_page(since="TEST_CASE_200")
        order = result["items"][0]

        row = mapper.to_flat_row(order, credential_ref="primary")

        # Core identity fields
        assert row["platform"] == "amazon"
        assert row["external_id"] == order["AmazonOrderId"]
        assert row["credential_ref"] == "primary"

        # Price conversion
        assert isinstance(row["total_price_cents"], int)
        assert row["total_price_cents"] == 1101  # $11.01 → 1101 cents

        # Status mapping
        assert row["order_status"] == "Unshipped"
        assert row["fulfillment_status"] == "unfulfilled"  # MFN → unfulfilled

        # Hash
        assert len(row["canonical_hash"]) == 64  # SHA-256 hex

        # Raw JSON preserved
        assert row["raw_json"] is not None
        assert order["AmazonOrderId"] in row["raw_json"]

    async def test_all_sandbox_orders_map_successfully(
        self, sandbox_client: AmazonClient, mapper: AmazonMapper,
    ) -> None:
        """Every sandbox order maps without errors."""
        result = await sandbox_client.fetch_orders_page(since="TEST_CASE_200")
        rows = []
        for order in result["items"]:
            row = mapper.to_flat_row(order, credential_ref="primary")
            rows.append(row)

        assert len(rows) == len(result["items"])
        # All rows have unique external_ids
        ids = [r["external_id"] for r in rows]
        assert len(set(ids)) == len(ids), "Duplicate order IDs in sandbox response"

    async def test_mapper_handles_missing_shipping_address(
        self, sandbox_client: AmazonClient, mapper: AmazonMapper,
    ) -> None:
        """Mapper handles orders without ShippingAddress gracefully.

        Sandbox getOrders doesn't include ShippingAddress in the list response —
        it requires a separate getOrderAddress call. Mapper should produce
        None for address fields rather than crashing.
        """
        result = await sandbox_client.fetch_orders_page(since="TEST_CASE_200")
        order = result["items"][0]

        # Ensure ShippingAddress is absent (sandbox list response doesn't include it)
        order.pop("ShippingAddress", None)

        row = mapper.to_flat_row(order, credential_ref="primary")

        # Should not crash — address fields should be None
        assert row["ship_to_name"] is None
        assert row["ship_to_address1"] is None
        assert row["ship_to_city"] is None


class TestSandboxCredentialResolution:
    """Verify credential resolution from env vars works for Amazon."""

    def test_env_var_resolution(self) -> None:
        """resolve_amazon_credentials picks up env vars as fallback."""
        from src.services.runtime_credentials import resolve_amazon_credentials

        creds = resolve_amazon_credentials()
        assert creds is not None
        assert creds.client_id == os.environ["AMAZON_SP_API_CLIENT_ID"].strip()
        assert creds.marketplace_id == os.environ.get("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER").strip()
        assert creds.refresh_token != ""
