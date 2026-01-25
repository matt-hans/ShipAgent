"""Schema-grounded SQL filter generation from natural language.

This module converts natural language filter expressions into validated SQL
WHERE clauses. The generation is grounded in the source schema to prevent
column hallucination - the LLM can only reference columns that actually exist.

Per CONTEXT.md Decision 3:
- Temporal filters with multiple date columns trigger clarification
- Ambiguous numeric comparisons trigger clarification
- Never guess - use elicitation for unclear cases
"""

from datetime import datetime

import sqlglot
from anthropic import Anthropic

from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult

# Re-export FilterGenerationError from models for convenience
from src.orchestrator.models.filter import FilterGenerationError

__all__ = [
    "generate_filter",
    "validate_sql_syntax",
    "FilterGenerationError",
]


def validate_sql_syntax(where_clause: str) -> bool:
    """Validate SQL WHERE clause syntax using sqlglot.

    Wraps the clause in a SELECT statement for proper validation.

    Args:
        where_clause: SQL WHERE clause without the 'WHERE' keyword.

    Returns:
        True if the syntax is valid.

    Raises:
        ValueError: If the SQL syntax is invalid.
    """
    try:
        # Wrap in SELECT to validate as complete statement
        sqlglot.parse(f"SELECT * FROM t WHERE {where_clause}")
        return True
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"Invalid SQL syntax: {e}") from e


def _identify_column_types(schema: list[ColumnInfo]) -> tuple[list[str], list[str]]:
    """Identify date and numeric columns from schema.

    Args:
        schema: List of ColumnInfo objects describing the source schema.

    Returns:
        Tuple of (date_columns, numeric_columns).
    """
    date_columns = []
    numeric_columns = []

    for col in schema:
        col_type = col.type.lower()
        if col_type in ("date", "datetime", "timestamp"):
            date_columns.append(col.name)
        elif col_type in ("integer", "float", "decimal", "numeric", "int", "number"):
            numeric_columns.append(col.name)

    return date_columns, numeric_columns


def _build_schema_context(schema: list[ColumnInfo]) -> str:
    """Build column context string for the LLM prompt.

    Args:
        schema: List of ColumnInfo objects.

    Returns:
        Formatted string listing all columns and their types.
    """
    lines = []
    for col in schema:
        sample_str = ""
        if col.sample_values:
            # Include up to 3 sample values
            samples = [str(v) for v in col.sample_values[:3]]
            sample_str = f" (examples: {', '.join(samples)})"
        lines.append(f"- {col.name} ({col.type}){sample_str}")
    return "\n".join(lines)


def _detect_temporal_filter(filter_expression: str) -> bool:
    """Detect if the filter expression contains temporal references.

    Args:
        filter_expression: The natural language filter expression.

    Returns:
        True if the expression contains date/time references.
    """
    temporal_keywords = [
        "today",
        "yesterday",
        "tomorrow",
        "this week",
        "last week",
        "next week",
        "this month",
        "last month",
        "this year",
        "last year",
        "recent",
        "latest",
        "newest",
        "oldest",
        "date",
        "dated",
    ]
    lower_expr = filter_expression.lower()
    return any(keyword in lower_expr for keyword in temporal_keywords)


def _validate_columns_used(
    columns_used: list[str],
    schema: list[ColumnInfo],
    original_expression: str,
) -> None:
    """Verify all referenced columns exist in the schema.

    Args:
        columns_used: List of column names from the generated filter.
        schema: The source schema.
        original_expression: Original NL expression for error context.

    Raises:
        FilterGenerationError: If any column doesn't exist in schema.
    """
    available_columns = [col.name for col in schema]
    available_lower = {c.lower(): c for c in available_columns}

    for col in columns_used:
        # Check exact match first, then case-insensitive
        if col not in available_columns and col.lower() not in available_lower:
            raise FilterGenerationError(
                message=f"Column '{col}' not found in schema",
                original_expression=original_expression,
                available_columns=available_columns,
            )


def generate_filter(
    filter_expression: str,
    schema: list[ColumnInfo],
    system_timezone: str = "America/Los_Angeles",
) -> SQLFilterResult:
    """Generate a SQL WHERE clause from a natural language filter expression.

    Uses Claude structured outputs for schema-grounded generation. The LLM is
    constrained to only reference columns from the provided schema.

    Per CONTEXT.md Decision 3:
    - Multiple date columns with temporal filter -> needs_clarification=True
    - Ambiguous numeric comparisons -> needs_clarification=True

    Args:
        filter_expression: Natural language filter like "California orders".
        schema: List of ColumnInfo objects describing source columns.
        system_timezone: Timezone for date interpretation (default: America/Los_Angeles).

    Returns:
        SQLFilterResult with the generated WHERE clause and metadata.

    Raises:
        FilterGenerationError: If generation fails or produces invalid SQL.
    """
    if not schema:
        raise FilterGenerationError(
            message="Schema cannot be empty",
            original_expression=filter_expression,
            available_columns=[],
        )

    # Build column context
    schema_context = _build_schema_context(schema)
    date_columns, numeric_columns = _identify_column_types(schema)
    available_columns = [col.name for col in schema]
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Check for pre-clarification needs
    is_temporal = _detect_temporal_filter(filter_expression)

    # Build system prompt with schema grounding
    system_prompt = f"""You generate SQL WHERE clauses for data filtering.

CURRENT CONTEXT:
- Current date: {current_date}
- System timezone: {system_timezone}

AVAILABLE COLUMNS (USE ONLY THESE):
{schema_context}

DATE COLUMNS: {date_columns if date_columns else 'None'}
NUMERIC COLUMNS: {numeric_columns if numeric_columns else 'None'}

CRITICAL RULES:
1. ONLY use column names from the AVAILABLE COLUMNS list above
2. For date filters like "today", use: column = '{current_date}'
3. For "this week", calculate the appropriate date range
4. Use proper SQL syntax matching the column types
5. For string comparisons, use single quotes: column = 'value'
6. State abbreviations: California='CA', Texas='TX', etc.

AMBIGUITY HANDLING:
- If filter is temporal AND there are multiple date columns, set needs_clarification=True
- If filter involves numeric comparison AND there are multiple similar numeric columns, set needs_clarification=True
- If filter is vague (like "big orders", "large"), set needs_clarification=True
- Add specific clarification questions when needs_clarification=True

OUTPUT REQUIREMENTS:
- where_clause: Valid SQL without 'WHERE' keyword
- columns_used: List all columns referenced in where_clause
- date_column: If temporal filter, which date column used
- needs_clarification: True if ambiguous
- clarification_questions: Specific questions for disambiguation
- original_expression: Copy the input expression exactly"""

    user_prompt = f"""Generate SQL WHERE clause for: "{filter_expression}"

Remember:
- Only use columns from the available list
- Set needs_clarification=True if ambiguous
- Use proper SQL syntax"""

    # Call Claude with structured outputs
    client = Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
            system=system_prompt,
            tools=[
                {
                    "name": "create_filter",
                    "description": "Create a SQL filter result",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "where_clause": {
                                "type": "string",
                                "description": "SQL WHERE clause without 'WHERE' keyword",
                            },
                            "columns_used": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Column names referenced in the filter",
                            },
                            "date_column": {
                                "type": "string",
                                "nullable": True,
                                "description": "Date column used for temporal filters",
                            },
                            "needs_clarification": {
                                "type": "boolean",
                                "description": "True if filter is ambiguous",
                            },
                            "clarification_questions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Questions for disambiguation",
                            },
                            "original_expression": {
                                "type": "string",
                                "description": "Original NL filter expression",
                            },
                        },
                        "required": [
                            "where_clause",
                            "columns_used",
                            "needs_clarification",
                            "original_expression",
                        ],
                    },
                }
            ],
            tool_choice={"type": "tool", "name": "create_filter"},
        )
    except Exception as e:
        raise FilterGenerationError(
            message=f"API call failed: {e}",
            original_expression=filter_expression,
            available_columns=available_columns,
        ) from e

    # Extract tool use result
    tool_use = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "create_filter":
            tool_use = block
            break

    if not tool_use:
        raise FilterGenerationError(
            message="No filter generated by LLM",
            original_expression=filter_expression,
            available_columns=available_columns,
        )

    # Parse the result
    result_data = tool_use.input

    # Build SQLFilterResult
    result = SQLFilterResult(
        where_clause=result_data.get("where_clause", ""),
        columns_used=result_data.get("columns_used", []),
        date_column=result_data.get("date_column"),
        needs_clarification=result_data.get("needs_clarification", False),
        clarification_questions=result_data.get("clarification_questions", []),
        original_expression=filter_expression,
    )

    # Post-generation validation

    # 1. Validate SQL syntax
    try:
        validate_sql_syntax(result.where_clause)
    except ValueError as e:
        raise FilterGenerationError(
            message=str(e),
            original_expression=filter_expression,
            available_columns=available_columns,
        ) from e

    # 2. Validate columns used exist in schema
    _validate_columns_used(result.columns_used, schema, filter_expression)

    # 3. Additional ambiguity check: temporal filter with multiple date columns
    if is_temporal and len(date_columns) > 1 and not result.needs_clarification:
        # LLM should have caught this, but enforce it
        result = SQLFilterResult(
            where_clause=result.where_clause,
            columns_used=result.columns_used,
            date_column=result.date_column,
            needs_clarification=True,
            clarification_questions=[
                f"Which date column should be used? Options: {', '.join(date_columns)}"
            ]
            + result.clarification_questions,
            original_expression=filter_expression,
        )

    return result
