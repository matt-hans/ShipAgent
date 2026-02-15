"""Intent models for natural language shipping commands.

These Pydantic models define the structure of parsed user commands,
including shipping intents, filter criteria, and row qualifiers.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Re-export canonical service code definitions for backward compatibility.
# All consumers that import ServiceCode, SERVICE_ALIASES, CODE_TO_SERVICE
# from this module continue to work unchanged.
from src.services.ups_service_codes import (  # noqa: F401
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    ServiceCode,
)


class RowQualifier(BaseModel):
    """Batch qualifier for row selection.

    Used to specify which rows to process, such as "first 10",
    "random sample of 5", or "every other row".

    Attributes:
        qualifier_type: Type of qualifier (first, last, random, every_nth, all)
        count: Number of rows for first/last/random qualifiers
        nth: Interval for every_nth qualifier (2 = every other row)
    """

    model_config = ConfigDict(from_attributes=True)

    qualifier_type: Literal["first", "last", "random", "every_nth", "all"] = Field(
        default="all",
        description="Type of row qualification",
    )
    count: Optional[int] = Field(
        default=None,
        ge=1,
        description="Number of rows for first/last/random qualifiers",
    )
    nth: Optional[int] = Field(
        default=None,
        ge=2,
        description="Interval for every_nth qualifier (2 = every other row)",
    )


class FilterCriteria(BaseModel):
    """Filter criteria for data selection.

    Represents the parsed filter expression from natural language,
    including type classification and clarification needs.

    Attributes:
        raw_expression: Original natural language filter text
        filter_type: Classification of filter type
        needs_clarification: Whether the filter needs user clarification
        clarification_reason: Reason clarification is needed
    """

    model_config = ConfigDict(from_attributes=True)

    raw_expression: str = Field(
        ...,
        description="Original natural language filter text",
    )
    filter_type: Literal["state", "date", "numeric", "compound", "none"] = Field(
        default="none",
        description="Classification of filter type",
    )
    needs_clarification: bool = Field(
        default=False,
        description="Whether the filter needs user clarification",
    )
    clarification_reason: Optional[str] = Field(
        default=None,
        description="Reason clarification is needed",
    )


class ShippingIntent(BaseModel):
    """Parsed shipping command intent.

    This is the main output of intent parsing, containing all the
    structured information extracted from a natural language command.

    Attributes:
        action: The action to perform (ship, rate, validate_address)
        data_source: File path or table reference for source data
        service_code: UPS service code for shipping
        filter_criteria: Filter expression for row selection
        row_qualifier: Batch qualifier for row selection
        package_defaults: Default package dimensions/weight
    """

    model_config = ConfigDict(from_attributes=True)

    action: Literal["ship", "rate", "validate_address"] = Field(
        ...,
        description="The shipping action to perform",
    )
    data_source: Optional[str] = Field(
        default=None,
        description="File path or table reference for source data",
    )
    service_code: Optional[ServiceCode] = Field(
        default=None,
        description="UPS service code for shipping",
    )
    filter_criteria: Optional[FilterCriteria] = Field(
        default=None,
        description="Filter expression for row selection",
    )
    row_qualifier: Optional[RowQualifier] = Field(
        default=None,
        description="Batch qualifier for row selection",
    )
    package_defaults: Optional[dict] = Field(
        default=None,
        description="Default package dimensions and weight",
    )
