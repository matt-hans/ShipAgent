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
        if tool_name in {"rate_shipment", "validate_address", "track_package"}:
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
                tool_name in {"create_shipment", "void_shipment"}
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
            is_non_mutating = tool_name in {
                "rate_shipment", "validate_address", "track_package",
            }
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

        return {
            "success": True,
            "totalCharges": {
                "monetaryValue": value,
                "amount": value,
                "currencyCode": charges.get("CurrencyCode", "USD"),
            },
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

    # ── Error translation ──────────────────────────────────────────────

    def _translate_error(self, error: MCPToolError) -> UPSServiceError:
        """Translate MCPToolError to UPSServiceError with ShipAgent E-code.

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

        sa_code, sa_message, remediation = translate_ups_error(
            ups_code, ups_message,
        )

        return UPSServiceError(
            code=sa_code,
            message=sa_message,
            remediation=remediation,
            details=error_data if isinstance(error_data, dict) else None,
        )
