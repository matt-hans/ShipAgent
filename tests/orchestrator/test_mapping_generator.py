"""Tests for mapping template generator.

This module tests the mapping generator functions including schema hashing,
template generation, and template rendering.
"""

import pytest

from src.orchestrator.models.filter import ColumnInfo
from src.orchestrator.models.mapping import (
    FieldMapping,
    MappingGenerationError,
    MappingTemplate,
    UPSTargetField,
)
from src.orchestrator.nl_engine.mapping_generator import (
    UPS_REQUIRED_FIELDS,
    compute_schema_hash,
    generate_mapping_template,
    render_template,
)


class TestSchemaHash:
    """Tests for compute_schema_hash function."""

    def test_deterministic(self):
        """Same columns produce same hash."""
        hash1 = compute_schema_hash(["name", "city", "state"])
        hash2 = compute_schema_hash(["name", "city", "state"])
        assert hash1 == hash2

    def test_order_independent(self):
        """Column order doesn't affect hash."""
        hash1 = compute_schema_hash(["a", "b", "c"])
        hash2 = compute_schema_hash(["c", "b", "a"])
        assert hash1 == hash2

    def test_different_columns_different_hash(self):
        """Different columns produce different hash."""
        hash1 = compute_schema_hash(["name", "city"])
        hash2 = compute_schema_hash(["address", "zip"])
        assert hash1 != hash2

    def test_hash_length_16(self):
        """Hash is 16 characters long."""
        result = compute_schema_hash(["name", "city"])
        assert len(result) == 16

    def test_hash_is_hex(self):
        """Hash contains only hex characters."""
        result = compute_schema_hash(["name", "city"])
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_columns(self):
        """Empty column list produces valid hash."""
        result = compute_schema_hash([])
        assert len(result) == 16


class TestFieldMapping:
    """Tests for FieldMapping model."""

    def test_minimal_mapping(self):
        """Minimal mapping with just source and target."""
        mapping = FieldMapping(
            source_column="name",
            target_path="ShipTo.Name",
        )
        assert mapping.source_column == "name"
        assert mapping.target_path == "ShipTo.Name"
        assert mapping.transformation is None
        assert mapping.default_value is None

    def test_mapping_with_transformation(self):
        """Mapping with transformation filter."""
        mapping = FieldMapping(
            source_column="name",
            target_path="ShipTo.Name",
            transformation="truncate_address(35)",
        )
        assert mapping.transformation == "truncate_address(35)"

    def test_mapping_with_default(self):
        """Mapping with default value."""
        mapping = FieldMapping(
            source_column="name",
            target_path="ShipTo.Name",
            default_value="Unknown",
        )
        assert mapping.default_value == "Unknown"

    def test_mapping_with_all_fields(self):
        """Mapping with all fields populated."""
        mapping = FieldMapping(
            source_column="name",
            target_path="ShipTo.Name",
            transformation="truncate_address(35)",
            default_value="Unknown",
        )
        assert mapping.source_column == "name"
        assert mapping.target_path == "ShipTo.Name"
        assert mapping.transformation == "truncate_address(35)"
        assert mapping.default_value == "Unknown"


class TestMappingTemplate:
    """Tests for MappingTemplate model."""

    def test_template_with_mappings(self):
        """Template with list of mappings."""
        template = MappingTemplate(
            name="test_template",
            source_schema_hash="abc123",
            mappings=[
                FieldMapping(source_column="name", target_path="ShipTo.Name"),
                FieldMapping(source_column="city", target_path="ShipTo.Address.City"),
            ],
        )
        assert template.name == "test_template"
        assert len(template.mappings) == 2

    def test_missing_required_detected(self):
        """Missing required fields are tracked."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            mappings=[],
            missing_required=["ShipTo.Name", "ShipTo.Address.City"],
        )
        assert len(template.missing_required) == 2
        assert "ShipTo.Name" in template.missing_required

    def test_jinja_template_populated(self):
        """Jinja template string can be set."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template='{"ShipTo": {"Name": "{{ name }}"}}',
        )
        assert template.jinja_template is not None
        assert "{{ name }}" in template.jinja_template


class TestUPSTargetField:
    """Tests for UPSTargetField model."""

    def test_field_creation(self):
        """UPS target field creation works."""
        field = UPSTargetField(
            path="ShipTo.Name",
            type="string",
            required=True,
            max_length=35,
            description="Recipient name",
        )
        assert field.path == "ShipTo.Name"
        assert field.type == "string"
        assert field.required is True
        assert field.max_length == 35

    def test_required_fields_defined(self):
        """UPS_REQUIRED_FIELDS contains expected fields."""
        paths = [f.path for f in UPS_REQUIRED_FIELDS]
        assert "ShipTo.Name" in paths
        assert "ShipTo.Address.City" in paths
        assert "ShipTo.Address.PostalCode" in paths


class TestGenerateMappingTemplate:
    """Tests for generate_mapping_template function."""

    @pytest.fixture
    def simple_schema(self):
        """Simple schema for testing."""
        return [
            ColumnInfo(name="name", type="string"),
            ColumnInfo(name="city", type="string"),
            ColumnInfo(name="state", type="string"),
        ]

    @pytest.fixture
    def simple_mappings(self):
        """Simple mappings for testing."""
        return [
            FieldMapping(source_column="name", target_path="ShipTo.Name"),
            FieldMapping(source_column="city", target_path="ShipTo.Address.City"),
        ]

    def test_simple_mapping_generates_template(self, simple_schema, simple_mappings):
        """Simple mapping generates valid template."""
        template = generate_mapping_template(
            simple_schema,
            simple_mappings,
            "test_template",
        )
        assert template.name == "test_template"
        assert len(template.mappings) == 2
        assert template.jinja_template is not None

    def test_template_compiles_in_environment(self, simple_schema, simple_mappings):
        """Generated template compiles in Jinja2 environment."""
        from src.orchestrator.filters.logistics import get_logistics_environment

        template = generate_mapping_template(simple_schema, simple_mappings)
        env = get_logistics_environment()
        # Should not raise
        jinja_template = env.from_string(template.jinja_template)
        assert jinja_template is not None

    def test_missing_required_fields_listed(self, simple_schema, simple_mappings):
        """Missing required UPS fields are identified."""
        template = generate_mapping_template(simple_schema, simple_mappings)
        # ShipTo.Name is mapped, but others are missing
        assert "ShipTo.Address.PostalCode" in template.missing_required
        assert "ShipTo.Address.CountryCode" in template.missing_required
        assert "Package.PackageWeight.Weight" in template.missing_required
        # ShipTo.Name is mapped, so should NOT be in missing
        assert "ShipTo.Name" not in template.missing_required

    def test_schema_hash_computed(self, simple_schema, simple_mappings):
        """Schema hash is computed from column names."""
        template = generate_mapping_template(simple_schema, simple_mappings)
        assert template.source_schema_hash is not None
        assert len(template.source_schema_hash) == 16

    def test_invalid_source_column_raises(self, simple_schema):
        """Mapping with invalid source column raises error."""
        invalid_mappings = [
            FieldMapping(source_column="nonexistent", target_path="ShipTo.Name"),
        ]
        with pytest.raises(MappingGenerationError) as exc_info:
            generate_mapping_template(simple_schema, invalid_mappings)
        assert "nonexistent" in str(exc_info.value)
        assert "not found in schema" in str(exc_info.value)

    def test_transformation_included_in_template(self, simple_schema):
        """Transformations are included in generated template."""
        mappings = [
            FieldMapping(
                source_column="name",
                target_path="ShipTo.Name",
                transformation="truncate_address(35)",
            ),
        ]
        template = generate_mapping_template(simple_schema, mappings)
        assert "truncate_address(35)" in template.jinja_template

    def test_default_value_included_in_template(self, simple_schema):
        """Default values are included in generated template."""
        mappings = [
            FieldMapping(
                source_column="name",
                target_path="ShipTo.Name",
                default_value="Unknown",
            ),
        ]
        template = generate_mapping_template(simple_schema, mappings)
        assert "default_value" in template.jinja_template
        assert "Unknown" in template.jinja_template


class TestRenderTemplate:
    """Tests for render_template function."""

    @pytest.fixture
    def simple_template(self):
        """Simple template for testing."""
        return MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template='{"ShipTo": {"Name": "{{ name }}"}}',
        )

    def test_render_with_simple_data(self, simple_template):
        """Basic rendering with simple data."""
        result = render_template(simple_template, {"name": "John Doe"})
        assert result == {"ShipTo": {"Name": "John Doe"}}

    def test_render_applies_filters(self):
        """Rendering applies Jinja2 filters."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template='{"ShipTo": {"Name": "{{ name | truncate_address(10) }}"}}',
        )
        result = render_template(template, {"name": "123 Main Street Suite 400"})
        assert result["ShipTo"]["Name"] == "123 Main"

    def test_render_uses_defaults_for_null(self):
        """Rendering uses default_value for null."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template='{"ShipTo": {"Name": "{{ name | default_value(\'Unknown\') }}"}}',
        )
        result = render_template(template, {"name": None})
        assert result["ShipTo"]["Name"] == "Unknown"

    def test_render_nested_structure(self):
        """Rendering handles nested structures."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template="""{
                "ShipTo": {
                    "Name": "{{ name }}",
                    "Address": {
                        "City": "{{ city }}",
                        "StateProvinceCode": "{{ state }}"
                    }
                }
            }""",
        )
        result = render_template(template, {
            "name": "John Doe",
            "city": "Los Angeles",
            "state": "CA",
        })
        assert result["ShipTo"]["Name"] == "John Doe"
        assert result["ShipTo"]["Address"]["City"] == "Los Angeles"
        assert result["ShipTo"]["Address"]["StateProvinceCode"] == "CA"

    def test_render_with_no_template_raises(self):
        """Rendering without jinja_template raises error."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template=None,
        )
        with pytest.raises(MappingGenerationError) as exc_info:
            render_template(template, {"name": "John"})
        assert "no jinja_template set" in str(exc_info.value)

    def test_render_with_format_filter(self):
        """Rendering with format_us_zip filter."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template='{"PostalCode": "{{ zip | format_us_zip }}"}',
        )
        result = render_template(template, {"zip": "900011234"})
        assert result["PostalCode"] == "90001-1234"

    def test_render_with_phone_filter(self):
        """Rendering with to_ups_phone filter."""
        template = MappingTemplate(
            name="test",
            source_schema_hash="abc123",
            jinja_template='{"Phone": "{{ phone | to_ups_phone }}"}',
        )
        result = render_template(template, {"phone": "(555) 123-4567"})
        assert result["Phone"] == "5551234567"


class TestMappingGenerationError:
    """Tests for MappingGenerationError exception."""

    def test_error_with_message_only(self):
        """Error with just message."""
        error = MappingGenerationError("Template compilation failed")
        assert str(error) == "Template compilation failed"

    def test_error_with_source_column(self):
        """Error with source column context."""
        error = MappingGenerationError(
            "Column not found",
            source_column="nonexistent",
        )
        assert "Column not found" in str(error)
        assert "nonexistent" in str(error)

    def test_error_with_target_path(self):
        """Error with target path context."""
        error = MappingGenerationError(
            "Invalid path",
            target_path="ShipTo.Name",
        )
        assert "Invalid path" in str(error)
        assert "ShipTo.Name" in str(error)

    def test_error_with_all_context(self):
        """Error with full context."""
        error = MappingGenerationError(
            "Mapping failed",
            source_column="name",
            target_path="ShipTo.Name",
        )
        assert error.message == "Mapping failed"
        assert error.source_column == "name"
        assert error.target_path == "ShipTo.Name"


class TestIntegrationScenarios:
    """Integration tests for complete mapping workflows."""

    def test_full_shipto_mapping(self):
        """Complete ShipTo mapping with all common fields."""
        schema = [
            ColumnInfo(name="customer_name", type="string"),
            ColumnInfo(name="street", type="string"),
            ColumnInfo(name="city", type="string"),
            ColumnInfo(name="state", type="string"),
            ColumnInfo(name="zip", type="string"),
            ColumnInfo(name="phone", type="string"),
        ]
        mappings = [
            FieldMapping(
                source_column="customer_name",
                target_path="ShipTo.Name",
                transformation="truncate_address(35)",
            ),
            FieldMapping(
                source_column="street",
                target_path="ShipTo.Address.AddressLine",
                transformation="truncate_address(35)",
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
                source_column="phone",
                target_path="ShipTo.Phone.Number",
                transformation="to_ups_phone",
            ),
        ]

        template = generate_mapping_template(schema, mappings, "full_shipto")

        # Render with sample data
        row_data = {
            "customer_name": "John Doe",
            "street": "123 Main Street",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "900011234",
            "phone": "(555) 123-4567",
        }
        result = render_template(template, row_data)

        assert result["ShipTo"]["Name"] == "John Doe"
        assert result["ShipTo"]["Address"]["AddressLine"] == "123 Main Street"
        assert result["ShipTo"]["Address"]["City"] == "Los Angeles"
        assert result["ShipTo"]["Address"]["StateProvinceCode"] == "CA"
        assert result["ShipTo"]["Address"]["PostalCode"] == "90001-1234"
        assert result["ShipTo"]["Phone"]["Number"] == "5551234567"

    def test_mapping_with_defaults(self):
        """Mapping with default values for optional fields."""
        schema = [
            ColumnInfo(name="name", type="string"),
            ColumnInfo(name="phone", type="string"),
        ]
        mappings = [
            FieldMapping(
                source_column="name",
                target_path="ShipTo.Name",
            ),
            FieldMapping(
                source_column="phone",
                target_path="ShipTo.Phone.Number",
                transformation="to_ups_phone",
                default_value="5550000000",
            ),
        ]

        template = generate_mapping_template(schema, mappings)

        # Test with missing phone
        result = render_template(template, {"name": "John", "phone": None})
        assert result["ShipTo"]["Name"] == "John"
        # Note: default_value filter returns default for None
        assert result["ShipTo"]["Phone"]["Number"] == "5550000000"
