"""Unit tests for intent parsing.

Tests cover:
- Service code resolution from aliases and direct codes
- ShippingIntent model validation
- FilterCriteria and RowQualifier model validation
- Integration tests with Claude API (skipped without API key)
"""

import os

import pytest

from src.orchestrator.models.intent import (
    FilterCriteria,
    RowQualifier,
    ServiceCode,
    ShippingIntent,
)
from src.orchestrator.nl_engine.intent_parser import (
    IntentParseError,
    parse_intent,
    resolve_service_code,
)


class TestServiceCodeResolution:
    """Tests for resolve_service_code function."""

    def test_ground_alias(self) -> None:
        """Test 'ground' resolves to ServiceCode.GROUND."""
        assert resolve_service_code("ground") == ServiceCode.GROUND

    def test_ground_alias_uppercase(self) -> None:
        """Test 'GROUND' resolves case-insensitively."""
        assert resolve_service_code("GROUND") == ServiceCode.GROUND

    def test_ground_alias_mixed_case(self) -> None:
        """Test 'Ground' resolves case-insensitively."""
        assert resolve_service_code("Ground") == ServiceCode.GROUND

    def test_ups_ground_alias(self) -> None:
        """Test 'ups ground' resolves to ServiceCode.GROUND."""
        assert resolve_service_code("ups ground") == ServiceCode.GROUND

    def test_overnight_alias(self) -> None:
        """Test 'overnight' resolves to ServiceCode.NEXT_DAY_AIR."""
        assert resolve_service_code("overnight") == ServiceCode.NEXT_DAY_AIR

    def test_next_day_alias(self) -> None:
        """Test 'next day' resolves to ServiceCode.NEXT_DAY_AIR."""
        assert resolve_service_code("next day") == ServiceCode.NEXT_DAY_AIR

    def test_next_day_air_alias(self) -> None:
        """Test 'next day air' resolves to ServiceCode.NEXT_DAY_AIR."""
        assert resolve_service_code("next day air") == ServiceCode.NEXT_DAY_AIR

    def test_nda_alias(self) -> None:
        """Test 'nda' resolves to ServiceCode.NEXT_DAY_AIR."""
        assert resolve_service_code("nda") == ServiceCode.NEXT_DAY_AIR

    def test_2_day_alias(self) -> None:
        """Test '2-day' resolves to ServiceCode.SECOND_DAY_AIR."""
        assert resolve_service_code("2-day") == ServiceCode.SECOND_DAY_AIR

    def test_2_day_no_hyphen_alias(self) -> None:
        """Test '2 day' resolves to ServiceCode.SECOND_DAY_AIR."""
        assert resolve_service_code("2 day") == ServiceCode.SECOND_DAY_AIR

    def test_two_day_alias(self) -> None:
        """Test 'two day' resolves to ServiceCode.SECOND_DAY_AIR."""
        assert resolve_service_code("two day") == ServiceCode.SECOND_DAY_AIR

    def test_2nd_day_air_alias(self) -> None:
        """Test '2nd day air' resolves to ServiceCode.SECOND_DAY_AIR."""
        assert resolve_service_code("2nd day air") == ServiceCode.SECOND_DAY_AIR

    def test_3_day_alias(self) -> None:
        """Test '3-day' resolves to ServiceCode.THREE_DAY_SELECT."""
        assert resolve_service_code("3-day") == ServiceCode.THREE_DAY_SELECT

    def test_3_day_no_hyphen_alias(self) -> None:
        """Test '3 day' resolves to ServiceCode.THREE_DAY_SELECT."""
        assert resolve_service_code("3 day") == ServiceCode.THREE_DAY_SELECT

    def test_three_day_alias(self) -> None:
        """Test 'three day' resolves to ServiceCode.THREE_DAY_SELECT."""
        assert resolve_service_code("three day") == ServiceCode.THREE_DAY_SELECT

    def test_3_day_select_alias(self) -> None:
        """Test '3 day select' resolves to ServiceCode.THREE_DAY_SELECT."""
        assert resolve_service_code("3 day select") == ServiceCode.THREE_DAY_SELECT

    def test_saver_alias(self) -> None:
        """Test 'saver' resolves to ServiceCode.NEXT_DAY_AIR_SAVER."""
        assert resolve_service_code("saver") == ServiceCode.NEXT_DAY_AIR_SAVER

    def test_next_day_air_saver_alias(self) -> None:
        """Test 'next day air saver' resolves to ServiceCode.NEXT_DAY_AIR_SAVER."""
        assert resolve_service_code("next day air saver") == ServiceCode.NEXT_DAY_AIR_SAVER

    def test_direct_code_03(self) -> None:
        """Test direct code '03' resolves to ServiceCode.GROUND."""
        assert resolve_service_code("03") == ServiceCode.GROUND

    def test_direct_code_01(self) -> None:
        """Test direct code '01' resolves to ServiceCode.NEXT_DAY_AIR."""
        assert resolve_service_code("01") == ServiceCode.NEXT_DAY_AIR

    def test_direct_code_02(self) -> None:
        """Test direct code '02' resolves to ServiceCode.SECOND_DAY_AIR."""
        assert resolve_service_code("02") == ServiceCode.SECOND_DAY_AIR

    def test_direct_code_12(self) -> None:
        """Test direct code '12' resolves to ServiceCode.THREE_DAY_SELECT."""
        assert resolve_service_code("12") == ServiceCode.THREE_DAY_SELECT

    def test_direct_code_13(self) -> None:
        """Test direct code '13' resolves to ServiceCode.NEXT_DAY_AIR_SAVER."""
        assert resolve_service_code("13") == ServiceCode.NEXT_DAY_AIR_SAVER

    def test_unknown_service_raises(self) -> None:
        """Test unknown service raises ValueError."""
        with pytest.raises(ValueError, match="Unknown service"):
            resolve_service_code("super fast express")

    def test_case_insensitive(self) -> None:
        """Test service resolution is case-insensitive."""
        assert resolve_service_code("OVERNIGHT") == ServiceCode.NEXT_DAY_AIR
        assert resolve_service_code("Overnight") == ServiceCode.NEXT_DAY_AIR
        assert resolve_service_code("oVerNiGhT") == ServiceCode.NEXT_DAY_AIR

    def test_whitespace_handling(self) -> None:
        """Test whitespace is stripped from input."""
        assert resolve_service_code("  ground  ") == ServiceCode.GROUND
        assert resolve_service_code("\tovernight\n") == ServiceCode.NEXT_DAY_AIR


class TestShippingIntentModel:
    """Tests for ShippingIntent Pydantic model."""

    def test_minimal_intent(self) -> None:
        """Test creating intent with only action."""
        intent = ShippingIntent(action="ship")
        assert intent.action == "ship"
        assert intent.data_source is None
        assert intent.service_code is None
        assert intent.filter_criteria is None
        assert intent.row_qualifier is None
        assert intent.package_defaults is None

    def test_full_intent(self) -> None:
        """Test creating intent with all fields populated."""
        intent = ShippingIntent(
            action="ship",
            data_source="orders.csv",
            service_code=ServiceCode.GROUND,
            filter_criteria=FilterCriteria(
                raw_expression="California orders",
                filter_type="state",
            ),
            row_qualifier=RowQualifier(
                qualifier_type="first",
                count=10,
            ),
            package_defaults={"weight": 5.0, "length": 10, "width": 8, "height": 6},
        )
        assert intent.action == "ship"
        assert intent.data_source == "orders.csv"
        assert intent.service_code == ServiceCode.GROUND
        assert intent.filter_criteria is not None
        assert intent.filter_criteria.filter_type == "state"
        assert intent.row_qualifier is not None
        assert intent.row_qualifier.count == 10
        assert intent.package_defaults is not None

    def test_rate_action(self) -> None:
        """Test rate action is valid."""
        intent = ShippingIntent(action="rate")
        assert intent.action == "rate"

    def test_validate_address_action(self) -> None:
        """Test validate_address action is valid."""
        intent = ShippingIntent(action="validate_address")
        assert intent.action == "validate_address"

    def test_invalid_action_raises(self) -> None:
        """Test invalid action raises validation error."""
        with pytest.raises(ValueError):
            ShippingIntent(action="invalid_action")


class TestRowQualifierModel:
    """Tests for RowQualifier Pydantic model."""

    def test_first_10(self) -> None:
        """Test 'first 10' row qualifier."""
        qualifier = RowQualifier(qualifier_type="first", count=10)
        assert qualifier.qualifier_type == "first"
        assert qualifier.count == 10
        assert qualifier.nth is None

    def test_last_5(self) -> None:
        """Test 'last 5' row qualifier."""
        qualifier = RowQualifier(qualifier_type="last", count=5)
        assert qualifier.qualifier_type == "last"
        assert qualifier.count == 5

    def test_random_sample_3(self) -> None:
        """Test 'random sample of 3' row qualifier."""
        qualifier = RowQualifier(qualifier_type="random", count=3)
        assert qualifier.qualifier_type == "random"
        assert qualifier.count == 3

    def test_every_other_row(self) -> None:
        """Test 'every other row' (nth=2) qualifier."""
        qualifier = RowQualifier(qualifier_type="every_nth", nth=2)
        assert qualifier.qualifier_type == "every_nth"
        assert qualifier.nth == 2
        assert qualifier.count is None

    def test_every_third_row(self) -> None:
        """Test 'every third row' (nth=3) qualifier."""
        qualifier = RowQualifier(qualifier_type="every_nth", nth=3)
        assert qualifier.nth == 3

    def test_all_rows(self) -> None:
        """Test 'all' row qualifier (default)."""
        qualifier = RowQualifier(qualifier_type="all")
        assert qualifier.qualifier_type == "all"
        assert qualifier.count is None
        assert qualifier.nth is None

    def test_default_qualifier_type(self) -> None:
        """Test default qualifier_type is 'all'."""
        qualifier = RowQualifier()
        assert qualifier.qualifier_type == "all"

    def test_count_must_be_positive(self) -> None:
        """Test count must be >= 1."""
        with pytest.raises(ValueError):
            RowQualifier(qualifier_type="first", count=0)

    def test_nth_must_be_at_least_2(self) -> None:
        """Test nth must be >= 2."""
        with pytest.raises(ValueError):
            RowQualifier(qualifier_type="every_nth", nth=1)


class TestFilterCriteriaModel:
    """Tests for FilterCriteria Pydantic model."""

    def test_state_filter(self) -> None:
        """Test state filter type."""
        criteria = FilterCriteria(raw_expression="California", filter_type="state")
        assert criteria.raw_expression == "California"
        assert criteria.filter_type == "state"
        assert criteria.needs_clarification is False

    def test_date_filter(self) -> None:
        """Test date filter type."""
        criteria = FilterCriteria(raw_expression="today's orders", filter_type="date")
        assert criteria.filter_type == "date"

    def test_numeric_filter(self) -> None:
        """Test numeric filter type."""
        criteria = FilterCriteria(raw_expression="over 5 lbs", filter_type="numeric")
        assert criteria.filter_type == "numeric"

    def test_compound_filter(self) -> None:
        """Test compound filter type."""
        criteria = FilterCriteria(
            raw_expression="California orders over 5 lbs",
            filter_type="compound",
        )
        assert criteria.filter_type == "compound"

    def test_needs_clarification(self) -> None:
        """Test filter that needs clarification."""
        criteria = FilterCriteria(
            raw_expression="big orders",
            filter_type="numeric",
            needs_clarification=True,
            clarification_reason="What defines 'big'? Weight, value, or dimensions?",
        )
        assert criteria.needs_clarification is True
        assert criteria.clarification_reason is not None

    def test_default_filter_type(self) -> None:
        """Test default filter_type is 'none'."""
        criteria = FilterCriteria(raw_expression="")
        assert criteria.filter_type == "none"


class TestIntentParseError:
    """Tests for IntentParseError exception."""

    def test_basic_error(self) -> None:
        """Test creating basic IntentParseError."""
        error = IntentParseError(
            message="Failed to parse",
            original_command="ship the stuff",
        )
        assert error.message == "Failed to parse"
        assert error.original_command == "ship the stuff"
        assert error.suggestions == []

    def test_error_with_suggestions(self) -> None:
        """Test IntentParseError with suggestions."""
        error = IntentParseError(
            message="Ambiguous command",
            original_command="do something",
            suggestions=["Ship orders", "Rate orders"],
        )
        assert len(error.suggestions) == 2
        assert "Ship orders" in error.suggestions

    def test_error_string_representation(self) -> None:
        """Test str() representation of error."""
        error = IntentParseError(
            message="Failed to parse",
            original_command="ship the stuff",
        )
        error_str = str(error)
        assert "Failed to parse" in error_str
        assert "ship the stuff" in error_str


# Integration tests that require API key
@pytest.mark.integration
class TestIntentParserIntegration:
    """Integration tests for parse_intent function.

    These tests require ANTHROPIC_API_KEY environment variable.
    Skip if not available.
    """

    @pytest.fixture(autouse=True)
    def skip_without_api_key(self) -> None:
        """Skip tests if ANTHROPIC_API_KEY not set."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

    def test_parse_simple_ship_command(self) -> None:
        """Test parsing 'Ship orders via Ground'."""
        intent = parse_intent("Ship orders via Ground")
        assert intent.action == "ship"
        assert intent.service_code == ServiceCode.GROUND

    def test_parse_with_filter(self) -> None:
        """Test parsing 'Ship California orders'."""
        intent = parse_intent("Ship California orders")
        assert intent.action == "ship"
        assert intent.filter_criteria is not None
        # Filter should contain California reference
        assert "california" in intent.filter_criteria.raw_expression.lower()

    def test_parse_with_qualifier(self) -> None:
        """Test parsing 'Ship first 10 orders'."""
        intent = parse_intent("Ship first 10 orders")
        assert intent.action == "ship"
        assert intent.row_qualifier is not None
        assert intent.row_qualifier.qualifier_type == "first"
        assert intent.row_qualifier.count == 10

    def test_parse_rate_command(self) -> None:
        """Test parsing rate command."""
        intent = parse_intent("Rate my orders")
        assert intent.action == "rate"

    def test_parse_validate_address_command(self) -> None:
        """Test parsing address validation command."""
        intent = parse_intent("Validate addresses")
        assert intent.action == "validate_address"

    def test_empty_command_raises(self) -> None:
        """Test empty command raises IntentParseError."""
        with pytest.raises(IntentParseError, match="cannot be empty"):
            parse_intent("")

    def test_parse_with_available_sources(self) -> None:
        """Test parsing with available data sources."""
        intent = parse_intent(
            "Ship orders from orders.csv via Ground",
            available_sources=["orders.csv", "customers.xlsx"],
        )
        assert intent.action == "ship"
        # Should reference the data source
        assert intent.data_source is not None
