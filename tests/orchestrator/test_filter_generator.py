"""Unit tests for the filter generator module.

Tests SQL validation, model construction, and integration with Claude API.
Integration tests require ANTHROPIC_API_KEY to be set.
"""

import os
from typing import Any

import pytest

from src.orchestrator.models.filter import (
    ColumnInfo,
    FilterGenerationError,
    SQLFilterResult,
)
from src.orchestrator.nl_engine.filter_generator import (
    validate_sql_syntax,
    _identify_column_types,
    _build_schema_context,
    _detect_temporal_filter,
    _validate_columns_used,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_schema() -> list[ColumnInfo]:
    """Simple schema with typical shipping columns."""
    return [
        ColumnInfo(name="order_id", type="integer", nullable=False),
        ColumnInfo(name="customer_name", type="string"),
        ColumnInfo(name="state", type="string", sample_values=["CA", "TX", "NY"]),
        ColumnInfo(name="order_date", type="date"),
        ColumnInfo(name="weight", type="float", sample_values=[2.5, 5.0, 10.0]),
        ColumnInfo(name="total", type="float", sample_values=[25.99, 99.99, 150.00]),
    ]


@pytest.fixture
def shipping_schema() -> list[ColumnInfo]:
    """Complex schema with multiple date and weight columns for ambiguity testing."""
    return [
        ColumnInfo(name="order_id", type="integer", nullable=False),
        ColumnInfo(name="customer_name", type="string"),
        ColumnInfo(name="state", type="string", sample_values=["CA", "TX", "NY"]),
        ColumnInfo(name="order_date", type="date"),
        ColumnInfo(name="ship_by_date", type="date"),
        ColumnInfo(name="created_at", type="datetime"),
        ColumnInfo(name="package_weight", type="float"),
        ColumnInfo(name="total_weight", type="float"),
        ColumnInfo(name="billing_weight", type="float"),
        ColumnInfo(name="order_total", type="float"),
        ColumnInfo(name="is_residential", type="boolean"),
    ]


# ============================================================================
# TestSQLValidation - SQL syntax validation using sqlglot
# ============================================================================


class TestSQLValidation:
    """Tests for validate_sql_syntax function."""

    def test_valid_simple_equality(self) -> None:
        """Simple equality comparison should pass validation."""
        assert validate_sql_syntax("state = 'CA'") is True

    def test_valid_date_comparison(self) -> None:
        """Date comparison should pass validation."""
        assert validate_sql_syntax("order_date = '2026-01-25'") is True

    def test_valid_numeric_comparison(self) -> None:
        """Numeric comparison should pass validation."""
        assert validate_sql_syntax("weight > 5") is True

    def test_valid_compound_filter(self) -> None:
        """Compound filter with AND should pass validation."""
        assert validate_sql_syntax("state = 'CA' AND weight > 5") is True

    def test_valid_compound_filter_with_or(self) -> None:
        """Compound filter with OR should pass validation."""
        assert validate_sql_syntax("state = 'CA' OR state = 'TX'") is True

    def test_valid_in_clause(self) -> None:
        """IN clause should pass validation."""
        assert validate_sql_syntax("state IN ('CA', 'TX', 'NY')") is True

    def test_valid_between(self) -> None:
        """BETWEEN clause should pass validation."""
        assert validate_sql_syntax("weight BETWEEN 5 AND 10") is True

    def test_valid_like(self) -> None:
        """LIKE pattern should pass validation."""
        assert validate_sql_syntax("customer_name LIKE 'John%'") is True

    def test_valid_is_null(self) -> None:
        """IS NULL check should pass validation."""
        assert validate_sql_syntax("order_date IS NULL") is True

    def test_valid_is_not_null(self) -> None:
        """IS NOT NULL check should pass validation."""
        assert validate_sql_syntax("order_date IS NOT NULL") is True

    def test_invalid_syntax_missing_value(self) -> None:
        """Missing value after operator should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL syntax"):
            validate_sql_syntax("state = ")

    def test_invalid_syntax_bad_operator(self) -> None:
        """Invalid operator should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL syntax"):
            validate_sql_syntax("state >< 'CA'")

    def test_invalid_syntax_unclosed_string(self) -> None:
        """Unclosed string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL syntax"):
            validate_sql_syntax("state = 'CA")

    def test_invalid_syntax_missing_and_operand(self) -> None:
        """AND without second operand should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL syntax"):
            validate_sql_syntax("state = 'CA' AND")


# ============================================================================
# TestColumnInfo - Model construction tests
# ============================================================================


class TestColumnInfo:
    """Tests for ColumnInfo model construction."""

    def test_minimal_column(self) -> None:
        """Column with only required fields should work."""
        col = ColumnInfo(name="test_col", type="string")
        assert col.name == "test_col"
        assert col.type == "string"
        assert col.nullable is True  # default
        assert col.sample_values == []  # default

    def test_column_with_samples(self) -> None:
        """Column with sample values should include them."""
        col = ColumnInfo(
            name="state",
            type="string",
            nullable=False,
            sample_values=["CA", "TX", "NY"],
        )
        assert col.name == "state"
        assert col.type == "string"
        assert col.nullable is False
        assert col.sample_values == ["CA", "TX", "NY"]

    def test_column_with_mixed_samples(self) -> None:
        """Column can have mixed-type sample values."""
        col = ColumnInfo(
            name="mixed",
            type="string",
            sample_values=["text", 123, 45.67, None],
        )
        assert len(col.sample_values) == 4


# ============================================================================
# TestSQLFilterResult - Result model tests
# ============================================================================


class TestSQLFilterResult:
    """Tests for SQLFilterResult model construction."""

    def test_simple_result(self) -> None:
        """Simple result with just where_clause should work."""
        result = SQLFilterResult(
            where_clause="state = 'CA'",
            original_expression="California orders",
        )
        assert result.where_clause == "state = 'CA'"
        assert result.original_expression == "California orders"
        assert result.columns_used == []  # default
        assert result.needs_clarification is False  # default

    def test_result_with_clarification(self) -> None:
        """Result with clarification flags should work."""
        result = SQLFilterResult(
            where_clause="order_date = '2026-01-25'",
            columns_used=["order_date"],
            date_column="order_date",
            needs_clarification=True,
            clarification_questions=[
                "Which date column? Options: order_date, ship_by_date"
            ],
            original_expression="today's orders",
        )
        assert result.needs_clarification is True
        assert len(result.clarification_questions) == 1
        assert result.date_column == "order_date"

    def test_result_columns_used_populated(self) -> None:
        """columns_used should track referenced columns."""
        result = SQLFilterResult(
            where_clause="state = 'CA' AND weight > 5",
            columns_used=["state", "weight"],
            original_expression="California orders over 5 lbs",
        )
        assert result.columns_used == ["state", "weight"]


# ============================================================================
# TestFilterGenerationError - Exception tests
# ============================================================================


class TestFilterGenerationError:
    """Tests for FilterGenerationError exception."""

    def test_basic_error(self) -> None:
        """Basic error construction should work."""
        error = FilterGenerationError(
            message="Column 'state_code' not found in schema",
            original_expression="California orders",
            available_columns=["state", "order_id", "customer_name"],
        )
        assert "state_code" in str(error)
        assert "California orders" in str(error)
        assert "state" in str(error)

    def test_error_attributes(self) -> None:
        """Error should expose all attributes."""
        error = FilterGenerationError(
            message="Test error",
            original_expression="test expression",
            available_columns=["col1", "col2"],
        )
        assert error.message == "Test error"
        assert error.original_expression == "test expression"
        assert error.available_columns == ["col1", "col2"]


# ============================================================================
# TestHelperFunctions - Internal helper function tests
# ============================================================================


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_identify_column_types_finds_dates(
        self, shipping_schema: list[ColumnInfo]
    ) -> None:
        """Should identify date/datetime columns."""
        date_cols, numeric_cols = _identify_column_types(shipping_schema)
        assert "order_date" in date_cols
        assert "ship_by_date" in date_cols
        assert "created_at" in date_cols
        assert len(date_cols) == 3

    def test_identify_column_types_finds_numerics(
        self, shipping_schema: list[ColumnInfo]
    ) -> None:
        """Should identify numeric columns including integer types."""
        date_cols, numeric_cols = _identify_column_types(shipping_schema)
        # order_id is integer, which is also numeric
        assert "order_id" in numeric_cols
        assert "package_weight" in numeric_cols
        assert "total_weight" in numeric_cols
        assert "billing_weight" in numeric_cols
        assert "order_total" in numeric_cols
        assert len(numeric_cols) == 5

    def test_build_schema_context_includes_all_columns(
        self, sample_schema: list[ColumnInfo]
    ) -> None:
        """Schema context should list all columns."""
        context = _build_schema_context(sample_schema)
        assert "order_id" in context
        assert "customer_name" in context
        assert "state" in context
        assert "order_date" in context
        assert "weight" in context

    def test_build_schema_context_includes_samples(
        self, sample_schema: list[ColumnInfo]
    ) -> None:
        """Schema context should include sample values."""
        context = _build_schema_context(sample_schema)
        assert "CA" in context or "examples" in context

    def test_detect_temporal_filter_today(self) -> None:
        """'today' should be detected as temporal."""
        assert _detect_temporal_filter("today's orders") is True

    def test_detect_temporal_filter_this_week(self) -> None:
        """'this week' should be detected as temporal."""
        assert _detect_temporal_filter("orders from this week") is True

    def test_detect_temporal_filter_yesterday(self) -> None:
        """'yesterday' should be detected as temporal."""
        assert _detect_temporal_filter("yesterday's shipments") is True

    def test_detect_temporal_filter_non_temporal(self) -> None:
        """Non-temporal expression should return False."""
        assert _detect_temporal_filter("California orders") is False

    def test_detect_temporal_filter_numeric(self) -> None:
        """Numeric filter should not be detected as temporal."""
        assert _detect_temporal_filter("orders over 5 lbs") is False

    def test_validate_columns_used_valid(
        self, sample_schema: list[ColumnInfo]
    ) -> None:
        """Valid columns should not raise error."""
        # Should not raise
        _validate_columns_used(["state", "weight"], sample_schema, "test")

    def test_validate_columns_used_case_insensitive(
        self, sample_schema: list[ColumnInfo]
    ) -> None:
        """Column validation should be case-insensitive."""
        # Should not raise - matching case-insensitively
        _validate_columns_used(["STATE", "WEIGHT"], sample_schema, "test")

    def test_validate_columns_used_invalid(
        self, sample_schema: list[ColumnInfo]
    ) -> None:
        """Invalid column should raise FilterGenerationError."""
        with pytest.raises(FilterGenerationError, match="not found in schema"):
            _validate_columns_used(["nonexistent_column"], sample_schema, "test")


# ============================================================================
# TestFilterGeneratorIntegration - API-dependent tests
# ============================================================================


def has_anthropic_key() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(
    not has_anthropic_key(),
    reason="ANTHROPIC_API_KEY not set",
)
class TestFilterGeneratorIntegration:
    """Integration tests that call the Claude API.

    These tests are skipped if ANTHROPIC_API_KEY is not set.
    Run with: pytest -m integration
    """

    def test_state_filter(self, sample_schema: list[ColumnInfo]) -> None:
        """'California orders' should generate state filter."""
        from src.orchestrator.nl_engine.filter_generator import generate_filter

        result = generate_filter("California orders", sample_schema)

        assert result.where_clause  # Non-empty
        assert "state" in result.columns_used or "CA" in result.where_clause
        assert result.needs_clarification is False

    def test_date_filter_single_column(self, sample_schema: list[ColumnInfo]) -> None:
        """'today's orders' with single date column should work."""
        from src.orchestrator.nl_engine.filter_generator import generate_filter

        result = generate_filter("today's orders", sample_schema)

        assert result.where_clause
        assert "order_date" in result.columns_used or "order_date" in result.where_clause
        # Single date column, should not need clarification
        assert result.needs_clarification is False

    def test_numeric_filter(self, sample_schema: list[ColumnInfo]) -> None:
        """'over 5 lbs' should generate weight comparison."""
        from src.orchestrator.nl_engine.filter_generator import generate_filter

        result = generate_filter("orders over 5 lbs", sample_schema)

        assert result.where_clause
        assert "weight" in result.columns_used or "weight" in result.where_clause
        assert "5" in result.where_clause

    def test_ambiguous_date_columns(self, shipping_schema: list[ColumnInfo]) -> None:
        """Multiple date columns should trigger clarification."""
        from src.orchestrator.nl_engine.filter_generator import generate_filter

        result = generate_filter("today's orders", shipping_schema)

        # With 3 date columns, should need clarification
        assert result.needs_clarification is True
        assert len(result.clarification_questions) > 0

    def test_compound_filter(self, sample_schema: list[ColumnInfo]) -> None:
        """Compound filter should work."""
        from src.orchestrator.nl_engine.filter_generator import generate_filter

        result = generate_filter("California orders over 5 lbs", sample_schema)

        assert result.where_clause
        # Should reference both state and weight
        assert len(result.columns_used) >= 2 or "AND" in result.where_clause.upper()

    def test_empty_schema_raises_error(self) -> None:
        """Empty schema should raise FilterGenerationError."""
        from src.orchestrator.nl_engine.filter_generator import generate_filter

        with pytest.raises(FilterGenerationError, match="cannot be empty"):
            generate_filter("California orders", [])
