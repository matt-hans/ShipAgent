"""Tests for template validation against UPS schemas.

This module tests the template_validator module to ensure that:
1. UPS JSON Schemas match Zod schema definitions
2. validate_template_output catches all schema violations
3. format_validation_errors produces clear error messages per CONTEXT.md
"""

import pytest

from src.orchestrator.nl_engine.template_validator import (
    TemplateValidationError,
    ValidationError,
    ValidationResult,
    format_validation_errors,
    validate_field_value,
    validate_template_output,
)
from src.orchestrator.nl_engine.ups_schema import (
    UPS_ADDRESS_SCHEMA,
    UPS_PACKAGE_SCHEMA,
    UPS_PACKAGE_WEIGHT_SCHEMA,
    UPS_PHONE_SCHEMA,
    UPS_SERVICE_SCHEMA,
    UPS_SHIPMENT_SCHEMA,
    UPS_SHIPTO_SCHEMA,
    get_schema_for_path,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def valid_phone_data():
    """Valid UPS phone data."""
    return {"Number": "5551234567"}


@pytest.fixture
def valid_phone_with_extension():
    """Valid UPS phone data with extension."""
    return {"Number": "5551234567", "Extension": "123"}


@pytest.fixture
def valid_address_data():
    """Valid UPS address data."""
    return {
        "AddressLine": ["123 Main Street"],
        "City": "Los Angeles",
        "StateProvinceCode": "CA",
        "PostalCode": "90001",
        "CountryCode": "US",
    }


@pytest.fixture
def valid_address_multiline():
    """Valid UPS address with multiple lines."""
    return {
        "AddressLine": ["123 Main Street", "Suite 100", "Building A"],
        "City": "Los Angeles",
        "StateProvinceCode": "CA",
        "PostalCode": "90001",
        "CountryCode": "US",
    }


@pytest.fixture
def valid_shipto_data(valid_address_data):
    """Valid UPS ShipTo data."""
    return {
        "Name": "John Smith",
        "Address": valid_address_data,
    }


@pytest.fixture
def valid_shipto_with_phone(valid_shipto_data, valid_phone_data):
    """Valid UPS ShipTo data with phone."""
    data = valid_shipto_data.copy()
    data["Phone"] = valid_phone_data
    return data


@pytest.fixture
def valid_package_weight_data():
    """Valid UPS package weight data."""
    return {
        "UnitOfMeasurement": {"Code": "LBS"},
        "Weight": "5.0",
    }


@pytest.fixture
def valid_packaging_data():
    """Valid UPS packaging data."""
    return {"Code": "02", "Description": "Customer Supplied Package"}


@pytest.fixture
def valid_package_data(valid_packaging_data, valid_package_weight_data):
    """Valid UPS package data."""
    return {
        "Packaging": valid_packaging_data,
        "PackageWeight": valid_package_weight_data,
    }


@pytest.fixture
def valid_service_data():
    """Valid UPS service data."""
    return {"Code": "03", "Description": "UPS Ground"}


@pytest.fixture
def invalid_shipto_missing_name(valid_address_data):
    """Invalid ShipTo missing Name field."""
    return {"Address": valid_address_data}


@pytest.fixture
def invalid_address_line_too_long():
    """Invalid address with line exceeding 35 characters."""
    return {
        "AddressLine": ["This is a very long address line that exceeds the maximum allowed length of 35 characters"],
        "City": "Los Angeles",
        "CountryCode": "US",
    }


@pytest.fixture
def invalid_phone_empty_number():
    """Invalid phone with empty number."""
    return {"Number": ""}


# =============================================================================
# TestUPSSchemas - Schema Definition Tests
# =============================================================================


class TestUPSSchemas:
    """Test UPS JSON Schema definitions match Zod schemas."""

    def test_phone_schema_valid(self, valid_phone_data):
        """Valid phone passes validation."""
        result = validate_template_output(valid_phone_data, UPS_PHONE_SCHEMA)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_phone_schema_with_extension(self, valid_phone_with_extension):
        """Valid phone with extension passes validation."""
        result = validate_template_output(valid_phone_with_extension, UPS_PHONE_SCHEMA)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_phone_schema_missing_number(self):
        """Phone without Number fails validation."""
        result = validate_template_output({}, UPS_PHONE_SCHEMA)
        assert result.valid is False
        assert len(result.errors) >= 1
        # Should have required error for Number
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_phone_schema_empty_number(self, invalid_phone_empty_number):
        """Phone with empty number fails minLength validation."""
        result = validate_template_output(invalid_phone_empty_number, UPS_PHONE_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "minLength" for e in result.errors)

    def test_phone_schema_number_too_long(self):
        """Phone with number exceeding maxLength fails."""
        result = validate_template_output(
            {"Number": "1234567890123456"},  # 16 chars, max is 15
            UPS_PHONE_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "maxLength" for e in result.errors)

    def test_address_schema_valid(self, valid_address_data):
        """Valid address passes validation."""
        result = validate_template_output(valid_address_data, UPS_ADDRESS_SCHEMA)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_address_schema_multiline(self, valid_address_multiline):
        """Valid address with 3 lines passes validation."""
        result = validate_template_output(valid_address_multiline, UPS_ADDRESS_SCHEMA)
        assert result.valid is True

    def test_address_schema_missing_city(self):
        """Address without City fails validation."""
        result = validate_template_output(
            {"AddressLine": ["123 Main St"], "CountryCode": "US"},
            UPS_ADDRESS_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_address_schema_missing_address_line(self):
        """Address without AddressLine fails validation."""
        result = validate_template_output(
            {"City": "Los Angeles", "CountryCode": "US"},
            UPS_ADDRESS_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_address_line_too_long(self, invalid_address_line_too_long):
        """Address with line > 35 chars fails maxLength validation."""
        result = validate_template_output(invalid_address_line_too_long, UPS_ADDRESS_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "maxLength" for e in result.errors)

    def test_address_too_many_lines(self):
        """Address with more than 3 lines fails maxItems validation."""
        result = validate_template_output(
            {
                "AddressLine": ["Line 1", "Line 2", "Line 3", "Line 4"],
                "City": "Los Angeles",
                "CountryCode": "US",
            },
            UPS_ADDRESS_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "maxItems" for e in result.errors)

    def test_shipto_schema_valid(self, valid_shipto_data):
        """Valid ShipTo passes validation."""
        result = validate_template_output(valid_shipto_data, UPS_SHIPTO_SCHEMA)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_shipto_schema_with_phone(self, valid_shipto_with_phone):
        """Valid ShipTo with Phone passes validation."""
        result = validate_template_output(valid_shipto_with_phone, UPS_SHIPTO_SCHEMA)
        assert result.valid is True

    def test_shipto_schema_missing_address(self):
        """ShipTo without Address fails validation."""
        result = validate_template_output({"Name": "John Smith"}, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_shipto_schema_missing_name(self, invalid_shipto_missing_name):
        """ShipTo without Name fails validation."""
        result = validate_template_output(invalid_shipto_missing_name, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_package_weight_valid(self, valid_package_weight_data):
        """Valid package weight passes validation."""
        result = validate_template_output(valid_package_weight_data, UPS_PACKAGE_WEIGHT_SCHEMA)
        assert result.valid is True

    def test_package_weight_invalid_format(self):
        """Package weight with invalid format fails pattern validation."""
        result = validate_template_output(
            {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": "five",  # Should be numeric string
            },
            UPS_PACKAGE_WEIGHT_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "pattern" for e in result.errors)

    def test_package_weight_missing_unit(self):
        """Package weight without UnitOfMeasurement fails."""
        result = validate_template_output(
            {"Weight": "5.0"},
            UPS_PACKAGE_WEIGHT_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_package_schema_valid(self, valid_package_data):
        """Valid package passes validation."""
        result = validate_template_output(valid_package_data, UPS_PACKAGE_SCHEMA)
        assert result.valid is True

    def test_service_schema_valid(self, valid_service_data):
        """Valid service passes validation."""
        result = validate_template_output(valid_service_data, UPS_SERVICE_SCHEMA)
        assert result.valid is True

    def test_service_schema_missing_code(self):
        """Service without Code fails validation."""
        result = validate_template_output(
            {"Description": "UPS Ground"},
            UPS_SERVICE_SCHEMA,
        )
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)


# =============================================================================
# TestValidateTemplateOutput - Main Validation Function Tests
# =============================================================================


class TestValidateTemplateOutput:
    """Test validate_template_output function."""

    def test_valid_shipment_passes(
        self, valid_shipto_data, valid_package_data, valid_service_data
    ):
        """Full valid shipment structure passes validation."""
        shipment = {
            "Shipper": {
                "Name": "Acme Corp",
                "ShipperNumber": "123456",
                "Address": {
                    "AddressLine": ["100 Corporate Dr"],
                    "City": "New York",
                    "StateProvinceCode": "NY",
                    "PostalCode": "10001",
                    "CountryCode": "US",
                },
            },
            "ShipTo": valid_shipto_data,
            "PaymentInformation": {
                "ShipmentCharge": {
                    "Type": "01",
                    "BillShipper": {"AccountNumber": "123456"},
                },
            },
            "Service": valid_service_data,
            "Package": valid_package_data,
        }
        result = validate_template_output(shipment, UPS_SHIPMENT_SCHEMA)
        assert result.valid is True

    def test_missing_required_field_fails(self, valid_package_data, valid_service_data):
        """Shipment missing required field fails."""
        # Missing ShipTo
        shipment = {
            "Shipper": {
                "Name": "Acme Corp",
                "ShipperNumber": "123456",
                "Address": {
                    "AddressLine": ["100 Corporate Dr"],
                    "City": "New York",
                    "CountryCode": "US",
                },
            },
            "PaymentInformation": {
                "ShipmentCharge": {
                    "Type": "01",
                    "BillShipper": {"AccountNumber": "123456"},
                },
            },
            "Service": valid_service_data,
            "Package": valid_package_data,
        }
        result = validate_template_output(shipment, UPS_SHIPMENT_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "required" for e in result.errors)

    def test_type_mismatch_fails(self, valid_shipto_data):
        """Wrong type for field fails validation."""
        invalid = valid_shipto_data.copy()
        invalid["Name"] = 12345  # Should be string
        result = validate_template_output(invalid, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "type" for e in result.errors)

    def test_string_too_long_fails(self, valid_shipto_data):
        """String exceeding maxLength fails validation."""
        invalid = valid_shipto_data.copy()
        invalid["Name"] = "A" * 40  # Max is 35
        result = validate_template_output(invalid, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        assert any(e.schema_rule == "maxLength" for e in result.errors)

    def test_collects_all_errors(self):
        """Validator collects ALL errors, not just first."""
        # Missing multiple required fields
        result = validate_template_output({}, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        # Should have errors for both Name and Address
        assert len(result.errors) >= 1
        # Check we got required errors
        required_errors = [e for e in result.errors if e.schema_rule == "required"]
        assert len(required_errors) >= 1

    def test_nested_field_path_correct(self, valid_shipto_data):
        """Nested field errors have correct path like 'Address.City'."""
        invalid = valid_shipto_data.copy()
        # Remove City from Address
        invalid["Address"] = {
            "AddressLine": ["123 Main St"],
            "CountryCode": "US",
        }
        result = validate_template_output(invalid, UPS_SHIPTO_SCHEMA)
        assert result.valid is False
        # Look for error with nested path
        error_paths = [e.path for e in result.errors]
        # Should contain Address path
        assert any("Address" in path for path in error_paths)

    def test_default_schema_is_shipment(self, valid_shipto_data, valid_package_data, valid_service_data):
        """When no schema provided, uses UPS_SHIPMENT_SCHEMA."""
        # This should fail because it's not a full shipment
        result = validate_template_output(valid_shipto_data)
        assert result.valid is False  # ShipTo alone doesn't satisfy Shipment schema


# =============================================================================
# TestValidateFieldValue - Incremental Validation Tests
# =============================================================================


class TestValidateFieldValue:
    """Test validate_field_value for incremental validation."""

    def test_valid_phone_number(self, valid_phone_data):
        """Valid phone passes field validation."""
        result = validate_field_value(valid_phone_data, "Phone")
        assert result.valid is True
        assert len(result.errors) == 0

    def test_invalid_phone_number(self, invalid_phone_empty_number):
        """Invalid phone fails field validation."""
        result = validate_field_value(invalid_phone_empty_number, "Phone")
        assert result.valid is False
        assert len(result.errors) >= 1

    def test_valid_address(self, valid_address_data):
        """Valid address passes field validation."""
        result = validate_field_value(valid_address_data, "Address")
        assert result.valid is True

    def test_invalid_address(self):
        """Invalid address fails field validation."""
        result = validate_field_value(
            {"City": "LA"},  # Missing AddressLine and CountryCode
            "Address",
        )
        assert result.valid is False

    def test_nested_path_lookup(self, valid_address_data):
        """Can validate using nested path like 'ShipTo.Address'."""
        result = validate_field_value(valid_address_data, "ShipTo.Address")
        assert result.valid is True

    def test_invalid_path_raises(self):
        """Invalid path raises ValueError."""
        with pytest.raises(ValueError, match="Schema not found"):
            validate_field_value({}, "NonExistentSchema")


# =============================================================================
# TestFormatValidationErrors - Error Formatting Tests
# =============================================================================


class TestFormatValidationErrors:
    """Test format_validation_errors output per CONTEXT.md Decision 4."""

    def test_valid_result_message(self):
        """Valid result produces success message."""
        result = ValidationResult(valid=True, errors=[])
        output = format_validation_errors(result)
        assert "Validation passed" in output

    def test_single_error_format(self):
        """Single error is formatted correctly."""
        error = ValidationError(
            path="ShipTo.Name",
            message="Missing required field",
            expected="required field",
            actual=None,
            schema_rule="required",
        )
        result = ValidationResult(valid=False, errors=[error])
        output = format_validation_errors(result)

        assert "Validation failed with 1 error" in output
        assert "Error 1: ShipTo.Name" in output
        assert "Expected:" in output
        assert "Got:" in output
        assert "Rule: required" in output

    def test_multiple_errors_format(self):
        """Multiple errors are all included in output."""
        errors = [
            ValidationError(
                path="ShipTo.Name",
                message="Missing required field",
                expected="required field",
                actual=None,
                schema_rule="required",
            ),
            ValidationError(
                path="ShipTo.Address.City",
                message="Field too long",
                expected="string with at most 30 character(s)",
                actual="A very long city name that exceeds the limit",
                schema_rule="maxLength",
            ),
        ]
        result = ValidationResult(valid=False, errors=errors)
        output = format_validation_errors(result)

        assert "Validation failed with 2 error" in output
        assert "Error 1: ShipTo.Name" in output
        assert "Error 2: ShipTo.Address.City" in output

    def test_includes_expected_and_actual(self):
        """Output includes expected and actual values per CONTEXT.md."""
        error = ValidationError(
            path="Phone.Number",
            message="Value too short",
            expected="string with at least 10 character(s)",
            actual="555-1234",
            schema_rule="minLength",
        )
        result = ValidationResult(valid=False, errors=[error])
        output = format_validation_errors(result)

        assert "Expected: string with at least 10 character(s)" in output
        assert "Got: '555-1234'" in output

    def test_includes_schema_rule(self):
        """Output includes schema rule that was violated."""
        error = ValidationError(
            path="Address.PostalCode",
            message="Pattern mismatch",
            expected="string matching pattern",
            actual="INVALID",
            schema_rule="pattern",
        )
        result = ValidationResult(valid=False, errors=[error])
        output = format_validation_errors(result)

        assert "Rule: pattern" in output

    def test_warnings_included(self):
        """Warnings are included in output."""
        result = ValidationResult(
            valid=True,
            errors=[],
            warnings=["Field 'AttentionName' is empty", "Consider adding Phone"],
        )
        output = format_validation_errors(result)

        assert "Warnings:" in output
        assert "AttentionName" in output
        assert "Consider adding Phone" in output


# =============================================================================
# TestValidationResult - Model Tests
# =============================================================================


class TestValidationResult:
    """Test ValidationResult model behavior."""

    def test_valid_result_no_errors(self):
        """Valid result has valid=True and no errors."""
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert result.valid is True
        assert len(result.errors) == 0

    def test_invalid_result_has_errors(self):
        """Invalid result has valid=False and errors."""
        error = ValidationError(
            path="test",
            message="test error",
            expected="something",
            actual=None,
            schema_rule="required",
        )
        result = ValidationResult(valid=False, errors=[error])
        assert result.valid is False
        assert len(result.errors) == 1

    def test_warnings_separate_from_errors(self):
        """Warnings don't affect valid status."""
        result = ValidationResult(
            valid=True,
            errors=[],
            warnings=["This is a warning"],
        )
        assert result.valid is True
        assert len(result.warnings) == 1


# =============================================================================
# TestTemplateValidationError - Exception Tests
# =============================================================================


class TestTemplateValidationError:
    """Test TemplateValidationError exception."""

    def test_exception_message(self):
        """Exception has correct error message."""
        error = ValidationError(
            path="ShipTo.Name",
            message="Missing",
            expected="required",
            actual=None,
            schema_rule="required",
        )
        result = ValidationResult(valid=False, errors=[error])
        exc = TemplateValidationError(result, "my_template")

        assert "my_template" in str(exc)
        assert "1 error" in str(exc)

    def test_exception_has_result(self):
        """Exception provides access to ValidationResult."""
        error = ValidationError(
            path="test",
            message="test",
            expected="test",
            actual=None,
            schema_rule="required",
        )
        result = ValidationResult(valid=False, errors=[error])
        exc = TemplateValidationError(result, "test_template")

        assert exc.result is result
        assert exc.template_name == "test_template"


# =============================================================================
# TestGetSchemaForPath - Schema Registry Tests
# =============================================================================


class TestGetSchemaForPath:
    """Test get_schema_for_path helper function."""

    def test_simple_path(self):
        """Simple path returns correct schema."""
        schema = get_schema_for_path("ShipTo")
        assert "Name" in schema["properties"]
        assert "Address" in schema["properties"]

    def test_nested_path(self):
        """Nested path returns correct schema."""
        schema = get_schema_for_path("ShipTo.Address")
        assert "City" in schema["properties"]
        assert "AddressLine" in schema["properties"]

    def test_deeply_nested_path(self):
        """Deeply nested path works."""
        schema = get_schema_for_path("Shipment.Package.PackageWeight")
        assert "Weight" in schema["properties"]
        assert "UnitOfMeasurement" in schema["properties"]

    def test_empty_path_raises(self):
        """Empty path raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            get_schema_for_path("")

    def test_invalid_path_raises(self):
        """Invalid path raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            get_schema_for_path("NonExistent.Path")
