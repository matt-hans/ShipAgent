"""Tests for international payload builder enrichment."""

import os
from unittest.mock import patch

from src.services.ups_payload_builder import (
    build_international_forms,
    build_shipment_request,
    build_ups_api_payload,
    build_ups_rate_payload,
    normalize_phone,
    normalize_zip,
)


class TestNormalizePhoneInternational:
    """Verify phone normalization handles international numbers."""

    def test_us_10_digit(self):
        assert normalize_phone("212-555-1234") == "2125551234"

    def test_international_with_country_code(self):
        result = normalize_phone("+44 20 7946 0958")
        assert result == "442079460958"

    def test_short_international_accepted(self):
        # 7-digit numbers valid in some countries
        result = normalize_phone("1234567")
        assert len(result) >= 7

    def test_none_returns_empty(self):
        # No more placeholder — missing phone should be caught by validation
        result = normalize_phone(None)
        assert result == ""

    def test_empty_returns_empty(self):
        result = normalize_phone("")
        assert result == ""


class TestNormalizeZipInternational:
    """Verify ZIP normalization passes through international codes."""

    def test_us_5_digit(self):
        assert normalize_zip("10001") == "10001"

    def test_canadian_postal_code(self):
        assert normalize_zip("V6B 3K9") == "V6B 3K9"

    def test_uk_postal_code(self):
        assert normalize_zip("W1A 2HH") == "W1A 2HH"

    def test_mexican_postal_code(self):
        assert normalize_zip("06600") == "06600"


class TestBuildInternationalForms:
    """Verify InternationalForms construction."""

    def test_builds_commercial_invoice(self):
        commodities = [
            {
                "description": "Coffee Beans",
                "commodity_code": "090111",
                "origin_country": "CO",
                "quantity": 5,
                "unit_value": "30.00",
                "unit_of_measure": "PCS",
            }
        ]
        forms = build_international_forms(
            commodities=commodities,
            currency_code="USD",
            form_type="01",
            reason_for_export="SALE",
        )
        assert forms["FormType"] == "01"
        assert forms["CurrencyCode"] == "USD"
        assert forms["ReasonForExport"] == "SALE"
        assert len(forms["Product"]) == 1
        product = forms["Product"][0]
        assert product["Description"] == "Coffee Beans"
        assert product["CommodityCode"] == "090111"
        assert product["OriginCountryCode"] == "CO"
        assert product["Unit"]["Number"] == "5"
        assert product["Unit"]["Value"] == "30.00"

    def test_multi_commodity(self):
        commodities = [
            {"description": "Item A", "commodity_code": "090111",
             "origin_country": "US", "quantity": 2, "unit_value": "10.00"},
            {"description": "Item B", "commodity_code": "123456",
             "origin_country": "MX", "quantity": 1, "unit_value": "25.00"},
        ]
        forms = build_international_forms(
            commodities=commodities,
            currency_code="USD",
        )
        assert len(forms["Product"]) == 2
        assert forms["Product"][0]["Description"] == "Item A"
        assert forms["Product"][1]["Description"] == "Item B"

    def test_default_unit_of_measure(self):
        commodities = [
            {"description": "Widget", "commodity_code": "999999",
             "origin_country": "US", "quantity": 1, "unit_value": "5.00"},
        ]
        forms = build_international_forms(commodities=commodities, currency_code="USD")
        uom = forms["Product"][0]["Unit"]["UnitOfMeasurement"]
        assert uom["Code"] == "PCS"

    def test_idempotent_call(self):
        commodities = [
            {"description": "Widget", "commodity_code": "999999",
             "origin_country": "US", "quantity": 1, "unit_value": "5.00"},
        ]
        forms1 = build_international_forms(commodities=commodities, currency_code="USD")
        forms2 = build_international_forms(commodities=commodities, currency_code="USD")
        assert forms1 == forms2


class TestPayloadIntegration:
    """P0: Assert actual final UPS payload JSON using the correct two-step chain.

    Call chain: build_shipment_request(order_data, shipper, service_code)
               -> simplified dict (enriched with international fields)
               -> build_ups_api_payload(simplified, account_number)
               -> final UPS API payload
    """

    def test_us_to_ca_payload_has_international_forms(self):
        """Full payload for US->CA must contain InternationalForms + InvoiceLineTotal."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            order_data = {
                "ship_to_name": "Jane Doe",
                "ship_to_address1": "100 Queen St W",
                "ship_to_city": "Toronto",
                "ship_to_state": "ON",
                "ship_to_zip": "M5H 2N2",
                "ship_to_country": "CA",
                "ship_to_phone": "4165551234",
                "ship_to_attention_name": "Jane Doe",
                "shipper_attention_name": "Acme Corp",
                "shipper_phone": "2125551234",
                "shipment_description": "Coffee Beans",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "150.00",
                "weight": "5.0",
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
            shipper = {
                "name": "Acme Corp",
                "addressLine1": "123 Main St",
                "city": "New York",
                "stateProvinceCode": "NY",
                "postalCode": "10001",
                "countryCode": "US",
                "shipperNumber": "ABC123",
            }

            # Step 1: build_shipment_request enriches simplified with intl fields
            simplified = build_shipment_request(
                order_data=order_data, shipper=shipper, service_code="11",
            )
            # Verify enrichment happened at this layer
            assert simplified.get("internationalForms") is not None
            assert simplified.get("invoiceLineTotal") is not None
            assert simplified.get("destinationCountry") == "CA"

            # Step 2: build_ups_api_payload reads from simplified (no order_data)
            payload = build_ups_api_payload(simplified, account_number="ABC123")

            shipment = payload["ShipmentRequest"]["Shipment"]
            # InvoiceLineTotal present for US->CA
            assert "InvoiceLineTotal" in shipment
            assert shipment["InvoiceLineTotal"]["CurrencyCode"] == "USD"
            # InternationalForms present
            sso = shipment.get("ShipmentServiceOptions", {})
            assert "InternationalForms" in sso
            forms = sso["InternationalForms"]
            assert forms["FormType"] == "01"
            assert len(forms["Product"]) == 1
            assert forms["Product"][0]["CommodityCode"] == "090111"
            # Contact fields
            assert "AttentionName" in shipment["ShipTo"]
            assert "Phone" in shipment["ShipTo"]
            # Description
            assert shipment.get("Description") == "Coffee Beans"

    def test_us_to_mx_payload_no_invoice_line_total(self):
        """US->MX does NOT require InvoiceLineTotal."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            order_data = {
                "ship_to_name": "Carlos Garcia",
                "ship_to_address1": "Av Insurgentes Sur 1000",
                "ship_to_city": "Mexico City",
                "ship_to_zip": "06600",
                "ship_to_country": "MX",
                "ship_to_phone": "5255551234",
                "ship_to_attention_name": "Carlos Garcia",
                "shipper_attention_name": "Acme Corp",
                "shipper_phone": "2125551234",
                "shipment_description": "Electronics",
                "weight": "3.0",
                "commodities": [
                    {
                        "description": "Laptop",
                        "commodity_code": "847130",
                        "origin_country": "US",
                        "quantity": 1,
                        "unit_value": "999.00",
                    }
                ],
            }
            shipper = {
                "name": "Acme Corp",
                "addressLine1": "123 Main St",
                "city": "New York",
                "stateProvinceCode": "NY",
                "postalCode": "10001",
                "countryCode": "US",
                "shipperNumber": "ABC123",
            }

            simplified = build_shipment_request(
                order_data=order_data, shipper=shipper, service_code="07",
            )
            payload = build_ups_api_payload(simplified, account_number="ABC123")

            shipment = payload["ShipmentRequest"]["Shipment"]
            # NO InvoiceLineTotal for US->MX
            assert "InvoiceLineTotal" not in shipment
            # InternationalForms still present
            sso = shipment.get("ShipmentServiceOptions", {})
            assert "InternationalForms" in sso

    def test_domestic_payload_unchanged(self):
        """Domestic US->US payload must NOT contain any international sections."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_address1": "456 Oak Ave",
            "ship_to_city": "Los Angeles",
            "ship_to_state": "CA",
            "ship_to_zip": "90001",
            "ship_to_country": "US",
            "weight": "2.0",
        }
        shipper = {
            "name": "Acme Corp",
            "addressLine1": "123 Main St",
            "city": "New York",
            "stateProvinceCode": "NY",
            "postalCode": "10001",
            "countryCode": "US",
            "shipperNumber": "ABC123",
        }

        simplified = build_shipment_request(
            order_data=order_data, shipper=shipper, service_code="03",
        )
        payload = build_ups_api_payload(simplified, account_number="ABC123")

        shipment = payload["ShipmentRequest"]["Shipment"]
        assert "InvoiceLineTotal" not in shipment
        assert "InternationalForms" not in shipment.get("ShipmentServiceOptions", {})

    def test_rate_payload_includes_invoice_line_total_for_ca(self):
        """Rate payload for US->CA must include InvoiceLineTotal for accurate quotes."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            order_data = {
                "ship_to_name": "Jane Doe",
                "ship_to_address1": "100 Queen St W",
                "ship_to_city": "Toronto",
                "ship_to_state": "ON",
                "ship_to_zip": "M5H 2N2",
                "ship_to_country": "CA",
                "ship_to_phone": "4165551234",
                "ship_to_attention_name": "Jane Doe",
                "shipper_attention_name": "Acme Corp",
                "shipper_phone": "2125551234",
                "shipment_description": "Coffee Beans",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "150.00",
                "weight": "5.0",
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
            shipper = {
                "name": "Acme Corp",
                "addressLine1": "123 Main St",
                "city": "New York",
                "stateProvinceCode": "NY",
                "postalCode": "10001",
                "countryCode": "US",
                "shipperNumber": "ABC123",
            }

            simplified = build_shipment_request(
                order_data=order_data, shipper=shipper, service_code="11",
            )
            rate_payload = build_ups_rate_payload(simplified, account_number="ABC123")

            rate_shipment = rate_payload["RateRequest"]["Shipment"]
            # InvoiceLineTotal present for accurate rate quotes
            assert "InvoiceLineTotal" in rate_shipment
            assert rate_shipment["InvoiceLineTotal"]["CurrencyCode"] == "USD"
            # Contact fields are required by UPS for international rating
            assert rate_shipment["Shipper"]["AttentionName"] == "Acme Corp"
            assert rate_shipment["Shipper"]["Phone"]["Number"] == "2125551234"
            assert rate_shipment["ShipTo"]["AttentionName"] == "Jane Doe"
            assert rate_shipment["ShipTo"]["Phone"]["Number"] == "4165551234"
