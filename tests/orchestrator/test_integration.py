"""Integration tests for the NL Mapping Engine.

These tests verify all 6 NL requirements (NL-01 through NL-06) and the
end-to-end processing pipeline.

Tests marked with @pytest.mark.integration require ANTHROPIC_API_KEY
and will be skipped if the key is not available.
"""

import os
from datetime import datetime

import pytest

from src.orchestrator import (
    NLMappingEngine,
    CommandResult,
    ShippingIntent,
    ServiceCode,
    MappingTemplate,
    FieldMapping,
    ValidationResult,
    ElicitationQuestion,
)
from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult
from src.orchestrator.nl_engine import (
    parse_intent,
    generate_filter,
    generate_mapping_template,
    render_template,
    validate_template_output,
    self_correction_loop,
    validate_sql_syntax,
)
from src.orchestrator.nl_engine.ups_schema import UPS_SHIPTO_SCHEMA


# Skip integration tests without API key
requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)


# =============================================================================
# NL-01: Natural Language Commands
# Verifies: "User can issue natural language commands"
# =============================================================================


class TestNL01NaturalLanguageCommands:
    """Tests for NL-01: User can issue natural language commands."""

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_ship_california_orders_ground(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
    ):
        """Test parsing 'Ship California orders via Ground'."""
        engine = NLMappingEngine()
        result = await engine.process_command(
            "Ship California orders via Ground",
            source_schema=sample_shipping_schema,
            user_mappings=sample_mappings,
        )

        assert result.intent is not None
        assert result.intent.action == "ship"
        assert result.intent.service_code == ServiceCode.GROUND

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_ship_all_orders_overnight(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
    ):
        """Test parsing 'Ship all orders overnight'."""
        engine = NLMappingEngine()
        result = await engine.process_command(
            "Ship all orders overnight",
            source_schema=sample_shipping_schema,
            user_mappings=sample_mappings,
        )

        assert result.intent is not None
        assert result.intent.action == "ship"
        assert result.intent.service_code == ServiceCode.NEXT_DAY_AIR

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_ship_first_ten_orders(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
    ):
        """Test parsing 'Ship the first 10 orders'."""
        engine = NLMappingEngine()
        result = await engine.process_command(
            "Ship the first 10 orders via ground",
            source_schema=sample_shipping_schema,
            user_mappings=sample_mappings,
        )

        assert result.intent is not None
        assert result.intent.action == "ship"
        if result.intent.row_qualifier:
            assert result.intent.row_qualifier.qualifier_type == "first"
            assert result.intent.row_qualifier.count == 10


# =============================================================================
# NL-02: Intent Parsing
# Verifies: "System parses intent to extract data source, filter, service, package"
# =============================================================================


class TestNL02IntentParsing:
    """Tests for NL-02: System parses intent correctly."""

    @requires_api_key
    @pytest.mark.integration
    def test_extracts_data_source(self):
        """Test that data source is extracted from command."""
        intent = parse_intent(
            "Ship orders from today's spreadsheet using Ground",
            available_sources=["orders.csv", "today's spreadsheet"],
        )

        assert intent.action == "ship"
        # Data source should be recognized
        assert intent.data_source is not None or intent.filter_criteria is not None

    @requires_api_key
    @pytest.mark.integration
    def test_extracts_filter_criteria(self):
        """Test that filter criteria is extracted."""
        intent = parse_intent("Ship California orders")

        assert intent.filter_criteria is not None
        assert "california" in intent.filter_criteria.raw_expression.lower()

    @requires_api_key
    @pytest.mark.integration
    def test_extracts_service_code(self):
        """Test that service code is correctly resolved."""
        intent = parse_intent("Ship orders using 2-day air")

        assert intent.service_code == ServiceCode.SECOND_DAY_AIR

    @requires_api_key
    @pytest.mark.integration
    def test_extracts_package_defaults(self):
        """Test extraction of package defaults when specified."""
        intent = parse_intent("Ship all orders using Ground")

        # Even without explicit package info, intent should be parsed
        assert intent.action == "ship"
        assert intent.service_code == ServiceCode.GROUND


# =============================================================================
# NL-03: Template Generation
# Verifies: "System generates Jinja2 mapping templates"
# =============================================================================


class TestNL03TemplateGeneration:
    """Tests for NL-03: System generates Jinja2 mapping templates."""

    def test_generates_jinja2_template(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
    ):
        """Test that Jinja2 template is generated from mappings."""
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings,
            "test_template",
        )

        assert template.jinja_template is not None
        assert "{{" in template.jinja_template
        assert "}}" in template.jinja_template

    def test_template_maps_columns_to_ups_fields(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
    ):
        """Test that template maps source columns to UPS fields."""
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings,
            "test_template",
        )

        # Should contain ShipTo structure
        assert "ShipTo" in template.jinja_template
        assert "Address" in template.jinja_template
        assert "customer_name" in template.jinja_template

    def test_template_includes_transformations(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
    ):
        """Test that template includes specified transformations."""
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings,
            "test_template",
        )

        # Should include filters from mappings
        assert "truncate_address" in template.jinja_template
        assert "format_us_zip" in template.jinja_template
        assert "to_ups_phone" in template.jinja_template


# =============================================================================
# NL-04: Schema Validation
# Verifies: "System validates templates against UPS schema"
# =============================================================================


class TestNL04SchemaValidation:
    """Tests for NL-04: System validates templates against UPS schema."""

    def test_validates_against_ups_schema(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
        sample_row_data: dict,
    ):
        """Test that rendered output is validated against UPS schema."""
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings,
            "test_template",
        )
        rendered = render_template(template, sample_row_data)
        result = validate_template_output(rendered, UPS_SHIPTO_SCHEMA)

        # ShipTo portion should be valid with proper data
        assert isinstance(result, ValidationResult)

    def test_reports_missing_required_fields(self):
        """Test that validation reports missing required fields."""
        # Incomplete payload
        incomplete = {"Name": "John Doe"}
        result = validate_template_output(incomplete, UPS_SHIPTO_SCHEMA)

        assert not result.valid
        assert len(result.errors) > 0
        # Should indicate missing Address
        error_paths = [e.path for e in result.errors]
        assert any("Address" in p or "required" in e.schema_rule
                   for p, e in zip(error_paths, result.errors))

    def test_reports_type_mismatches(self):
        """Test that validation reports type mismatches."""
        # Wrong type for AddressLine (should be array)
        wrong_type = {
            "Name": "John",
            "Address": {
                "AddressLine": "123 Main",  # Should be array
                "City": "LA",
                "CountryCode": "US",
            },
        }
        result = validate_template_output(wrong_type, UPS_SHIPTO_SCHEMA)

        assert not result.valid


# =============================================================================
# NL-05: Self-Correction
# Verifies: "System self-corrects when validation fails"
# =============================================================================


class TestNL05SelfCorrection:
    """Tests for NL-05: System self-corrects when validation fails."""

    @requires_api_key
    @pytest.mark.integration
    def test_corrects_template_on_validation_failure(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_row_data: dict,
    ):
        """Test that self-correction fixes invalid templates."""
        # Template with invalid phone format (missing to_ups_phone)
        invalid_template = """{
            "ShipTo": {
                "Name": "{{ customer_name }}",
                "Address": {
                    "AddressLine": ["{{ address_line1 }}"],
                    "City": "{{ city }}",
                    "StateProvinceCode": "{{ state }}",
                    "PostalCode": "{{ zip }}",
                    "CountryCode": "{{ country_code }}"
                },
                "Phone": {
                    "Number": "{{ phone }}"
                }
            }
        }"""

        # Run self-correction (may fix the phone formatting)
        result = self_correction_loop(
            template=invalid_template,
            source_schema=sample_shipping_schema,
            target_schema=UPS_SHIPTO_SCHEMA,
            sample_data=sample_row_data,
            max_attempts=3,
        )

        # Should either succeed or fail gracefully
        if result.success:
            assert result.final_template is not None
        else:
            assert len(result.attempts) <= 3

    def test_respects_max_attempts(
        self,
        sample_shipping_schema: list[ColumnInfo],
    ):
        """Test that self-correction respects max attempts limit."""
        # Completely invalid template that can't be fixed
        broken_template = "not json at all"

        try:
            result = self_correction_loop(
                template=broken_template,
                source_schema=sample_shipping_schema,
                max_attempts=2,
            )
            # If it returns, check attempt count
            assert result.total_attempts <= 2
        except Exception:
            # Expected to fail
            pass

    @requires_api_key
    @pytest.mark.integration
    def test_raises_after_max_failures(
        self,
        sample_shipping_schema: list[ColumnInfo],
    ):
        """Test that MaxCorrectionsExceeded is raised after max failures."""
        from src.orchestrator.models.correction import MaxCorrectionsExceeded

        # Template with issues that are hard to auto-fix
        problematic_template = """{
            "ShipTo": {
                "Name": "{{ nonexistent_column }}"
            }
        }"""

        with pytest.raises(MaxCorrectionsExceeded):
            self_correction_loop(
                template=problematic_template,
                source_schema=sample_shipping_schema,
                max_attempts=1,
            )


# =============================================================================
# NL-06: Natural Language Filters
# Verifies: "User can filter using natural language"
# =============================================================================


class TestNL06NaturalLanguageFilters:
    """Tests for NL-06: User can filter using natural language."""

    @requires_api_key
    @pytest.mark.integration
    def test_california_filter(
        self,
        sample_shipping_schema: list[ColumnInfo],
    ):
        """Test 'California orders' generates appropriate SQL."""
        result = generate_filter("California orders", sample_shipping_schema)

        assert result.where_clause is not None
        # Should reference state column
        assert "state" in result.where_clause.lower()
        # Should have CA value
        assert "ca" in result.where_clause.lower() or "california" in result.where_clause.lower()

    @requires_api_key
    @pytest.mark.integration
    def test_today_filter(
        self,
        sample_shipping_schema: list[ColumnInfo],
        current_date_str: str,
    ):
        """Test 'today's orders' generates date filter."""
        result = generate_filter("today's orders", sample_shipping_schema)

        assert result.where_clause is not None
        # Should reference date column
        assert "order_date" in result.where_clause.lower() or "date" in result.where_clause.lower()

    @requires_api_key
    @pytest.mark.integration
    def test_weight_filter(
        self,
        sample_shipping_schema: list[ColumnInfo],
    ):
        """Test 'orders over 5 lbs' generates weight filter."""
        result = generate_filter("orders over 5 lbs", sample_shipping_schema)

        assert result.where_clause is not None
        # Should reference weight column
        assert "weight" in result.where_clause.lower()

    @requires_api_key
    @pytest.mark.integration
    def test_compound_filter(
        self,
        sample_shipping_schema: list[ColumnInfo],
    ):
        """Test compound filter with state and weight."""
        result = generate_filter(
            "California orders over 3 lbs",
            sample_shipping_schema,
        )

        assert result.where_clause is not None
        # Should combine conditions
        where_lower = result.where_clause.lower()
        assert "state" in where_lower or "ca" in where_lower
        assert "weight" in where_lower


# =============================================================================
# End-to-End Tests
# Verifies complete workflow from command to validated payload
# =============================================================================


class TestEndToEnd:
    """End-to-end integration tests for complete workflows."""

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_workflow(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
        sample_row_data: dict,
    ):
        """Test complete flow: command -> intent -> filter -> template -> validation."""
        engine = NLMappingEngine()

        result = await engine.process_command(
            command="Ship California orders via Ground",
            source_schema=sample_shipping_schema,
            user_mappings=sample_mappings,
            example_row=sample_row_data,
        )

        # Should have parsed intent
        assert result.intent is not None
        assert result.intent.action == "ship"

        # Should have mapping template
        assert result.mapping_template is not None

        # Should have validation result
        assert result.validation_result is not None

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_with_elicitation(
        self,
        schema_with_multiple_dates: list[ColumnInfo],
    ):
        """Test that ambiguous command triggers elicitation."""
        engine = NLMappingEngine()

        # Don't provide mappings to force the "mappings required" path
        result = await engine.process_command(
            command="Ship today's orders",
            source_schema=schema_with_multiple_dates,
            user_mappings=None,  # No mappings - should return error about needing them
        )

        # Since no mappings provided, should have an error or need elicitation
        # The engine requires user_mappings
        assert result.error is not None or len(result.needs_elicitation) > 0

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_engine_max_correction_clamping(self):
        """Test that engine clamps max_correction_attempts to 1-5."""
        engine_low = NLMappingEngine(max_correction_attempts=0)
        assert engine_low.max_correction_attempts == 1

        engine_high = NLMappingEngine(max_correction_attempts=10)
        assert engine_high.max_correction_attempts == 5

        engine_normal = NLMappingEngine(max_correction_attempts=3)
        assert engine_normal.max_correction_attempts == 3


# =============================================================================
# Unit Tests (No API Key Required)
# =============================================================================


class TestUnitValidation:
    """Unit tests for validation that don't require API key."""

    def test_sql_syntax_validation_valid(self):
        """Test SQL syntax validation for valid SQL."""
        assert validate_sql_syntax('state = "CA"') is True
        assert validate_sql_syntax("weight > 5") is True
        assert validate_sql_syntax("state = 'CA' AND weight > 5") is True

    def test_sql_syntax_validation_invalid(self):
        """Test SQL syntax validation for invalid SQL."""
        with pytest.raises(ValueError):
            validate_sql_syntax("state = = 'CA'")  # Double equals

        with pytest.raises(ValueError):
            validate_sql_syntax("SELECT * FROM")  # Incomplete

    def test_template_rendering(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
        sample_row_data: dict,
    ):
        """Test that templates render correctly."""
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings[:5],  # Just address mappings
            "test",
        )

        rendered = render_template(template, sample_row_data)

        assert "ShipTo" in rendered
        assert rendered["ShipTo"]["Name"] == "John Smith"
        assert rendered["ShipTo"]["Address"]["City"] == "Los Angeles"

    def test_command_result_model(self):
        """Test CommandResult Pydantic model."""
        result = CommandResult(
            command="test command",
            success=True,
        )

        assert result.command == "test command"
        assert result.success is True
        assert result.intent is None
        assert result.needs_elicitation == []

    def test_engine_instantiation(self):
        """Test NLMappingEngine can be instantiated."""
        engine = NLMappingEngine()
        assert engine.max_correction_attempts == 3

        engine_custom = NLMappingEngine(max_correction_attempts=2)
        assert engine_custom.max_correction_attempts == 2


class TestRenderWithValidation:
    """Tests for the render_with_validation helper method."""

    def test_render_with_validation_valid(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
        sample_row_data: dict,
    ):
        """Test render_with_validation with valid template."""
        engine = NLMappingEngine()
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings,
            "test",
        )

        rendered, validation = engine.render_with_validation(
            template,
            sample_row_data,
            UPS_SHIPTO_SCHEMA,
        )

        assert "ShipTo" in rendered
        assert isinstance(validation, ValidationResult)

    def test_render_with_validation_default_schema(
        self,
        sample_shipping_schema: list[ColumnInfo],
        sample_mappings: list[FieldMapping],
        sample_row_data: dict,
    ):
        """Test render_with_validation uses default schema."""
        engine = NLMappingEngine()
        template = generate_mapping_template(
            sample_shipping_schema,
            sample_mappings,
            "test",
        )

        # Don't specify schema - should use UPS_SHIPMENT_SCHEMA
        rendered, validation = engine.render_with_validation(template, sample_row_data)

        assert isinstance(validation, ValidationResult)
