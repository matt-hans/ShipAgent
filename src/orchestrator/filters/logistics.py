"""Jinja2 logistics filter library for shipping data transformations.

This module provides the Jinja2 filter library referenced in CLAUDE.md for
transforming source data to UPS API payload format. All filters are registered
in a SandboxedEnvironment for security.

Filters provided:
    truncate_address: Truncate address to max length at word boundary
    format_us_zip: Normalize ZIP codes to 5-digit or ZIP+4 format
    round_weight: Round weight with minimum 0.1 lbs
    convert_weight: Convert between weight units (g, kg, oz, lbs)
    lookup_service_code: Map service names to UPS codes
    to_ups_date: Convert dates to UPS YYYYMMDD format
    to_ups_phone: Normalize phone numbers to 10-digit format
    default_value: Provide fallback for null/empty values
    split_name: Extract first or last name from full name
"""

import math
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from dateutil import parser as date_parser
from jinja2.sandbox import SandboxedEnvironment

from src.orchestrator.models.intent import CODE_TO_SERVICE, SERVICE_ALIASES


def truncate_address(value: str, max_length: int = 35) -> str:
    """Truncate address to max_length without cutting words.

    UPS has maximum field lengths (typically 35 chars for address lines).
    This filter truncates at word boundaries to avoid mid-word breaks.

    Args:
        value: Address string to truncate.
        max_length: Maximum allowed length (default 35 for UPS).

    Returns:
        Truncated address string, stripped of trailing whitespace.

    Examples:
        >>> truncate_address("123 Main Street Suite 400", 20)
        '123 Main Street'
        >>> truncate_address("Short", 35)
        'Short'
    """
    if not isinstance(value, str):
        value = str(value)

    value = value.strip()

    if len(value) <= max_length:
        return value

    # Find the last space before max_length
    truncated = value[:max_length]
    last_space = truncated.rfind(" ")

    if last_space > 0:
        # Truncate at word boundary
        return truncated[:last_space].rstrip()
    else:
        # Single long word - truncate at exact length
        return truncated.rstrip()


def format_us_zip(value: str) -> str:
    """Normalize ZIP code to 5-digit or ZIP+4 format.

    Extracts digits only, then formats:
    - 5 digits: returns as-is
    - 9 digits: formats as "XXXXX-XXXX"
    - Other lengths: returns first 5 digits or pads with zeros

    Args:
        value: ZIP code string (may contain formatting characters).

    Returns:
        Normalized ZIP code string.

    Examples:
        >>> format_us_zip("90001")
        '90001'
        >>> format_us_zip("900011234")
        '90001-1234'
        >>> format_us_zip("90001-1234")
        '90001-1234'
    """
    if not isinstance(value, str):
        value = str(value)

    # Extract digits only
    digits = re.sub(r"\D", "", value)

    if len(digits) == 5:
        return digits
    elif len(digits) >= 9:
        # Format as ZIP+4
        return f"{digits[:5]}-{digits[5:9]}"
    elif len(digits) > 5:
        # More than 5 but less than 9 - just use first 5
        return digits[:5]
    else:
        # Less than 5 digits - pad with zeros (edge case)
        return digits.ljust(5, "0")


def round_weight(value: float, decimals: int = 1) -> float:
    """Round weight to specified decimal places with minimum 0.1.

    UPS requires a minimum weight of 0.1 lbs for packages.
    This filter rounds to the specified precision and ensures minimum weight.

    Args:
        value: Weight value to round.
        decimals: Number of decimal places (default 1).

    Returns:
        Rounded weight, minimum 0.1.

    Examples:
        >>> round_weight(5.678, 1)
        5.7
        >>> round_weight(0.02, 1)
        0.1
    """
    if not isinstance(value, (int, float)):
        value = float(value)

    rounded = round(value, decimals)
    return max(rounded, 0.1)


# Weight conversion factors to lbs (base unit)
_WEIGHT_TO_LBS: dict[str, float] = {
    "lbs": 1.0,
    "lb": 1.0,
    "kg": 2.20462,
    "oz": 0.0625,
    "g": 0.00220462,
}


def convert_weight(value: float, from_unit: str, to_unit: str) -> float:
    """Convert weight between units.

    Supported units: g, kg, oz, lbs (lb is alias for lbs).

    Args:
        value: Weight value to convert.
        from_unit: Source unit (g, kg, oz, lbs).
        to_unit: Target unit (g, kg, oz, lbs).

    Returns:
        Converted weight value.

    Raises:
        ValueError: If from_unit or to_unit is not supported.

    Examples:
        >>> convert_weight(1.0, "kg", "lbs")
        2.20462
        >>> convert_weight(16, "oz", "lbs")
        1.0
    """
    if not isinstance(value, (int, float)):
        value = float(value)

    from_unit_lower = from_unit.lower().strip()
    to_unit_lower = to_unit.lower().strip()

    if from_unit_lower not in _WEIGHT_TO_LBS:
        raise ValueError(f"Unsupported source unit: '{from_unit}'. Supported: g, kg, oz, lbs")

    if to_unit_lower not in _WEIGHT_TO_LBS:
        raise ValueError(f"Unsupported target unit: '{to_unit}'. Supported: g, kg, oz, lbs")

    # Convert to lbs first, then to target
    in_lbs = value * _WEIGHT_TO_LBS[from_unit_lower]
    result = in_lbs / _WEIGHT_TO_LBS[to_unit_lower]

    return result


def lookup_service_code(value: str) -> str:
    """Map service name or alias to UPS service code.

    Uses SERVICE_ALIASES from the intent module to resolve user-friendly
    terms like "ground", "overnight", "2-day" to UPS codes.

    Args:
        value: Service name, alias, or code.

    Returns:
        UPS service code (e.g., "03" for Ground).

    Examples:
        >>> lookup_service_code("ground")
        '03'
        >>> lookup_service_code("overnight")
        '01'
        >>> lookup_service_code("03")
        '03'
    """
    if not isinstance(value, str):
        value = str(value)

    value_lower = value.lower().strip()

    # Check if it's already a valid code
    if value_lower in CODE_TO_SERVICE or value in CODE_TO_SERVICE:
        return CODE_TO_SERVICE.get(value, CODE_TO_SERVICE.get(value_lower, value)).value

    # Look up in aliases
    if value_lower in SERVICE_ALIASES:
        return SERVICE_ALIASES[value_lower].value

    # Check if the original value is a valid code
    if value in CODE_TO_SERVICE:
        return value

    # Return as-is if no match (let validation catch invalid codes)
    return value


def to_ups_date(value: str | datetime | date) -> str:
    """Convert date to UPS format (YYYYMMDD).

    Parses various input formats using python-dateutil and outputs
    in UPS's required YYYYMMDD format.

    Args:
        value: Date as string, datetime, or date object.

    Returns:
        Date string in YYYYMMDD format.

    Raises:
        ValueError: If date cannot be parsed.

    Examples:
        >>> to_ups_date("2024-01-15")
        '20240115'
        >>> to_ups_date("January 15, 2024")
        '20240115'
    """
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    elif isinstance(value, date):
        return value.strftime("%Y%m%d")
    elif isinstance(value, str):
        try:
            parsed = date_parser.parse(value)
            return parsed.strftime("%Y%m%d")
        except Exception as e:
            raise ValueError(f"Cannot parse date: '{value}'") from e
    else:
        raise ValueError(f"Unsupported date type: {type(value)}")


def to_ups_phone(value: str) -> str:
    """Normalize phone number to 10-digit format.

    Strips all non-digit characters. If 11 digits starting with "1",
    removes the leading country code.

    Args:
        value: Phone number string (may contain formatting).

    Returns:
        10-digit phone number string.

    Raises:
        ValueError: If phone number is not 10 digits after normalization.

    Examples:
        >>> to_ups_phone("(555) 123-4567")
        '5551234567'
        >>> to_ups_phone("1-555-123-4567")
        '5551234567'
    """
    if not isinstance(value, str):
        value = str(value)

    # Strip all non-digit characters
    digits = re.sub(r"\D", "", value)

    # Remove leading 1 if 11 digits
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        raise ValueError(
            f"Invalid phone number: '{value}' (got {len(digits)} digits, expected 10)"
        )

    return digits


def default_value(value: Any, default: Any) -> Any:
    """Return default if value is None, empty string, or NaN.

    Provides fallback values for null/empty fields in source data.

    Args:
        value: The value to check.
        default: The fallback value to return if value is empty.

    Returns:
        The original value if valid, otherwise the default.

    Examples:
        >>> default_value(None, "N/A")
        'N/A'
        >>> default_value("", "Unknown")
        'Unknown'
        >>> default_value("Alice", "Unknown")
        'Alice'
    """
    # Check for None
    if value is None:
        return default

    # Check for empty string
    if isinstance(value, str) and value.strip() == "":
        return default

    # Check for NaN (float or numpy)
    if isinstance(value, float) and math.isnan(value):
        return default

    return value


def split_name(value: str, part: str) -> str:
    """Extract first or last name from full name.

    Splits on whitespace and returns the requested portion.

    Args:
        value: Full name string.
        part: Which part to return - "first", "last", or "all".

    Returns:
        Requested name portion.

    Examples:
        >>> split_name("John Doe", "first")
        'John'
        >>> split_name("John Doe", "last")
        'Doe'
        >>> split_name("John", "last")
        'John'
    """
    if not isinstance(value, str):
        value = str(value)

    value = value.strip()
    parts = value.split()

    if part == "first":
        return parts[0] if parts else value
    elif part == "last":
        return parts[-1] if parts else value
    elif part == "all":
        return value
    else:
        raise ValueError(f"Invalid name part: '{part}'. Use 'first', 'last', or 'all'")


# Dictionary mapping filter names to functions
LOGISTICS_FILTERS: dict[str, Callable[..., Any]] = {
    "truncate_address": truncate_address,
    "format_us_zip": format_us_zip,
    "round_weight": round_weight,
    "convert_weight": convert_weight,
    "lookup_service_code": lookup_service_code,
    "to_ups_date": to_ups_date,
    "to_ups_phone": to_ups_phone,
    "default_value": default_value,
    "split_name": split_name,
}


def get_logistics_environment() -> SandboxedEnvironment:
    """Create a Jinja2 SandboxedEnvironment with logistics filters registered.

    The SandboxedEnvironment provides security by restricting access to
    potentially dangerous attributes and methods in templates.

    Returns:
        Configured Jinja2 SandboxedEnvironment with all logistics filters.

    Example:
        >>> env = get_logistics_environment()
        >>> template = env.from_string("{{ name | truncate_address(20) }}")
        >>> template.render(name="123 Main Street Suite 400")
        '123 Main Street'
    """
    env = SandboxedEnvironment(autoescape=False)

    # Register all logistics filters
    for name, func in LOGISTICS_FILTERS.items():
        env.filters[name] = func

    return env
