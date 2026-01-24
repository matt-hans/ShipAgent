"""Error handling framework for ShipAgent.

This package provides:
- Error code registry with E-XXXX format codes
- UPS error translation to friendly messages
- Error formatting and grouping utilities

Error categories:
- E-1xxx: User data errors
- E-2xxx: Validation errors
- E-3xxx: UPS API errors
- E-4xxx: System/internal errors
- E-5xxx: Authentication errors
"""

from src.errors.registry import (
    ErrorCategory,
    ErrorCode,
    ERROR_REGISTRY,
    get_error,
    get_errors_by_category,
)
from src.errors.ups_translation import (
    UPS_ERROR_MAP,
    extract_ups_error,
    translate_ups_error,
)
from src.errors.formatter import (
    ShipAgentError,
    format_error,
    format_error_summary,
    group_errors,
)

__all__ = [
    # Registry
    "ErrorCode",
    "ErrorCategory",
    "ERROR_REGISTRY",
    "get_error",
    "get_errors_by_category",
    # UPS translation
    "translate_ups_error",
    "extract_ups_error",
    "UPS_ERROR_MAP",
    # Formatter
    "ShipAgentError",
    "format_error",
    "group_errors",
    "format_error_summary",
]
