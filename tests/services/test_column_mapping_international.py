"""Tests for international column mapping support."""

from src.services.column_mapping import (
    _FIELD_TO_ORDER_DATA,
    validate_mapping,
    SERVICE_NAME_TO_CODE,
)


class TestInternationalFieldMappings:
    """Verify international fields are mappable."""

    def test_shipper_attention_name_mappable(self):
        assert "shipper.attentionName" in _FIELD_TO_ORDER_DATA
        assert _FIELD_TO_ORDER_DATA["shipper.attentionName"] == "shipper_attention_name"

    def test_ship_to_attention_name_mappable(self):
        assert "shipTo.attentionName" in _FIELD_TO_ORDER_DATA

    def test_invoice_currency_mappable(self):
        assert "invoiceLineTotal.currencyCode" in _FIELD_TO_ORDER_DATA
        assert _FIELD_TO_ORDER_DATA["invoiceLineTotal.currencyCode"] == "invoice_currency_code"

    def test_invoice_value_mappable(self):
        assert "invoiceLineTotal.monetaryValue" in _FIELD_TO_ORDER_DATA

    def test_invoice_number_mappable(self):
        assert "internationalForms.invoiceNumber" in _FIELD_TO_ORDER_DATA
        assert _FIELD_TO_ORDER_DATA["internationalForms.invoiceNumber"] == "invoice_number"

    def test_shipment_description_mappable(self):
        assert "shipmentDescription" in _FIELD_TO_ORDER_DATA


class TestContextAwareValidation:
    """Verify validation adapts for international shipments."""

    def test_domestic_does_not_require_state(self):
        # Domestic still requires state
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }
        errors = validate_mapping(mapping, destination_country="US")
        field_errors = [e for e in errors if "stateProvinceCode" in e]
        assert len(field_errors) == 1

    def test_international_state_optional(self):
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }
        errors = validate_mapping(mapping, destination_country="CA")
        field_errors = [e for e in errors if "stateProvinceCode" in e]
        assert len(field_errors) == 0  # State optional for international


class TestInternationalServiceCodes:
    """Verify international service name mapping."""

    def test_worldwide_express_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide express") == "07"

    def test_worldwide_expedited_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide expedited") == "08"

    def test_ups_standard_code(self):
        assert SERVICE_NAME_TO_CODE.get("ups standard") == "11"

    def test_bare_standard_not_mapped(self):
        """P1: bare 'standard' must NOT map to international service."""
        assert "standard" not in SERVICE_NAME_TO_CODE

    def test_worldwide_saver_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide saver") == "65"

    def test_worldwide_express_plus_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide express plus") == "54"
