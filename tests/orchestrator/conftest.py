"""Pytest fixtures for orchestrator integration tests."""

import os
from datetime import datetime

import pytest

from src.orchestrator.models.filter import ColumnInfo
from src.orchestrator.models.mapping import FieldMapping


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
    """Sample row for template rendering.

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
def sample_mappings() -> list[FieldMapping]:
    """User-confirmed mappings for common shipping columns.

    Maps source columns to UPS API payload paths.
    """
    return [
        FieldMapping(
            source_column="customer_name",
            target_path="ShipTo.Name",
            transformation="truncate_address(35)",
        ),
        FieldMapping(
            source_column="address_line1",
            target_path="ShipTo.Address.AddressLine",
            transformation=None,
            default_value=None,
        ),
        FieldMapping(
            source_column="city",
            target_path="ShipTo.Address.City",
        ),
        FieldMapping(
            source_column="state",
            target_path="ShipTo.Address.StateProvinceCode",
        ),
        FieldMapping(
            source_column="zip",
            target_path="ShipTo.Address.PostalCode",
            transformation="format_us_zip",
        ),
        FieldMapping(
            source_column="country_code",
            target_path="ShipTo.Address.CountryCode",
        ),
        FieldMapping(
            source_column="phone",
            target_path="ShipTo.Phone.Number",
            transformation="to_ups_phone",
        ),
        FieldMapping(
            source_column="weight_lbs",
            target_path="Package.PackageWeight.Weight",
            transformation="round_weight(1)",
        ),
    ]


@pytest.fixture
def complete_mappings(sample_mappings: list[FieldMapping]) -> list[FieldMapping]:
    """Complete mappings including Shipper and PaymentInformation.

    Extends sample_mappings with hardcoded shipper info for full validation.
    """
    # Add shipper info (typically from configuration, not source data)
    shipper_mappings = [
        FieldMapping(
            source_column="customer_name",  # Will be overridden
            target_path="Shipper.Name",
            default_value="ShipAgent Corp",
        ),
        FieldMapping(
            source_column="customer_name",  # Will be overridden
            target_path="Shipper.ShipperNumber",
            default_value="ABC123",
        ),
        FieldMapping(
            source_column="address_line1",  # Will be overridden
            target_path="Shipper.Address.AddressLine",
            default_value="100 Corporate Way",
        ),
        FieldMapping(
            source_column="city",  # Will be overridden
            target_path="Shipper.Address.City",
            default_value="San Francisco",
        ),
        FieldMapping(
            source_column="state",  # Will be overridden
            target_path="Shipper.Address.StateProvinceCode",
            default_value="CA",
        ),
        FieldMapping(
            source_column="zip",  # Will be overridden
            target_path="Shipper.Address.PostalCode",
            default_value="94105",
        ),
        FieldMapping(
            source_column="country_code",  # Will be overridden
            target_path="Shipper.Address.CountryCode",
            default_value="US",
        ),
    ]
    return sample_mappings + shipper_mappings


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
