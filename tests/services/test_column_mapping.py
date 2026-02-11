"""Tests for column mapping service."""

import pytest

from src.services.column_mapping import (
    REQUIRED_FIELDS,
    apply_mapping,
    validate_mapping,
)


class TestValidateMapping:
    """Test mapping validation."""

    def test_valid_mapping_passes(self):
        """Test valid mapping with all required fields."""
        mapping = {
            "shipTo.name": "recipient_name",
            "shipTo.addressLine1": "address",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        errors = validate_mapping(mapping)
        assert errors == []

    def test_missing_required_field(self):
        """Test missing required field is reported."""
        mapping = {
            "shipTo.name": "recipient_name",
            # Missing addressLine1
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        errors = validate_mapping(mapping)
        assert len(errors) == 1
        assert "shipTo.addressLine1" in errors[0]

    def test_extra_optional_fields_allowed(self):
        """Test optional fields don't cause errors."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr1",
            "shipTo.addressLine2": "addr2",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
            "shipTo.phone": "phone",
            "description": "notes",
        }

        errors = validate_mapping(mapping)
        assert errors == []


class TestApplyMapping:
    """Test mapping application to row data."""

    def test_extracts_fields(self):
        """Test fields are extracted from row using mapping."""
        mapping = {
            "shipTo.name": "recipient",
            "shipTo.addressLine1": "address",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight_lbs",
        }

        row = {
            "recipient": "John Doe",
            "address": "123 Main St",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90001",
            "country": "US",
            "weight_lbs": 2.5,
        }

        order_data = apply_mapping(mapping, row)

        assert order_data["ship_to_name"] == "John Doe"
        assert order_data["ship_to_address1"] == "123 Main St"
        assert order_data["ship_to_city"] == "Los Angeles"
        assert order_data["ship_to_state"] == "CA"
        assert order_data["ship_to_postal_code"] == "90001"
        assert order_data["ship_to_country"] == "US"
        assert order_data["weight"] == 2.5

    def test_handles_missing_optional_fields(self):
        """Test missing optional fields are not included."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        row = {
            "name": "Jane",
            "addr": "456 Oak",
            "city": "SF",
            "state": "CA",
            "zip": "94102",
            "country": "US",
            "weight": 1.0,
        }

        order_data = apply_mapping(mapping, row)

        assert "ship_to_phone" not in order_data
        assert "ship_to_address2" not in order_data

    def test_includes_service_code(self):
        """Test serviceCode is mapped."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
            "serviceCode": "service",
        }

        row = {
            "name": "Jane",
            "addr": "456 Oak",
            "city": "SF",
            "state": "CA",
            "zip": "94102",
            "country": "US",
            "weight": 1.0,
            "service": "01",
        }

        order_data = apply_mapping(mapping, row)

        assert order_data["service_code"] == "01"
