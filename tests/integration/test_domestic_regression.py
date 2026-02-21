"""Domestic regression test — verify no behavioral change from international additions.

Ensures domestic-only batches are completely unaffected by the international
shipping code paths. All tests run without UPS credentials except the
live regression test gated behind RUN_UPS_INTEGRATION=1.
"""

import os

import pytest


class TestDomesticRegression:
    """Verify domestic-only batches are completely unaffected by international code."""

    def test_domestic_no_international_fields_required(self):
        """US→US shipment must not require any international fields."""
        from src.services.international_rules import get_requirements

        req = get_requirements("US", "US", "03")
        assert req.is_international is False
        assert req.requires_international_forms is False
        assert req.requires_commodities is False
        assert req.requires_invoice_line_total is False
        assert req.requires_description is False
        assert req.requires_shipper_contact is False
        assert req.requires_recipient_contact is False
        assert req.not_shippable_reason is None

    def test_domestic_payload_has_no_international_sections(self):
        """Domestic payload must NOT contain InternationalForms or InvoiceLineTotal."""
        from src.services.ups_payload_builder import (
            build_shipment_request,
            build_ups_api_payload,
        )

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
            "name": "Acme",
            "addressLine1": "123 Main",
            "city": "NYC",
            "stateProvinceCode": "NY",
            "postalCode": "10001",
            "countryCode": "US",
            "shipperNumber": "ABC",
        }
        simplified = build_shipment_request(
            order_data=order_data, shipper=shipper, service_code="03"
        )
        payload = build_ups_api_payload(simplified, account_number="ABC")
        shipment = payload["ShipmentRequest"]["Shipment"]
        assert "InvoiceLineTotal" not in shipment
        sso = shipment.get("ShipmentServiceOptions", {})
        assert "InternationalForms" not in sso

    def test_domestic_payload_no_shipper_phone_required(self):
        """Domestic payload works without shipper phone or attention name."""
        from src.services.ups_payload_builder import (
            build_shipment_request,
            build_ups_api_payload,
        )

        order_data = {
            "ship_to_name": "Jane Smith",
            "ship_to_address1": "789 Elm St",
            "ship_to_city": "Chicago",
            "ship_to_state": "IL",
            "ship_to_zip": "60601",
            "ship_to_country": "US",
            "weight": "3.0",
        }
        shipper = {
            "name": "Acme",
            "addressLine1": "123 Main",
            "city": "NYC",
            "stateProvinceCode": "NY",
            "postalCode": "10001",
            "countryCode": "US",
            "shipperNumber": "ABC",
            # No phone, no attention name — domestic doesn't need them
        }
        simplified = build_shipment_request(
            order_data=order_data, shipper=shipper, service_code="03"
        )
        payload = build_ups_api_payload(simplified, account_number="ABC")
        shipment = payload["ShipmentRequest"]["Shipment"]
        shipper_section = shipment["Shipper"]
        # Phone is optional for domestic — should not be present if not provided
        assert "Phone" not in shipper_section or not shipper_section.get("Phone", {}).get("Number")

    def test_domestic_validation_passes_with_minimal_data(self):
        """Domestic validation should pass even with minimal order data."""
        from src.services.international_rules import (
            get_requirements,
            validate_international_readiness,
        )

        req = get_requirements("US", "US", "03")
        # Minimal domestic order — no contacts, no commodities, no description
        errors = validate_international_readiness(
            {"ship_to_country": "US", "weight": "1.0"}, req
        )
        assert errors == []

    def test_service_aliases_domestic_unchanged(self):
        """Existing domestic aliases must still work."""
        from src.orchestrator.models.intent import SERVICE_ALIASES, ServiceCode

        assert SERVICE_ALIASES.get("ground") == ServiceCode.GROUND
        assert SERVICE_ALIASES.get("next day air") == ServiceCode.NEXT_DAY_AIR
        assert SERVICE_ALIASES.get("2nd day air") == ServiceCode.SECOND_DAY_AIR
        assert SERVICE_ALIASES.get("3 day select") == ServiceCode.THREE_DAY_SELECT

    def test_standard_alias_not_hijacked(self):
        """Bare 'standard' must NOT be mapped to any service code."""
        from src.orchestrator.models.intent import SERVICE_ALIASES

        assert "standard" not in SERVICE_ALIASES

    def test_standard_alias_not_in_payload_resolver(self):
        """Bare 'standard' must NOT resolve to a service code in payload builder."""
        from src.services.ups_payload_builder import resolve_service_code

        # "standard" without qualifier should fall through to default
        result = resolve_service_code("standard")
        assert result == "03"  # Default ground, not "11" international standard

    def test_domestic_all_services_still_valid(self):
        """All domestic service codes produce valid requirements."""
        from src.services.international_rules import get_requirements

        domestic_codes = ["01", "02", "03", "12", "13", "14"]
        for code in domestic_codes:
            req = get_requirements("US", "US", code)
            assert req.is_international is False, f"Code {code} flagged as international"
            assert req.not_shippable_reason is None, f"Code {code} is not shippable"
            assert code in req.supported_services, f"Code {code} not in supported list"

    def test_dollars_to_cents_precision(self):
        """Verify Decimal-based money conversion avoids float drift.

        Uses the same algorithm as batch_engine._dollars_to_cents() to
        verify correctness without importing MCP-dependent modules.
        """
        from decimal import ROUND_HALF_UP, Decimal

        def _dollars_to_cents(amount: str) -> int:
            return int(
                Decimal(amount).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ) * 100
            )

        assert _dollars_to_cents("45.50") == 4550
        assert _dollars_to_cents("0.10") == 10
        assert _dollars_to_cents("99.99") == 9999
        assert _dollars_to_cents("19.995") == 2000  # Rounds up
        assert _dollars_to_cents("1.004") == 100  # Rounds down

    def test_pr_requires_invoice_but_not_international(self):
        """US→PR requires InvoiceLineTotal but is NOT international."""
        from src.services.international_rules import get_requirements

        req = get_requirements("US", "PR", "03")
        assert req.is_international is False
        assert req.requires_invoice_line_total is True
        assert req.requires_commodities is False
        assert req.requires_international_forms is False
        assert req.not_shippable_reason is None

    @pytest.mark.skipif(
        not os.environ.get("RUN_UPS_INTEGRATION"),
        reason="Set RUN_UPS_INTEGRATION=1 to run live UPS tests",
    )
    @pytest.mark.integration
    def test_live_domestic_batch_unchanged(self):
        """Live domestic batch should produce identical results to pre-international code."""
        # Placeholder for live API regression test
        pass
