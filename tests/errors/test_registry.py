"""Unit tests for src/errors/registry.py.

Tests verify:
- UPS MCP v2 error codes are registered with correct categories and titles
"""

import pytest

from src.errors.registry import ErrorCategory, get_error


@pytest.mark.parametrize(
    "code,category,title",
    [
        ("E-2020", ErrorCategory.VALIDATION, "Missing Required Fields"),
        ("E-2021", ErrorCategory.VALIDATION, "Malformed Request Structure"),
        ("E-2022", ErrorCategory.VALIDATION, "Ambiguous Billing"),
        ("E-3007", ErrorCategory.UPS_API, "Document Not Found"),
        ("E-3008", ErrorCategory.UPS_API, "Pickup Timing Error"),
        ("E-3009", ErrorCategory.UPS_API, "No Locations Found"),
        ("E-3010", ErrorCategory.UPS_API, "CIE Service Unavailable"),
        ("E-4011", ErrorCategory.SYSTEM, "Missing Required Fields"),
        ("E-4012", ErrorCategory.SYSTEM, "Elicitation Cancelled"),
    ],
)
def test_v2_error_codes_registered(code, category, title):
    """All UPS MCP v2 error codes must be registered."""
    error = get_error(code)
    assert error is not None, f"{code} not found in registry"
    assert error.category == category
    assert error.title == title


@pytest.mark.parametrize(
    "code,title",
    [
        ("E-6001", "Relay Target Offline"),
        ("E-6002", "Relay Disconnected Mid Call"),
        ("E-6003", "Relay Invocation Deadline Exceeded"),
        ("E-6004", "Relay Processing Unknown"),
        ("E-6005", "Relay Invocation Abandoned"),
        ("E-6006", "Relay Envelope Rejected"),
        ("E-6007", "Relay Invocation Unavailable"),
        ("E-6008", "Execution Approval Expired"),
    ],
)
def test_provider_lifecycle_errors_are_registered_without_automatic_retry(code, title):
    error = get_error(code)
    assert error is not None
    assert error.category.value == "provider"
    assert error.title == title
    assert error.is_retryable is False
    assert "{" not in error.message_template  # No dependency payload interpolation.
