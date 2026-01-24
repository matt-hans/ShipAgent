"""Error code registry with E-XXXX format codes.

This module defines the error code system for ShipAgent, organizing errors
into categories:
- E-1xxx: User data errors
- E-2xxx: Validation errors
- E-3xxx: UPS API errors
- E-4xxx: System/internal errors
- E-5xxx: Authentication errors

Each error includes a code, title, message template, and remediation steps.
"""

from dataclasses import dataclass
from enum import Enum


class ErrorCategory(str, Enum):
    """Categories for error codes."""

    DATA = "data"  # E-1xxx: User data errors
    VALIDATION = "validation"  # E-2xxx: Validation errors
    UPS_API = "ups_api"  # E-3xxx: UPS API errors
    SYSTEM = "system"  # E-4xxx: System/internal errors
    AUTH = "auth"  # E-5xxx: Authentication errors


@dataclass
class ErrorCode:
    """Definition of an error code with metadata.

    Attributes:
        code: Error code in E-XXXX format.
        category: Error category for grouping.
        title: Short title for display.
        message_template: Message with {placeholders} for context.
        remediation: Action user should take to resolve.
        is_retryable: Whether the operation can be retried without user action.
    """

    code: str  # E-XXXX format
    category: ErrorCategory
    title: str  # Short title for display
    message_template: str  # Message with {placeholders}
    remediation: str  # Action user should take
    is_retryable: bool = False  # Can be retried without user action


# Error registry - all defined error codes
ERROR_REGISTRY: dict[str, ErrorCode] = {
    # Data errors (E-1xxx)
    "E-1001": ErrorCode(
        code="E-1001",
        category=ErrorCategory.DATA,
        title="Missing Required Field",
        message_template="Required field '{field}' is missing in row {row}.",
        remediation="Add the missing field to your data source and retry.",
    ),
    "E-1002": ErrorCode(
        code="E-1002",
        category=ErrorCategory.DATA,
        title="Empty Data Source",
        message_template="No rows found in data source after applying filters.",
        remediation="Check your filter criteria or verify the data source contains data.",
    ),
    "E-1003": ErrorCode(
        code="E-1003",
        category=ErrorCategory.DATA,
        title="Invalid Data Type",
        message_template="Field '{field}' in row {row} has invalid type. Expected {expected}, got {actual}.",
        remediation="Correct the data type in your source and retry.",
    ),
    # Validation errors (E-2xxx)
    "E-2001": ErrorCode(
        code="E-2001",
        category=ErrorCategory.VALIDATION,
        title="Invalid ZIP Code",
        message_template="Invalid ZIP code format in row {row}, column '{column}'. Value: '{value}'.",
        remediation="US ZIP codes should be 5 digits (12345) or 9 digits (12345-6789). Correct and retry.",
    ),
    "E-2002": ErrorCode(
        code="E-2002",
        category=ErrorCategory.VALIDATION,
        title="Invalid State Code",
        message_template="Invalid state code '{value}' in row {row}. Must be 2-letter US state code.",
        remediation="Use standard 2-letter state codes (CA, NY, TX, etc.). Correct and retry.",
    ),
    "E-2003": ErrorCode(
        code="E-2003",
        category=ErrorCategory.VALIDATION,
        title="Invalid Phone Number",
        message_template="Invalid phone number format in row {row}. Value: '{value}'.",
        remediation="Phone numbers should be 10 digits. Remove special characters and retry.",
    ),
    "E-2004": ErrorCode(
        code="E-2004",
        category=ErrorCategory.VALIDATION,
        title="Invalid Weight",
        message_template="Invalid weight '{value}' in row {row}. Weight must be positive number.",
        remediation="Correct the weight value and retry.",
    ),
    "E-2005": ErrorCode(
        code="E-2005",
        category=ErrorCategory.VALIDATION,
        title="Address Too Long",
        message_template="Address in row {row} exceeds maximum length ({max_length} characters).",
        remediation="Shorten the address field and retry. UPS limits address lines to 35 characters.",
    ),
    # UPS API errors (E-3xxx)
    "E-3001": ErrorCode(
        code="E-3001",
        category=ErrorCategory.UPS_API,
        title="UPS Service Unavailable",
        message_template="UPS {service} API is not responding.",
        remediation="Wait a few minutes and retry. Check UPS system status at ups.com if issue persists.",
        is_retryable=True,
    ),
    "E-3002": ErrorCode(
        code="E-3002",
        category=ErrorCategory.UPS_API,
        title="UPS Rate Limit Exceeded",
        message_template="Too many requests to UPS API. Rate limit exceeded.",
        remediation="Wait 60 seconds and retry. Consider reducing batch size.",
        is_retryable=True,
    ),
    "E-3003": ErrorCode(
        code="E-3003",
        category=ErrorCategory.UPS_API,
        title="UPS Address Validation Failed",
        message_template="UPS could not validate address in row {row}.",
        remediation="Verify the address is complete and correct. Check for typos.",
    ),
    "E-3004": ErrorCode(
        code="E-3004",
        category=ErrorCategory.UPS_API,
        title="UPS Service Not Available",
        message_template="UPS {service} is not available for this shipment.",
        remediation="Try a different service level or verify delivery address is serviceable.",
    ),
    "E-3005": ErrorCode(
        code="E-3005",
        category=ErrorCategory.UPS_API,
        title="UPS Unknown Error",
        message_template="UPS returned an unexpected error: {ups_message}",
        remediation="Contact support with error code E-3005 and the UPS message for assistance.",
    ),
    # System errors (E-4xxx)
    "E-4001": ErrorCode(
        code="E-4001",
        category=ErrorCategory.SYSTEM,
        title="Database Error",
        message_template="Database operation failed: {details}",
        remediation="This is a system error. Retry the operation. Contact support if issue persists.",
        is_retryable=True,
    ),
    "E-4002": ErrorCode(
        code="E-4002",
        category=ErrorCategory.SYSTEM,
        title="File System Error",
        message_template="Could not {operation} file: {path}",
        remediation="Check disk space and permissions. Retry the operation.",
        is_retryable=True,
    ),
    "E-4003": ErrorCode(
        code="E-4003",
        category=ErrorCategory.SYSTEM,
        title="Template Error",
        message_template="Error processing mapping template: {details}",
        remediation="This indicates a problem with the generated mapping. Contact support.",
    ),
    # Auth errors (E-5xxx)
    "E-5001": ErrorCode(
        code="E-5001",
        category=ErrorCategory.AUTH,
        title="UPS Authentication Failed",
        message_template="Failed to authenticate with UPS API.",
        remediation="Check your UPS credentials in settings. Verify client ID and secret are correct.",
    ),
    "E-5002": ErrorCode(
        code="E-5002",
        category=ErrorCategory.AUTH,
        title="UPS Token Expired",
        message_template="UPS access token has expired and could not be refreshed.",
        remediation="Re-authenticate with UPS in settings.",
        is_retryable=True,
    ),
}


def get_error(code: str) -> ErrorCode | None:
    """Get error definition by code.

    Args:
        code: Error code in E-XXXX format.

    Returns:
        ErrorCode if found, None otherwise.
    """
    return ERROR_REGISTRY.get(code)


def get_errors_by_category(category: ErrorCategory) -> list[ErrorCode]:
    """Get all errors in a category.

    Args:
        category: The error category to filter by.

    Returns:
        List of ErrorCode objects in the specified category.
    """
    return [e for e in ERROR_REGISTRY.values() if e.category == category]
