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

        # Prefer negotiated charges over published charges
        negotiated = (
            results.get("NegotiatedRateCharges", {})
            .get("TotalCharge", {})
        )
        published = (
            results.get("ShipmentCharges", {})
            .get("TotalCharges", {})
        )
        charges = negotiated if negotiated.get("MonetaryValue") else published

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
        """Extract rate from raw UPS rate response.

        Prefers negotiated rate over published rate when available.
        """
        rated = (
            raw.get("RateResponse", {})
            .get("RatedShipment", [{}])
        )
        # RatedShipment may be a dict (single) or list (multi)
        if isinstance(rated, dict):
            rated = [rated]
        first = rated[0] if rated else {}

        # Prefer negotiated rate over published rate
        negotiated = (
            first.get("NegotiatedRateCharges", {})
            .get("TotalCharge", {})
        )
        published = first.get("TotalCharges", {})
        charges = negotiated if negotiated.get("MonetaryValue") else published
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
        raw_str = str(error)

        try:
            error_data = json.loads(raw_str)
        except (json.JSONDecodeError, TypeError):
            return UPSServiceError(
                code="E-3005",
                message=f"UPS error: {raw_str}",
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

        # Ensure we never lose the actual error text
        if not ups_message or ups_message == "Unknown error":
            ups_message = raw_str[:500]

        sa_code, sa_message, remediation = translate_ups_error(
            ups_code, ups_message
        )

        return UPSServiceError(
            code=sa_code,
            message=sa_message,
            remediation=remediation,
            details=error_data,
        )
