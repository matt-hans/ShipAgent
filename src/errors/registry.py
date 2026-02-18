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
    # MCP preflight validation errors (E-2010 – E-2012)
    "E-2010": ErrorCode(
        code="E-2010",
        category=ErrorCategory.VALIDATION,
        title="Missing Required Shipment Fields",
        message_template="Shipment is missing {count} required field(s): {fields}",
        remediation="Provide the missing fields listed above and retry.",
    ),
    "E-2011": ErrorCode(
        code="E-2011",
        category=ErrorCategory.VALIDATION,
        title="Malformed Shipment Request",
        message_template="Shipment request has invalid structure: {ups_message}",
        remediation="Check the request format and correct any structural issues.",
    ),
    "E-2012": ErrorCode(
        code="E-2012",
        category=ErrorCategory.VALIDATION,
        title="Shipment Creation Cancelled",
        message_template="Shipment creation was cancelled: {ups_message}",
        remediation="Re-initiate the shipment when ready.",
    ),
    # International shipping validation errors (E-2013 – E-2017)
    "E-2013": ErrorCode(
        code="E-2013",
        category=ErrorCategory.VALIDATION,
        title="Missing International Field",
        message_template="Missing required international field: {field_name}",
        remediation="Add the missing field to your source data or provide it during shipment creation.",
    ),
    "E-2014": ErrorCode(
        code="E-2014",
        category=ErrorCategory.VALIDATION,
        title="Invalid HS Tariff Code",
        message_template="Invalid HS tariff code: '{hs_code}'. Must be 6-10 digits.",
        remediation="Check the harmonized system code against your country's tariff schedule.",
    ),
    "E-2015": ErrorCode(
        code="E-2015",
        category=ErrorCategory.VALIDATION,
        title="Unsupported Shipping Lane",
        message_template="Unsupported shipping lane: {origin} to {destination}.",
        remediation="Check that the lane is enabled via INTERNATIONAL_ENABLED_LANES (use * for all destinations).",
    ),
    "E-2016": ErrorCode(
        code="E-2016",
        category=ErrorCategory.VALIDATION,
        title="International Service Unavailable",
        message_template="Service '{service}' is not available for {origin} to {destination}.",
        remediation="Use one of the supported international services for this destination.",
    ),
    "E-2017": ErrorCode(
        code="E-2017",
        category=ErrorCategory.VALIDATION,
        title="Currency Mismatch",
        message_template="Currency mismatch: commodity uses '{commodity_currency}' but invoice uses '{invoice_currency}'.",
        remediation="All commodity values must use the same currency as the invoice total.",
    ),
    # FilterSpec compiler errors (E-2030 – E-2043)
    "E-2030": ErrorCode(
        code="E-2030",
        category=ErrorCategory.VALIDATION,
        title="Unknown Filter Column",
        message_template="Column '{column}' is not in the data source schema.",
        remediation="Check the column name against the schema. Use get_schema to see available columns.",
    ),
    "E-2031": ErrorCode(
        code="E-2031",
        category=ErrorCategory.VALIDATION,
        title="Unknown Canonical Term",
        message_template="Canonical term '{term}' is not recognized.",
        remediation="Use a known region name, state name, or business predicate.",
    ),
    "E-2032": ErrorCode(
        code="E-2032",
        category=ErrorCategory.VALIDATION,
        title="Ambiguous Filter Term",
        message_template="Term '{term}' is ambiguous — multiple interpretations possible.",
        remediation="Choose one of the suggested options to clarify your intent.",
    ),
    "E-2033": ErrorCode(
        code="E-2033",
        category=ErrorCategory.VALIDATION,
        title="Invalid Filter Operator",
        message_template="Operator '{operator}' is not valid for column '{column}' of type '{col_type}'.",
        remediation="Use a supported operator for this column type.",
    ),
    "E-2034": ErrorCode(
        code="E-2034",
        category=ErrorCategory.VALIDATION,
        title="Filter Type Mismatch",
        message_template="Value '{value}' has type '{value_type}' but column '{column}' expects '{col_type}'.",
        remediation="Provide a value that matches the column's data type.",
    ),
    "E-2035": ErrorCode(
        code="E-2035",
        category=ErrorCategory.VALIDATION,
        title="Schema Changed During Filter",
        message_template="Schema signature mismatch: expected '{expected}', got '{actual}'.",
        remediation="The data source schema changed. Re-run the filter to use the updated schema.",
    ),
    "E-2036": ErrorCode(
        code="E-2036",
        category=ErrorCategory.VALIDATION,
        title="Missing Target Column",
        message_template="Business predicate '{predicate}' requires column matching '{patterns}' but none found in schema.",
        remediation="The data source does not have a column matching this predicate. Adjust your filter.",
    ),
    "E-2037": ErrorCode(
        code="E-2037",
        category=ErrorCategory.VALIDATION,
        title="Invalid Operator Arity",
        message_template="Operator '{operator}' expects {expected} operand(s) but got {actual}.",
        remediation="Provide the correct number of operands for this operator.",
    ),
    "E-2038": ErrorCode(
        code="E-2038",
        category=ErrorCategory.VALIDATION,
        title="Missing Filter Operand",
        message_template="Filter condition on column '{column}' is missing required operand(s).",
        remediation="Provide the value(s) to filter by.",
    ),
    "E-2039": ErrorCode(
        code="E-2039",
        category=ErrorCategory.VALIDATION,
        title="Empty IN List",
        message_template="IN operator on column '{column}' has an empty value list.",
        remediation="Provide at least one value for the IN operator.",
    ),
    "E-2040": ErrorCode(
        code="E-2040",
        category=ErrorCategory.VALIDATION,
        title="Filter Token Invalid",
        message_template="Filter resolution token is invalid or expired.",
        remediation="Re-run the filter resolution to get a fresh token.",
    ),
    "E-2041": ErrorCode(
        code="E-2041",
        category=ErrorCategory.VALIDATION,
        title="Filter Token Mismatch",
        message_template="Filter token does not match the current filter spec.",
        remediation="The filter was modified after confirmation. Re-confirm the updated filter.",
    ),
    "E-2042": ErrorCode(
        code="E-2042",
        category=ErrorCategory.VALIDATION,
        title="Filter Confirmation Required",
        message_template="Filter contains terms requiring user confirmation before execution.",
        remediation="Review and confirm the expanded filter terms before proceeding.",
    ),
    "E-2043": ErrorCode(
        code="E-2043",
        category=ErrorCategory.VALIDATION,
        title="Filter Structural Limit",
        message_template="Filter exceeds structural limit: {limit_name} ({actual} > {max}).",
        remediation="Simplify the filter to stay within limits.",
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
    "E-3006": ErrorCode(
        code="E-3006",
        category=ErrorCategory.UPS_API,
        title="Customs Validation Failed",
        message_template="UPS customs validation failed: {ups_message}",
        remediation="Review commodity descriptions, HS codes, and declared values for accuracy.",
    ),
    # UPS MCP v2 — Structured validation errors (E-2020 – E-2022)
    "E-2020": ErrorCode(
        code="E-2020",
        category=ErrorCategory.VALIDATION,
        title="Missing Required Fields",
        message_template="Missing {count} required field(s): {fields}",
        remediation="Provide the missing fields listed above. Check your data source column mapping.",
    ),
    "E-2021": ErrorCode(
        code="E-2021",
        category=ErrorCategory.VALIDATION,
        title="Malformed Request Structure",
        message_template="Request body has structural errors: {ups_message}",
        remediation="Check that the request body matches the expected UPS API format.",
    ),
    "E-2022": ErrorCode(
        code="E-2022",
        category=ErrorCategory.VALIDATION,
        title="Ambiguous Billing",
        message_template="Multiple billing objects found in ShipmentCharge. Only one payer type allowed.",
        remediation="Use exactly one of: BillShipper, BillReceiver, or BillThirdParty per charge.",
    ),
    "E-2023": ErrorCode(
        code="E-2023",
        category=ErrorCategory.VALIDATION,
        title="Structural Fields Required",
        message_template="International shipment requires structural data: {ups_message}",
        remediation=(
            "This shipment requires complex structured data (InternationalForms, Product arrays) "
            "that cannot be collected via simple prompts. Provide the data in your source file "
            "or use the batch path with full commodity and customs information."
        ),
    ),
    # UPS MCP v2 — Domain-specific UPS API errors (E-3007 – E-3009)
    "E-3007": ErrorCode(
        code="E-3007",
        category=ErrorCategory.UPS_API,
        title="Document Not Found",
        message_template="Paperless document not found or expired: {ups_message}",
        remediation="The document may have expired. Re-upload the document and try again.",
    ),
    "E-3008": ErrorCode(
        code="E-3008",
        category=ErrorCategory.UPS_API,
        title="Pickup Timing Error",
        message_template="Pickup scheduling failed: {ups_message}",
        remediation="Check that the pickup date is in the future and within UPS scheduling windows.",
    ),
    "E-3009": ErrorCode(
        code="E-3009",
        category=ErrorCategory.UPS_API,
        title="No Locations Found",
        message_template="No UPS locations found for the given search criteria.",
        remediation="Try expanding the search radius or adjusting the address.",
    ),
    "E-3010": ErrorCode(
        code="E-3010",
        category=ErrorCategory.UPS_API,
        title="CIE Service Unavailable",
        message_template="UPS CIE environment does not support this API: {ups_message}",
        remediation=(
            "The UPS Customer Integration Environment (CIE) has an internal "
            "infrastructure issue for this API. Switch to the production "
            "environment (set ENVIRONMENT=production) or contact UPS developer "
            "support."
        ),
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
    # MCP elicitation integration error (E-4010)
    "E-4010": ErrorCode(
        code="E-4010",
        category=ErrorCategory.SYSTEM,
        title="Elicitation Integration Error",
        message_template="Elicitation response conflict: {ups_message}",
        remediation="This is an internal integration error. Retry the shipment. If the issue persists, report it.",
        # is_retryable is user-facing guidance only; runtime auto-retry is
        # disabled because create_shipment may have side effects.
        # See _ups_is_retryable() which returns False for this code.
        is_retryable=True,
    ),
    # UPS MCP v2 — Elicitation user actions (E-4011 – E-4012)
    "E-4011": ErrorCode(
        code="E-4011",
        category=ErrorCategory.SYSTEM,
        title="Missing Required Fields",
        message_template="Missing {count} required field(s): {fields}",
        remediation="Provide the missing fields listed above and retry the operation.",
    ),
    "E-4012": ErrorCode(
        code="E-4012",
        category=ErrorCategory.SYSTEM,
        title="Elicitation Cancelled",
        message_template="User cancelled the operation.",
        remediation="The operation was cancelled by the user.",
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
