"""UPS error code translation to ShipAgent friendly messages.

This module maps UPS API error codes and messages to ShipAgent's
error code system, providing user-friendly error messages with
actionable remediation steps.
"""

from src.errors.registry import get_error


# Map of UPS error codes to ShipAgent error codes
# Source: UPS API error documentation
UPS_ERROR_MAP: dict[str, str] = {
    # Address validation errors
    "120100": "E-3003",  # Address validation failed
    "120101": "E-3003",  # Invalid postal code
    "120102": "E-3003",  # Invalid city/state combination
    "120104": "E-3003",  # Invalid address
    # Service availability errors
    "111030": "E-3004",  # Service not available
    "111050": "E-3004",  # Delivery not available to postal code
    "111057": "E-3004",  # Service not available for package type
    # Weight/dimension errors
    "120500": "E-2004",  # Invalid weight
    "120501": "E-2004",  # Weight exceeds limit
    "120502": "E-2004",  # Invalid dimensions
    # Rate errors
    "111210": "E-3004",  # Rate not available
    # Authentication errors
    "250001": "E-5001",  # Invalid credentials
    "250002": "E-5001",  # Authentication failed
    "250003": "E-5002",  # Token expired
    # System/availability errors
    "190001": "E-3001",  # System unavailable
    "190002": "E-3001",  # Service temporarily unavailable
    "190100": "E-3002",  # Rate limit exceeded
    # MCP preflight validation errors
    "ELICITATION_UNSUPPORTED": "E-2010",
    "INCOMPLETE_SHIPMENT": "E-2010",
    "MALFORMED_REQUEST": "E-2011",
    "ELICITATION_DECLINED": "E-2012",
    "ELICITATION_CANCELLED": "E-2012",
    "ELICITATION_INVALID_RESPONSE": "E-4010",
    "ELICITATION_FAILED": "E-4010",
}

# Additional UPS error messages that require pattern matching
UPS_MESSAGE_PATTERNS: dict[str, str] = {
    "invalid zip": "E-2001",
    "invalid postal": "E-2001",
    "address not found": "E-3003",
    "service unavailable": "E-3001",
    "rate limit": "E-3002",
    "unauthorized": "E-5001",
    "token expired": "E-5002",
}


def translate_ups_error(
    ups_code: str | None,
    ups_message: str | None,
    context: dict | None = None,
) -> tuple[str, str, str]:
    """Translate UPS error to ShipAgent error.

    Args:
        ups_code: UPS error code (e.g., "120100").
        ups_message: UPS error message text.
        context: Additional context (row number, field name, etc.).

    Returns:
        Tuple of (error_code, formatted_message, remediation).
    """
    context = context or {}

    # Try direct code lookup first
    if ups_code and ups_code in UPS_ERROR_MAP:
        sa_code = UPS_ERROR_MAP[ups_code]
        error = get_error(sa_code)
        if error:
            message = _format_message(
                error.message_template,
                ups_message=ups_message or "Unknown error",
                **context,
            )
            return (error.code, message, error.remediation)

    # Try message pattern matching
    if ups_message:
        ups_message_lower = ups_message.lower()
        for pattern, sa_code in UPS_MESSAGE_PATTERNS.items():
            if pattern in ups_message_lower:
                error = get_error(sa_code)
                if error:
                    message = _format_message(
                        error.message_template,
                        ups_message=ups_message,
                        **context,
                    )
                    return (error.code, message, error.remediation)

    # Fallback to generic UPS error
    error = get_error("E-3005")  # UPS Unknown Error
    if error:
        message = _format_message(
            error.message_template,
            ups_message=ups_message or f"Code: {ups_code}",
            **context,
        )
        return (error.code, message, error.remediation)

    # Ultimate fallback
    return (
        "E-3005",
        f"UPS error: {ups_message or ups_code or 'Unknown'}",
        "Contact support with this error message for assistance.",
    )


def _format_message(template: str, **kwargs: object) -> str:
    """Format a message template with context, ignoring missing keys.

    Args:
        template: Message template with {placeholder} syntax.
        **kwargs: Values to substitute into the template.

    Returns:
        Formatted message string.
    """
    try:
        return template.format(**kwargs)
    except KeyError:
        # Keep template if some placeholders are missing
        # This handles cases where the template has placeholders
        # that aren't in the context
        return template


def extract_ups_error(response: dict) -> tuple[str | None, str | None]:
    """Extract error code and message from UPS API response.

    UPS responses vary in structure. This handles common formats.

    Args:
        response: UPS API response dictionary.

    Returns:
        Tuple of (error_code, error_message), either may be None.
    """
    # Format 1: response.errors[0].code/message
    if "errors" in response and response["errors"]:
        err = response["errors"][0]
        return (err.get("code"), err.get("message"))

    # Format 2: response.response.errors[0]
    if "response" in response:
        inner = response["response"]
        if "errors" in inner and inner["errors"]:
            err = inner["errors"][0]
            return (err.get("code"), err.get("message"))

    # Format 3: Fault format
    if "Fault" in response:
        fault = response["Fault"]
        if "detail" in fault:
            detail = fault["detail"]
            if "Errors" in detail:
                err = detail["Errors"]
                if isinstance(err, dict) and "ErrorDetail" in err:
                    ed = err["ErrorDetail"]
                    if isinstance(ed, list):
                        ed = ed[0]
                    return (
                        ed.get("PrimaryErrorCode", {}).get("Code"),
                        ed.get("PrimaryErrorCode", {}).get("Description"),
                    )

    return (None, None)
