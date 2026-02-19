"""Tests for international shipping rules engine."""

import os
from unittest.mock import patch

from src.services.international_rules import (
    RequirementSet,
    ValidationError,
    get_requirements,
    validate_international_readiness,
    is_lane_enabled,
    SUPPORTED_INTERNATIONAL_SERVICES,
)


class TestGetRequirements:
    """Test lane-driven requirement determination."""

    def test_domestic_us_to_us(self):
        req = get_requirements("US", "US", "03")
        assert req.is_international is False
        assert req.requires_international_forms is False

    def test_us_to_ca_is_international(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.is_international is True
            assert req.requires_description is True
            assert req.requires_shipper_contact is True
            assert req.requires_recipient_contact is True
            assert req.requires_invoice_line_total is True
            assert req.requires_international_forms is True
            assert req.requires_commodities is True
            assert req.form_type == "01"
            assert req.currency_code == "USD"

    def test_us_to_mx_no_invoice_line_total(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            req = get_requirements("US", "MX", "07")
            assert req.is_international is True
            assert req.requires_invoice_line_total is False
            assert req.requires_international_forms is True

    def test_us_to_pr_requires_invoice_line_total(self):
        req = get_requirements("US", "PR", "03")
        assert req.is_international is False  # PR is US territory
        assert req.requires_invoice_line_total is True

    def test_feature_flag_rejects_unlisted_lane(self):
        """Lane not in INTERNATIONAL_ENABLED_LANES is rejected."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "GB", "07")
            assert req.not_shippable_reason is not None
            assert "not enabled" in req.not_shippable_reason.lower()

    def test_wildcard_enables_all_lanes(self):
        """Wildcard * enables any international lane."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            for dest in ("GB", "JP", "AU", "DE"):
                req = get_requirements("US", dest, "07")
                assert req.not_shippable_reason is None, f"US→{dest} rejected with wildcard"
                assert req.is_international is True

    def test_wildcard_enables_non_us_origin(self):
        """Wildcard enables non-US origin lanes too."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            req = get_requirements("DE", "FR", "07")
            assert req.not_shippable_reason is None
            assert req.is_international is True

    def test_ups_letter_exemption(self):
        """UPS Letter (packaging 01) reduces requirements."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            req = get_requirements("US", "GB", "07", packaging_code="01")
            assert req.is_international is True
            assert req.requires_description is False
            assert req.requires_international_forms is False
            assert req.requires_commodities is False
            assert req.requires_shipper_contact is True
            assert req.requires_recipient_contact is True

    def test_eu_to_eu_standard_exemption(self):
        """EU-to-EU Standard (service 11) reduces requirements."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            req = get_requirements("DE", "FR", "11")
            assert req.is_international is True
            assert req.requires_description is False
            assert req.requires_international_forms is False
            assert req.requires_commodities is False
            assert req.requires_shipper_contact is True

    def test_eu_to_eu_non_standard_full_requirements(self):
        """EU-to-EU with non-Standard service requires full documentation."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            req = get_requirements("DE", "FR", "07")
            assert req.is_international is True
            assert req.requires_description is True
            assert req.requires_international_forms is True
            assert req.requires_commodities is True

    def test_eu_to_non_eu_full_requirements(self):
        """EU to non-EU requires full documentation."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            req = get_requirements("DE", "US", "07")
            assert req.is_international is True
            assert req.requires_description is True
            assert req.requires_international_forms is True

    def test_invalid_service_for_lane(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "CA", "03")  # Ground is domestic only
            assert req.not_shippable_reason is not None

    def test_all_international_services_accepted_for_ca(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            for code in SUPPORTED_INTERNATIONAL_SERVICES:
                req = get_requirements("US", "CA", code)
                assert req.not_shippable_reason is None, f"Service {code} rejected for US→CA"

    def test_requirement_set_has_rule_version(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.rule_version is not None
            assert req.effective_date is not None

    def test_kill_switch_blocks_enabled_lane(self):
        """P0: get_requirements() must enforce is_lane_enabled() kill switch."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": ""}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is not None
            assert "disabled" in req.not_shippable_reason.lower() or "not enabled" in req.not_shippable_reason.lower()

    def test_kill_switch_allows_when_enabled(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is None
            assert req.is_international is True


class TestValidateInternationalReadiness:
    """Test pre-submit validation of order data."""

    def test_valid_international_order(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane Doe",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme Corp",
                "shipment_description": "Coffee Beans",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "150.00",
                "commodities": [
                    {
                        "description": "Coffee Beans",
                        "commodity_code": "090111",
                        "origin_country": "CO",
                        "quantity": 5,
                        "unit_value": "30.00",
                    }
                ],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            assert errors == []

    def test_missing_recipient_phone(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_attention_name": "Jane Doe",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme Corp",
                "shipment_description": "Coffee Beans",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "150.00",
                "commodities": [{"description": "Coffee", "commodity_code": "090111",
                                "origin_country": "CO", "quantity": 1, "unit_value": "30.00"}],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            assert len(errors) == 1
            assert errors[0].machine_code == "MISSING_RECIPIENT_PHONE"
            assert errors[0].field_path == "ShipTo.Phone.Number"

    def test_recipient_attention_defaults_to_ship_to_name(self):
        """Missing recipient attention should auto-default to ship_to_name."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_name": "Jane Doe",
                "ship_to_phone": "6045551234",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme Corp",
                "shipment_description": "Coffee Beans",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "150.00",
                "commodities": [
                    {
                        "description": "Coffee Beans",
                        "commodity_code": "090111",
                        "origin_country": "CO",
                        "quantity": 5,
                        "unit_value": "30.00",
                    }
                ],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_RECIPIENT_ATTENTION_NAME" not in codes
            assert order["ship_to_attention_name"] == "Jane Doe"

    def test_missing_recipient_state_for_gb(self):
        """Destination-specific rule: GB requires ship_to_state."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-GB"}, clear=False):
            order = {
                "ship_to_country": "GB",
                "ship_to_phone": "442079430800",
                "ship_to_attention_name": "Elizabeth Taylor",
                "shipper_phone": "12125551234",
                "shipper_attention_name": "Warehouse Desk",
                "shipment_description": "Books",
                "commodities": [{
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }],
            }
            req = get_requirements("US", "GB", "07")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_RECIPIENT_STATE" in codes
            state_error = next(e for e in errors if e.machine_code == "MISSING_RECIPIENT_STATE")
            assert state_error.field_path == "ShipTo.Address.StateProvinceCode"

    def test_invalid_recipient_state_when_matches_postal_code(self):
        """State/province copied from postal code should fail validation."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-GB"}, clear=False):
            order = {
                "ship_to_country": "GB",
                "ship_to_state": "W1J 7NT",
                "ship_to_postal_code": "W1J 7NT",
                "ship_to_phone": "442079430800",
                "ship_to_attention_name": "Elizabeth Taylor",
                "shipper_phone": "12125551234",
                "shipper_attention_name": "Warehouse Desk",
                "shipment_description": "Books",
                "commodities": [{
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }],
            }
            req = get_requirements("US", "GB", "07")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "INVALID_RECIPIENT_STATE" in codes

    def test_invalid_recipient_state_for_gb_with_digits(self):
        """GB state/province should reject postal-style values with digits."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-GB"}, clear=False):
            order = {
                "ship_to_country": "GB",
                "ship_to_state": "W1J7NT",
                "ship_to_postal_code": "W1J 7NT",
                "ship_to_phone": "442079430800",
                "ship_to_attention_name": "Elizabeth Taylor",
                "shipper_phone": "12125551234",
                "shipper_attention_name": "Warehouse Desk",
                "shipment_description": "Books",
                "commodities": [{
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }],
            }
            req = get_requirements("US", "GB", "07")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "INVALID_RECIPIENT_STATE" in codes

    def test_gb_state_name_is_normalized_to_short_code(self):
        """GB state names like 'Greater London' normalize to short code."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-GB"}, clear=False):
            order = {
                "ship_to_country": "GB",
                "ship_to_state": "Greater London",
                "ship_to_postal_code": "SW1A 1AA",
                "ship_to_phone": "442079430800",
                "ship_to_attention_name": "Elizabeth Taylor",
                "shipper_phone": "12125551234",
                "shipper_attention_name": "Warehouse Desk",
                "shipment_description": "Books",
                "commodities": [{
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }],
            }
            req = get_requirements("US", "GB", "07")
            errors = validate_international_readiness(order, req)
            assert not any(e.machine_code == "INVALID_RECIPIENT_STATE" for e in errors)
            assert order["ship_to_state"] == "LND"

    def test_missing_commodities(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme",
                "shipment_description": "Goods",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "50.00",
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "MISSING_COMMODITIES" in codes

    def test_invalid_hs_code_format(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme",
                "shipment_description": "Goods",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "50.00",
                "commodities": [{"description": "Widget", "commodity_code": "ABC",
                                "origin_country": "US", "quantity": 1, "unit_value": "10.00"}],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "INVALID_HS_CODE" in codes

    def test_hs_code_with_periods_is_normalized(self):
        """HS codes with periods (standard tariff notation) are stripped to digits."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            comm = {"description": "Bearings", "commodity_code": "8482.10",
                    "origin_country": "US", "quantity": 1, "unit_value": "25.00"}
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme",
                "shipment_description": "Bearings",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "25.00",
                "commodities": [comm],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "INVALID_HS_CODE" not in codes
            # Verify write-back: commodity_code should now be digits-only
            assert comm["commodity_code"] == "848210"

    def test_hs_code_with_hyphens_is_normalized(self):
        """HS codes with hyphens are stripped to digits."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            comm = {"description": "Parts", "commodity_code": "8487-90-00",
                    "origin_country": "US", "quantity": 2, "unit_value": "10.00"}
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme",
                "shipment_description": "Parts",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "20.00",
                "commodities": [comm],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "INVALID_HS_CODE" not in codes
            assert comm["commodity_code"] == "84879000"

    def test_currency_mismatch_e2017(self):
        """P2: E-2017 must fire when commodity currency differs from invoice currency."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme",
                "shipment_description": "Goods",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "50.00",
                "commodities": [
                    {"description": "Widget", "commodity_code": "999999",
                     "origin_country": "US", "quantity": 1, "unit_value": "50.00",
                     "currency_code": "CAD"},  # Mismatch!
                ],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "CURRENCY_MISMATCH" in codes
            # Verify it maps to E-2017
            mismatch_error = next(e for e in errors if e.machine_code == "CURRENCY_MISMATCH")
            assert mismatch_error.error_code == "E-2017"

    def test_domestic_returns_no_errors(self):
        order = {"ship_to_country": "US"}
        req = get_requirements("US", "US", "03")
        errors = validate_international_readiness(order, req)
        assert errors == []


class TestLaneEnabled:
    """Test feature flag gating."""

    def test_default_lanes_disabled(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": ""}, clear=False):
            assert is_lane_enabled("US", "CA") is False

    def test_ca_lane_enabled(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            assert is_lane_enabled("US", "CA") is True
            assert is_lane_enabled("US", "MX") is True
            assert is_lane_enabled("US", "GB") is False

    def test_wildcard_enables_all(self):
        """Wildcard * enables any lane."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "*"}, clear=False):
            assert is_lane_enabled("US", "GB") is True
            assert is_lane_enabled("DE", "FR") is True
            assert is_lane_enabled("JP", "AU") is True
