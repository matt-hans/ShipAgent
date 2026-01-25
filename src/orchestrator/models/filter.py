"""Filter models for SQL generation from natural language.

These models define the structures for schema-grounded SQL filter generation.
The filter generator produces SQLFilterResult instances that contain validated
WHERE clauses referencing only columns that exist in the source schema.
"""

from typing import Any

from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    """Schema column information for grounding SQL filter generation.

    Provides the filter generator with column metadata to ensure generated
    WHERE clauses only reference valid columns with appropriate operations.

    Attributes:
        name: Column name as found in the source data.
        type: Inferred data type (string, integer, float, date, boolean).
        nullable: Whether the column contains null/empty values.
        sample_values: Optional sample values for context (helps LLM understand data).
    """

    name: str = Field(..., description="Column name as found in the source")
    type: str = Field(
        ...,
        description="Data type: 'string', 'integer', 'float', 'date', or 'boolean'",
    )
    nullable: bool = Field(default=True, description="Whether column allows nulls")
    sample_values: list[Any] = Field(
        default_factory=list,
        description="Optional sample values for LLM context",
    )


class SQLFilterResult(BaseModel):
    """Result of generating a SQL WHERE clause from natural language.

    Contains the generated SQL, metadata about columns used, and flags
    for ambiguous filters that require user clarification.

    Attributes:
        where_clause: SQL WHERE clause without the 'WHERE' keyword.
        columns_used: List of column names referenced in the filter.
        date_column: Date column used for temporal filters (if any).
        needs_clarification: True if the filter is ambiguous.
        clarification_questions: Questions to ask user for disambiguation.
        original_expression: The original natural language filter expression.
    """

    where_clause: str = Field(
        ...,
        description="SQL WHERE clause without 'WHERE' keyword",
    )
    columns_used: list[str] = Field(
        default_factory=list,
        description="Column names referenced in the filter",
    )
    date_column: str | None = Field(
        default=None,
        description="Date column used for temporal filters",
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if filter criteria are ambiguous",
    )
    clarification_questions: list[str] = Field(
        default_factory=list,
        description="Questions to ask user for disambiguation",
    )
    original_expression: str = Field(
        ...,
        description="Original natural language filter expression",
    )


class FilterGenerationError(Exception):
    """Error raised when filter generation fails.

    This exception is raised when the LLM generates invalid SQL or references
    columns that don't exist in the provided schema.

    Attributes:
        message: Human-readable error description.
        original_expression: The NL filter expression that failed.
        available_columns: List of valid column names from the schema.
    """

    def __init__(
        self,
        message: str,
        original_expression: str,
        available_columns: list[str],
    ) -> None:
        """Initialize FilterGenerationError.

        Args:
            message: Human-readable error description.
            original_expression: The NL filter expression that failed.
            available_columns: List of valid column names from the schema.
        """
        self.message = message
        self.original_expression = original_expression
        self.available_columns = available_columns
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error string."""
        return (
            f"{self.message}\n"
            f"Expression: {self.original_expression}\n"
            f"Available columns: {', '.join(self.available_columns)}"
        )
