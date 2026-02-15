"""Tests for international charge breakdown parsing."""

from src.services.ups_mcp_client import UPSMCPClient


class TestShipmentResponseChargeBreakdown:
    """Verify itemized charge extraction from shipment response."""

    def test_domestic_response_no_breakdown(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z999",
                    "PackageResults": {"TrackingNumber": "1Z999", "ShippingLabel": {"GraphicImage": "base64"}},
                    "ShipmentCharges": {
                        "TotalCharges": {"MonetaryValue": "15.50", "CurrencyCode": "USD"},
                    },
                }
            }
        }
        result = client._normalize_shipment_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "15.50"
        assert "chargeBreakdown" not in result or result.get("chargeBreakdown") is None

    def test_international_response_with_breakdown(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z999",
                    "PackageResults": {"TrackingNumber": "1Z999", "ShippingLabel": {"GraphicImage": "base64"}},
                    "ShipmentCharges": {
                        "TransportationCharges": {"MonetaryValue": "45.50", "CurrencyCode": "USD"},
                        "ServiceOptionsCharges": {"MonetaryValue": "5.00", "CurrencyCode": "USD"},
                        "TotalCharges": {"MonetaryValue": "62.50", "CurrencyCode": "USD"},
                        "DutyAndTaxCharges": {"MonetaryValue": "12.00", "CurrencyCode": "USD"},
                    },
                }
            }
        }
        result = client._normalize_shipment_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "62.50"
        breakdown = result.get("chargeBreakdown")
        assert breakdown is not None
        assert breakdown["version"] == "1.0"
        assert breakdown["transportationCharges"]["monetaryValue"] == "45.50"
        assert breakdown["dutiesAndTaxes"]["monetaryValue"] == "12.00"


class TestRateResponseChargeBreakdown:
    """Verify itemized charge extraction from rate response."""

    def test_domestic_rate_no_breakdown(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "TotalCharges": {"MonetaryValue": "20.00", "CurrencyCode": "USD"},
                }
            }
        }
        result = client._normalize_rate_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "20.00"

    def test_international_rate_with_duties(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "TransportationCharges": {"MonetaryValue": "35.00", "CurrencyCode": "USD"},
                    "ServiceOptionsCharges": {"MonetaryValue": "3.00", "CurrencyCode": "USD"},
                    "TotalCharges": {"MonetaryValue": "50.00", "CurrencyCode": "USD"},
                }
            }
        }
        result = client._normalize_rate_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "50.00"
        breakdown = result.get("chargeBreakdown")
        assert breakdown is not None
        assert breakdown["transportationCharges"]["monetaryValue"] == "35.00"
