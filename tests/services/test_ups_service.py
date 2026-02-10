"""Tests for UPS service layer (direct ToolManager import)."""

import json
import pytest
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp.exceptions import ToolError


class TestUPSServiceInit:
    """Test UPSService initialization."""

    def test_creates_tool_manager(self):
        """Test ToolManager is created with credentials."""
        with patch("ups_mcp.tools.ToolManager") as MockTM:
            from src.services.ups_service import UPSService

            svc = UPSService(
                base_url="https://onlinetools.ups.com",
                client_id="test_id",
                client_secret="test_secret",
            )
            MockTM.assert_called_once_with(
                base_url="https://onlinetools.ups.com",
                client_id="test_id",
                client_secret="test_secret",
            )


class TestUPSServiceCreateShipment:
    """Test create_shipment response normalization."""

    def _make_service(self):
        """Create UPSService with mocked ToolManager."""
        with patch("ups_mcp.tools.ToolManager") as MockTM:
            from src.services.ups_service import UPSService

            svc = UPSService(
                base_url="https://test.ups.com",
                client_id="id",
                client_secret="secret",
            )
            return svc, MockTM.return_value

    def test_extracts_tracking_number(self):
        """Test tracking number extraction from UPS response."""
        svc, mock_tm = self._make_service()
        mock_tm.create_shipment.return_value = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z999AA10123456784",
                    "PackageResults": {
                        "TrackingNumber": "1Z999AA10123456784",
                        "ShippingLabel": {
                            "GraphicImage": "base64labeldata=="
                        },
                    },
                    "ShipmentCharges": {
                        "TotalCharges": {
                            "MonetaryValue": "15.50",
                            "CurrencyCode": "USD",
                        }
                    },
                }
            }
        }

        result = svc.create_shipment(request_body={"ShipmentRequest": {}})

        assert result["success"] is True
        assert result["trackingNumbers"] == ["1Z999AA10123456784"]
        assert result["shipmentIdentificationNumber"] == "1Z999AA10123456784"
        assert result["totalCharges"]["monetaryValue"] == "15.50"
        assert result["totalCharges"]["currencyCode"] == "USD"

    def test_handles_multi_package(self):
        """Test multi-package response with array of PackageResults."""
        svc, mock_tm = self._make_service()
        mock_tm.create_shipment.return_value = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1ZSHIP001",
                    "PackageResults": [
                        {
                            "TrackingNumber": "1ZPKG001",
                            "ShippingLabel": {"GraphicImage": "label1=="},
                        },
                        {
                            "TrackingNumber": "1ZPKG002",
                            "ShippingLabel": {"GraphicImage": "label2=="},
                        },
                    ],
                    "ShipmentCharges": {
                        "TotalCharges": {"MonetaryValue": "25.00", "CurrencyCode": "USD"}
                    },
                }
            }
        }

        result = svc.create_shipment(request_body={"ShipmentRequest": {}})

        assert result["success"] is True
        assert result["trackingNumbers"] == ["1ZPKG001", "1ZPKG002"]

    def test_translates_tool_error(self):
        """Test ToolError is caught and translated."""
        svc, mock_tm = self._make_service()
        mock_tm.create_shipment.side_effect = ToolError(
            json.dumps({
                "status_code": 400,
                "code": "120100",
                "message": "Address validation failed",
                "details": {},
            })
        )

        from src.services.ups_service import UPSServiceError

        with pytest.raises(UPSServiceError) as exc_info:
            svc.create_shipment(request_body={})

        assert exc_info.value.code == "E-3003"


class TestUPSServiceGetRate:
    """Test rate_shipment response normalization."""

    def _make_service(self):
        """Create UPSService with mocked ToolManager."""
        with patch("ups_mcp.tools.ToolManager") as MockTM:
            from src.services.ups_service import UPSService

            svc = UPSService(
                base_url="https://test.ups.com",
                client_id="id",
                client_secret="secret",
            )
            return svc, MockTM.return_value

    def test_extracts_rate(self):
        """Test rate extraction from UPS response."""
        svc, mock_tm = self._make_service()
        mock_tm.rate_shipment.return_value = {
            "RateResponse": {
                "RatedShipment": [{
                    "TotalCharges": {
                        "MonetaryValue": "12.50",
                        "CurrencyCode": "USD",
                    },
                    "Service": {"Code": "03"},
                }]
            }
        }

        result = svc.get_rate(request_body={})

        assert result["success"] is True
        assert result["totalCharges"]["monetaryValue"] == "12.50"
        assert result["totalCharges"]["amount"] == "12.50"

    def test_shop_returns_multiple_rates(self):
        """Test shop mode returns array of rates."""
        svc, mock_tm = self._make_service()
        mock_tm.rate_shipment.return_value = {
            "RateResponse": {
                "RatedShipment": [
                    {
                        "TotalCharges": {"MonetaryValue": "12.50", "CurrencyCode": "USD"},
                        "Service": {"Code": "03"},
                    },
                    {
                        "TotalCharges": {"MonetaryValue": "45.00", "CurrencyCode": "USD"},
                        "Service": {"Code": "01"},
                    },
                ]
            }
        }

        result = svc.get_rate_shop(request_body={})

        assert len(result["rates"]) == 2
        assert result["rates"][0]["serviceCode"] == "03"


class TestUPSServiceValidateAddress:
    """Test validate_address response normalization."""

    def _make_service(self):
        """Create UPSService with mocked ToolManager."""
        with patch("ups_mcp.tools.ToolManager") as MockTM:
            from src.services.ups_service import UPSService

            svc = UPSService(
                base_url="https://test.ups.com",
                client_id="id",
                client_secret="secret",
            )
            return svc, MockTM.return_value

    def test_valid_address(self):
        """Test valid address returns status 'valid'."""
        svc, mock_tm = self._make_service()
        mock_tm.validate_address.return_value = {
            "XAVResponse": {
                "ValidAddressIndicator": "",
                "Candidate": {
                    "AddressKeyFormat": {
                        "AddressLine": ["123 MAIN ST"],
                        "PoliticalDivision2": "LOS ANGELES",
                        "PoliticalDivision1": "CA",
                        "PostcodePrimaryLow": "90001",
                    }
                },
            }
        }

        result = svc.validate_address(
            addressLine1="123 Main St",
            city="Los Angeles",
            stateProvinceCode="CA",
            postalCode="90001",
            countryCode="US",
        )

        assert result["status"] == "valid"

    def test_invalid_address(self):
        """Test no candidates returns status 'invalid'."""
        svc, mock_tm = self._make_service()
        mock_tm.validate_address.return_value = {
            "XAVResponse": {"NoCandidatesIndicator": ""}
        }

        result = svc.validate_address(
            addressLine1="999 Fake St",
            city="Nowhere",
            stateProvinceCode="XX",
            postalCode="00000",
            countryCode="US",
        )

        assert result["status"] == "invalid"


class TestUPSServiceVoidShipment:
    """Test void_shipment response normalization."""

    def _make_service(self):
        """Create UPSService with mocked ToolManager."""
        with patch("ups_mcp.tools.ToolManager") as MockTM:
            from src.services.ups_service import UPSService

            svc = UPSService(
                base_url="https://test.ups.com",
                client_id="id",
                client_secret="secret",
            )
            return svc, MockTM.return_value

    def test_void_success(self):
        """Test successful void."""
        svc, mock_tm = self._make_service()
        mock_tm.void_shipment.return_value = {
            "VoidShipmentResponse": {
                "SummaryResult": {
                    "Status": {"Code": "1", "Description": "Success"},
                }
            }
        }

        result = svc.void_shipment(shipment_id="1Z999AA10123456784")

        assert result["success"] is True
