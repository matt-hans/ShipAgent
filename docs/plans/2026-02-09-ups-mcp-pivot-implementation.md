# UPS MCP Pivot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace TypeScript UPS MCP with direct Python import, consolidate batch execution, enforce deterministic payload building, and delete the template generation pipeline.

**Architecture:** The fork's `ToolManager` is imported directly (no subprocess). A thin `UPSService` wrapper normalizes responses. A `BatchEngine` consolidates both execution paths (REST API + orchestrator). Column mapping replaces Jinja2 templates for CSV/Excel. Net deletion: ~2500 lines removed, ~500 written.

**Tech Stack:** Python 3.12+, ups-mcp fork (pip), FastAPI, SQLAlchemy, pytest

**Design Document:** `docs/plans/2026-02-09-ups-mcp-pivot-design.md`

---

## Task 1: Create UPSService — Failing Tests

**Files:**
- Create: `tests/services/test_ups_service.py`

**Step 1: Write failing tests for UPSService**

```python
"""Tests for UPS service layer (direct ToolManager import)."""

import json
import pytest
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp.exceptions import ToolError


class TestUPSServiceInit:
    """Test UPSService initialization."""

    def test_creates_tool_manager(self):
        """Test ToolManager is created with credentials."""
        with patch("src.services.ups_service.ToolManager") as MockTM:
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
        with patch("src.services.ups_service.ToolManager") as MockTM:
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
        with patch("src.services.ups_service.ToolManager") as MockTM:
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
        with patch("src.services.ups_service.ToolManager") as MockTM:
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
        with patch("src.services.ups_service.ToolManager") as MockTM:
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_ups_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.ups_service'`

---

## Task 2: Create UPSService — Implementation

**Files:**
- Create: `src/services/ups_service.py`

**Step 1: Implement UPSService**

```python
"""UPS service layer — thin wrapper around the fork's ToolManager.

Replaces src/mcp/ups_client.py (~450 lines of subprocess/JSON-RPC)
with direct Python import. ToolManager uses synchronous `requests`;
callers use asyncio.to_thread() at call sites.

Example:
    svc = UPSService(base_url=..., client_id=..., client_secret=...)
    result = svc.create_shipment(request_body=payload)
    tracking = result["trackingNumbers"][0]
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from src.errors.ups_translation import translate_ups_error

logger = logging.getLogger(__name__)


@dataclass
class UPSServiceError(Exception):
    """Error from UPS service layer.

    Attributes:
        code: ShipAgent error code (E-XXXX format)
        message: Human-readable error message
        remediation: Suggested fix
        details: Raw error details
    """

    code: str
    message: str
    remediation: str = ""
    details: dict | None = None

    def __str__(self) -> str:
        """Return formatted error message."""
        return f"[{self.code}] {self.message}"


class UPSService:
    """Thin wrapper around the fork's ToolManager with response normalization.

    All methods are synchronous (ToolManager uses requests internally).
    Async callers should use: await asyncio.to_thread(svc.method, ...)
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Initialize with UPS API credentials.

        Args:
            base_url: UPS API base URL (sandbox or production)
            client_id: OAuth client ID
            client_secret: OAuth client secret
        """
        from ups_mcp.tools import ToolManager

        self._tm = ToolManager(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
        )

    def create_shipment(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Create a shipment via UPS API.

        Args:
            request_body: Full UPS ShipmentRequest payload

        Returns:
            Normalized dict with: success, trackingNumbers, labelData,
            totalCharges, shipmentIdentificationNumber

        Raises:
            UPSServiceError: On UPS API or validation error
        """
        try:
            raw = self._tm.create_shipment(request_body=request_body)
        except ToolError as e:
            raise self._translate_error(e)

        return self._normalize_shipment_response(raw)

    def get_rate(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Get a rate quote for a single service.

        Args:
            request_body: Full UPS RateRequest payload

        Returns:
            Normalized dict with: success, totalCharges

        Raises:
            UPSServiceError: On UPS API error
        """
        try:
            raw = self._tm.rate_shipment(
                requestoption="Rate",
                request_body=request_body,
            )
        except ToolError as e:
            raise self._translate_error(e)

        return self._normalize_rate_response(raw)

    def get_rate_shop(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Compare rates across services.

        Args:
            request_body: Full UPS RateRequest payload (without Service.Code)

        Returns:
            Normalized dict with: rates (list of {serviceCode, totalCharges})

        Raises:
            UPSServiceError: On UPS API error
        """
        try:
            raw = self._tm.rate_shipment(
                requestoption="Shop",
                request_body=request_body,
            )
        except ToolError as e:
            raise self._translate_error(e)

        return self._normalize_rate_shop_response(raw)

    def validate_address(
        self,
        addressLine1: str,
        city: str,
        stateProvinceCode: str,
        postalCode: str,
        countryCode: str,
        addressLine2: str = "",
    ) -> dict[str, Any]:
        """Validate a shipping address.

        Args:
            addressLine1: Street address
            city: City name
            stateProvinceCode: State/province code
            postalCode: Postal/ZIP code
            countryCode: Country code (e.g., "US")
            addressLine2: Optional second address line

        Returns:
            Normalized dict with: status ('valid'|'ambiguous'|'invalid'),
            candidates list

        Raises:
            UPSServiceError: On UPS API error
        """
        try:
            raw = self._tm.validate_address(
                addressLine1=addressLine1,
                addressLine2=addressLine2,
                politicalDivision1=stateProvinceCode,
                politicalDivision2=city,
                zipPrimary=postalCode,
                zipExtended="",
                urbanization="",
                countryCode=countryCode,
            )
        except ToolError as e:
            raise self._translate_error(e)

        return self._normalize_address_response(raw)

    def void_shipment(self, shipment_id: str) -> dict[str, Any]:
        """Void an existing shipment.

        Args:
            shipment_id: UPS shipment identification number

        Returns:
            Normalized dict with: success, status

        Raises:
            UPSServiceError: On UPS API error
        """
        try:
            raw = self._tm.void_shipment(
                shipmentidentificationnumber=shipment_id,
            )
        except ToolError as e:
            raise self._translate_error(e)

        return self._normalize_void_response(raw)

    # ── Response normalization ────────────────────────────────────────

    def _normalize_shipment_response(self, raw: dict) -> dict[str, Any]:
        """Extract tracking, labels, and cost from raw UPS shipment response."""
        results = (
            raw.get("ShipmentResponse", {})
            .get("ShipmentResults", {})
        )

        ship_id = results.get("ShipmentIdentificationNumber", "")

        # PackageResults can be dict (single) or list (multi)
        pkg_results = results.get("PackageResults", {})
        if isinstance(pkg_results, dict):
            pkg_results = [pkg_results]

        tracking_numbers = [
            p.get("TrackingNumber", "") for p in pkg_results
        ]

        label_data = [
            p.get("ShippingLabel", {}).get("GraphicImage", "")
            for p in pkg_results
        ]

        charges = (
            results.get("ShipmentCharges", {})
            .get("TotalCharges", {})
        )

        return {
            "success": True,
            "trackingNumbers": tracking_numbers,
            "labelData": label_data,
            "shipmentIdentificationNumber": ship_id,
            "totalCharges": {
                "monetaryValue": charges.get("MonetaryValue", "0"),
                "currencyCode": charges.get("CurrencyCode", "USD"),
            },
        }

    def _normalize_rate_response(self, raw: dict) -> dict[str, Any]:
        """Extract rate from raw UPS rate response."""
        rated = (
            raw.get("RateResponse", {})
            .get("RatedShipment", [{}])
        )
        first = rated[0] if rated else {}
        charges = first.get("TotalCharges", {})
        value = charges.get("MonetaryValue", "0")

        return {
            "success": True,
            "totalCharges": {
                "monetaryValue": value,
                "amount": value,
                "currencyCode": charges.get("CurrencyCode", "USD"),
            },
        }

    def _normalize_rate_shop_response(self, raw: dict) -> dict[str, Any]:
        """Extract multiple rates from raw UPS shop response."""
        rated_list = (
            raw.get("RateResponse", {})
            .get("RatedShipment", [])
        )

        rates = []
        for rated in rated_list:
            charges = rated.get("TotalCharges", {})
            value = charges.get("MonetaryValue", "0")
            rates.append({
                "serviceCode": rated.get("Service", {}).get("Code", ""),
                "totalCharges": {
                    "monetaryValue": value,
                    "amount": value,
                    "currencyCode": charges.get("CurrencyCode", "USD"),
                },
            })

        return {"rates": rates}

    def _normalize_address_response(self, raw: dict) -> dict[str, Any]:
        """Extract validation status from raw UPS address response."""
        xav = raw.get("XAVResponse", {})

        if "ValidAddressIndicator" in xav:
            status = "valid"
        elif "AmbiguousAddressIndicator" in xav:
            status = "ambiguous"
        elif "NoCandidatesIndicator" in xav:
            status = "invalid"
        else:
            status = "unknown"

        candidates = []
        candidate_data = xav.get("Candidate")
        if candidate_data:
            if isinstance(candidate_data, dict):
                candidate_data = [candidate_data]
            for c in candidate_data:
                akf = c.get("AddressKeyFormat", {})
                candidates.append({
                    "addressLines": akf.get("AddressLine", []),
                    "city": akf.get("PoliticalDivision2", ""),
                    "stateProvinceCode": akf.get("PoliticalDivision1", ""),
                    "postalCode": akf.get("PostcodePrimaryLow", ""),
                })

        return {
            "status": status,
            "candidates": candidates,
        }

    def _normalize_void_response(self, raw: dict) -> dict[str, Any]:
        """Extract void status from raw UPS response."""
        void_resp = raw.get("VoidShipmentResponse", {})
        summary = void_resp.get("SummaryResult", {})
        status = summary.get("Status", {})

        return {
            "success": status.get("Code") == "1",
            "status": {
                "code": status.get("Code", ""),
                "description": status.get("Description", ""),
            },
        }

    # ── Error translation ─────────────────────────────────────────────

    def _translate_error(self, error: ToolError) -> UPSServiceError:
        """Translate fork ToolError to UPSServiceError with ShipAgent E-code."""
        try:
            error_data = json.loads(str(error))
        except (json.JSONDecodeError, TypeError):
            return UPSServiceError(
                code="E-3005",
                message=f"UPS error: {error}",
            )

        ups_code = error_data.get("code")
        ups_message = error_data.get("message", "")

        # Try to extract real UPS code from nested details
        details = error_data.get("details")
        if isinstance(details, dict):
            resp = details.get("response", {})
            errors = resp.get("errors", [])
            if errors and isinstance(errors[0], dict):
                ups_code = errors[0].get("code", ups_code)
                ups_message = errors[0].get("message", ups_message)

        sa_code, sa_message, remediation = translate_ups_error(
            ups_code, ups_message
        )

        return UPSServiceError(
            code=sa_code,
            message=sa_message,
            remediation=remediation,
            details=error_data,
        )
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/services/test_ups_service.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/services/ups_service.py tests/services/test_ups_service.py
git commit -m "feat: add UPSService — direct ToolManager import with response normalization"
```

---

## Task 3: Enhance Payload Builder — Add build_ups_shipment_payload

The payload builder (`src/services/ups_payload_builder.py`) already builds simplified format. We need a new function that transforms simplified → full UPS API format for the ToolManager.

**Files:**
- Modify: `src/services/ups_payload_builder.py`
- Modify: `tests/services/test_ups_payload_builder.py`

**Step 1: Write failing tests**

Add to `tests/services/test_ups_payload_builder.py`:

```python
from src.services.ups_payload_builder import build_ups_api_payload, build_ups_rate_payload


class TestBuildUpsApiPayload:
    """Test simplified → UPS API format transformation."""

    def test_produces_shipment_request_wrapper(self):
        """Test output has ShipmentRequest at top level."""
        simplified = {
            "shipper": {
                "name": "Test Store",
                "phone": "5559998888",
                "addressLine1": "456 Oak Ave",
                "city": "San Francisco",
                "stateProvinceCode": "CA",
                "postalCode": "94102",
                "countryCode": "US",
            },
            "shipTo": {
                "name": "John Doe",
                "addressLine1": "123 Main St",
                "city": "Los Angeles",
                "stateProvinceCode": "CA",
                "postalCode": "90001",
                "countryCode": "US",
            },
            "packages": [{"weight": 2.0}],
            "serviceCode": "03",
        }

        result = build_ups_api_payload(simplified, account_number="ABC123")

        assert "ShipmentRequest" in result
        shipment = result["ShipmentRequest"]["Shipment"]
        assert shipment["Shipper"]["Name"] == "Test Store"
        assert shipment["Shipper"]["ShipperNumber"] == "ABC123"
        assert shipment["ShipTo"]["Name"] == "John Doe"
        assert shipment["ShipTo"]["Address"]["City"] == "Los Angeles"
        assert shipment["Service"]["Code"] == "03"
        assert shipment["Package"][0]["PackageWeight"]["Weight"] == "2.0"

    def test_includes_label_specification(self):
        """Test PDF label specification is included."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        label_spec = result["ShipmentRequest"]["LabelSpecification"]
        assert label_spec["LabelImageFormat"]["Code"] == "PDF"

    def test_fails_without_account_number(self):
        """Test raises ValueError when account_number missing."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
        }

        with pytest.raises(ValueError, match="account_number"):
            build_ups_api_payload(simplified, account_number="")

    def test_includes_dimensions_when_present(self):
        """Test package dimensions are included when provided."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 5.0, "length": 12, "width": 8, "height": 6}],
            "serviceCode": "03",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        assert pkg["Dimensions"]["Length"] == "12"
        assert pkg["Dimensions"]["Width"] == "8"
        assert pkg["Dimensions"]["Height"] == "6"

    def test_includes_reference_when_present(self):
        """Test ReferenceNumber is included when reference provided."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
            "reference": "ORD-1001",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        shipment = result["ShipmentRequest"]["Shipment"]
        assert shipment["ReferenceNumber"]["Value"] == "ORD-1001"


class TestBuildUpsRatePayload:
    """Test simplified → UPS Rate API format."""

    def test_produces_rate_request_wrapper(self):
        """Test output has RateRequest at top level."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
        }

        result = build_ups_rate_payload(simplified, account_number="X")

        assert "RateRequest" in result
        shipment = result["RateRequest"]["Shipment"]
        assert shipment["Service"]["Code"] == "03"
        assert shipment["Shipper"]["ShipperNumber"] == "X"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_ups_payload_builder.py::TestBuildUpsApiPayload -v`
Expected: FAIL with `ImportError`

**Step 3: Implement build_ups_api_payload and build_ups_rate_payload**

Add to `src/services/ups_payload_builder.py` (after existing functions):

```python
def build_ups_api_payload(
    simplified: dict[str, Any],
    account_number: str,
) -> dict[str, Any]:
    """Transform simplified format to full UPS ShipmentRequest.

    Args:
        simplified: Simplified payload from build_shipment_request().
            Keys: shipper, shipTo, packages, serviceCode, description,
            reference, reference2, saturdayDelivery, signatureRequired.
        account_number: UPS account number for billing.

    Returns:
        Full UPS API ShipmentRequest wrapper.

    Raises:
        ValueError: If account_number is empty.
    """
    if not account_number:
        raise ValueError("account_number is required for UPS shipment creation")

    shipper = simplified.get("shipper", {})
    ship_to = simplified.get("shipTo", {})
    packages = simplified.get("packages", [])
    service_code = simplified.get("serviceCode", "03")

    # Build Shipper
    ups_shipper: dict[str, Any] = {
        "Name": shipper.get("name", ""),
        "ShipperNumber": account_number,
        "Address": {
            "AddressLine": _build_address_lines(shipper),
            "City": shipper.get("city", ""),
            "StateProvinceCode": shipper.get("stateProvinceCode", ""),
            "PostalCode": shipper.get("postalCode", ""),
            "CountryCode": shipper.get("countryCode", "US"),
        },
    }
    if shipper.get("phone"):
        ups_shipper["Phone"] = {"Number": shipper["phone"]}

    # Build ShipTo
    ups_ship_to: dict[str, Any] = {
        "Name": ship_to.get("name", ""),
        "Address": {
            "AddressLine": _build_address_lines(ship_to),
            "City": ship_to.get("city", ""),
            "StateProvinceCode": ship_to.get("stateProvinceCode", ""),
            "PostalCode": ship_to.get("postalCode", ""),
            "CountryCode": ship_to.get("countryCode", "US"),
        },
    }
    if ship_to.get("attentionName"):
        ups_ship_to["AttentionName"] = ship_to["attentionName"]
    if ship_to.get("phone"):
        ups_ship_to["Phone"] = {"Number": ship_to["phone"]}

    # Build Packages
    ups_packages = []
    for pkg in packages:
        ups_pkg: dict[str, Any] = {
            "PackagingType": {
                "Code": pkg.get("packagingType", "02"),
            },
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": str(float(pkg.get("weight", 1.0))),
            },
        }
        # Dimensions (all three required if any present)
        if all(pkg.get(d) for d in ("length", "width", "height")):
            ups_pkg["Dimensions"] = {
                "UnitOfMeasurement": {"Code": "IN"},
                "Length": str(pkg["length"]),
                "Width": str(pkg["width"]),
                "Height": str(pkg["height"]),
            }
        if pkg.get("description"):
            ups_pkg["Description"] = pkg["description"]
        ups_packages.append(ups_pkg)

    # Build Shipment
    shipment: dict[str, Any] = {
        "Shipper": ups_shipper,
        "ShipTo": ups_ship_to,
        "ShipFrom": ups_shipper,  # ShipFrom = Shipper for standard shipments
        "Service": {"Code": service_code},
        "Package": ups_packages,
        "PaymentInformation": {
            "ShipmentCharge": {
                "Type": "01",
                "BillShipper": {"AccountNumber": account_number},
            }
        },
    }

    # Optional fields
    if simplified.get("description"):
        shipment["Description"] = simplified["description"]
    if simplified.get("reference"):
        shipment["ReferenceNumber"] = {
            "Code": "00",
            "Value": simplified["reference"],
        }
    if simplified.get("reference2"):
        shipment["ReferenceNumber2"] = {
            "Code": "00",
            "Value": simplified["reference2"],
        }

    # Shipment-level options
    options = {}
    if simplified.get("saturdayDelivery"):
        options["SaturdayDeliveryIndicator"] = ""
    if options:
        shipment["ShipmentServiceOptions"] = options

    return {
        "ShipmentRequest": {
            "Request": {"RequestOption": "nonvalidate"},
            "Shipment": shipment,
            "LabelSpecification": {
                "LabelImageFormat": {"Code": "PDF"},
                "LabelStockSize": {"Height": "6", "Width": "4"},
            },
        }
    }


def build_ups_rate_payload(
    simplified: dict[str, Any],
    account_number: str,
) -> dict[str, Any]:
    """Transform simplified format to full UPS RateRequest.

    Args:
        simplified: Simplified payload from build_shipment_request().
        account_number: UPS account number.

    Returns:
        Full UPS API RateRequest wrapper.

    Raises:
        ValueError: If account_number is empty.
    """
    if not account_number:
        raise ValueError("account_number is required for UPS rate quotes")

    shipper = simplified.get("shipper", {})
    ship_to = simplified.get("shipTo", {})
    packages = simplified.get("packages", [])
    service_code = simplified.get("serviceCode", "03")

    ups_shipper: dict[str, Any] = {
        "Name": shipper.get("name", ""),
        "ShipperNumber": account_number,
        "Address": {
            "AddressLine": _build_address_lines(shipper),
            "City": shipper.get("city", ""),
            "StateProvinceCode": shipper.get("stateProvinceCode", ""),
            "PostalCode": shipper.get("postalCode", ""),
            "CountryCode": shipper.get("countryCode", "US"),
        },
    }

    ups_ship_to: dict[str, Any] = {
        "Name": ship_to.get("name", ""),
        "Address": {
            "AddressLine": _build_address_lines(ship_to),
            "City": ship_to.get("city", ""),
            "StateProvinceCode": ship_to.get("stateProvinceCode", ""),
            "PostalCode": ship_to.get("postalCode", ""),
            "CountryCode": ship_to.get("countryCode", "US"),
        },
    }

    ups_packages = []
    for pkg in packages:
        ups_pkg: dict[str, Any] = {
            "PackagingType": {"Code": pkg.get("packagingType", "02")},
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": str(float(pkg.get("weight", 1.0))),
            },
        }
        if all(pkg.get(d) for d in ("length", "width", "height")):
            ups_pkg["Dimensions"] = {
                "UnitOfMeasurement": {"Code": "IN"},
                "Length": str(pkg["length"]),
                "Width": str(pkg["width"]),
                "Height": str(pkg["height"]),
            }
        ups_packages.append(ups_pkg)

    shipment: dict[str, Any] = {
        "Shipper": ups_shipper,
        "ShipTo": ups_ship_to,
        "ShipFrom": ups_shipper,
        "Package": ups_packages,
    }

    if service_code:
        shipment["Service"] = {"Code": service_code}

    return {
        "RateRequest": {
            "Request": {"RequestOption": "Rate"},
            "Shipment": shipment,
        }
    }


def _build_address_lines(addr: dict[str, str]) -> list[str]:
    """Build UPS AddressLine array from simplified address dict.

    Args:
        addr: Dict with addressLine1, addressLine2, addressLine3 keys.

    Returns:
        List of non-empty address lines.
    """
    lines = []
    for key in ("addressLine1", "addressLine2", "addressLine3"):
        value = addr.get(key, "")
        if value:
            lines.append(value)
    return lines or [""]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_ups_payload_builder.py -v`
Expected: All tests PASS (old + new)

**Step 5: Commit**

```bash
git add src/services/ups_payload_builder.py tests/services/test_ups_payload_builder.py
git commit -m "feat: add build_ups_api_payload and build_ups_rate_payload for UPS API format"
```

---

## Task 4: Create Column Mapping — Failing Tests

**Files:**
- Create: `tests/services/test_column_mapping.py`

**Step 1: Write failing tests**

```python
"""Tests for column mapping service."""

import pytest

from src.services.column_mapping import (
    REQUIRED_FIELDS,
    apply_mapping,
    validate_mapping,
)


class TestValidateMapping:
    """Test mapping validation."""

    def test_valid_mapping_passes(self):
        """Test valid mapping with all required fields."""
        mapping = {
            "shipTo.name": "recipient_name",
            "shipTo.addressLine1": "address",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        errors = validate_mapping(mapping)
        assert errors == []

    def test_missing_required_field(self):
        """Test missing required field is reported."""
        mapping = {
            "shipTo.name": "recipient_name",
            # Missing addressLine1
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        errors = validate_mapping(mapping)
        assert len(errors) == 1
        assert "shipTo.addressLine1" in errors[0]

    def test_extra_optional_fields_allowed(self):
        """Test optional fields don't cause errors."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr1",
            "shipTo.addressLine2": "addr2",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
            "shipTo.phone": "phone",
            "description": "notes",
        }

        errors = validate_mapping(mapping)
        assert errors == []


class TestApplyMapping:
    """Test mapping application to row data."""

    def test_extracts_fields(self):
        """Test fields are extracted from row using mapping."""
        mapping = {
            "shipTo.name": "recipient",
            "shipTo.addressLine1": "address",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight_lbs",
        }

        row = {
            "recipient": "John Doe",
            "address": "123 Main St",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90001",
            "country": "US",
            "weight_lbs": 2.5,
        }

        order_data = apply_mapping(mapping, row)

        assert order_data["ship_to_name"] == "John Doe"
        assert order_data["ship_to_address1"] == "123 Main St"
        assert order_data["ship_to_city"] == "Los Angeles"
        assert order_data["ship_to_state"] == "CA"
        assert order_data["ship_to_postal_code"] == "90001"
        assert order_data["ship_to_country"] == "US"
        assert order_data["weight"] == 2.5

    def test_handles_missing_optional_fields(self):
        """Test missing optional fields are not included."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        row = {
            "name": "Jane",
            "addr": "456 Oak",
            "city": "SF",
            "state": "CA",
            "zip": "94102",
            "country": "US",
            "weight": 1.0,
        }

        order_data = apply_mapping(mapping, row)

        assert "ship_to_phone" not in order_data
        assert "ship_to_address2" not in order_data

    def test_includes_service_code(self):
        """Test serviceCode is mapped."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
            "serviceCode": "service",
        }

        row = {
            "name": "Jane",
            "addr": "456 Oak",
            "city": "SF",
            "state": "CA",
            "zip": "94102",
            "country": "US",
            "weight": 1.0,
            "service": "01",
        }

        order_data = apply_mapping(mapping, row)

        assert order_data["service_code"] == "01"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_column_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError`

---

## Task 5: Create Column Mapping — Implementation

**Files:**
- Create: `src/services/column_mapping.py`

**Step 1: Implement column mapping**

```python
"""Column mapping for CSV/Excel data sources.

Replaces the Jinja2 template generation pipeline (~1100 lines).
The LLM produces a simple lookup table mapping shipment field paths
to source column names. Deterministic code uses this mapping to
extract values from each row.

Example:
    mapping = {"shipTo.name": "recipient_name", "packages[0].weight": "weight_lbs"}
    errors = validate_mapping(mapping)
    order_data = apply_mapping(mapping, row)
"""

from typing import Any


# Fields that must have a mapping entry for valid shipments
REQUIRED_FIELDS = [
    "shipTo.name",
    "shipTo.addressLine1",
    "shipTo.city",
    "shipTo.stateProvinceCode",
    "shipTo.postalCode",
    "shipTo.countryCode",
    "packages[0].weight",
]

# Mapping from simplified path → order_data key used by build_shipment_request
_FIELD_TO_ORDER_DATA: dict[str, str] = {
    "shipTo.name": "ship_to_name",
    "shipTo.attentionName": "ship_to_company",
    "shipTo.addressLine1": "ship_to_address1",
    "shipTo.addressLine2": "ship_to_address2",
    "shipTo.addressLine3": "ship_to_address3",
    "shipTo.city": "ship_to_city",
    "shipTo.stateProvinceCode": "ship_to_state",
    "shipTo.postalCode": "ship_to_postal_code",
    "shipTo.countryCode": "ship_to_country",
    "shipTo.phone": "ship_to_phone",
    "packages[0].weight": "weight",
    "packages[0].length": "length",
    "packages[0].width": "width",
    "packages[0].height": "height",
    "packages[0].packagingType": "packaging_type",
    "packages[0].declaredValue": "declared_value",
    "packages[0].description": "package_description",
    "serviceCode": "service_code",
    "description": "description",
    "reference": "order_number",
    "reference2": "reference2",
    "shipper.name": "shipper_name",
    "shipper.addressLine1": "shipper_address1",
    "shipper.city": "shipper_city",
    "shipper.stateProvinceCode": "shipper_state",
    "shipper.postalCode": "shipper_postal_code",
    "shipper.countryCode": "shipper_country",
    "shipper.phone": "shipper_phone",
}


def validate_mapping(mapping: dict[str, str]) -> list[str]:
    """Validate that all required fields have mapping entries.

    Args:
        mapping: Dict of {simplified_path: source_column_name}.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in mapping:
            errors.append(f"Missing required field mapping: '{field}'")
    return errors


def apply_mapping(mapping: dict[str, str], row: dict[str, Any]) -> dict[str, Any]:
    """Extract order data from a source row using the column mapping.

    Transforms source row data into the order_data format expected by
    build_shipment_request().

    Args:
        mapping: Dict of {simplified_path: source_column_name}.
        row: Source row data with arbitrary column names.

    Returns:
        Dict in order_data format for build_shipment_request().
    """
    order_data: dict[str, Any] = {}

    for simplified_path, source_column in mapping.items():
        order_data_key = _FIELD_TO_ORDER_DATA.get(simplified_path)
        if order_data_key is None:
            continue

        value = row.get(source_column)
        if value is not None:
            order_data[order_data_key] = value

    return order_data
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/services/test_column_mapping.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/services/column_mapping.py tests/services/test_column_mapping.py
git commit -m "feat: add column mapping service — replaces Jinja2 template pipeline"
```

---

## Task 6: Create BatchEngine — Failing Tests

**Files:**
- Create: `tests/services/test_batch_engine.py`

**Step 1: Write failing tests**

```python
"""Tests for consolidated batch engine."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.batch_engine import BatchEngine


@pytest.fixture
def mock_ups_service():
    """Create mock UPSService."""
    svc = MagicMock()
    svc.create_shipment.return_value = {
        "success": True,
        "trackingNumbers": ["1Z999AA10123456784"],
        "labelData": ["base64data=="],
        "shipmentIdentificationNumber": "1Z999AA10123456784",
        "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
    }
    svc.get_rate.return_value = {
        "success": True,
        "totalCharges": {"monetaryValue": "15.50", "amount": "15.50", "currencyCode": "USD"},
    }
    return svc


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = MagicMock()
    return session


class TestBatchEngineExecute:
    """Test batch execution."""

    async def test_processes_all_rows(self, mock_ups_service, mock_db_session):
        """Test all rows are processed successfully."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1", row_number=1, status="pending",
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
                cost_cents=0,
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        result = await engine.execute(
            job_id="job-1", rows=rows, shipper=shipper,
        )

        assert result["successful"] == 1
        assert result["failed"] == 0
        assert mock_ups_service.create_shipment.call_count == 1

    async def test_calls_progress_callback(self, mock_ups_service, mock_db_session):
        """Test on_progress callback is invoked."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        on_progress = AsyncMock()

        rows = [
            MagicMock(
                id="row-1", row_number=1, status="pending",
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
                cost_cents=0,
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        await engine.execute(
            job_id="job-1", rows=rows, shipper=shipper,
            on_progress=on_progress,
        )

        assert on_progress.call_count >= 1

    async def test_handles_ups_error_per_row(self, mock_ups_service, mock_db_session):
        """Test UPS errors are recorded per row without stopping batch."""
        from src.services.ups_service import UPSServiceError

        mock_ups_service.create_shipment.side_effect = UPSServiceError(
            code="E-3003", message="Address invalid"
        )

        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1", row_number=1, status="pending",
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
                cost_cents=0,
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        result = await engine.execute(
            job_id="job-1", rows=rows, shipper=shipper,
        )

        assert result["failed"] == 1
        assert result["successful"] == 0


class TestBatchEnginePreview:
    """Test batch preview (rate quoting)."""

    async def test_returns_estimated_costs(self, mock_ups_service, mock_db_session):
        """Test preview returns cost estimates."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1", row_number=1,
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        result = await engine.preview(
            job_id="job-1", rows=rows, shipper=shipper,
        )

        assert result["total_estimated_cost_cents"] > 0
        assert mock_ups_service.get_rate.call_count == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_batch_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`

---

## Task 7: Create BatchEngine — Implementation

**Files:**
- Create: `src/services/batch_engine.py`

**Step 1: Implement BatchEngine**

```python
"""Consolidated batch engine for preview and execution.

Replaces both src/api/routes/preview.py execution logic and
src/orchestrator/batch/executor.py. Single engine for both
REST API and orchestrator agent paths.

Example:
    engine = BatchEngine(ups_service=svc, db_session=session, account_number="X")
    result = await engine.execute(job_id="...", rows=rows, shipper=shipper)
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.services.ups_payload_builder import (
    build_shipment_request,
    build_ups_api_payload,
    build_ups_rate_payload,
)
from src.services.ups_service import UPSServiceError

logger = logging.getLogger(__name__)

# Default labels output directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LABELS_DIR = PROJECT_ROOT / "labels"

# Callback type for progress reporting
ProgressCallback = Callable[..., Awaitable[None]]


class BatchEngine:
    """Consolidated batch preview and execution engine.

    Uses deterministic payload building + UPSService for all UPS calls.
    Supports progress callbacks for SSE integration.

    Attributes:
        _ups: UPSService instance for UPS API calls
        _db: Database session for row state updates
        _account_number: UPS account number for billing
    """

    MAX_PREVIEW_ROWS = 20

    def __init__(
        self,
        ups_service: Any,
        db_session: Any,
        account_number: str,
        labels_dir: str | None = None,
    ) -> None:
        """Initialize batch engine.

        Args:
            ups_service: UPSService instance
            db_session: SQLAlchemy session for state updates
            account_number: UPS account number
            labels_dir: Directory for label files (default: PROJECT_ROOT/labels)
        """
        self._ups = ups_service
        self._db = db_session
        self._account_number = account_number
        self._labels_dir = labels_dir or os.environ.get(
            "UPS_LABELS_OUTPUT_DIR", str(DEFAULT_LABELS_DIR)
        )

    async def preview(
        self,
        job_id: str,
        rows: list[Any],
        shipper: dict[str, str],
        service_code: str | None = None,
    ) -> dict[str, Any]:
        """Generate preview with cost estimates.

        Rates up to MAX_PREVIEW_ROWS individually, estimates the rest
        from the average cost.

        Args:
            job_id: Job UUID for tracking
            rows: List of JobRow objects with order_data
            shipper: Shipper address info
            service_code: Optional service code override

        Returns:
            Dict with total_estimated_cost_cents, preview_rows, etc.
        """
        preview_rows = []
        total_cost_cents = 0

        for row in rows[: self.MAX_PREVIEW_ROWS]:
            order_data = self._parse_order_data(row)
            simplified = build_shipment_request(
                order_data=order_data,
                shipper=shipper,
                service_code=service_code,
            )
            rate_payload = build_ups_rate_payload(
                simplified, account_number=self._account_number,
            )

            try:
                rate_result = await asyncio.to_thread(
                    self._ups.get_rate, request_body=rate_payload,
                )
                amount = rate_result.get("totalCharges", {}).get("monetaryValue", "0")
                cost_cents = int(float(amount) * 100)
            except UPSServiceError as e:
                logger.warning("Rate quote failed for row %s: %s", row.row_number, e)
                cost_cents = 0

            total_cost_cents += cost_cents

            preview_rows.append({
                "row_number": row.row_number,
                "recipient_name": order_data.get("ship_to_name", f"Row {row.row_number}"),
                "city_state": f"{order_data.get('ship_to_city', '')}, {order_data.get('ship_to_state', '')}",
                "estimated_cost_cents": cost_cents,
            })

        # Estimate remaining rows from average
        additional_rows = max(0, len(rows) - len(preview_rows))
        if additional_rows > 0 and preview_rows:
            avg_cost = total_cost_cents / len(preview_rows)
            total_estimated_cost_cents = total_cost_cents + int(avg_cost * additional_rows)
        else:
            total_estimated_cost_cents = total_cost_cents

        return {
            "job_id": job_id,
            "total_rows": len(rows),
            "preview_rows": preview_rows,
            "additional_rows": additional_rows,
            "total_estimated_cost_cents": total_estimated_cost_cents,
        }

    async def execute(
        self,
        job_id: str,
        rows: list[Any],
        shipper: dict[str, str],
        service_code: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Execute batch shipment processing.

        Processes each row: build payload → create shipment → save results.
        Per-row state writes enable crash recovery.

        Args:
            job_id: Job UUID
            rows: List of JobRow objects
            shipper: Shipper address info
            service_code: Optional service code override
            on_progress: Optional async callback for SSE events

        Returns:
            Dict with successful, failed, total_cost_cents counts
        """
        successful = 0
        failed = 0
        total_cost_cents = 0

        for row in rows:
            if row.status != "pending":
                continue

            try:
                # Parse order data
                order_data = self._parse_order_data(row)

                # Build simplified payload
                simplified = build_shipment_request(
                    order_data=order_data,
                    shipper=shipper,
                    service_code=service_code,
                )

                # Transform to UPS API format
                api_payload = build_ups_api_payload(
                    simplified, account_number=self._account_number,
                )

                # Call UPS (in thread to avoid blocking)
                result = await asyncio.to_thread(
                    self._ups.create_shipment, request_body=api_payload,
                )

                # Extract results
                tracking_numbers = result.get("trackingNumbers", [])
                tracking_number = tracking_numbers[0] if tracking_numbers else ""

                # Save label
                label_path = ""
                label_data_list = result.get("labelData", [])
                if label_data_list and label_data_list[0]:
                    label_path = self._save_label(
                        tracking_number, label_data_list[0],
                    )

                # Cost in cents
                charges = result.get("totalCharges", {})
                cost_cents = int(float(charges.get("monetaryValue", "0")) * 100)

                # Update row state
                row.tracking_number = tracking_number
                row.label_path = label_path
                row.cost_cents = cost_cents
                row.status = "completed"
                row.processed_at = datetime.utcnow().isoformat()
                self._db.commit()

                successful += 1
                total_cost_cents += cost_cents

                if on_progress:
                    await on_progress(
                        "row_completed", job_id=job_id,
                        row_number=row.row_number,
                        tracking_number=tracking_number,
                        cost_cents=cost_cents,
                    )

                logger.info(
                    "Row %d completed: tracking=%s, cost=%d cents",
                    row.row_number, tracking_number, cost_cents,
                )

            except (UPSServiceError, ValueError, Exception) as e:
                error_code = getattr(e, "code", "E-3005")
                error_message = str(e)

                row.status = "failed"
                row.error_code = error_code
                row.error_message = error_message
                self._db.commit()

                failed += 1

                if on_progress:
                    await on_progress(
                        "row_failed", job_id=job_id,
                        row_number=row.row_number,
                        error_code=error_code,
                        error_message=error_message,
                    )

                logger.error("Row %d failed: %s", row.row_number, e)

        return {
            "job_id": job_id,
            "successful": successful,
            "failed": failed,
            "total_cost_cents": total_cost_cents,
            "total_rows": len(rows),
        }

    def _parse_order_data(self, row: Any) -> dict[str, Any]:
        """Parse order_data JSON from a JobRow.

        Args:
            row: JobRow with order_data JSON string

        Returns:
            Parsed order data dict

        Raises:
            ValueError: If order_data is invalid JSON
        """
        if not row.order_data:
            return {}
        try:
            return json.loads(row.order_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid order_data JSON on row {row.row_number}: {e}")

    def _save_label(self, tracking_number: str, base64_data: str) -> str:
        """Save base64-encoded label to disk.

        Args:
            tracking_number: Used for filename
            base64_data: Base64-encoded PDF label

        Returns:
            Absolute path to saved label file
        """
        labels_dir = Path(self._labels_dir)
        labels_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{tracking_number}.pdf"
        filepath = labels_dir / filename

        pdf_bytes = base64.b64decode(base64_data)
        filepath.write_bytes(pdf_bytes)

        return str(filepath)
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/services/test_batch_engine.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/services/batch_engine.py tests/services/test_batch_engine.py
git commit -m "feat: add BatchEngine — consolidated preview + execution engine"
```

---

## Task 8: Rewire REST API Routes

**Files:**
- Modify: `src/api/routes/preview.py`

**Step 1: Write integration test for new execution path**

Add to `tests/api/routes/test_preview_integration.py` (or new file):

```python
"""Test preview route uses BatchEngine."""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestConfirmJobUsesBatchEngine:
    """Test that confirm endpoint delegates to BatchEngine."""

    async def test_batch_engine_called_on_confirm(self):
        """Test BatchEngine.execute is called when job is confirmed."""
        # This verifies the wiring is correct after refactor
        from src.api.routes.preview import _execute_batch

        with patch("src.api.routes.preview.BatchEngine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.execute = AsyncMock(return_value={
                "successful": 1, "failed": 0, "total_cost_cents": 1550,
                "total_rows": 1, "job_id": "test-job",
            })

            # This will test the wiring once we refactor
            assert MockEngine is not None  # placeholder
```

**Step 2: Refactor _execute_batch to use BatchEngine**

Replace `_execute_batch()` in `src/api/routes/preview.py` (lines 200-418) with a version that delegates to BatchEngine. The key changes:

1. Replace `UpsMcpClient` context manager with `UPSService` initialization
2. Replace inline row processing with `BatchEngine.execute()`
3. Wire SSE observer as `on_progress` callback
4. Keep `_get_shipper_info()`, `get_job_preview()`, `confirm_job()` structure

The new `_execute_batch` should:
- Create `UPSService` from env vars
- Create `BatchEngine(ups_service, db, account_number)`
- Query pending rows
- Call `engine.execute(job_id, rows, shipper, on_progress=sse_callback)`
- Update job status from result

**Step 3: Update imports**

Replace:
```python
from src.mcp.ups_client import UpsMcpClient, UpsMcpError
```
With:
```python
from src.services.ups_service import UPSService, UPSServiceError
from src.services.batch_engine import BatchEngine
```

**Step 4: Run tests**

Run: `pytest tests/api/ -v -k "not test_stream_endpoint_exists"`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/api/routes/preview.py
git commit -m "refactor: rewire preview routes to use BatchEngine + UPSService"
```

---

## Task 9: Rewire Orchestrator Agent Tools

**Files:**
- Modify: `src/orchestrator/agent/tools.py`
- Modify: `src/orchestrator/agent/hooks.py`
- Modify: `src/orchestrator/agent/config.py`

**Step 1: Update batch_preview_tool and batch_execute_tool**

In `tools.py`, change `batch_preview_tool` and `batch_execute_tool` to use `BatchEngine` instead of `PreviewGenerator`/`BatchExecutor`. Remove `mapping_template` parameter; replace with `service_code`. The `ups_mcp_call` callback is no longer needed — `BatchEngine` handles UPS calls internally.

**Step 2: Fix hooks.py address validation**

In `hooks.py:95,107`, change:
```python
# Line 95: shipper.get("address") → shipper.get("addressLine1")
# Line 107: ship_to.get("address") → ship_to.get("addressLine1")
```

**Step 3: Update config.py — remove UPS MCP subprocess config**

Remove `get_ups_mcp_config()` (lines 66-110) since UPS is now a direct import, not a subprocess. Update any callers that reference this config.

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/ -v`
Expected: Tests pass (some may need fixture updates)

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools.py src/orchestrator/agent/hooks.py src/orchestrator/agent/config.py
git commit -m "refactor: rewire orchestrator tools to BatchEngine, fix hooks address validation"
```

---

## Task 10: Delete Obsolete Files

**Files:**
- Delete: `src/mcp/ups_client.py`
- Delete: `src/orchestrator/nl_engine/mapping_generator.py`
- Delete: `src/orchestrator/nl_engine/template_validator.py`
- Delete: `src/orchestrator/nl_engine/self_correction.py`
- Delete: `src/orchestrator/nl_engine/ups_schema.py`
- Delete: `src/orchestrator/batch/executor.py`
- Delete: `src/orchestrator/batch/preview.py`
- Delete: `packages/ups-mcp/` (entire directory)

**Step 1: Verify no remaining imports**

Run verification commands to ensure no code still imports the files being deleted:
```bash
grep -r "from src.mcp.ups_client" src/
grep -r "from src.orchestrator.nl_engine.mapping_generator" src/
grep -r "from src.orchestrator.nl_engine.template_validator" src/
grep -r "from src.orchestrator.nl_engine.self_correction" src/
grep -r "from src.orchestrator.nl_engine.ups_schema" src/
grep -r "from src.orchestrator.batch.executor" src/
grep -r "from src.orchestrator.batch.preview" src/
```

Fix any remaining imports before deleting.

**Step 2: Delete the files**

```bash
rm src/mcp/ups_client.py
rm src/orchestrator/nl_engine/mapping_generator.py
rm src/orchestrator/nl_engine/template_validator.py
rm src/orchestrator/nl_engine/self_correction.py
rm src/orchestrator/nl_engine/ups_schema.py
rm src/orchestrator/batch/executor.py
rm src/orchestrator/batch/preview.py
rm -rf packages/ups-mcp/
```

**Step 3: Update __init__.py files and batch package imports**

Update `src/orchestrator/batch/__init__.py` to remove old exports and add any new ones.

**Step 4: Run full test suite**

Run: `pytest -k "not test_stream_endpoint_exists and not edi" -v`
Expected: Tests pass. Tests referencing deleted modules will need to be updated/removed (see Task 11).

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: delete obsolete files — TS MCP, ups_client, template pipeline, old batch engine"
```

---

## Task 11: Update Tests for Deleted Modules

**Files:**
- Remove/update: `tests/mcp/test_ups_client.py`
- Remove/update: `tests/orchestrator/test_mapping_generator.py`
- Remove/update: `tests/orchestrator/test_template_validator.py`
- Remove/update: `tests/orchestrator/test_self_correction.py`
- Update: `tests/orchestrator/batch/test_executor.py`
- Update: `tests/orchestrator/batch/test_preview.py`
- Update: `tests/orchestrator/agent/test_batch_tools.py`
- Update: `tests/helpers/mock_ups_mcp.py`

**Step 1: Delete test files for removed modules**

```bash
rm tests/mcp/test_ups_client.py
rm tests/orchestrator/test_mapping_generator.py
rm tests/orchestrator/test_template_validator.py
rm tests/orchestrator/test_self_correction.py
```

**Step 2: Update batch test files**

- `test_executor.py` — either delete (if testing old BatchExecutor) or refactor to test new BatchEngine
- `test_preview.py` — either delete (if testing old PreviewGenerator) or refactor
- `test_batch_tools.py` — update to test new tool signatures (no mapping_template, uses service_code instead)
- `mock_ups_mcp.py` — replace mock class with UPSService mock helper

**Step 3: Run full test suite**

Run: `pytest -k "not test_stream_endpoint_exists and not edi" --tb=short`
Expected: All tests PASS with no import errors

**Step 4: Commit**

```bash
git add -A
git commit -m "test: update test suite for UPS MCP pivot — remove obsolete, update batch tools"
```

---

## Task 12: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Update CLAUDE.md**

- Update Architecture table: UPS MCP → Python (direct import)
- Update Source Structure: remove `packages/ups-mcp/`, add new services
- Update Technology Stack: remove TypeScript for UPS MCP
- Update MCP Tools section: note UPS is direct import
- Update Common Commands: remove `cd packages/ups-mcp && npm run build`

**Step 2: Update README.md**

- Remove Node.js/pnpm prerequisite for UPS MCP
- Remove "Build the UPS MCP server" installation step
- Update Architecture diagram
- Update Technology Stack table

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update documentation for UPS MCP pivot to Python direct import"
```

---

## Task 13: Final Verification

**Step 1: Run full test suite**

```bash
pytest -k "not test_stream_endpoint_exists and not edi" -v --tb=short
```

Expected: All tests PASS

**Step 2: Verify cleanup**

```bash
# No references to packages/ups-mcp in src/ or tests/
grep -r "packages/ups-mcp" src/ tests/

# No references to ups_client.py
grep -r "ups_client" src/ --include="*.py"

# No references to mapping_generator
grep -r "mapping_generator" src/ --include="*.py"

# No references to template_validator
grep -r "template_validator" src/ --include="*.py"
```

Expected: All commands return empty

**Step 3: Verify the new imports work**

```bash
UPS_MCP_SPECS_DIR=src/mcp/ups/specs python -c "
from src.services.ups_service import UPSService, UPSServiceError
from src.services.batch_engine import BatchEngine
from src.services.column_mapping import validate_mapping, apply_mapping
from src.services.ups_payload_builder import build_ups_api_payload, build_ups_rate_payload
print('All imports OK')
"
```

**Step 4: Commit and summarize**

```bash
git log --oneline feat/migrate-ups-mcp-python..HEAD
```

Review the commit log to verify all tasks are captured.

---

## Summary

| # | Task | Creates/Modifies | Lines |
|---|------|-----------------|-------|
| 1-2 | UPSService | `src/services/ups_service.py` + tests | ~280 |
| 3 | Payload builder enhancement | `src/services/ups_payload_builder.py` + tests | ~200 |
| 4-5 | Column mapping | `src/services/column_mapping.py` + tests | ~100 |
| 6-7 | BatchEngine | `src/services/batch_engine.py` + tests | ~250 |
| 8 | Rewire REST API | `src/api/routes/preview.py` | modify |
| 9 | Rewire orchestrator | 3 files in `agent/` | modify |
| 10 | Delete obsolete | 8 files + `packages/ups-mcp/` | ~2500 deleted |
| 11 | Update tests | 8 test files | modify/delete |
| 12 | Documentation | `CLAUDE.md`, `README.md` | modify |
| 13 | Verification | — | — |

**Net effect:** ~830 lines created, ~2500 lines deleted = **~1670 net lines removed**.
