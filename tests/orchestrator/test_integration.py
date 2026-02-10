"""Integration tests for the NL Mapping Engine.

These tests verify intent parsing (NL-01, NL-02), filter generation (NL-06),
and the end-to-end engine pipeline.

Tests marked with @pytest.mark.integration require ANTHROPIC_API_KEY
and will be skipped if the key is not available.
"""

import os

import pytest

from src.orchestrator import (
    NLMappingEngine,
    CommandResult,
    ShippingIntent,
    ServiceCode,
    ElicitationQuestion,
)
from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult
from src.orchestrator.nl_engine import (
    parse_intent,
    generate_filter,
    validate_sql_syntax,
)


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
    ):
        """Test parsing 'Ship California orders via Ground'."""
        engine = NLMappingEngine()
        result = await engine.process_command(
            "Ship California orders via Ground",
            source_schema=sample_shipping_schema,
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
    ):
        """Test parsing 'Ship all orders overnight'."""
        engine = NLMappingEngine()
        result = await engine.process_command(
            "Ship all orders overnight",
            source_schema=sample_shipping_schema,
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
    ):
        """Test parsing 'Ship the first 10 orders'."""
        engine = NLMappingEngine()
        result = await engine.process_command(
            "Ship the first 10 orders via ground",
            source_schema=sample_shipping_schema,
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
# Verifies complete workflow from command to intent + filter
# =============================================================================


class TestEndToEnd:
    """End-to-end integration tests for complete workflows."""

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_workflow(
        self,
        sample_shipping_schema: list[ColumnInfo],
    ):
        """Test complete flow: command -> intent -> filter."""
        engine = NLMappingEngine()

        result = await engine.process_command(
            command="Ship California orders via Ground",
            source_schema=sample_shipping_schema,
        )

        # Should have parsed intent
        assert result.intent is not None
        assert result.intent.action == "ship"
        assert result.success is True

        # Should have filter result for California
        assert result.sql_where is not None

    @requires_api_key
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_with_elicitation(
        self,
        schema_with_multiple_dates: list[ColumnInfo],
    ):
        """Test that ambiguous command triggers elicitation."""
        engine = NLMappingEngine()

        result = await engine.process_command(
            command="Ship today's orders",
            source_schema=schema_with_multiple_dates,
        )

        # May trigger elicitation for ambiguous date columns or succeed
        assert result.success or len(result.needs_elicitation) > 0


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
        assert engine._elicitation_responses == {}
