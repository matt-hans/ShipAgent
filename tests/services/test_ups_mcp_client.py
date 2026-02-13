"""Tests for UPSMCPClient (async MCP-based UPS client)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.errors import UPSServiceError
from src.services.mcp_client import MCPConnectionError, MCPToolError
from src.services.ups_mcp_client import UPSMCPClient, _ups_is_retryable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCPClient with async call_tool."""
    client = AsyncMock()
    client.call_tool = AsyncMock()
    return client


@pytest.fixture
def ups_client(mock_mcp_client):
    """Create a UPSMCPClient with a pre-injected mock MCPClient."""
    client = UPSMCPClient(
        client_id="test-id",
        client_secret="test-secret",
        environment="test",
    )
    client._mcp = mock_mcp_client
    return client


# ---------------------------------------------------------------------------
# Retryable classifier
# ---------------------------------------------------------------------------


class TestUPSIsRetryable:
    """Test _ups_is_retryable error classification."""

    @pytest.mark.parametrize("text", [
        "429 Too Many Requests",
        "503 Service Unavailable",
        "502 Bad Gateway",
        "rate limit exceeded",
        "connection refused",
        "timeout after 30s",
        '{"code": "190001", "message": "System unavailable"}',
        '{"code": "190002", "message": "Service temporarily unavailable"}',
    ])
    def test_retryable_patterns(self, text: str):
        """Transient errors are classified as retryable."""
        assert _ups_is_retryable(text) is True

    @pytest.mark.parametrize("text", [
        '{"code": "120100", "message": "Invalid address"}',
        "Missing required field: weight",
        "Authentication failed: invalid credentials",
        "400 Bad Request: invalid payload",
    ])
    def test_non_retryable_patterns(self, text: str):
        """Validation and auth errors are not retryable."""
        assert _ups_is_retryable(text) is False


# ---------------------------------------------------------------------------
# get_rate normalization
# ---------------------------------------------------------------------------


class TestGetRate:
    """Test get_rate() with response normalization."""

    @pytest.mark.asyncio
    async def test_normalizes_published_rate(self, ups_client, mock_mcp_client):
        """Normalizes published rate when no negotiated rate exists."""
        mock_mcp_client.call_tool.return_value = {
            "RateResponse": {
                "RatedShipment": [{
                    "TotalCharges": {
                        "MonetaryValue": "15.50",
                        "CurrencyCode": "USD",
                    },
                }],
            },
        }

        result = await ups_client.get_rate(request_body={"test": True})

        assert result["success"] is True
        assert result["totalCharges"]["monetaryValue"] == "15.50"
        assert result["totalCharges"]["amount"] == "15.50"
        assert result["totalCharges"]["currencyCode"] == "USD"

        mock_mcp_client.call_tool.assert_awaited_once_with(
            "rate_shipment",
            {"requestoption": "Rate", "request_body": {"test": True}},
            max_retries=2,
            base_delay=0.2,
        )

    @pytest.mark.asyncio
    async def test_prefers_negotiated_rate(self, ups_client, mock_mcp_client):
        """Prefers negotiated rate over published rate."""
        mock_mcp_client.call_tool.return_value = {
            "RateResponse": {
                "RatedShipment": [{
                    "TotalCharges": {
                        "MonetaryValue": "20.00",
                        "CurrencyCode": "USD",
                    },
                    "NegotiatedRateCharges": {
                        "TotalCharge": {
                            "MonetaryValue": "12.50",
                            "CurrencyCode": "USD",
                        },
                    },
                }],
            },
        }

        result = await ups_client.get_rate(request_body={})

        assert result["totalCharges"]["monetaryValue"] == "12.50"

    @pytest.mark.asyncio
    async def test_translates_tool_error(self, ups_client, mock_mcp_client):
        """MCPToolError is translated to UPSServiceError."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="rate_shipment",
            error_text=json.dumps({
                "code": "120100",
                "message": "Address validation failed",
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.get_rate(request_body={})

        assert exc_info.value.code == "E-3003"


# ---------------------------------------------------------------------------
# create_shipment normalization
# ---------------------------------------------------------------------------


class TestCreateShipment:
    """Test create_shipment() with response normalization."""

    @pytest.mark.asyncio
    async def test_normalizes_shipment_response(self, ups_client, mock_mcp_client):
        """Extracts tracking numbers, labels, and charges."""
        mock_mcp_client.call_tool.return_value = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z999AA1",
                    "PackageResults": {
                        "TrackingNumber": "1Z999AA1PKG",
                        "ShippingLabel": {
                            "GraphicImage": "base64data==",
                        },
                    },
                    "ShipmentCharges": {
                        "TotalCharges": {
                            "MonetaryValue": "15.50",
                            "CurrencyCode": "USD",
                        },
                    },
                },
            },
        }

        result = await ups_client.create_shipment(request_body={"test": True})

        assert result["success"] is True
        assert result["trackingNumbers"] == ["1Z999AA1PKG"]
        assert result["labelData"] == ["base64data=="]
        assert result["shipmentIdentificationNumber"] == "1Z999AA1"
        assert result["totalCharges"]["monetaryValue"] == "15.50"

        mock_mcp_client.call_tool.assert_awaited_once_with(
            "create_shipment",
            {"request_body": {"test": True}},
            max_retries=0,
            base_delay=1.0,
        )

    @pytest.mark.asyncio
    async def test_prefers_negotiated_charges(self, ups_client, mock_mcp_client):
        """Prefers negotiated charges over published."""
        mock_mcp_client.call_tool.return_value = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z",
                    "PackageResults": [],
                    "ShipmentCharges": {
                        "TotalCharges": {
                            "MonetaryValue": "20.00",
                            "CurrencyCode": "USD",
                        },
                    },
                    "NegotiatedRateCharges": {
                        "TotalCharge": {
                            "MonetaryValue": "10.00",
                            "CurrencyCode": "USD",
                        },
                    },
                },
            },
        }

        result = await ups_client.create_shipment(request_body={})
        assert result["totalCharges"]["monetaryValue"] == "10.00"

    @pytest.mark.asyncio
    async def test_handles_multiple_packages(self, ups_client, mock_mcp_client):
        """Handles list of PackageResults (multi-package shipment)."""
        mock_mcp_client.call_tool.return_value = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z",
                    "PackageResults": [
                        {"TrackingNumber": "PKG1", "ShippingLabel": {"GraphicImage": "lbl1"}},
                        {"TrackingNumber": "PKG2", "ShippingLabel": {"GraphicImage": "lbl2"}},
                    ],
                    "ShipmentCharges": {
                        "TotalCharges": {"MonetaryValue": "30.00", "CurrencyCode": "USD"},
                    },
                },
            },
        }

        result = await ups_client.create_shipment(request_body={})
        assert result["trackingNumbers"] == ["PKG1", "PKG2"]
        assert result["labelData"] == ["lbl1", "lbl2"]


# ---------------------------------------------------------------------------
# void_shipment normalization
# ---------------------------------------------------------------------------


class TestVoidShipment:
    """Test void_shipment() normalization."""

    @pytest.mark.asyncio
    async def test_normalizes_void_response(self, ups_client, mock_mcp_client):
        """Extracts success status from void response."""
        mock_mcp_client.call_tool.return_value = {
            "VoidShipmentResponse": {
                "SummaryResult": {
                    "Status": {
                        "Code": "1",
                        "Description": "Success",
                    },
                },
            },
        }

        result = await ups_client.void_shipment(shipment_id="1Z999AA1")

        assert result["success"] is True
        assert result["status"]["code"] == "1"

        mock_mcp_client.call_tool.assert_awaited_once_with(
            "void_shipment",
            {"shipmentidentificationnumber": "1Z999AA1"},
            max_retries=0,
            base_delay=1.0,
        )


# ---------------------------------------------------------------------------
# validate_address normalization
# ---------------------------------------------------------------------------


class TestValidateAddress:
    """Test validate_address() normalization."""

    @pytest.mark.asyncio
    async def test_normalizes_valid_address(self, ups_client, mock_mcp_client):
        """Normalizes valid address response."""
        mock_mcp_client.call_tool.return_value = {
            "XAVResponse": {
                "ValidAddressIndicator": "",
                "Candidate": {
                    "AddressKeyFormat": {
                        "AddressLine": ["123 MAIN ST"],
                        "PoliticalDivision2": "LOS ANGELES",
                        "PoliticalDivision1": "CA",
                        "PostcodePrimaryLow": "90001",
                    },
                },
            },
        }

        result = await ups_client.validate_address(
            addressLine1="123 Main St",
            city="Los Angeles",
            stateProvinceCode="CA",
            postalCode="90001",
            countryCode="US",
        )

        assert result["status"] == "valid"
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["city"] == "LOS ANGELES"


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


class TestErrorTranslation:
    """Test MCPToolError → UPSServiceError translation."""

    @pytest.mark.asyncio
    async def test_json_error_with_nested_details(self, ups_client, mock_mcp_client):
        """Extracts error code from nested details."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "unknown",
                "message": "Generic error",
                "details": {
                    "response": {
                        "errors": [{
                            "code": "120500",
                            "message": "Invalid weight value",
                        }],
                    },
                },
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        assert exc_info.value.code == "E-2004"

    @pytest.mark.asyncio
    async def test_non_json_error_text(self, ups_client, mock_mcp_client):
        """Non-JSON error text gets fallback E-3005 code."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="rate_shipment",
            error_text="Connection refused to UPS API",
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.get_rate(request_body={})

        assert exc_info.value.code == "E-3005"
        assert "Connection refused" in exc_info.value.message


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestUPSMCPClientLifecycle:
    """Test async context manager lifecycle."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """async with creates and closes MCPClient."""
        with patch("src.services.ups_mcp_client.MCPClient") as MockMCP:
            mock_mcp = AsyncMock()
            mock_mcp.connect = AsyncMock(return_value=None)
            mock_mcp.disconnect = AsyncMock(return_value=None)
            MockMCP.return_value = mock_mcp

            async with UPSMCPClient(
                client_id="id",
                client_secret="secret",
            ) as client:
                assert client._mcp is mock_mcp

            mock_mcp.connect.assert_awaited_once()
            mock_mcp.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_disconnect_delegate_to_mcp(self):
        """connect()/disconnect() delegate to underlying MCPClient."""
        with patch("src.services.ups_mcp_client.MCPClient") as MockMCP:
            mock_mcp = AsyncMock()
            mock_mcp.connect = AsyncMock(return_value=None)
            mock_mcp.disconnect = AsyncMock(return_value=None)
            MockMCP.return_value = mock_mcp

            client = UPSMCPClient(client_id="id", client_secret="secret")
            await client.connect()
            await client.disconnect()

            mock_mcp.connect.assert_awaited_once()
            mock_mcp.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_connected_raises(self):
        """Calling methods without context raises RuntimeError."""
        client = UPSMCPClient(client_id="id", client_secret="secret")

        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_rate(request_body={})


class TestUPSMCPReconnectBehavior:
    """Transport reconnect behavior in _call()."""

    @pytest.mark.asyncio
    async def test_rate_call_reconnects_and_replays_once(self, ups_client, mock_mcp_client):
        """Non-mutating rate calls are replayed once after reconnect."""
        mock_mcp_client._session = object()
        mock_mcp_client.call_tool = AsyncMock(side_effect=[
            MCPConnectionError(command="test", reason="transport down"),
            {"ok": True},
        ])
        mock_mcp_client.disconnect = AsyncMock(return_value=None)
        mock_mcp_client.connect = AsyncMock(return_value=None)

        result = await ups_client._call("rate_shipment", {"request_body": {}})

        assert result == {"ok": True}
        assert mock_mcp_client.call_tool.call_count == 2
        mock_mcp_client.disconnect.assert_awaited_once()
        mock_mcp_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_shipment_reconnects_without_replay(self, ups_client, mock_mcp_client):
        """Mutating create_shipment calls reconnect but do not auto-replay."""
        mock_mcp_client._session = object()
        mock_mcp_client.call_tool = AsyncMock(side_effect=[
            MCPConnectionError(command="test", reason="transport down"),
        ])
        mock_mcp_client.disconnect = AsyncMock(return_value=None)
        mock_mcp_client.connect = AsyncMock(return_value=None)

        with pytest.raises(MCPConnectionError):
            await ups_client._call("create_shipment", {"request_body": {}})

        assert mock_mcp_client.call_tool.call_count == 1
        mock_mcp_client.disconnect.assert_awaited_once()
        mock_mcp_client.connect.assert_awaited_once()
