"""Elicitation templates and handlers for ambiguous commands.

This module provides pre-built question templates for common ambiguity scenarios
and handlers for processing user responses. Follows the Claude Agent SDK
AskUserQuestion pattern per CONTEXT.md Decision 1.

Templates cover:
- Date column selection
- Weight column ambiguity
- Missing dimensions
- Ambiguous "big" definition
- Missing shipping service
"""

import re
from typing import TYPE_CHECKING

from src.orchestrator.models.elicitation import (
    ElicitationContext,
    ElicitationOption,
    ElicitationQuestion,
    ElicitationResponse,
)

if TYPE_CHECKING:
    from src.orchestrator.models.filter import ColumnInfo
    from src.orchestrator.models.intent import ShippingIntent, FilterCriteria


# Template IDs for common elicitation scenarios
TEMPLATE_MISSING_DATE_COLUMN = "missing_date_column"
TEMPLATE_AMBIGUOUS_WEIGHT = "ambiguous_weight"
TEMPLATE_MISSING_DIMENSIONS = "missing_dimensions"
TEMPLATE_AMBIGUOUS_BIG = "ambiguous_big"
TEMPLATE_MISSING_SERVICE = "missing_service"


# Pre-built question templates per CONTEXT.md
ELICITATION_TEMPLATES: dict[str, ElicitationQuestion] = {
    TEMPLATE_MISSING_DATE_COLUMN: ElicitationQuestion(
        id="date_column",
        header="Date Column",
        question="Which date column should I use for 'today's orders'?",
        options=[
            ElicitationOption(
                id="order_date",
                label="order_date",
                description="When the order was placed",
            ),
            ElicitationOption(
                id="ship_by_date",
                label="ship_by_date",
                description="Required ship date",
            ),
            ElicitationOption(
                id="created_at",
                label="created_at",
                description="Record creation timestamp",
            ),
        ],
        allow_free_text=True,
        multi_select=False,
        required=True,
    ),
    TEMPLATE_AMBIGUOUS_WEIGHT: ElicitationQuestion(
        id="weight_column",
        header="Weight",
        question="Which weight column should I use?",
        options=[
            ElicitationOption(
                id="package_weight",
                label="package_weight",
                description="Individual package weight",
            ),
            ElicitationOption(
                id="total_weight",
                label="total_weight",
                description="Combined order weight",
            ),
        ],
        allow_free_text=True,
        multi_select=False,
        required=True,
    ),
    TEMPLATE_MISSING_DIMENSIONS: ElicitationQuestion(
        id="dimensions",
        header="Dimensions",
        question="Package dimensions are required. How would you like to provide them?",
        options=[
            ElicitationOption(
                id="default",
                label="Default",
                description="Use standard box: 10x10x10 in",
                value={"length": 10, "width": 10, "height": 10, "unit": "IN"},
            ),
            ElicitationOption(
                id="custom",
                label="Custom",
                description="Enter custom L x W x H",
            ),
            ElicitationOption(
                id="add_column",
                label="Add Column",
                description="I'll add dimension columns to source",
            ),
        ],
        allow_free_text=True,
        multi_select=False,
        required=True,
    ),
    TEMPLATE_AMBIGUOUS_BIG: ElicitationQuestion(
        id="big_definition",
        header="Size Definition",
        question="What defines 'big'?",
        options=[
            ElicitationOption(
                id="weight",
                label="Weight",
                description="Weight > 5 lbs",
                value={"column": "weight", "operator": ">", "threshold": 5},
            ),
            ElicitationOption(
                id="dimensions",
                label="Dimensions",
                description="Any dimension > 12 in",
                value={"column": "dimensions", "operator": ">", "threshold": 12},
            ),
            ElicitationOption(
                id="value",
                label="Value",
                description="Order value > $100",
                value={"column": "value", "operator": ">", "threshold": 100},
            ),
        ],
        allow_free_text=True,
        multi_select=False,
        required=True,
    ),
    TEMPLATE_MISSING_SERVICE: ElicitationQuestion(
        id="shipping_service",
        header="Shipping Service",
        question="Which shipping service should I use?",
        options=[
            ElicitationOption(
                id="ground",
                label="UPS Ground",
                description="3-5 business days",
                value="03",
            ),
            ElicitationOption(
                id="2-day",
                label="2nd Day Air",
                description="2 business days",
                value="02",
            ),
            ElicitationOption(
                id="overnight",
                label="Next Day Air",
                description="1 business day",
                value="01",
            ),
        ],
        allow_free_text=False,
        multi_select=False,
        required=True,
    ),
}


def create_elicitation_question(
    template_id: str,
    schema: list["ColumnInfo"] | None = None,
) -> ElicitationQuestion:
    """Create an elicitation question from a template.

    If schema is provided, customizes options based on actual columns
    present in the source data.

    Args:
        template_id: ID of the template to use
        schema: Optional list of ColumnInfo for customizing options

    Returns:
        ElicitationQuestion with customized options

    Raises:
        KeyError: If template_id is not found
    """
    if template_id not in ELICITATION_TEMPLATES:
        raise KeyError(f"Unknown template_id: {template_id}")

    # Get a copy of the template
    template = ELICITATION_TEMPLATES[template_id].model_copy(deep=True)

    if schema is None:
        return template

    # Customize options based on schema
    if template_id == TEMPLATE_MISSING_DATE_COLUMN:
        # Replace with actual date columns from schema
        date_columns = _find_date_columns(schema)
        if date_columns:
            template.options = [
                ElicitationOption(
                    id=col.name,
                    label=col.name,
                    description=f"Type: {col.type}",
                )
                for col in date_columns
            ]

    elif template_id == TEMPLATE_AMBIGUOUS_WEIGHT:
        # Replace with actual numeric columns that look like weights
        weight_columns = _find_weight_columns(schema)
        if weight_columns:
            template.options = [
                ElicitationOption(
                    id=col.name,
                    label=col.name,
                    description=f"Type: {col.type}",
                )
                for col in weight_columns
            ]

    return template


def handle_elicitation_response(
    response: ElicitationResponse,
    context: dict | None = None,
) -> dict:
    """Process a user's elicitation response.

    Converts the user's selection into a dict of resolved values
    that can be merged into the intent or filter.

    Args:
        response: The user's response to an elicitation question
        context: Optional additional context (e.g., available columns)

    Returns:
        Dict of resolved values to merge into intent/filter
    """
    context = context or {}
    result: dict = {}

    question_id = response.question_id

    if question_id == "date_column":
        # Return the selected date column
        if response.selected_options:
            result["date_column"] = response.selected_options[0]
        elif response.free_text:
            result["date_column"] = response.free_text.strip()

    elif question_id == "weight_column":
        # Return the selected weight column
        if response.selected_options:
            result["weight_column"] = response.selected_options[0]
        elif response.free_text:
            result["weight_column"] = response.free_text.strip()

    elif question_id == "dimensions":
        # Handle dimension responses
        if response.selected_options:
            selection = response.selected_options[0]
            if selection == "default":
                result["dimensions"] = {
                    "length": 10,
                    "width": 10,
                    "height": 10,
                    "unit": "IN",
                }
            elif selection == "add_column":
                result["dimensions_action"] = "add_column"
            elif selection == "custom":
                # Parse custom dimensions from free_text
                if response.free_text:
                    parsed = _parse_dimensions(response.free_text)
                    if parsed:
                        result["dimensions"] = parsed
        elif response.free_text:
            # User provided custom dimensions directly
            parsed = _parse_dimensions(response.free_text)
            if parsed:
                result["dimensions"] = parsed

    elif question_id == "big_definition":
        # Handle "big" definition
        if response.selected_options:
            selection = response.selected_options[0]
            if selection == "weight":
                result["big_filter"] = {"column": "weight", "operator": ">", "threshold": 5}
            elif selection == "dimensions":
                result["big_filter"] = {"column": "dimensions", "operator": ">", "threshold": 12}
            elif selection == "value":
                result["big_filter"] = {"column": "value", "operator": ">", "threshold": 100}

    elif question_id == "shipping_service":
        # Handle service selection
        if response.selected_options:
            selection = response.selected_options[0]
            service_map = {
                "ground": "03",
                "2-day": "02",
                "overnight": "01",
            }
            result["service_code"] = service_map.get(selection, selection)

    return result


def needs_elicitation(
    intent: "ShippingIntent | None" = None,
    filter_result: "SQLFilterResult | None" = None,
) -> list[str]:
    """Check if intent or filter requires elicitation.

    Analyzes the parsed intent and filter result to determine
    what questions need to be asked.

    Args:
        intent: Parsed shipping intent (optional)
        filter_result: Generated SQL filter (optional)

    Returns:
        List of template_ids for questions to ask
    """
    # Import here to avoid circular imports
    from src.orchestrator.models.filter import SQLFilterResult

    template_ids: list[str] = []

    if intent is not None:
        # Check if filter criteria needs clarification
        if intent.filter_criteria and intent.filter_criteria.needs_clarification:
            reason = intent.filter_criteria.clarification_reason or ""
            # Determine which template based on reason
            if "date" in reason.lower():
                template_ids.append(TEMPLATE_MISSING_DATE_COLUMN)
            elif "weight" in reason.lower():
                template_ids.append(TEMPLATE_AMBIGUOUS_WEIGHT)
            elif "big" in reason.lower() or "size" in reason.lower():
                template_ids.append(TEMPLATE_AMBIGUOUS_BIG)

        # Check if service code is missing
        if intent.action == "ship" and intent.service_code is None:
            template_ids.append(TEMPLATE_MISSING_SERVICE)

        # Check if package defaults are missing dimensions
        if intent.action == "ship" and not intent.package_defaults:
            # No default package info - might need dimensions
            template_ids.append(TEMPLATE_MISSING_DIMENSIONS)

    if filter_result is not None and isinstance(filter_result, SQLFilterResult):
        # Check filter result clarification questions
        if filter_result.needs_clarification:
            for question in filter_result.clarification_questions:
                question_lower = question.lower()
                if "date" in question_lower:
                    if TEMPLATE_MISSING_DATE_COLUMN not in template_ids:
                        template_ids.append(TEMPLATE_MISSING_DATE_COLUMN)
                elif "weight" in question_lower:
                    if TEMPLATE_AMBIGUOUS_WEIGHT not in template_ids:
                        template_ids.append(TEMPLATE_AMBIGUOUS_WEIGHT)

    return template_ids


def create_elicitation_context(
    template_ids: list[str],
    schema: list["ColumnInfo"] | None = None,
) -> ElicitationContext:
    """Build an elicitation context with questions.

    Creates a full context with all requested questions, limiting
    to max 4 per Agent SDK requirements.

    Args:
        template_ids: List of template IDs for questions to include
        schema: Optional schema for customizing questions

    Returns:
        ElicitationContext ready for use
    """
    # Limit to max 4 questions per Agent SDK
    limited_ids = template_ids[:4]

    questions = []
    for template_id in limited_ids:
        try:
            question = create_elicitation_question(template_id, schema)
            questions.append(question)
        except KeyError:
            # Skip unknown templates
            pass

    return ElicitationContext(
        questions=questions,
        responses={},
        timeout_seconds=60,
        complete=False,
    )


def _find_date_columns(schema: list["ColumnInfo"]) -> list["ColumnInfo"]:
    """Find columns that appear to be date/datetime columns.

    Args:
        schema: List of ColumnInfo from source

    Returns:
        List of columns that look like dates
    """
    date_keywords = ["date", "time", "created", "updated", "timestamp", "at"]
    date_types = ["date", "datetime", "timestamp"]

    result = []
    for col in schema:
        # Check type first
        if col.type.lower() in date_types:
            result.append(col)
            continue

        # Check name for date-like patterns
        name_lower = col.name.lower()
        if any(keyword in name_lower for keyword in date_keywords):
            result.append(col)

    return result


def _find_weight_columns(schema: list["ColumnInfo"]) -> list["ColumnInfo"]:
    """Find columns that appear to be weight columns.

    Args:
        schema: List of ColumnInfo from source

    Returns:
        List of columns that look like weights
    """
    weight_keywords = ["weight", "wt", "lbs", "pounds", "kg", "kilos", "oz", "ounces"]
    numeric_types = ["integer", "float", "number", "decimal"]

    result = []
    for col in schema:
        # Must be numeric
        if col.type.lower() not in numeric_types:
            continue

        # Check name for weight-like patterns
        name_lower = col.name.lower()
        if any(keyword in name_lower for keyword in weight_keywords):
            result.append(col)

    return result


def _parse_dimensions(text: str) -> dict | None:
    """Parse dimension string into structured format.

    Supports formats like:
    - "10x12x8"
    - "10 x 12 x 8"
    - "L:10 W:12 H:8"
    - "10, 12, 8"

    Args:
        text: User-provided dimension string

    Returns:
        Dict with length, width, height, unit or None if parsing fails
    """
    text = text.strip()

    # Try "NxNxN" format
    match = re.match(r"(\d+(?:\.\d+)?)\s*[xX,]\s*(\d+(?:\.\d+)?)\s*[xX,]\s*(\d+(?:\.\d+)?)", text)
    if match:
        return {
            "length": float(match.group(1)),
            "width": float(match.group(2)),
            "height": float(match.group(3)),
            "unit": "IN",
        }

    # Try "L:N W:N H:N" format
    match = re.match(
        r"[Ll]:?\s*(\d+(?:\.\d+)?)\s*[Ww]:?\s*(\d+(?:\.\d+)?)\s*[Hh]:?\s*(\d+(?:\.\d+)?)",
        text,
    )
    if match:
        return {
            "length": float(match.group(1)),
            "width": float(match.group(2)),
            "height": float(match.group(3)),
            "unit": "IN",
        }

    return None
