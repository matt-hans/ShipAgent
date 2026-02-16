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


class TestTranslateErrorMCPPreflight:
    """Tests for _translate_error() handling MCP preflight ToolErrors.

    Verifies that structured ToolError payloads from UPS MCP preflight
    (elicitation v1) are correctly mapped to ShipAgent E-codes with
    actionable messages synthesised from missing[].prompt.
    """

    @pytest.mark.asyncio
    async def test_elicitation_unsupported_with_missing(self, ups_client, mock_mcp_client):
        """ELICITATION_UNSUPPORTED with missing[] -> E-2010 with prompt-based fields."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_UNSUPPORTED",
                "message": "Missing 3 required field(s)",
                "reason": "unsupported",
                "missing": [
                    {"dot_path": "ShipmentRequest.Shipment.Shipper.Name", "flat_key": "shipper_name", "prompt": "Shipper name"},
                    {"dot_path": "ShipmentRequest.Shipment.ShipTo.Address.City", "flat_key": "ship_to_city", "prompt": "Recipient city"},
                    {"dot_path": "ShipmentRequest.Shipment.Package.PackageWeight.Weight", "flat_key": "package_1_weight", "prompt": "Package weight"},
                ],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2010"
        assert "3" in err.message
        assert "Shipper name" in err.message
        assert "Recipient city" in err.message
        assert "Package weight" in err.message

    @pytest.mark.asyncio
    async def test_elicitation_unsupported_many_fields_truncated(self, ups_client, mock_mcp_client):
        """ELICITATION_UNSUPPORTED with 12 missing fields shows first 8 + count."""
        missing = [
            {"flat_key": f"field_{i}", "prompt": f"Field {i}"}
            for i in range(12)
        ]
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_UNSUPPORTED",
                "message": "Missing 12 required field(s)",
                "missing": missing,
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2010"
        assert "(+4 more)" in err.message
        assert "Field 0" in err.message
        assert "Field 7" in err.message

    @pytest.mark.asyncio
    async def test_prompt_fallback_to_flat_key(self, ups_client, mock_mcp_client):
        """When prompt is None, falls back to flat_key for display."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_UNSUPPORTED",
                "message": "Missing 1 required field(s)",
                "missing": [
                    {"dot_path": "ShipmentRequest.Shipment.Shipper.Name", "flat_key": "shipper_name", "prompt": None},
                ],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2010"
        assert "shipper_name" in err.message

    @pytest.mark.asyncio
    async def test_e2010_empty_missing_uses_fallback(self, ups_client, mock_mcp_client):
        """E-2010 with absent/empty missing[] uses fallback context (no raw placeholders)."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_UNSUPPORTED",
                "message": "Something about missing fields",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2010"
        # Must not contain raw template placeholders
        assert "{count}" not in err.message
        assert "{fields}" not in err.message

    @pytest.mark.asyncio
    async def test_malformed_request_maps_to_e2011(self, ups_client, mock_mcp_client):
        """MALFORMED_REQUEST with empty missing[] -> E-2011."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "MALFORMED_REQUEST",
                "message": "Ambiguous payer configuration",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        assert exc_info.value.code == "E-2011"
        assert "Ambiguous payer" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_elicitation_cancelled_maps_to_e4012(self, ups_client, mock_mcp_client):
        """ELICITATION_CANCELLED -> E-4012."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_CANCELLED",
                "message": "User cancelled the form",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        assert exc_info.value.code == "E-4012"

    @pytest.mark.asyncio
    async def test_elicitation_invalid_response_maps_to_e4010(self, ups_client, mock_mcp_client):
        """ELICITATION_INVALID_RESPONSE -> E-4010."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_INVALID_RESPONSE",
                "message": "Rehydration error: field conflict",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        assert exc_info.value.code == "E-4010"

    @pytest.mark.asyncio
    async def test_missing_ordering_preserved(self, ups_client, mock_mcp_client):
        """Field order from missing[] is preserved in the message."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "ELICITATION_UNSUPPORTED",
                "message": "Missing fields",
                "missing": [
                    {"flat_key": "a", "prompt": "Alpha"},
                    {"flat_key": "b", "prompt": "Bravo"},
                    {"flat_key": "c", "prompt": "Charlie"},
                ],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        msg = exc_info.value.message
        # Order should match: Alpha before Bravo before Charlie
        assert msg.index("Alpha") < msg.index("Bravo") < msg.index("Charlie")


class TestMalformedRequestReasonPreservation:
    """Tests for MALFORMED_REQUEST reason field preservation."""

    @pytest.mark.asyncio
    async def test_malformed_request_preserves_reason_in_details(self, ups_client, mock_mcp_client):
        """MALFORMED_REQUEST preserves reason variant in details and message."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "MALFORMED_REQUEST",
                "message": "Ambiguous payer configuration",
                "reason": "ambiguous_payer",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2022"  # Routed to Ambiguous Billing via reason
        assert err.details is not None
        assert err.details.get("reason") == "ambiguous_payer"
        # E-2022 has a fixed template; reason is preserved in details only
        assert "billing" in err.message.lower() or "payer" in err.message.lower()

    @pytest.mark.asyncio
    async def test_malformed_request_reason_malformed_structure(self, ups_client, mock_mcp_client):
        """MALFORMED_REQUEST with malformed_structure reason routes to E-2021."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "MALFORMED_REQUEST",
                "message": "Invalid payload structure",
                "reason": "malformed_structure",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2021"  # Routed to Malformed Structure via reason
        assert err.details.get("reason") == "malformed_structure"
        assert "(reason: malformed_structure)" in err.message

    @pytest.mark.asyncio
    async def test_reason_absent_does_not_crash(self, ups_client, mock_mcp_client):
        """Missing reason field does not crash _translate_error."""
        mock_mcp_client.call_tool.side_effect = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "code": "MALFORMED_REQUEST",
                "message": "Some error",
                "missing": [],
            }),
        )

        with pytest.raises(UPSServiceError) as exc_info:
            await ups_client.create_shipment(request_body={})

        err = exc_info.value
        assert err.code == "E-2011"
        assert "(reason:" not in err.message  # No reason appended when absent


class TestRetryableRegressionMCPPreflight:
    """Verify _ups_is_retryable returns False for all 6 MCP preflight codes.

    E-4010 has is_retryable=True in the error registry, but that is
    user-facing guidance only. Runtime auto-retry must be disabled
    because create_shipment may have side effects.
    """

    @pytest.mark.parametrize("code", [
        "ELICITATION_UNSUPPORTED",
        "INCOMPLETE_SHIPMENT",
        "MALFORMED_REQUEST",
        "ELICITATION_DECLINED",
        "ELICITATION_CANCELLED",
        "ELICITATION_INVALID_RESPONSE",
    ])
    def test_not_retryable(self, code: str):
        """MCP preflight codes are never auto-retried."""
        error_text = json.dumps({"code": code, "message": "test"})
        assert _ups_is_retryable(error_text) is False

    def test_elicitation_invalid_response_not_retryable_despite_registry(self):
        """E-4010 is_retryable=True is user-facing guidance only.

        Runtime auto-retry via _ups_is_retryable() must return False for
        ELICITATION_INVALID_RESPONSE because create_shipment may have
        side effects. The is_retryable flag in the error registry tells
        the user they can manually retry, not that the system should
        auto-retry.
        """
        error_text = json.dumps({
            "code": "ELICITATION_INVALID_RESPONSE",
            "message": "Rehydration error",
        })
        assert _ups_is_retryable(error_text) is False


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

    @pytest.mark.asyncio
    async def test_create_shipment_retries_once_for_no_healthy_upstream(self, ups_client, mock_mcp_client):
        """Mutating call retries once only for strict upstream 503 signatures."""
        mock_mcp_client._session = object()
        mock_mcp_client.call_tool = AsyncMock(side_effect=[
            MCPToolError(
                tool_name="create_shipment",
                error_text=json.dumps({
                    "status_code": 503,
                    "code": "503",
                    "message": "UPS API returned HTTP 503",
                    "details": {"raw": "no healthy upstream"},
                }),
            ),
            {"ok": True},
        ])

        result = await ups_client._call("create_shipment", {"request_body": {"x": 1}})

        assert result == {"ok": True}
        assert mock_mcp_client.call_tool.call_count == 2
        mock_mcp_client.call_tool.assert_any_await(
            "create_shipment",
            {"request_body": {"x": 1}},
            max_retries=0,
            base_delay=1.0,
        )

    @pytest.mark.asyncio
    async def test_create_shipment_does_not_retry_generic_503(self, ups_client, mock_mcp_client):
        """Generic 503 without upstream signature remains non-retry for safety."""
        mock_mcp_client._session = object()
        err = MCPToolError(
            tool_name="create_shipment",
            error_text=json.dumps({
                "status_code": 503,
                "code": "503",
                "message": "Service temporarily unavailable",
            }),
        )
        mock_mcp_client.call_tool = AsyncMock(side_effect=[err])

        with pytest.raises(MCPToolError):
            await ups_client._call("create_shipment", {"request_body": {"x": 1}})

        assert mock_mcp_client.call_tool.call_count == 1


# ---------------------------------------------------------------------------
# Pickup methods (Task 8)
# ---------------------------------------------------------------------------


class TestSchedulePickup:
    """Test schedule_pickup() method and normalization."""

    @pytest.mark.asyncio
    async def test_schedule_pickup_calls_correct_tool(self, ups_client, mock_mcp_client):
        """schedule_pickup must call MCP tool 'schedule_pickup'."""
        mock_mcp_client.call_tool.return_value = {
            "PickupCreationResponse": {"PRN": "2929602E9CP"}
        }
        result = await ups_client.schedule_pickup(
            pickup_date="20260220", ready_time="0900", close_time="1700",
            address_line="123 Main St", city="Austin", state="TX",
            postal_code="78701", country_code="US",
            contact_name="John Smith", phone_number="5125551234",
        )
        assert result["success"] is True
        assert result["prn"] == "2929602E9CP"
        call_args = mock_mcp_client.call_tool.call_args
        assert call_args[0][0] == "schedule_pickup"

    @pytest.mark.asyncio
    async def test_schedule_pickup_uses_mutating_retry(self, ups_client, mock_mcp_client):
        """schedule_pickup must NOT retry (mutating operation)."""
        mock_mcp_client.call_tool.return_value = {
            "PickupCreationResponse": {"PRN": "X"}
        }
        await ups_client.schedule_pickup(
            pickup_date="20260220", ready_time="0900", close_time="1700",
            address_line="123 Main St", city="Austin", state="TX",
            postal_code="78701", country_code="US",
            contact_name="John", phone_number="512555",
        )
        mock_mcp_client.call_tool.assert_awaited_once_with(
            "schedule_pickup",
            {
                "pickup_date": "20260220", "ready_time": "0900", "close_time": "1700",
                "address_line": "123 Main St", "city": "Austin", "state": "TX",
                "postal_code": "78701", "country_code": "US",
                "contact_name": "John", "phone_number": "512555",
            },
            max_retries=0,
            base_delay=1.0,
        )


class TestCancelPickup:
    """Test cancel_pickup() method and normalization."""

    @pytest.mark.asyncio
    async def test_cancel_pickup_by_prn(self, ups_client, mock_mcp_client):
        """cancel_pickup with PRN calls correct tool."""
        mock_mcp_client.call_tool.return_value = {
            "PickupCancelResponse": {"Status": {"Code": "1"}}
        }
        result = await ups_client.cancel_pickup(cancel_by="prn", prn="2929602E9CP")
        assert result["success"] is True
        assert result["status"] == "cancelled"


class TestRatePickup:
    """Test rate_pickup() method and normalization."""

    @pytest.mark.asyncio
    async def test_rate_pickup_returns_charges(self, ups_client, mock_mcp_client):
        """rate_pickup returns estimated charges."""
        mock_mcp_client.call_tool.return_value = {
            "PickupRateResponse": {
                "RateResult": {
                    "ChargeDetail": [{"ChargeAmount": "5.50", "ChargeCode": "C"}],
                    "GrandTotalOfAllCharge": "5.50",
                }
            }
        }
        result = await ups_client.rate_pickup(
            pickup_type="oncall", address_line="123 Main", city="Austin",
            state="TX", postal_code="78701", country_code="US",
            pickup_date="20260220", ready_time="0900", close_time="1700",
        )
        assert result["success"] is True
        assert "charges" in result
        assert result["charges"][0]["chargeAmount"] == "5.50"
        assert result["charges"][0]["chargeCode"] == "C"

    @pytest.mark.asyncio
    async def test_rate_pickup_uses_read_only_retry(self, ups_client, mock_mcp_client):
        """rate_pickup uses read-only retry policy."""
        mock_mcp_client.call_tool.return_value = {
            "PickupRateResponse": {"RateResult": {"GrandTotalOfAllCharge": "0"}}
        }
        await ups_client.rate_pickup(
            pickup_type="oncall", address_line="x", city="x",
            state="TX", postal_code="78701", country_code="US",
            pickup_date="20260220", ready_time="0900", close_time="1700",
        )
        mock_mcp_client.call_tool.assert_awaited_once()
        call_kwargs = mock_mcp_client.call_tool.call_args
        assert call_kwargs[1]["max_retries"] == 2
        assert call_kwargs[1]["base_delay"] == 0.2


class TestGetPickupStatus:
    """Test get_pickup_status() method and normalization."""

    @pytest.mark.asyncio
    async def test_get_pickup_status(self, ups_client, mock_mcp_client):
        """get_pickup_status returns pending pickups."""
        mock_mcp_client.call_tool.return_value = {
            "PickupPendingStatusResponse": {
                "PendingStatus": [{"PickupDate": "20260220", "PRN": "ABC123"}]
            }
        }
        result = await ups_client.get_pickup_status(pickup_type="oncall")
        assert result["success"] is True
        assert "pickups" in result


class TestPickupRetryClassification:
    """Test that retry classification constants exist and are correct."""

    def test_read_only_tools_exist(self, ups_client):
        """_READ_ONLY_TOOLS class attribute exists with expected tools."""
        assert hasattr(UPSMCPClient, "_READ_ONLY_TOOLS")
        assert "rate_pickup" in UPSMCPClient._READ_ONLY_TOOLS
        assert "get_pickup_status" in UPSMCPClient._READ_ONLY_TOOLS

    def test_mutating_tools_exist(self, ups_client):
        """_MUTATING_TOOLS class attribute exists with expected tools."""
        assert hasattr(UPSMCPClient, "_MUTATING_TOOLS")
        assert "schedule_pickup" in UPSMCPClient._MUTATING_TOOLS
        assert "cancel_pickup" in UPSMCPClient._MUTATING_TOOLS

    def test_original_tools_still_classified(self, ups_client):
        """Original tools remain in the classification sets."""
        assert "rate_shipment" in UPSMCPClient._READ_ONLY_TOOLS
        assert "validate_address" in UPSMCPClient._READ_ONLY_TOOLS
        assert "track_package" in UPSMCPClient._READ_ONLY_TOOLS
        assert "create_shipment" in UPSMCPClient._MUTATING_TOOLS
        assert "void_shipment" in UPSMCPClient._MUTATING_TOOLS


# ---------------------------------------------------------------------------
# Landed cost methods (Task 9)
# ---------------------------------------------------------------------------


class TestGetLandedCost:
    """Test get_landed_cost() method and normalization."""

    @pytest.mark.asyncio
    async def test_get_landed_cost(self, ups_client, mock_mcp_client):
        """get_landed_cost returns duty/tax breakdown."""
        mock_mcp_client.call_tool.return_value = {
            "LandedCostResponse": {
                "shipment": {
                    "totalLandedCost": "45.23",
                    "currencyCode": "USD",
                    "shipmentItems": [
                        {"commodityId": "1", "duties": "12.50", "taxes": "7.73", "fees": "0.00"}
                    ],
                }
            }
        }
        result = await ups_client.get_landed_cost(
            currency_code="USD", export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 25.00, "quantity": 2}],
        )
        assert result["success"] is True
        assert result["totalLandedCost"] == "45.23"
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_get_landed_cost_uses_read_only_retry(self, ups_client, mock_mcp_client):
        """get_landed_cost uses read-only retry policy."""
        mock_mcp_client.call_tool.return_value = {
            "LandedCostResponse": {"shipment": {"totalLandedCost": "0", "shipmentItems": []}}
        }
        await ups_client.get_landed_cost(
            currency_code="USD", export_country_code="US",
            import_country_code="GB", commodities=[],
        )
        call_kwargs = mock_mcp_client.call_tool.call_args
        assert call_kwargs[1]["max_retries"] == 2


# ---------------------------------------------------------------------------
# Paperless document methods (Task 9)
# ---------------------------------------------------------------------------


class TestUploadDocument:
    """Test upload_document() method and normalization."""

    @pytest.mark.asyncio
    async def test_upload_document(self, ups_client, mock_mcp_client):
        """upload_document returns DocumentID."""
        mock_mcp_client.call_tool.return_value = {
            "UploadResponse": {
                "FormsHistoryDocumentID": {"DocumentID": "2013-12-04-00.15.33.207814"}
            }
        }
        result = await ups_client.upload_document(
            file_content_base64="dGVzdA==", file_name="invoice.pdf",
            file_format="pdf", document_type="002",
        )
        assert result["success"] is True
        assert result["documentId"] == "2013-12-04-00.15.33.207814"

    @pytest.mark.asyncio
    async def test_upload_document_no_retry(self, ups_client, mock_mcp_client):
        """upload_document must NOT retry (mutating)."""
        assert "upload_paperless_document" in UPSMCPClient._MUTATING_TOOLS


class TestPushDocument:
    """Test push_document() method and normalization."""

    @pytest.mark.asyncio
    async def test_push_document(self, ups_client, mock_mcp_client):
        """push_document links document to shipment."""
        mock_mcp_client.call_tool.return_value = {
            "PushToImageRepositoryResponse": {"FormsHistoryDocumentID": {"DocumentID": "TEST"}}
        }
        result = await ups_client.push_document(
            document_id="TEST", shipment_identifier="1Z123",
        )
        assert result["success"] is True


class TestDeleteDocument:
    """Test delete_document() method and normalization."""

    @pytest.mark.asyncio
    async def test_delete_document(self, ups_client, mock_mcp_client):
        """delete_document removes from Forms History."""
        mock_mcp_client.call_tool.return_value = {
            "DeleteResponse": {"Status": "Success"}
        }
        result = await ups_client.delete_document(document_id="TEST")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Locator methods (Task 9)
# ---------------------------------------------------------------------------


class TestFindLocations:
    """Test find_locations() method and normalization."""

    @pytest.mark.asyncio
    async def test_find_locations(self, ups_client, mock_mcp_client):
        """find_locations returns location list."""
        mock_mcp_client.call_tool.return_value = {
            "LocatorResponse": {
                "SearchResults": {
                    "DropLocation": [
                        {
                            "LocationID": "L1",
                            "AddressKeyFormat": {"AddressLine": "123 Main"},
                            "PhoneNumber": "555-1234",
                            "OperatingHours": {"StandardHours": {"DayOfWeek": []}},
                        }
                    ]
                }
            }
        }
        result = await ups_client.find_locations(
            location_type="retail", address_line="123 Main",
            city="Austin", state="TX", postal_code="78701", country_code="US",
        )
        assert result["success"] is True
        assert len(result["locations"]) == 1
        assert result["locations"][0]["id"] == "L1"

    @pytest.mark.asyncio
    async def test_find_locations_uses_read_only_retry(self, ups_client, mock_mcp_client):
        """find_locations uses read-only retry policy."""
        assert "find_locations" in UPSMCPClient._READ_ONLY_TOOLS


class TestGetServiceCenterFacilities:
    """Test get_service_center_facilities() method and normalization."""

    @pytest.mark.asyncio
    async def test_get_service_center_facilities(self, ups_client, mock_mcp_client):
        """get_service_center_facilities returns normalised facility list."""
        mock_mcp_client.call_tool.return_value = {
            "ServiceCenterResponse": {
                "ServiceCenterList": [
                    {
                        "FacilityName": "UPS Store #1234",
                        "FacilityAddress": {
                            "AddressLine": "123 Main St",
                            "City": "Austin",
                            "StateProvinceCode": "TX",
                            "PostalCode": "78701",
                        },
                    }
                ]
            }
        }
        result = await ups_client.get_service_center_facilities(
            city="Austin", state="TX", postal_code="78701", country_code="US",
        )
        assert result["success"] is True
        assert len(result["facilities"]) == 1
        fac = result["facilities"][0]
        assert fac["name"] == "UPS Store #1234"
        assert "Austin" in fac["address"]
        assert "TX" in fac["address"]
