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
