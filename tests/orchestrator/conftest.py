"""Pytest fixtures for orchestrator integration tests."""

import os
from datetime import datetime

import pytest

from src.orchestrator.models.filter import ColumnInfo


@pytest.fixture
def sample_shipping_schema() -> list[ColumnInfo]:
    """Schema for typical shipping data.

    Includes common columns found in shipping spreadsheets:
    customer info, address fields, package details, order metadata.
    """
    return [
        ColumnInfo(name="customer_name", type="string"),
        ColumnInfo(name="address_line1", type="string"),
        ColumnInfo(name="city", type="string"),
        ColumnInfo(name="state", type="string"),
        ColumnInfo(name="zip", type="string"),
        ColumnInfo(name="phone", type="string"),
        ColumnInfo(name="weight_lbs", type="float"),
        ColumnInfo(name="order_date", type="date"),
        ColumnInfo(name="country_code", type="string"),
    ]


@pytest.fixture
def sample_row_data() -> dict:
    """Sample row for rendering tests.

    Contains realistic data for a California shipping order.
    """
    return {
        "customer_name": "John Smith",
        "address_line1": "123 Main Street",
        "city": "Los Angeles",
        "state": "CA",
        "zip": "90001",
        "phone": "5551234567",
        "weight_lbs": 2.5,
        "order_date": "2026-01-25",
        "country_code": "US",
    }


@pytest.fixture
def schema_with_multiple_dates() -> list[ColumnInfo]:
    """Schema with multiple date columns for elicitation testing."""
    return [
        ColumnInfo(name="customer_name", type="string"),
        ColumnInfo(name="order_date", type="date"),
        ColumnInfo(name="ship_by_date", type="date"),
        ColumnInfo(name="created_at", type="datetime"),
        ColumnInfo(name="state", type="string"),
    ]


@pytest.fixture
def schema_with_weights() -> list[ColumnInfo]:
    """Schema with multiple weight columns for elicitation testing."""
    return [
        ColumnInfo(name="customer_name", type="string"),
        ColumnInfo(name="package_weight", type="float"),
        ColumnInfo(name="total_weight", type="float"),
        ColumnInfo(name="item_weight", type="float"),
        ColumnInfo(name="state", type="string"),
    ]


@pytest.fixture
def has_anthropic_key() -> bool:
    """Check if ANTHROPIC_API_KEY is available."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def current_date_str() -> str:
    """Get current date as string."""
    return datetime.now().strftime("%Y-%m-%d")


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring API key"
    )
