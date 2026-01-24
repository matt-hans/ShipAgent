"""Pydantic models for Data Source MCP tool inputs and outputs.

These models define the contracts for data exchange between the MCP tools
and client applications. All tool responses are validated against these models.
"""

from typing import Any

from pydantic import BaseModel, Field


class SchemaColumn(BaseModel):
    """Represents a column in the discovered schema.

    Attributes:
        name: Column name as found in the source
        type: Inferred data type (string, integer, float, date, boolean)
        nullable: Whether the column contains null/empty values
        warnings: Any warnings during type inference (e.g., mixed types)
    """

    name: str = Field(..., description="Column name as found in the source")
    type: str = Field(..., description="Inferred data type")
    nullable: bool = Field(default=True, description="Whether column allows nulls")
    warnings: list[str] = Field(
        default_factory=list, description="Warnings from type inference"
    )


class ImportResult(BaseModel):
    """Result of importing a data source.

    Attributes:
        row_count: Number of rows successfully imported
        columns: Discovered schema columns
        warnings: Import-level warnings (e.g., skipped rows)
        source_type: Type of source imported (csv, excel, postgres, mysql)
    """

    row_count: int = Field(..., description="Number of rows imported")
    columns: list[SchemaColumn] = Field(..., description="Discovered schema")
    warnings: list[str] = Field(
        default_factory=list, description="Import-level warnings"
    )
    source_type: str = Field(..., description="Type of data source")


class RowData(BaseModel):
    """Represents a single row of imported data.

    Attributes:
        row_number: 1-indexed row number in the source
        data: Dictionary of column name to value
        checksum: SHA-256 checksum for integrity verification
    """

    row_number: int = Field(..., ge=1, description="1-indexed row number")
    data: dict[str, Any] = Field(..., description="Row data as key-value pairs")
    checksum: str | None = Field(default=None, description="SHA-256 row checksum")


class QueryResult(BaseModel):
    """Result of querying imported data.

    Attributes:
        rows: List of rows matching the query
        total_count: Total number of matching rows
    """

    rows: list[RowData] = Field(..., description="Matching rows")
    total_count: int = Field(..., description="Total count of matching rows")


class ChecksumResult(BaseModel):
    """Checksum for a single row.

    Attributes:
        row_number: 1-indexed row number
        checksum: SHA-256 checksum of the row data
    """

    row_number: int = Field(..., ge=1, description="1-indexed row number")
    checksum: str = Field(..., description="SHA-256 checksum")


class DateWarning(BaseModel):
    """Warning for ambiguous date format.

    Per CONTEXT.md: Dates like 01/02/03 are ambiguous between US and EU formats.
    These warnings help users understand how dates were interpreted.

    Attributes:
        column: Column name containing the ambiguous date
        sample_value: The original value as found in source
        us_interpretation: Date if parsed as US format (MM/DD/YYYY)
        eu_interpretation: Date if parsed as EU format (DD/MM/YYYY)
    """

    column: str = Field(..., description="Column containing ambiguous date")
    sample_value: str = Field(..., description="Original date string")
    us_interpretation: str = Field(..., description="Date in US format interpretation")
    eu_interpretation: str = Field(..., description="Date in EU format interpretation")


class ValidationError(BaseModel):
    """Validation error for a specific cell.

    Attributes:
        row_number: 1-indexed row number with the error
        column: Column name where error occurred
        message: Human-readable error description
        value: The problematic value
    """

    row_number: int = Field(..., ge=1, description="Row with the error")
    column: str = Field(..., description="Column name")
    message: str = Field(..., description="Error description")
    value: Any = Field(..., description="The problematic value")
