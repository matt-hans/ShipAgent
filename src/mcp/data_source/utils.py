"""Utility functions for Data Source MCP.

Provides helper functions for:
- Row checksum computation (SHA-256 with deterministic JSON serialization)
- Date parsing with ambiguity detection (US vs EU format)

Per RESEARCH.md:
- Use hashlib + JSON with sorted keys for deterministic checksums
- Use dateutil.parser for date parsing with ambiguity detection
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

from dateutil.parser import ParserError, parse

# Excel serial date detection pattern (5-digit numbers)
EXCEL_SERIAL_PATTERN = re.compile(r"^\d{5}$")


def compute_row_checksum(row_data: dict[str, Any]) -> str:
    """Compute SHA-256 checksum for a row.

    Uses JSON serialization with sorted keys for deterministic output.
    This ensures the same data always produces the same checksum,
    regardless of dictionary key insertion order.

    Args:
        row_data: Dictionary of column name to value

    Returns:
        Hex-encoded SHA-256 checksum string (64 characters)

    Example:
        >>> compute_row_checksum({"a": 1, "b": 2})
        >>> compute_row_checksum({"b": 2, "a": 1})  # Same result
    """
    # Sort keys for consistent ordering
    # Use default=str to handle non-JSON-serializable types (dates, decimals, etc.)
    canonical = json.dumps(row_data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_date_with_warnings(value: str | None) -> dict[str, Any]:
    """Parse date string with ambiguity detection.

    Per CONTEXT.md decisions:
    - Auto-detect common formats (ISO, US, EU, Excel serial)
    - Default to US format (MM/DD/YYYY) when ambiguous
    - Flag ambiguous dates with warnings

    Args:
        value: Date string to parse (or None)

    Returns:
        Dictionary with:
        - value: Parsed date as ISO format string (YYYY-MM-DD), or original if unparseable
        - format_detected: Format identifier ('iso', 'us', 'eu', 'excel_serial', 'auto', None)
        - warnings: List of warning dictionaries with type, message, and interpretations

    Example:
        >>> parse_date_with_warnings("2026-01-24")
        {"value": "2026-01-24", "format_detected": "auto", "warnings": []}

        >>> parse_date_with_warnings("01/02/26")  # Ambiguous
        {"value": "2026-01-02",
         "format_detected": "auto",
         "warnings": [{"type": "AMBIGUOUS_DATE", ...}]}
    """
    if not value or not isinstance(value, str):
        return {"value": None, "format_detected": None, "warnings": []}

    value = value.strip()
    if not value:
        return {"value": None, "format_detected": None, "warnings": []}

    warnings: list[dict[str, str]] = []

    # Check for Excel serial date (5-digit number)
    if EXCEL_SERIAL_PATTERN.match(value):
        serial = int(value)
        # Excel epoch is Dec 30, 1899 (accounting for Excel's leap year bug)
        excel_epoch = datetime(1899, 12, 30)
        parsed = excel_epoch + timedelta(days=serial)
        return {
            "value": parsed.date().isoformat(),
            "format_detected": "excel_serial",
            "warnings": [],
        }

    try:
        # Try US format (default per CONTEXT.md)
        us_parsed = parse(value, dayfirst=False)

        # Check for ambiguity by also trying EU format
        try:
            eu_parsed = parse(value, dayfirst=True)
            if us_parsed.date() != eu_parsed.date():
                warnings.append(
                    {
                        "type": "AMBIGUOUS_DATE",
                        "message": (
                            f"Date '{value}' could be "
                            f"{us_parsed.strftime('%b %d, %Y')} (US) or "
                            f"{eu_parsed.strftime('%b %d, %Y')} (EU). "
                            "Using US format."
                        ),
                        "us_interpretation": us_parsed.date().isoformat(),
                        "eu_interpretation": eu_parsed.date().isoformat(),
                    }
                )
        except ParserError:
            # EU parsing failed - no ambiguity
            pass

        return {
            "value": us_parsed.date().isoformat(),
            "format_detected": "auto",
            "warnings": warnings,
        }
    except ParserError:
        # Could not parse - return original value as string
        return {
            "value": value,  # Keep original as string
            "format_detected": None,
            "warnings": [
                {
                    "type": "UNPARSEABLE_DATE",
                    "message": f"Could not parse '{value}' as date",
                }
            ],
        }
