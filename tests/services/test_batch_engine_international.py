"""Tests for batch engine international integration.

Covers:
- Decimal-based money conversion (_dollars_to_cents)
- International validation in preview/execute loops
- Commodity hydration helper (_get_commodities_bulk)
- Charge breakdown storage on JobRow
"""

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDollarsToCents:
    """Verify Decimal-based money conversion avoids float drift."""

    def test_simple_conversion(self):
        """Simple dollar-to-cents conversion."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("45.50") == 4550

    def test_problematic_float_value(self):
        """33.33 * 100 = 3332.9999... with float — Decimal avoids this."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("33.33") == 3333

    def test_zero(self):
        """Zero values convert correctly."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("0") == 0
        assert _dollars_to_cents("0.00") == 0

    def test_large_value(self):
        """Large dollar amounts convert correctly."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("99999.99") == 9999999

    def test_no_decimal(self):
        """Whole dollar amounts convert correctly."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("100") == 10000

    def test_rounding_half_up(self):
        """Values with more than 2 decimal places round HALF_UP."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("10.555") == 1056  # ROUND_HALF_UP
        assert _dollars_to_cents("10.554") == 1055

    def test_another_problematic_float(self):
        """19.99 * 100 = 1998.9999... with float."""
        from src.services.batch_engine import _dollars_to_cents

        assert _dollars_to_cents("19.99") == 1999


class TestCommodityHydration:
    """Verify _get_commodities_bulk helper in BatchEngine."""

    @pytest.fixture
    def engine(self):
        """Create a BatchEngine with mocked dependencies."""
        from src.services.batch_engine import BatchEngine

        ups = AsyncMock()
        db = MagicMock()
        return BatchEngine(ups_service=ups, db_session=db, account_number="TEST")

    @pytest.mark.asyncio
    async def test_get_commodities_bulk_success(self, engine):
        """Successful commodity fetch returns mapped data."""
        mock_gateway = AsyncMock()
        mock_gateway.get_commodities_bulk.return_value = {
            1001: [{"description": "Coffee", "commodity_code": "090111"}],
        }
        with patch(
            "src.services.batch_engine.get_data_gateway",
            return_value=mock_gateway,
        ):
            result = await engine._get_commodities_bulk([1001])
            assert 1001 in result
            assert result[1001][0]["description"] == "Coffee"

    @pytest.mark.asyncio
    async def test_get_commodities_bulk_failure_returns_empty(self, engine):
        """Gateway failure returns empty dict (non-critical)."""
        with patch(
            "src.services.batch_engine.get_data_gateway",
            side_effect=Exception("MCP down"),
        ):
            result = await engine._get_commodities_bulk([1001])
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_commodities_bulk_empty_ids(self, engine):
        """Empty order IDs list returns empty dict."""
        mock_gateway = AsyncMock()
        mock_gateway.get_commodities_bulk.return_value = {}
        with patch(
            "src.services.batch_engine.get_data_gateway",
            return_value=mock_gateway,
        ):
            result = await engine._get_commodities_bulk([])
            assert result == {}


class TestInternationalPreviewValidation:
    """Verify international validation runs during preview."""

    @pytest.fixture
    def engine(self):
        """Create a BatchEngine with mocked UPS client."""
        from src.services.batch_engine import BatchEngine

        ups = AsyncMock()
        # Rate returns a basic rate result
        ups.get_rate.return_value = {
            "totalCharges": {"monetaryValue": "25.00"},
        }
        db = MagicMock()
        return BatchEngine(ups_service=ups, db_session=db, account_number="TEST")

    def _make_row(self, row_number, order_data):
        """Create a mock JobRow."""
        row = SimpleNamespace(
            row_number=row_number,
            order_data=json.dumps(order_data),
            status="pending",
        )
        return row

    @pytest.mark.asyncio
    async def test_preview_unsupported_lane_marks_error(self, engine):
        """Preview for unsupported international lane produces rate_error."""
        row = self._make_row(1, {
            "ship_to_name": "Test",
            "ship_to_country": "GB",
            "ship_to_address1": "1 High St",
            "ship_to_city": "London",
            "ship_to_zip": "SW1A 1AA",
            "weight": "5",
        })
        result = await engine.preview(
            job_id="test-job",
            rows=[row],
            shipper={"name": "Shipper", "country": "US"},
            service_code="07",
        )
        # The row should have a rate_error indicating unsupported lane
        assert len(result["preview_rows"]) == 1
        row_info = result["preview_rows"][0]
        assert "rate_error" in row_info
        assert "not enabled" in row_info["rate_error"].lower()

    @pytest.mark.asyncio
    async def test_preview_disabled_lane_marks_error(self, engine, monkeypatch):
        """Preview for disabled lane (kill switch) produces rate_error."""
        monkeypatch.delenv("INTERNATIONAL_ENABLED_LANES", raising=False)
        row = self._make_row(1, {
            "ship_to_name": "Test",
            "ship_to_country": "CA",
            "ship_to_address1": "123 Maple",
            "ship_to_city": "Toronto",
            "ship_to_state": "ON",
            "ship_to_zip": "M5V 1A1",
            "weight": "5",
        })
        result = await engine.preview(
            job_id="test-job",
            rows=[row],
            shipper={"name": "Shipper", "country": "US"},
            service_code="11",
        )
        row_info = result["preview_rows"][0]
        assert "rate_error" in row_info
        assert "not enabled" in row_info["rate_error"].lower()

    @pytest.mark.asyncio
    async def test_preview_domestic_row_skips_international_validation(self, engine):
        """Domestic rows skip international validation and rate normally."""
        row = self._make_row(1, {
            "ship_to_name": "Test",
            "ship_to_country": "US",
            "ship_to_address1": "123 Main St",
            "ship_to_city": "Austin",
            "ship_to_state": "TX",
            "ship_to_zip": "73301",
            "weight": "5",
        })
        result = await engine.preview(
            job_id="test-job",
            rows=[row],
            shipper={"name": "Shipper", "country": "US"},
            service_code="03",
        )
        row_info = result["preview_rows"][0]
        # No rate_error — domestic goes straight through
        assert "rate_error" not in row_info
        assert row_info["estimated_cost_cents"] == 2500


class TestInternationalExecuteValidation:
    """Verify international validation runs during execute."""

    @pytest.fixture
    def engine(self):
        """Create BatchEngine with mocked UPS client."""
        from src.services.batch_engine import BatchEngine

        ups = AsyncMock()
        db = MagicMock()
        return BatchEngine(ups_service=ups, db_session=db, account_number="TEST")

    def _make_row(self, row_number, order_data):
        """Create a mock JobRow."""
        row = SimpleNamespace(
            row_number=row_number,
            order_data=json.dumps(order_data),
            status="pending",
            tracking_number=None,
            label_path=None,
            cost_cents=None,
            error_code=None,
            error_message=None,
            processed_at=None,
            destination_country=None,
            duties_taxes_cents=None,
            charge_breakdown=None,
        )
        return row

    @pytest.mark.asyncio
    async def test_execute_unsupported_lane_fails_row(self, engine):
        """Execution for unsupported lane fails the row with error code."""
        row = self._make_row(1, {
            "ship_to_name": "Test",
            "ship_to_country": "GB",
            "ship_to_address1": "1 High St",
            "ship_to_city": "London",
            "ship_to_zip": "SW1A 1AA",
            "weight": "5",
        })
        result = await engine.execute(
            job_id="test-job",
            rows=[row],
            shipper={"name": "Shipper", "country": "US"},
            service_code="07",
            write_back_enabled=False,
        )
        assert result["failed"] == 1
        assert result["successful"] == 0
        assert row.status == "failed"
        assert "not enabled" in row.error_message.lower()

    @pytest.mark.asyncio
    async def test_execute_stores_destination_country(self, engine):
        """International shipment stores destination_country on JobRow."""
        engine._ups.create_shipment.return_value = {
            "trackingNumbers": ["1Z999"],
            "labelData": [],
            "totalCharges": {"monetaryValue": "50.00"},
        }
        row = self._make_row(1, {
            "ship_to_name": "Test",
            "ship_to_country": "CA",
            "ship_to_address1": "123 Maple",
            "ship_to_city": "Toronto",
            "ship_to_state": "ON",
            "ship_to_zip": "M5V 1A1",
            "ship_to_attention_name": "Test Attn",
            "ship_to_phone": "4165551234",
            "shipper_attention_name": "Shipper Attn",
            "shipper_phone": "5125559999",
            "shipment_description": "Electronics",
            "invoice_currency_code": "USD",
            "invoice_monetary_value": "999.00",
            "weight": "5",
            "commodities": [
                {"description": "Laptop", "commodity_code": "847130",
                 "origin_country": "US", "quantity": 1, "unit_value": "999.00"},
            ],
        })
        with patch.dict("os.environ", {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            result = await engine.execute(
                job_id="test-job",
                rows=[row],
                shipper={
                    "name": "Shipper",
                    "country": "US",
                    "attention_name": "Shipper Attn",
                    "phone": "5125559999",
                },
                service_code="11",
                write_back_enabled=False,
            )
        assert result["successful"] == 1
        assert row.destination_country == "CA"
