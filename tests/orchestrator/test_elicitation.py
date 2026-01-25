"""Unit tests for the elicitation module.

Tests cover:
- Elicitation models (Option, Question, Response, Context)
- Elicitation templates (5 common scenarios)
- Question creation with schema customization
- Response handling for all question types
- Needs-elicitation detection
- Context creation with question limits
"""

from datetime import datetime

import pytest

from src.orchestrator.models.elicitation import (
    ElicitationContext,
    ElicitationOption,
    ElicitationQuestion,
    ElicitationResponse,
)
from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult
from src.orchestrator.models.intent import FilterCriteria, ShippingIntent
from src.orchestrator.nl_engine.elicitation import (
    ELICITATION_TEMPLATES,
    TEMPLATE_AMBIGUOUS_BIG,
    TEMPLATE_AMBIGUOUS_WEIGHT,
    TEMPLATE_MISSING_DATE_COLUMN,
    TEMPLATE_MISSING_DIMENSIONS,
    TEMPLATE_MISSING_SERVICE,
    create_elicitation_context,
    create_elicitation_question,
    handle_elicitation_response,
    needs_elicitation,
    _find_date_columns,
    _find_weight_columns,
    _parse_dimensions,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_schema_with_dates() -> list[ColumnInfo]:
    """Schema with multiple date columns for testing date elicitation."""
    return [
        ColumnInfo(name="order_id", type="integer", nullable=False),
        ColumnInfo(name="order_date", type="date"),
        ColumnInfo(name="ship_by_date", type="date"),
        ColumnInfo(name="created_at", type="datetime"),
        ColumnInfo(name="customer_name", type="string"),
    ]


@pytest.fixture
def sample_schema_with_weights() -> list[ColumnInfo]:
    """Schema with multiple weight columns for testing weight elicitation."""
    return [
        ColumnInfo(name="order_id", type="integer", nullable=False),
        ColumnInfo(name="package_weight", type="float"),
        ColumnInfo(name="total_weight", type="float"),
        ColumnInfo(name="billing_weight_lbs", type="float"),
        ColumnInfo(name="customer_name", type="string"),
    ]


@pytest.fixture
def ambiguous_intent() -> ShippingIntent:
    """Intent with needs_clarification=True for testing."""
    return ShippingIntent(
        action="ship",
        data_source="orders.csv",
        filter_criteria=FilterCriteria(
            raw_expression="today's orders",
            filter_type="date",
            needs_clarification=True,
            clarification_reason="Multiple date columns found: order_date, ship_by_date",
        ),
    )


@pytest.fixture
def ambiguous_filter() -> SQLFilterResult:
    """SQLFilterResult with needs_clarification=True for testing."""
    return SQLFilterResult(
        where_clause="",
        columns_used=[],
        needs_clarification=True,
        clarification_questions=["Which date column should be used for filtering?"],
        original_expression="today's orders",
    )


# ============================================================================
# TestElicitationModels - Model validation tests
# ============================================================================


class TestElicitationModels:
    """Tests for elicitation Pydantic models."""

    def test_option_minimal(self) -> None:
        """Option with required fields only."""
        option = ElicitationOption(
            id="order_date",
            label="Order Date",
            description="When the order was placed",
        )
        assert option.id == "order_date"
        assert option.label == "Order Date"
        assert option.description == "When the order was placed"
        assert option.value is None

    def test_option_with_value(self) -> None:
        """Option with explicit value."""
        option = ElicitationOption(
            id="ground",
            label="UPS Ground",
            description="3-5 business days",
            value="03",
        )
        assert option.id == "ground"
        assert option.value == "03"

    def test_question_with_options(self) -> None:
        """Question with list of options."""
        question = ElicitationQuestion(
            id="date_column",
            header="Date Column",
            question="Which date column?",
            options=[
                ElicitationOption(
                    id="order_date",
                    label="Order Date",
                    description="When placed",
                ),
                ElicitationOption(
                    id="ship_by_date",
                    label="Ship By Date",
                    description="Required ship date",
                ),
            ],
        )
        assert question.id == "date_column"
        assert question.header == "Date Column"
        assert len(question.options) == 2
        assert question.allow_free_text is True
        assert question.multi_select is False
        assert question.required is True

    def test_question_multi_select(self) -> None:
        """Question with multi_select enabled."""
        question = ElicitationQuestion(
            id="columns_to_use",
            header="Columns",
            question="Which columns?",
            options=[],
            multi_select=True,
        )
        assert question.multi_select is True

    def test_response_with_selection(self) -> None:
        """Response with selected options."""
        response = ElicitationResponse(
            question_id="date_column",
            selected_options=["order_date"],
        )
        assert response.question_id == "date_column"
        assert response.selected_options == ["order_date"]
        assert response.free_text is None
        assert isinstance(response.timestamp, datetime)

    def test_response_with_free_text(self) -> None:
        """Response with free text instead of selection."""
        response = ElicitationResponse(
            question_id="dimensions",
            selected_options=["custom"],
            free_text="10x12x8",
        )
        assert response.free_text == "10x12x8"

    def test_context_with_questions(self) -> None:
        """Context with questions list."""
        question = ElicitationQuestion(
            id="test",
            header="Test",
            question="Test question",
            options=[],
        )
        context = ElicitationContext(
            questions=[question],
        )
        assert len(context.questions) == 1
        assert context.timeout_seconds == 60
        assert context.complete is False
        assert context.responses == {}


# ============================================================================
# TestElicitationTemplates - Template existence and structure
# ============================================================================


class TestElicitationTemplates:
    """Tests for pre-defined elicitation templates."""

    def test_all_templates_exist(self) -> None:
        """All 5 expected templates exist."""
        expected = [
            "missing_date_column",
            "ambiguous_weight",
            "missing_dimensions",
            "ambiguous_big",
            "missing_service",
        ]
        assert len(ELICITATION_TEMPLATES) == 5
        for template_id in expected:
            assert template_id in ELICITATION_TEMPLATES

    def test_missing_date_column_template(self) -> None:
        """Date column template has expected structure."""
        template = ELICITATION_TEMPLATES[TEMPLATE_MISSING_DATE_COLUMN]
        assert template.id == "date_column"
        assert template.header == "Date Column"
        assert "date column" in template.question.lower()
        assert len(template.options) >= 2

    def test_ambiguous_weight_template(self) -> None:
        """Weight template has expected structure."""
        template = ELICITATION_TEMPLATES[TEMPLATE_AMBIGUOUS_WEIGHT]
        assert template.id == "weight_column"
        assert template.header == "Weight"
        assert "weight" in template.question.lower()
        assert len(template.options) >= 2

    def test_missing_dimensions_template(self) -> None:
        """Dimensions template has expected structure."""
        template = ELICITATION_TEMPLATES[TEMPLATE_MISSING_DIMENSIONS]
        assert template.id == "dimensions"
        assert template.header == "Dimensions"
        assert "dimensions" in template.question.lower()
        # Should have default, custom, add_column options
        option_ids = [o.id for o in template.options]
        assert "default" in option_ids
        assert "custom" in option_ids
        assert "add_column" in option_ids

    def test_ambiguous_big_template(self) -> None:
        """Big definition template has expected structure."""
        template = ELICITATION_TEMPLATES[TEMPLATE_AMBIGUOUS_BIG]
        assert template.id == "big_definition"
        assert template.header == "Size Definition"
        assert "big" in template.question.lower()
        # Should have weight, dimensions, value options
        option_ids = [o.id for o in template.options]
        assert "weight" in option_ids
        assert "dimensions" in option_ids
        assert "value" in option_ids

    def test_missing_service_template(self) -> None:
        """Service template has expected structure."""
        template = ELICITATION_TEMPLATES[TEMPLATE_MISSING_SERVICE]
        assert template.id == "shipping_service"
        assert template.header == "Shipping Service"
        assert "service" in template.question.lower()
        # Should have ground, 2-day, overnight options
        option_ids = [o.id for o in template.options]
        assert "ground" in option_ids
        assert "overnight" in option_ids


# ============================================================================
# TestCreateElicitationQuestion - Question customization
# ============================================================================


class TestCreateElicitationQuestion:
    """Tests for create_elicitation_question function."""

    def test_returns_template_question(self) -> None:
        """Returns a copy of the template question."""
        question = create_elicitation_question(TEMPLATE_MISSING_DATE_COLUMN)
        assert question.id == "date_column"
        assert question.header == "Date Column"

    def test_customizes_with_schema(
        self, sample_schema_with_dates: list[ColumnInfo]
    ) -> None:
        """Customizes options based on schema."""
        question = create_elicitation_question(
            TEMPLATE_MISSING_DATE_COLUMN,
            schema=sample_schema_with_dates,
        )
        # Options should be from actual schema
        option_ids = [o.id for o in question.options]
        assert "order_date" in option_ids
        assert "ship_by_date" in option_ids
        assert "created_at" in option_ids

    def test_date_columns_from_schema(
        self, sample_schema_with_dates: list[ColumnInfo]
    ) -> None:
        """Date columns are extracted from schema."""
        question = create_elicitation_question(
            TEMPLATE_MISSING_DATE_COLUMN,
            schema=sample_schema_with_dates,
        )
        # Should only include date-type columns
        option_ids = [o.id for o in question.options]
        assert "order_id" not in option_ids  # integer
        assert "customer_name" not in option_ids  # string

    def test_weight_columns_from_schema(
        self, sample_schema_with_weights: list[ColumnInfo]
    ) -> None:
        """Weight columns are extracted from schema."""
        question = create_elicitation_question(
            TEMPLATE_AMBIGUOUS_WEIGHT,
            schema=sample_schema_with_weights,
        )
        option_ids = [o.id for o in question.options]
        assert "package_weight" in option_ids
        assert "total_weight" in option_ids
        assert "billing_weight_lbs" in option_ids
        assert "customer_name" not in option_ids

    def test_unknown_template_raises(self) -> None:
        """Unknown template ID raises KeyError."""
        with pytest.raises(KeyError) as exc_info:
            create_elicitation_question("nonexistent_template")
        assert "nonexistent_template" in str(exc_info.value)

    def test_no_schema_uses_default_options(self) -> None:
        """Without schema, uses template default options."""
        question = create_elicitation_question(TEMPLATE_MISSING_DATE_COLUMN)
        # Default template options
        option_ids = [o.id for o in question.options]
        assert "order_date" in option_ids
        assert "ship_by_date" in option_ids
        assert "created_at" in option_ids


# ============================================================================
# TestHandleElicitationResponse - Response processing
# ============================================================================


class TestHandleElicitationResponse:
    """Tests for handle_elicitation_response function."""

    def test_date_column_response(self) -> None:
        """Handles date column selection."""
        response = ElicitationResponse(
            question_id="date_column",
            selected_options=["order_date"],
        )
        result = handle_elicitation_response(response)
        assert result == {"date_column": "order_date"}

    def test_weight_column_response(self) -> None:
        """Handles weight column selection."""
        response = ElicitationResponse(
            question_id="weight_column",
            selected_options=["package_weight"],
        )
        result = handle_elicitation_response(response)
        assert result == {"weight_column": "package_weight"}

    def test_dimensions_default_response(self) -> None:
        """Handles default dimensions selection."""
        response = ElicitationResponse(
            question_id="dimensions",
            selected_options=["default"],
        )
        result = handle_elicitation_response(response)
        assert result["dimensions"] == {
            "length": 10,
            "width": 10,
            "height": 10,
            "unit": "IN",
        }

    def test_dimensions_custom_response(self) -> None:
        """Handles custom dimensions with free text."""
        response = ElicitationResponse(
            question_id="dimensions",
            selected_options=["custom"],
            free_text="10x12x8",
        )
        result = handle_elicitation_response(response)
        assert result["dimensions"]["length"] == 10
        assert result["dimensions"]["width"] == 12
        assert result["dimensions"]["height"] == 8
        assert result["dimensions"]["unit"] == "IN"

    def test_dimensions_add_column_response(self) -> None:
        """Handles add_column selection for dimensions."""
        response = ElicitationResponse(
            question_id="dimensions",
            selected_options=["add_column"],
        )
        result = handle_elicitation_response(response)
        assert result["dimensions_action"] == "add_column"

    def test_service_response_ground(self) -> None:
        """Handles ground service selection."""
        response = ElicitationResponse(
            question_id="shipping_service",
            selected_options=["ground"],
        )
        result = handle_elicitation_response(response)
        assert result == {"service_code": "03"}

    def test_service_response_overnight(self) -> None:
        """Handles overnight service selection."""
        response = ElicitationResponse(
            question_id="shipping_service",
            selected_options=["overnight"],
        )
        result = handle_elicitation_response(response)
        assert result == {"service_code": "01"}

    def test_big_definition_weight(self) -> None:
        """Handles big definition by weight."""
        response = ElicitationResponse(
            question_id="big_definition",
            selected_options=["weight"],
        )
        result = handle_elicitation_response(response)
        assert result["big_filter"]["column"] == "weight"
        assert result["big_filter"]["operator"] == ">"
        assert result["big_filter"]["threshold"] == 5

    def test_free_text_date_column(self) -> None:
        """Handles free text response for date column."""
        response = ElicitationResponse(
            question_id="date_column",
            selected_options=[],
            free_text="custom_date_field",
        )
        result = handle_elicitation_response(response)
        assert result == {"date_column": "custom_date_field"}


# ============================================================================
# TestNeedsElicitation - Detection of clarification needs
# ============================================================================


class TestNeedsElicitation:
    """Tests for needs_elicitation function."""

    def test_clear_intent_no_elicitation(self) -> None:
        """Clear intent with all info needs no elicitation."""
        intent = ShippingIntent(
            action="ship",
            data_source="orders.csv",
            service_code="03",
            package_defaults={"length": 10, "width": 10, "height": 10},
        )
        result = needs_elicitation(intent=intent)
        assert result == []

    def test_ambiguous_filter_needs_elicitation(
        self, ambiguous_intent: ShippingIntent
    ) -> None:
        """Ambiguous filter triggers date elicitation."""
        result = needs_elicitation(intent=ambiguous_intent)
        assert TEMPLATE_MISSING_DATE_COLUMN in result

    def test_missing_service_needs_elicitation(self) -> None:
        """Missing service code triggers service elicitation."""
        intent = ShippingIntent(
            action="ship",
            data_source="orders.csv",
            service_code=None,
        )
        result = needs_elicitation(intent=intent)
        assert TEMPLATE_MISSING_SERVICE in result

    def test_missing_dimensions_needs_elicitation(self) -> None:
        """Missing package defaults triggers dimension elicitation."""
        intent = ShippingIntent(
            action="ship",
            data_source="orders.csv",
            service_code="03",
            package_defaults=None,
        )
        result = needs_elicitation(intent=intent)
        assert TEMPLATE_MISSING_DIMENSIONS in result

    def test_multiple_issues_returns_all(self) -> None:
        """Multiple issues return all needed templates."""
        intent = ShippingIntent(
            action="ship",
            data_source="orders.csv",
            service_code=None,
            package_defaults=None,
            filter_criteria=FilterCriteria(
                raw_expression="today's orders",
                filter_type="date",
                needs_clarification=True,
                clarification_reason="Multiple date columns",
            ),
        )
        result = needs_elicitation(intent=intent)
        assert TEMPLATE_MISSING_SERVICE in result
        assert TEMPLATE_MISSING_DIMENSIONS in result
        assert TEMPLATE_MISSING_DATE_COLUMN in result

    def test_filter_result_with_date_clarification(
        self, ambiguous_filter: SQLFilterResult
    ) -> None:
        """Filter result with date clarification question."""
        result = needs_elicitation(filter_result=ambiguous_filter)
        assert TEMPLATE_MISSING_DATE_COLUMN in result

    def test_rate_action_no_dimension_elicitation(self) -> None:
        """Rate action without package defaults doesn't trigger dimension elicitation."""
        intent = ShippingIntent(
            action="rate",
            data_source="orders.csv",
            service_code="03",
            package_defaults=None,
        )
        result = needs_elicitation(intent=intent)
        # Rate action doesn't require dimensions (would use row data)
        assert TEMPLATE_MISSING_DIMENSIONS not in result


# ============================================================================
# TestCreateElicitationContext - Context creation
# ============================================================================


class TestCreateElicitationContext:
    """Tests for create_elicitation_context function."""

    def test_creates_context_with_questions(self) -> None:
        """Creates context with specified questions."""
        template_ids = [TEMPLATE_MISSING_DATE_COLUMN, TEMPLATE_MISSING_SERVICE]
        context = create_elicitation_context(template_ids)
        assert len(context.questions) == 2
        question_ids = [q.id for q in context.questions]
        assert "date_column" in question_ids
        assert "shipping_service" in question_ids

    def test_limits_to_four_questions(self) -> None:
        """Limits to 4 questions per Agent SDK requirement."""
        template_ids = [
            TEMPLATE_MISSING_DATE_COLUMN,
            TEMPLATE_AMBIGUOUS_WEIGHT,
            TEMPLATE_MISSING_DIMENSIONS,
            TEMPLATE_AMBIGUOUS_BIG,
            TEMPLATE_MISSING_SERVICE,  # This one should be dropped
        ]
        context = create_elicitation_context(template_ids)
        assert len(context.questions) == 4

    def test_timeout_default_60(self) -> None:
        """Default timeout is 60 seconds per Agent SDK."""
        context = create_elicitation_context([TEMPLATE_MISSING_DATE_COLUMN])
        assert context.timeout_seconds == 60

    def test_skips_unknown_templates(self) -> None:
        """Skips unknown template IDs gracefully."""
        template_ids = [TEMPLATE_MISSING_DATE_COLUMN, "unknown_template"]
        context = create_elicitation_context(template_ids)
        assert len(context.questions) == 1

    def test_customizes_with_schema(
        self, sample_schema_with_dates: list[ColumnInfo]
    ) -> None:
        """Customizes questions with schema."""
        context = create_elicitation_context(
            [TEMPLATE_MISSING_DATE_COLUMN],
            schema=sample_schema_with_dates,
        )
        question = context.questions[0]
        option_ids = [o.id for o in question.options]
        assert "order_date" in option_ids


# ============================================================================
# TestHelperFunctions - Internal helper tests
# ============================================================================


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_find_date_columns(
        self, sample_schema_with_dates: list[ColumnInfo]
    ) -> None:
        """Finds columns with date-like types or names."""
        result = _find_date_columns(sample_schema_with_dates)
        names = [c.name for c in result]
        assert "order_date" in names
        assert "ship_by_date" in names
        assert "created_at" in names
        assert "order_id" not in names

    def test_find_weight_columns(
        self, sample_schema_with_weights: list[ColumnInfo]
    ) -> None:
        """Finds numeric columns with weight-like names."""
        result = _find_weight_columns(sample_schema_with_weights)
        names = [c.name for c in result]
        assert "package_weight" in names
        assert "total_weight" in names
        assert "billing_weight_lbs" in names
        assert "customer_name" not in names
        assert "order_id" not in names

    def test_parse_dimensions_standard_format(self) -> None:
        """Parses 10x12x8 format."""
        result = _parse_dimensions("10x12x8")
        assert result == {
            "length": 10,
            "width": 12,
            "height": 8,
            "unit": "IN",
        }

    def test_parse_dimensions_with_spaces(self) -> None:
        """Parses 10 x 12 x 8 format with spaces."""
        result = _parse_dimensions("10 x 12 x 8")
        assert result["length"] == 10
        assert result["width"] == 12
        assert result["height"] == 8

    def test_parse_dimensions_decimals(self) -> None:
        """Parses dimensions with decimal values."""
        result = _parse_dimensions("10.5x12.25x8.75")
        assert result["length"] == 10.5
        assert result["width"] == 12.25
        assert result["height"] == 8.75

    def test_parse_dimensions_comma_separated(self) -> None:
        """Parses comma-separated format."""
        result = _parse_dimensions("10, 12, 8")
        assert result["length"] == 10
        assert result["width"] == 12
        assert result["height"] == 8

    def test_parse_dimensions_invalid_returns_none(self) -> None:
        """Invalid format returns None."""
        result = _parse_dimensions("not dimensions")
        assert result is None

    def test_parse_dimensions_lwh_format(self) -> None:
        """Parses L:10 W:12 H:8 format."""
        result = _parse_dimensions("L:10 W:12 H:8")
        assert result["length"] == 10
        assert result["width"] == 12
        assert result["height"] == 8
