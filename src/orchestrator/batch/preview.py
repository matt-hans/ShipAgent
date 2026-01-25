"""Preview generation for batch shipments.

Per CONTEXT.md Decision 1:
- Show first 20 rows in detail
- Aggregate stats for remaining rows
- Per-row cost shown plus batch total
- Flag rows with warnings
"""

import json
import logging
from decimal import Decimal
from typing import Any, Awaitable, Callable

from jinja2 import Environment

from src.orchestrator.batch.models import BatchPreview, PreviewRow
from src.orchestrator.filters.logistics import get_logistics_environment

logger = logging.getLogger(__name__)


class PreviewGenerator:
    """Generates batch previews with cost estimates.

    The PreviewGenerator fetches data from the Data MCP, renders Jinja2
    templates, and calls the UPS MCP for rate quotes. It produces a
    BatchPreview object suitable for user confirmation.

    Per CONTEXT.md Decision 1, the first 20 rows are quoted individually
    and remaining rows are estimated from the average cost.
    """

    MAX_PREVIEW_ROWS = 20  # Per CONTEXT.md Decision 1

    def __init__(
        self,
        data_mcp_call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        ups_mcp_call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        jinja_env: Environment | None = None,
    ) -> None:
        """Initialize the preview generator.

        Args:
            data_mcp_call: Function to call Data MCP tools (tool_name, args) -> result.
            ups_mcp_call: Function to call UPS MCP tools (tool_name, args) -> result.
            jinja_env: Optional Jinja2 environment (defaults to logistics env).
        """
        self._data_mcp = data_mcp_call
        self._ups_mcp = ups_mcp_call
        self._jinja_env = jinja_env or get_logistics_environment()

    async def generate_preview(
        self,
        job_id: str,
        filter_clause: str,
        mapping_template: str,
        shipper_info: dict[str, Any],
    ) -> BatchPreview:
        """Generate preview with cost estimates.

        Args:
            job_id: Job ID for tracking.
            filter_clause: SQL WHERE clause for filtering rows.
            mapping_template: Jinja2 template string for mapping row data to UPS payload.
            shipper_info: Shipper address and account info.

        Returns:
            BatchPreview with detailed rows and aggregates.

        Raises:
            RuntimeError: If data retrieval or rate quoting fails.
        """
        # Fetch rows from Data MCP
        data_result = await self._data_mcp(
            "get_rows_by_filter",
            {
                "where_clause": filter_clause,
                "limit": self.MAX_PREVIEW_ROWS,
                "offset": 0,
            },
        )

        total_rows = data_result.get("total_count", 0)
        rows = data_result.get("rows", [])

        # Handle empty batch
        if total_rows == 0:
            return BatchPreview(
                job_id=job_id,
                total_rows=0,
                preview_rows=[],
                additional_rows=0,
                total_estimated_cost_cents=0,
                rows_with_warnings=0,
            )

        # Generate preview rows with rate quotes
        preview_rows: list[PreviewRow] = []
        total_cost_cents = 0
        rows_with_warnings = 0

        template = self._jinja_env.from_string(mapping_template)

        for row in rows:
            row_number = row.get("row_number", 0)
            row_data = row.get("data", {})

            try:
                # Render template with row data
                rendered = template.render(row=row_data, shipper=shipper_info)
                payload = json.loads(rendered)

                # Get rate quote from UPS MCP
                quote_result = await self._ups_mcp("rating_quote", payload)

                # Extract cost
                cost_cents = self._parse_cost_cents(
                    quote_result.get("totalCharges", {}).get("amount", "0.00")
                )

                # Check for warnings
                warnings = self._check_warnings(row_data, quote_result)
                if warnings:
                    rows_with_warnings += 1

                # Extract display fields from payload
                recipient_name = self._extract_recipient_name(payload)
                city_state = self._extract_city_state(payload)
                service = self._extract_service(payload)

                preview_rows.append(
                    PreviewRow(
                        row_number=row_number,
                        recipient_name=self._truncate(recipient_name, 20),
                        city_state=city_state,
                        service=service,
                        estimated_cost_cents=cost_cents,
                        warnings=warnings,
                    )
                )

                total_cost_cents += cost_cents

            except Exception as e:
                logger.error(
                    "Failed to generate preview for row %d: %s",
                    row_number,
                    str(e),
                )
                raise RuntimeError(
                    f"Failed to generate preview for row {row_number}: {e}"
                ) from e

        # Calculate additional rows and estimated cost
        additional_rows = max(0, total_rows - len(preview_rows))

        if additional_rows > 0 and preview_rows:
            # Estimate remaining rows from average cost
            avg_cost = total_cost_cents / len(preview_rows)
            additional_cost = int(avg_cost * additional_rows)
            total_estimated_cost_cents = total_cost_cents + additional_cost
        else:
            total_estimated_cost_cents = total_cost_cents

        return BatchPreview(
            job_id=job_id,
            total_rows=total_rows,
            preview_rows=preview_rows,
            additional_rows=additional_rows,
            total_estimated_cost_cents=total_estimated_cost_cents,
            rows_with_warnings=rows_with_warnings,
        )

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text without cutting words.

        Args:
            text: Text to truncate.
            max_len: Maximum allowed length.

        Returns:
            Truncated text, stripped of trailing whitespace.
        """
        if not text:
            return ""

        text = str(text).strip()

        if len(text) <= max_len:
            return text

        # Find the last space before max_len
        truncated = text[:max_len]
        last_space = truncated.rfind(" ")

        if last_space > 0:
            return truncated[:last_space].rstrip()
        else:
            # Single long word - truncate at exact length
            return truncated.rstrip()

    def _check_warnings(
        self, row_data: dict[str, Any], quote_result: dict[str, Any]
    ) -> list[str]:
        """Extract warnings from rate quote response.

        Checks for address corrections and other warnings in the UPS response.

        Args:
            row_data: Original row data from source.
            quote_result: Rate quote result from UPS MCP.

        Returns:
            List of warning messages.
        """
        warnings: list[str] = []

        # Check for address correction indicator
        if quote_result.get("addressCorrection"):
            warnings.append("Address correction suggested")

        # Check for warnings array in response
        response_warnings = quote_result.get("warnings", [])
        if isinstance(response_warnings, list):
            for warning in response_warnings:
                if isinstance(warning, str):
                    warnings.append(warning)
                elif isinstance(warning, dict) and "message" in warning:
                    warnings.append(warning["message"])

        return warnings

    def _parse_cost_cents(self, amount: str) -> int:
        """Convert string amount to cents.

        Args:
            amount: Amount string (e.g., "12.50").

        Returns:
            Amount in cents as integer (e.g., 1250).
        """
        try:
            # Use Decimal for precision
            decimal_amount = Decimal(str(amount))
            cents = int(decimal_amount * 100)
            return max(0, cents)
        except Exception:
            return 0

    def _extract_recipient_name(self, payload: dict[str, Any]) -> str:
        """Extract recipient name from UPS payload.

        Args:
            payload: Rendered UPS shipping payload.

        Returns:
            Recipient name string.
        """
        # Navigate UPS payload structure
        ship_to = payload.get("ShipTo", {})
        name = ship_to.get("Name", "")

        if not name:
            # Try alternative structure
            attention = ship_to.get("AttentionName", "")
            if attention:
                return attention

        return name or "Unknown"

    def _extract_city_state(self, payload: dict[str, Any]) -> str:
        """Extract city and state from UPS payload.

        Args:
            payload: Rendered UPS shipping payload.

        Returns:
            City and state in 'City, ST' format.
        """
        ship_to = payload.get("ShipTo", {})
        address = ship_to.get("Address", {})

        city = address.get("City", "")
        state = address.get("StateProvinceCode", "")

        if city and state:
            return f"{city}, {state}"
        elif city:
            return city
        elif state:
            return state
        else:
            return "Unknown"

    def _extract_service(self, payload: dict[str, Any]) -> str:
        """Extract service name from UPS payload.

        Args:
            payload: Rendered UPS shipping payload.

        Returns:
            Service name string.
        """
        service = payload.get("Service", {})
        code = service.get("Code", "")

        # Map common codes to names
        service_map = {
            "01": "Next Day Air",
            "02": "2nd Day Air",
            "03": "Ground",
            "12": "3 Day Select",
            "13": "Next Day Air Saver",
            "14": "UPS Next Day Air Early",
            "59": "2nd Day Air A.M.",
            "65": "UPS Saver",
        }

        return service_map.get(code, code or "Unknown")
