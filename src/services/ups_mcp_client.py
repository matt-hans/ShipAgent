"""Async UPS client via MCP protocol.

Replaces the synchronous UPSService (direct ToolManager import) for the
batch shipping path. Communicates with the UPS MCP server over stdio,
providing the same normalised response format that BatchEngine expects.

Example:
    async with UPSMCPClient(client_id="X", client_secret="Y") as ups:
        rate = await ups.get_rate(request_body=payload)
        shipment = await ups.create_shipment(request_body=payload)
"""

import json
import logging
import os
import asyncio
from typing import Any

from mcp import StdioServerParameters

from src.errors.ups_translation import translate_ups_error
from src.services.errors import UPSServiceError
from src.services.mcp_client import MCPClient, MCPConnectionError, MCPToolError
from src.services.ups_specs import ensure_ups_specs_dir

logger = logging.getLogger(__name__)

# Resolve the venv Python binary for spawning UPS MCP as a subprocess.
# The local fork of ups-mcp is installed as an editable package in the venv.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")


def _ups_is_retryable(error_text: str) -> bool:
    """Classify UPS errors as retryable or not.

    Retries on rate limits, temporary unavailability, and transient
    network issues. Skips retry for validation/auth errors.

    Note: MCP preflight codes (ELICITATION_UNSUPPORTED, INCOMPLETE_SHIPMENT,
    MALFORMED_REQUEST, ELICITATION_DECLINED, ELICITATION_CANCELLED,
    ELICITATION_INVALID_RESPONSE) intentionally do NOT match any pattern
    below, so they are never auto-retried. E-4010 ``is_retryable=True`` in
    the error registry is user-facing guidance only; runtime auto-retry is
    disabled because ``create_shipment`` may have side effects.

    Args:
        error_text: Raw error text from the MCP tool response.

    Returns:
        True if the error is transient and should be retried.
    """
    patterns = [
        "rate limit", "429", "503", "502",
        "timeout", "connection",
        "190001", "190002",  # UPS system unavailable codes
    ]
    lower = error_text.lower()
    return any(p in lower for p in patterns)


class UPSMCPClient:
    """Async UPS client communicating via MCP stdio protocol.

    Drop-in async replacement for the synchronous UPSService.
    Provides the same normalised response dicts that BatchEngine expects.

    Attributes:
        _client_id: UPS OAuth client ID.
        _client_secret: UPS OAuth client secret.
        _environment: 'test' or 'production'.
        _account_number: UPS account number (informational).
        _max_retries: Max retry attempts per tool call.
        _mcp: Underlying generic MCPClient instance.
    """

    # Retry classification: read-only tools get fast retries;
    # mutating tools get zero retries to prevent side effects.
    _READ_ONLY_TOOLS: frozenset[str] = frozenset({
        "rate_shipment", "validate_address", "track_package",
        "rate_pickup", "get_pickup_status", "get_landed_cost_quote",
        "find_locations", "get_political_divisions", "get_service_center_facilities",
    })

    _MUTATING_TOOLS: frozenset[str] = frozenset({
        "create_shipment", "void_shipment", "schedule_pickup", "cancel_pickup",
        "upload_paperless_document", "push_document_to_shipment",
        "delete_paperless_document",
    })

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        environment: str = "test",
        account_number: str = "",
        max_retries: int = 3,
    ) -> None:
        """Initialize UPS MCP client.

        Args:
            client_id: UPS OAuth client ID.
            client_secret: UPS OAuth client secret.
            environment: 'test' or 'production'.
            account_number: UPS account number (for logging).
            max_retries: Max retry attempts for transient errors.
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._environment = environment
        self._account_number = account_number
        self._max_retries = max_retries
        self._mcp = MCPClient(
            server_params=self._build_server_params(),
            max_retries=self._max_retries,
            base_delay=1.0,
            is_retryable=_ups_is_retryable,
        )
        self._reconnect_count = 0

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the UPS MCP server.

        Returns:
            Configured StdioServerParameters.
        """
        specs_dir = ensure_ups_specs_dir()
        return StdioServerParameters(
            command=_VENV_PYTHON,
            args=["-m", "ups_mcp"],
            env={
                "CLIENT_ID": self._client_id,
                "CLIENT_SECRET": self._client_secret,
                "ENVIRONMENT": self._environment,
                "UPS_ACCOUNT_NUMBER": self._account_number,
                "UPS_MCP_SPECS_DIR": specs_dir,
                "PATH": os.environ.get("PATH", ""),
            },
        )

    async def __aenter__(self) -> "UPSMCPClient":
        """Spawn UPS MCP server and initialize connection.

        Returns:
            Self with active MCP connection.

        Raises:
            MCPConnectionError: If server fails to spawn.
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Shut down MCP connection.

        Args:
            exc_type: Exception type if exiting due to error.
            exc_val: Exception value if exiting due to error.
            exc_tb: Exception traceback if exiting due to error.
        """
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to UPS MCP if disconnected."""
        connected = getattr(self._mcp, "is_connected", False)
        if isinstance(connected, bool) and connected:
            return
        await self._mcp.connect()
        logger.info("UPS MCP client connected (env=%s)", self._environment)

    async def disconnect(self) -> None:
        """Disconnect from UPS MCP."""
        await self._mcp.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the underlying MCP session is connected."""
        connected = getattr(self._mcp, "is_connected", False)
        if isinstance(connected, bool):
            return connected
        return getattr(self._mcp, "_session", None) is not None

    @property
    def reconnect_count(self) -> int:
        """Number of reconnects performed after transport failures."""
        return self._reconnect_count

    @property
    def retry_attempts_total(self) -> int:
        """Total MCP retry attempts across tool calls."""
        return self._mcp.retry_attempts_total

    # ── Public API ─────────────────────────────────────────────────────

    async def get_rate(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Get a rate quote for a single service.

        Args:
            request_body: Full UPS RateRequest payload.

        Returns:
            Normalised dict with: success, totalCharges.

        Raises:
            UPSServiceError: On UPS API error.
        """
        try:
            raw = await self._call("rate_shipment", {
                "requestoption": "Rate",
                "request_body": request_body,
            })
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_rate_response(raw)

    async def create_shipment(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Create a shipment via UPS API.

        Args:
            request_body: Full UPS ShipmentRequest payload.

        Returns:
            Normalised dict with: success, trackingNumbers, labelData,
            totalCharges, shipmentIdentificationNumber.

        Raises:
            UPSServiceError: On UPS API or validation error.
        """
        try:
            raw = await self._call("create_shipment", {
                "request_body": request_body,
            })
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_shipment_response(raw)

    async def void_shipment(self, shipment_id: str) -> dict[str, Any]:
        """Void an existing shipment.

        Args:
            shipment_id: UPS shipment identification number.

        Returns:
            Normalised dict with: success, status.

        Raises:
            UPSServiceError: On UPS API error.
        """
        try:
            raw = await self._call("void_shipment", {
                "shipmentidentificationnumber": shipment_id,
            })
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_void_response(raw)

    async def validate_address(
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
            addressLine1: Street address.
            city: City name.
            stateProvinceCode: State/province code.
            postalCode: Postal/ZIP code.
            countryCode: Country code (e.g., "US").
            addressLine2: Optional second address line.

        Returns:
            Normalised dict with: status, candidates.

        Raises:
            UPSServiceError: On UPS API error.
        """
        try:
            raw = await self._call("validate_address", {
                "addressLine1": addressLine1,
                "addressLine2": addressLine2,
                "politicalDivision1": stateProvinceCode,
                "politicalDivision2": city,
                "zipPrimary": postalCode,
                "zipExtended": "",
                "urbanization": "",
                "countryCode": countryCode,
            })
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_address_response(raw)

    # ── Pickup methods ─────────────────────────────────────────────────

    async def schedule_pickup(
        self,
        pickup_date: str,
        ready_time: str,
        close_time: str,
        address_line: str,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        contact_name: str,
        phone_number: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Schedule a UPS carrier pickup.

        Args:
            pickup_date: Pickup date (YYYYMMDD).
            ready_time: Earliest ready time (HHMM, 24-hour).
            close_time: Latest close time (HHMM, 24-hour).
            address_line: Street address.
            city: City name.
            state: State/province code.
            postal_code: Postal/ZIP code.
            country_code: Country code (e.g., "US").
            contact_name: Contact person name.
            phone_number: Contact phone number.
            **kwargs: Additional optional parameters forwarded to MCP tool.

        Returns:
            Normalised dict with: success, prn.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args = {
            "pickup_date": pickup_date,
            "ready_time": ready_time,
            "close_time": close_time,
            "address_line": address_line,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country_code": country_code,
            "contact_name": contact_name,
            "phone_number": phone_number,
            **kwargs,
        }
        try:
            raw = await self._call("schedule_pickup", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_schedule_pickup_response(raw)

    async def cancel_pickup(
        self,
        cancel_by: str,
        prn: str = "",
    ) -> dict[str, Any]:
        """Cancel a previously scheduled pickup.

        Args:
            cancel_by: "prn" to cancel by PRN, "account" for most recent.
            prn: Pickup Request Number (required when cancel_by="prn").

        Returns:
            Normalised dict with: success, status.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args: dict[str, Any] = {"cancel_by": cancel_by}
        if prn:
            args["prn"] = prn
        try:
            raw = await self._call("cancel_pickup", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return {"success": True, "status": "cancelled"}

    async def rate_pickup(
        self,
        pickup_type: str,
        address_line: str,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        pickup_date: str,
        ready_time: str,
        close_time: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get a pickup cost estimate.

        Args:
            pickup_type: "oncall", "smart", or "both".
            address_line: Street address.
            city: City name.
            state: State/province code.
            postal_code: Postal/ZIP code.
            country_code: Country code.
            pickup_date: Pickup date (YYYYMMDD).
            ready_time: Earliest ready time (HHMM).
            close_time: Latest close time (HHMM).
            **kwargs: Additional optional parameters.

        Returns:
            Normalised dict with: success, charges, grandTotal.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args = {
            "pickup_type": pickup_type,
            "address_line": address_line,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country_code": country_code,
            "pickup_date": pickup_date,
            "ready_time": ready_time,
            "close_time": close_time,
            **kwargs,
        }
        try:
            raw = await self._call("rate_pickup", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_rate_pickup_response(raw)

    async def get_pickup_status(
        self,
        pickup_type: str,
        account_number: str = "",
    ) -> dict[str, Any]:
        """Get pending pickup status for the account.

        Args:
            pickup_type: "oncall", "smart", or "both".
            account_number: UPS account number (optional, uses env fallback).

        Returns:
            Normalised dict with: success, pickups.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args: dict[str, Any] = {"pickup_type": pickup_type}
        if account_number:
            args["account_number"] = account_number
        try:
            raw = await self._call("get_pickup_status", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_pickup_status_response(raw)

    # ── Landed cost methods ────────────────────────────────────────────

    async def get_landed_cost(
        self,
        currency_code: str,
        export_country_code: str,
        import_country_code: str,
        commodities: list[dict[str, Any]],
        shipment_type: str = "Sale",
        account_number: str = "",
    ) -> dict[str, Any]:
        """Estimate duties, taxes, and fees for an international shipment.

        Args:
            currency_code: ISO currency code (e.g., "USD").
            export_country_code: Origin country code (e.g., "US").
            import_country_code: Destination country code (e.g., "GB").
            commodities: List of commodity dicts (price, quantity, hs_code).
            shipment_type: Shipment type (default "Sale").
            account_number: UPS account number (optional, uses env fallback).

        Returns:
            Normalised dict with: success, totalLandedCost, currencyCode, items.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args: dict[str, Any] = {
            "currency_code": currency_code,
            "export_country_code": export_country_code,
            "import_country_code": import_country_code,
            "commodities": commodities,
            "shipment_type": shipment_type,
        }
        if account_number:
            args["account_number"] = account_number
        try:
            raw = await self._call("get_landed_cost_quote", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_landed_cost_response(raw)

    # ── Paperless document methods ─────────────────────────────────────

    async def upload_document(
        self,
        file_content_base64: str,
        file_name: str,
        file_format: str,
        document_type: str,
        shipper_number: str = "",
    ) -> dict[str, Any]:
        """Upload a customs/trade document to UPS Forms History.

        Args:
            file_content_base64: Base64-encoded file content.
            file_name: File name (e.g., "invoice.pdf").
            file_format: File format (pdf, doc, xls, etc.).
            document_type: UPS document type code ("002", "003", etc.).
            shipper_number: Shipper number (optional, uses env fallback).

        Returns:
            Normalised dict with: success, documentId.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args: dict[str, Any] = {
            "file_content_base64": file_content_base64,
            "file_name": file_name,
            "file_format": file_format,
            "document_type": document_type,
        }
        if shipper_number:
            args["shipper_number"] = shipper_number
        try:
            raw = await self._call("upload_paperless_document", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_upload_response(raw)

    async def push_document(
        self,
        document_id: str,
        shipment_identifier: str,
        shipment_type: str = "1",
        shipper_number: str = "",
    ) -> dict[str, Any]:
        """Attach a previously uploaded document to a shipment.

        Args:
            document_id: Document ID from upload_document response.
            shipment_identifier: 1Z tracking number.
            shipment_type: "1" for forward, "2" for return.
            shipper_number: Shipper number (optional, uses env fallback).

        Returns:
            Normalised dict with: success.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args: dict[str, Any] = {
            "document_id": document_id,
            "shipment_identifier": shipment_identifier,
            "shipment_type": shipment_type,
        }
        if shipper_number:
            args["shipper_number"] = shipper_number
        try:
            await self._call("push_document_to_shipment", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return {"success": True}

    async def delete_document(
        self,
        document_id: str,
        shipper_number: str = "",
    ) -> dict[str, Any]:
        """Delete a document from UPS Forms History.

        Args:
            document_id: Document ID from upload_document response.
            shipper_number: Shipper number (optional, uses env fallback).

        Returns:
            Normalised dict with: success.

        Raises:
            UPSServiceError: On UPS API error.
        """
        args: dict[str, Any] = {"document_id": document_id}
        if shipper_number:
            args["shipper_number"] = shipper_number
        try:
            await self._call("delete_paperless_document", args)
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return {"success": True}

    # ── Locator methods ────────────────────────────────────────────────

    async def find_locations(
        self,
        location_type: str,
        address_line: str,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        radius: float = 15.0,
        unit_of_measure: str = "MI",
    ) -> dict[str, Any]:
        """Find nearby UPS locations (Access Points, retail, etc.).

        Args:
            location_type: "access_point", "retail", "general", or "services".
            address_line: Street address.
            city: City name.
            state: State/province code.
            postal_code: Postal/ZIP code.
            country_code: Country code.
            radius: Search radius (default 15.0).
            unit_of_measure: "MI" or "KM" (default "MI").

        Returns:
            Normalised dict with: success, locations.

        Raises:
            UPSServiceError: On UPS API error.
        """
        try:
            raw = await self._call("find_locations", {
                "location_type": location_type,
                "address_line": address_line,
                "city": city,
                "state": state,
                "postal_code": postal_code,
                "country_code": country_code,
                "radius": radius,
                "unit_of_measure": unit_of_measure,
            })
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_locations_response(raw)

    async def get_service_center_facilities(
        self,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        pickup_pieces: int = 1,
        container_code: str = "03",
    ) -> dict[str, Any]:
        """Find UPS service center drop-off locations.

        Args:
            city: City name.
            state: State/province code.
            postal_code: Postal/ZIP code.
            country_code: Country code.
            pickup_pieces: Number of pieces (default 1).
            container_code: Container code (default "03").

        Returns:
            Normalised dict with: success, facilities.

        Raises:
            UPSServiceError: On UPS API error.
        """
        try:
            raw = await self._call("get_service_center_facilities", {
                "city": city,
                "state": state,
                "postal_code": postal_code,
                "country_code": country_code,
                "pickup_pieces": pickup_pieces,
                "container_code": container_code,
            })
        except MCPToolError as e:
            raise self._translate_error(e) from e

        return self._normalize_service_center_response(raw)

    # ── Internal helpers ───────────────────────────────────────────────

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool, ensuring the client is connected.

        Args:
            tool_name: MCP tool name.
            arguments: Tool arguments.

        Returns:
            Parsed JSON response dict.

        Raises:
            MCPToolError: On tool error.
            RuntimeError: If client not connected.
        """
        if not self.is_connected:
            raise RuntimeError(
                "UPSMCPClient not connected. Use 'async with UPSMCPClient(...)' context."
            )

        # Faster retries for non-mutating requests. Mutating operations
        # intentionally avoid tool-level retries to prevent side effects.
        if tool_name in self._READ_ONLY_TOOLS:
            retry_kwargs = {"max_retries": 2, "base_delay": 0.2}
        else:
            retry_kwargs = {"max_retries": 0, "base_delay": 1.0}

        try:
            return await self._mcp.call_tool(tool_name, arguments, **retry_kwargs)
        except MCPToolError as e:
            # Keep mutating operations conservative, but allow one bounded
            # retry for known upstream gateway outages where UPS never
            # actually processed the request (e.g., "no healthy upstream").
            if (
                tool_name in self._MUTATING_TOOLS
                and self._is_safe_mutating_retry_error(e.error_text)
            ):
                logger.warning(
                    "UPS upstream transient failure during '%s'; retrying once: %s",
                    tool_name,
                    str(e)[:200],
                )
                await asyncio.sleep(0.5)
                return await self._mcp.call_tool(tool_name, arguments, **retry_kwargs)
            raise
        except Exception as e:
            is_non_mutating = tool_name in self._READ_ONLY_TOOLS
            # For non-mutating operations, treat ANY non-MCPToolError as a
            # transport failure worth reconnecting for.  This handles stale
            # subprocess connections (anyio ClosedResourceError, etc.) that
            # may not appear in the explicit type list.
            if not (is_non_mutating or self._is_transport_error(e)):
                raise

            logger.warning(
                "UPS MCP transport failure during '%s', reconnecting once: %s [%s]",
                tool_name,
                e or type(e).__name__,
                type(e).__name__,
            )
            self._reconnect_count += 1
            await self.disconnect()
            await self.connect()

            # Replay only non-mutating operations after reconnect.
            if is_non_mutating:
                return await self._mcp.call_tool(tool_name, arguments, **retry_kwargs)
            raise

    @staticmethod
    def _is_safe_mutating_retry_error(error_text: str) -> bool:
        """Return True only for strict transient upstream outage signatures.

        This intentionally does NOT retry generic 5xx errors for mutating UPS
        operations to avoid duplicate shipment side effects.
        """
        status_code = None
        message = error_text
        details_raw = ""

        try:
            payload = json.loads(error_text)
            if isinstance(payload, dict):
                status_code = payload.get("status_code")
                message = str(payload.get("message", message))
                details = payload.get("details", {})
                if isinstance(details, dict):
                    details_raw = str(details.get("raw", ""))
        except (TypeError, json.JSONDecodeError):
            pass

        combined = f"{message} {details_raw} {error_text}".lower()
        has_503 = (
            status_code == 503
            or '"status_code": 503' in combined
            or "http 503" in combined
            or "503" in combined
        )
        has_gateway_signature = (
            "no healthy upstream" in combined
            or "upstream connect error" in combined
        )
        return has_503 and has_gateway_signature

    def _is_transport_error(self, error: Exception) -> bool:
        """Classify transport/session failures that warrant reconnect.

        Tool-level UPS errors (MCPToolError) are handled separately and
        should not trigger reconnect retries. Catches anyio closed/broken
        resource errors that occur when MCP subprocess dies while idle.
        """
        if isinstance(error, MCPToolError):
            return False

        # Direct type check for common transport failures.
        if isinstance(
            error,
            (
                MCPConnectionError,
                ConnectionError,
                OSError,
                RuntimeError,
                BrokenPipeError,
                EOFError,
            ),
        ):
            return True

        # anyio raises ClosedResourceError / BrokenResourceError when the
        # subprocess dies. These may not be in our import scope, so check
        # by class name to avoid hard dependency.
        err_name = type(error).__name__
        if err_name in ("ClosedResourceError", "BrokenResourceError", "EndOfStream"):
            return True

        return False

    # ── Response normalisation (ported from UPSService) ────────────────

    def _normalize_shipment_response(self, raw: dict) -> dict[str, Any]:
        """Extract tracking, labels, and cost from raw UPS shipment response.

        Args:
            raw: Raw UPS ShipmentResponse dict.

        Returns:
            Normalised response dict.
        """
        results = (
            raw.get("ShipmentResponse", {})
            .get("ShipmentResults", {})
        )

        ship_id = results.get("ShipmentIdentificationNumber", "")

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

        negotiated = (
            results.get("NegotiatedRateCharges", {})
            .get("TotalCharge", {})
        )
        published = (
            results.get("ShipmentCharges", {})
            .get("TotalCharges", {})
        )
        charges = negotiated if negotiated.get("MonetaryValue") else published

        # Extract itemized charge breakdown (international shipments)
        shipment_charges = results.get("ShipmentCharges", {})
        charge_breakdown = None
        transportation = shipment_charges.get("TransportationCharges", {})
        if transportation.get("MonetaryValue"):
            charge_breakdown = {
                "version": "1.0",
                "transportationCharges": {
                    "monetaryValue": transportation.get("MonetaryValue", "0"),
                    "currencyCode": transportation.get("CurrencyCode", "USD"),
                },
            }
            service_opts = shipment_charges.get("ServiceOptionsCharges", {})
            if service_opts.get("MonetaryValue"):
                charge_breakdown["serviceOptionsCharges"] = {
                    "monetaryValue": service_opts["MonetaryValue"],
                    "currencyCode": service_opts.get("CurrencyCode", "USD"),
                }
            duties = shipment_charges.get("DutyAndTaxCharges", {})
            if duties.get("MonetaryValue"):
                charge_breakdown["dutiesAndTaxes"] = {
                    "monetaryValue": duties["MonetaryValue"],
                    "currencyCode": duties.get("CurrencyCode", "USD"),
                }

        return {
            "success": True,
            "trackingNumbers": tracking_numbers,
            "labelData": label_data,
            "shipmentIdentificationNumber": ship_id,
            "totalCharges": {
                "monetaryValue": charges.get("MonetaryValue", "0"),
                "currencyCode": charges.get("CurrencyCode", "USD"),
            },
            "chargeBreakdown": charge_breakdown,
        }

    def _normalize_rate_response(self, raw: dict) -> dict[str, Any]:
        """Extract rate from raw UPS rate response.

        Prefers negotiated rate over published rate when available.

        Args:
            raw: Raw UPS RateResponse dict.

        Returns:
            Normalised response dict.
        """
        rated = (
            raw.get("RateResponse", {})
            .get("RatedShipment", [{}])
        )
        if isinstance(rated, dict):
            rated = [rated]
        first = rated[0] if rated else {}

        negotiated = (
            first.get("NegotiatedRateCharges", {})
            .get("TotalCharge", {})
        )
        published = first.get("TotalCharges", {})
        charges = negotiated if negotiated.get("MonetaryValue") else published
        value = charges.get("MonetaryValue", "0")

        # Extract itemized charge breakdown (international rates)
        charge_breakdown = None
        transportation = first.get("TransportationCharges", {})
        if transportation.get("MonetaryValue"):
            charge_breakdown = {
                "version": "1.0",
                "transportationCharges": {
                    "monetaryValue": transportation.get("MonetaryValue", "0"),
                    "currencyCode": transportation.get("CurrencyCode", "USD"),
                },
            }
            service_opts = first.get("ServiceOptionsCharges", {})
            if service_opts.get("MonetaryValue"):
                charge_breakdown["serviceOptionsCharges"] = {
                    "monetaryValue": service_opts["MonetaryValue"],
                    "currencyCode": service_opts.get("CurrencyCode", "USD"),
                }

        return {
            "success": True,
            "totalCharges": {
                "monetaryValue": value,
                "amount": value,
                "currencyCode": charges.get("CurrencyCode", "USD"),
            },
            "chargeBreakdown": charge_breakdown,
        }

    def _normalize_address_response(self, raw: dict) -> dict[str, Any]:
        """Extract validation status from raw UPS address response.

        Args:
            raw: Raw UPS XAVResponse dict.

        Returns:
            Normalised response dict.
        """
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
        """Extract void status from raw UPS response.

        Args:
            raw: Raw UPS VoidShipmentResponse dict.

        Returns:
            Normalised response dict.
        """
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

    # ── Pickup response normalisation ─────────────────────────────────

    def _normalize_schedule_pickup_response(self, raw: dict) -> dict[str, Any]:
        """Extract PRN from raw UPS pickup creation response.

        Args:
            raw: Raw UPS PickupCreationResponse dict.

        Returns:
            Normalised response dict with success and prn.
        """
        creation = raw.get("PickupCreationResponse", {})
        prn = creation.get("PRN", "")
        return {
            "success": True,
            "prn": prn,
        }

    def _normalize_rate_pickup_response(self, raw: dict) -> dict[str, Any]:
        """Extract charges from raw UPS pickup rate response.

        Args:
            raw: Raw UPS PickupRateResponse dict.

        Returns:
            Normalised response dict with success, charges, and grandTotal.
        """
        rate_result = raw.get("PickupRateResponse", {}).get("RateResult", {})
        charge_detail = rate_result.get("ChargeDetail", [])
        if isinstance(charge_detail, dict):
            charge_detail = [charge_detail]
        grand_total = rate_result.get("GrandTotalOfAllCharge", "0")
        charges = [
            {
                "amount": c.get("ChargeAmount", "0"),
                "code": c.get("ChargeCode", ""),
            }
            for c in charge_detail
        ]
        return {
            "success": True,
            "charges": charges,
            "grandTotal": grand_total,
        }

    def _normalize_pickup_status_response(self, raw: dict) -> dict[str, Any]:
        """Extract pending pickups from raw UPS pickup status response.

        Args:
            raw: Raw UPS PickupPendingStatusResponse dict.

        Returns:
            Normalised response dict with success and pickups list.
        """
        status_resp = raw.get("PickupPendingStatusResponse", {})
        pending = status_resp.get("PendingStatus", [])
        if isinstance(pending, dict):
            pending = [pending]
        pickups = [
            {
                "pickupDate": p.get("PickupDate", ""),
                "prn": p.get("PRN", ""),
            }
            for p in pending
        ]
        return {
            "success": True,
            "pickups": pickups,
        }

    # ── Landed cost + paperless + locator normalisation ────────────────

    def _normalize_landed_cost_response(self, raw: dict) -> dict[str, Any]:
        """Extract landed cost from raw UPS response.

        Args:
            raw: Raw UPS LandedCostResponse dict.

        Returns:
            Normalised response dict with success, totalLandedCost, items.
        """
        shipment = raw.get("LandedCostResponse", {}).get("shipment", {})
        total = shipment.get("totalLandedCost", "0")
        currency = shipment.get("currencyCode", "USD")
        items_raw = shipment.get("shipmentItems", [])
        if isinstance(items_raw, dict):
            items_raw = [items_raw]
        items = [
            {
                "commodityId": item.get("commodityId", ""),
                "duties": item.get("duties", "0"),
                "taxes": item.get("taxes", "0"),
                "fees": item.get("fees", "0"),
            }
            for item in items_raw
        ]
        return {
            "success": True,
            "totalLandedCost": total,
            "currencyCode": currency,
            "items": items,
        }

    def _normalize_upload_response(self, raw: dict) -> dict[str, Any]:
        """Extract document ID from raw UPS upload response.

        Args:
            raw: Raw UPS UploadResponse dict.

        Returns:
            Normalised response dict with success and documentId.
        """
        upload = raw.get("UploadResponse", {})
        doc_id = (
            upload
            .get("FormsHistoryDocumentID", {})
            .get("DocumentID", "")
        )
        return {
            "success": True,
            "documentId": doc_id,
        }

    def _normalize_locations_response(self, raw: dict) -> dict[str, Any]:
        """Extract locations from raw UPS locator response.

        Args:
            raw: Raw UPS LocatorResponse dict.

        Returns:
            Normalised response dict with success and locations list.
        """
        search = raw.get("LocatorResponse", {}).get("SearchResults", {})
        drop_locs = search.get("DropLocation", [])
        if isinstance(drop_locs, dict):
            drop_locs = [drop_locs]
        locations = [
            {
                "id": loc.get("LocationID", ""),
                "address": loc.get("AddressKeyFormat", {}),
                "phone": loc.get("PhoneNumber", ""),
                "hours": loc.get("OperatingHours", {}),
            }
            for loc in drop_locs
        ]
        return {
            "success": True,
            "locations": locations,
        }

    def _normalize_service_center_response(self, raw: dict) -> dict[str, Any]:
        """Extract service center facilities from raw UPS response.

        Args:
            raw: Raw UPS ServiceCenterResponse dict.

        Returns:
            Normalised response dict with success and facilities list.
        """
        center = raw.get("ServiceCenterResponse", {})
        facilities_raw = center.get("ServiceCenterList", [])
        if isinstance(facilities_raw, dict):
            facilities_raw = [facilities_raw]
        return {
            "success": True,
            "facilities": facilities_raw,
        }

    # ── Error translation ──────────────────────────────────────────────

    def _translate_error(self, error: MCPToolError) -> UPSServiceError:
        """Translate MCPToolError to UPSServiceError with ShipAgent E-code.

        Builds a context dict from ``missing[]`` entries when present,
        using ``prompt`` (plain-English label) with fallback to ``flat_key``.
        Caps displayed fields at 8 with a "+N more" summary.

        Args:
            error: The MCPToolError to translate.

        Returns:
            UPSServiceError with appropriate error code and message.
        """
        raw_str = error.error_text

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

        # Build context from missing[] for E-2010 template placeholders
        missing = error_data.get("missing", [])
        if missing and isinstance(missing, list):
            # Use prompt (plain-English) with fallback to flat_key
            prompts = [
                item.get("prompt") or item.get("flat_key", "unknown")
                for item in missing
                if isinstance(item, dict)
            ]
            # Display first 8, summarize rest
            display_limit = 8
            if len(prompts) > display_limit:
                shown = ", ".join(prompts[:display_limit])
                fields = f"{shown} (+{len(prompts) - display_limit} more)"
            else:
                fields = ", ".join(prompts)
            context = {"count": str(len(prompts)), "fields": fields}
        else:
            # Fallback: prevent raw {count}/{fields} in rendered message
            fallback_fields = (ups_message or "unspecified fields")[:200]
            context = {"count": "0", "fields": fallback_fields}

        # Route MALFORMED_REQUEST by reason for finer error codes
        reason = error_data.get("reason")
        if ups_code == "MALFORMED_REQUEST" and reason:
            if reason == "ambiguous_payer":
                ups_code = "MALFORMED_REQUEST_AMBIGUOUS"
            elif reason == "malformed_structure":
                ups_code = "MALFORMED_REQUEST_STRUCTURE"

        # Preserve MCP reason field for diagnostics (P2 feedback)
        if reason and isinstance(reason, str):
            ups_message = f"{ups_message} (reason: {reason})"

        # Log rare server-side conflict at warning level
        if ups_code == "ELICITATION_INVALID_RESPONSE":
            logger.warning(
                "Elicitation integration conflict for create_shipment: %s",
                ups_message[:200],
            )

        sa_code, sa_message, remediation = translate_ups_error(
            ups_code, ups_message, context=context,
        )

        return UPSServiceError(
            code=sa_code,
            message=sa_message,
            remediation=remediation,
            details=error_data if isinstance(error_data, dict) else None,
        )
