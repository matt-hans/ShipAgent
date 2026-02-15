"""End-to-end mixed domestic + international batch integration test.

Validation-only tests run unconditionally. Tests requiring UPS API
credentials are gated behind RUN_UPS_INTEGRATION=1 env var.
"""

import os
from unittest.mock import patch

import pytest

from src.services.international_rules import (
    get_requirements,
    validate_international_readiness,
)


# ---------------------------------------------------------------------------
# Validation-only tests (no UPS credentials needed)
# ---------------------------------------------------------------------------

class TestMixedBatchValidation:
    """Validation-only tests that don't require UPS API."""

    def test_international_row_missing_commodities_fails(self):
        """Row to CA without commodities should fail with MISSING_COMMODITIES."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness({"ship_to_country": "CA"}, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_COMMODITIES" in codes

    def test_international_row_missing_contacts_fails(self):
        """Row to CA without contact info should fail with MISSING_*_PHONE."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness({"ship_to_country": "CA"}, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_SHIPPER_PHONE" in codes
            assert "MISSING_RECIPIENT_PHONE" in codes
            assert "MISSING_SHIPPER_ATTENTION_NAME" in codes
            assert "MISSING_RECIPIENT_ATTENTION_NAME" in codes

    def test_international_row_missing_description_fails(self):
        """Row to MX without description should fail with MISSING_SHIPMENT_DESCRIPTION."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            req = get_requirements("US", "MX", "07")
            errors = validate_international_readiness({"ship_to_country": "MX"}, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_SHIPMENT_DESCRIPTION" in codes

    def test_international_ca_missing_invoice_fails(self):
        """Row to CA without InvoiceLineTotal should fail."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness({"ship_to_country": "CA"}, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_INVOICE_CURRENCY" in codes
            assert "MISSING_INVOICE_VALUE" in codes

    def test_international_mx_no_invoice_needed(self):
        """Row to MX should NOT require InvoiceLineTotal."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            req = get_requirements("US", "MX", "07")
            assert req.requires_invoice_line_total is False

    def test_domestic_row_no_validation_needed(self):
        """Domestic US→US row should pass with no errors."""
        req = get_requirements("US", "US", "03")
        errors = validate_international_readiness({"ship_to_country": "US"}, req)
        assert errors == []

    def test_domestic_row_no_international_fields_required(self):
        """US→US shipment has no international requirement flags."""
        req = get_requirements("US", "US", "03")
        assert req.is_international is False
        assert req.requires_international_forms is False
        assert req.requires_commodities is False
        assert req.requires_invoice_line_total is False
        assert req.requires_description is False

    def test_kill_switch_blocks_international(self):
        """With INTERNATIONAL_ENABLED_LANES empty, international rows are rejected."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": ""}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is not None
            assert "not enabled" in req.not_shippable_reason.lower()

    def test_kill_switch_allows_when_enabled(self):
        """With INTERNATIONAL_ENABLED_LANES set, international rows are allowed."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is None
            assert req.is_international is True

    def test_domestic_service_rejected_for_international(self):
        """Domestic-only service code rejected for international lane."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            req = get_requirements("US", "CA", "03")
            assert req.not_shippable_reason is not None
            assert "domestic-only" in req.not_shippable_reason.lower()

    def test_unsupported_lane_rejected(self):
        """Unsupported lane (e.g., US→GB) is rejected."""
        req = get_requirements("US", "GB", "07")
        assert req.not_shippable_reason is not None
        assert "not currently supported" in req.not_shippable_reason.lower()

    def test_valid_international_row_passes(self):
        """Fully valid international row produces no errors."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}):
            req = get_requirements("US", "CA", "11")
            order_data = {
                "ship_to_country": "CA",
                "shipper_attention_name": "Acme Shipping",
                "shipper_phone": "5551234567",
                "ship_to_attention_name": "John Doe",
                "ship_to_phone": "5559876543",
                "shipment_description": "Electronics",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "500.00",
                "commodities": [
                    {
                        "description": "Laptop",
                        "commodity_code": "847130",
                        "origin_country": "US",
                        "quantity": 1,
                        "unit_value": "500.00",
                        "currency_code": "USD",
                    },
                ],
            }
            errors = validate_international_readiness(order_data, req)
            assert errors == []

    def test_currency_mismatch_detected(self):
        """Commodity with different currency than invoice raises E-2017."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}):
            req = get_requirements("US", "CA", "11")
            order_data = {
                "ship_to_country": "CA",
                "shipper_attention_name": "Acme",
                "shipper_phone": "5551234567",
                "ship_to_attention_name": "John",
                "ship_to_phone": "5559876543",
                "shipment_description": "Goods",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "100.00",
                "commodities": [
                    {
                        "description": "Widget",
                        "commodity_code": "123456",
                        "origin_country": "US",
                        "quantity": 1,
                        "unit_value": "100.00",
                        "currency_code": "CAD",
                    },
                ],
            }
            errors = validate_international_readiness(order_data, req)
            codes = [e.machine_code for e in errors]
            assert "CURRENCY_MISMATCH" in codes
            err = next(e for e in errors if e.machine_code == "CURRENCY_MISMATCH")
            assert err.error_code == "E-2017"

    def test_mixed_batch_domestic_and_international_rules(self):
        """In a mixed batch, domestic and international rows get different requirements."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}):
            # Domestic row
            domestic_req = get_requirements("US", "US", "03")
            assert domestic_req.is_international is False
            assert domestic_req.not_shippable_reason is None

            # International row (CA)
            intl_req = get_requirements("US", "CA", "11")
            assert intl_req.is_international is True
            assert intl_req.requires_commodities is True
            assert intl_req.not_shippable_reason is None

            # Domestic row passes validation without international fields
            domestic_errors = validate_international_readiness({}, domestic_req)
            assert domestic_errors == []

            # International row fails without international fields
            intl_errors = validate_international_readiness(
                {"ship_to_country": "CA"}, intl_req
            )
            assert len(intl_errors) > 0


# ---------------------------------------------------------------------------
# Live UPS API tests (gated behind RUN_UPS_INTEGRATION=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("RUN_UPS_INTEGRATION"),
    reason="Set RUN_UPS_INTEGRATION=1 and provide UPS credentials to run",
)
class TestMixedBatch:
    """Test batch with mixed domestic + international rows (requires UPS API)."""

    @pytest.mark.integration
    def test_domestic_rows_process_normally(self):
        """Domestic rows should not require international fields."""
        # Placeholder for live API test
        pass

    @pytest.mark.integration
    def test_international_rows_with_valid_data_succeed(self):
        """International rows with all required fields should succeed."""
        # Placeholder for live API test
        pass

    @pytest.mark.integration
    def test_aggregate_totals_correct(self):
        """Aggregate totals include shipping + duties for international."""
        # Placeholder for live API test
        pass
