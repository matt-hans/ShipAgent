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

__all__ = [
    "ErrorCode",
    "ErrorCategory",
    "ERROR_REGISTRY",
    "get_error",
    "get_errors_by_category",
]
