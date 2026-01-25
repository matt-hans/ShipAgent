"""Mapping models for data-to-UPS payload transformations.

These Pydantic models define the structure for field mappings and mapping
templates that transform source data columns to UPS API payload format.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class FieldMapping(BaseModel):
    """Single field mapping from source column to UPS target field.

    Represents one mapping from a source data column to a target field
    in the UPS API payload, with optional transformation and default value.

    Attributes:
        source_column: Column name from source data (e.g., "customer_name").
        target_path: JSONPath in UPS payload (e.g., "ShipTo.Name").
        transformation: Optional Jinja2 filter expression (e.g., "truncate_address(35)").
        default_value: Optional fallback if source is null/empty.

    Example:
        FieldMapping(
            source_column="full_name",
            target_path="ShipTo.Name",
            transformation="truncate_address(35)",
            default_value=None
        )
    """

    model_config = ConfigDict(from_attributes=True)

    source_column: str = Field(
        ...,
        description="Column name from source data",
    )
    target_path: str = Field(
        ...,
        description="JSONPath in UPS payload (e.g., ShipTo.Name)",
    )
    transformation: Optional[str] = Field(
        default=None,
        description="Jinja2 filter expression (e.g., truncate_address(35))",
    )
    default_value: Optional[Any] = Field(
        default=None,
        description="Default value if source is null/empty",
    )


class MappingTemplate(BaseModel):
    """Complete mapping template for source-to-UPS transformation.

    Contains all field mappings needed to transform source data rows
    to valid UPS API payloads, plus metadata for template reuse.

    Attributes:
        name: Template name for saving/retrieving (e.g., "Weekly Fulfillment").
        source_schema_hash: Hash of source column names for matching.
        mappings: List of individual field mappings.
        missing_required: List of required UPS fields not mapped.
        jinja_template: Compiled Jinja2 template string.

    Example:
        MappingTemplate(
            name="order_export",
            source_schema_hash="a1b2c3d4e5f6...",
            mappings=[
                FieldMapping(source_column="name", target_path="ShipTo.Name"),
                FieldMapping(source_column="city", target_path="ShipTo.Address.City"),
            ],
            missing_required=["ShipTo.Phone.Number"],
            jinja_template="{ ... }"
        )
    """

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(
        ...,
        description="Template name for saving/retrieving",
    )
    source_schema_hash: str = Field(
        ...,
        description="Hash of source column names for matching",
    )
    mappings: list[FieldMapping] = Field(
        default_factory=list,
        description="List of field mappings",
    )
    missing_required: list[str] = Field(
        default_factory=list,
        description="Required UPS fields not mapped",
    )
    jinja_template: Optional[str] = Field(
        default=None,
        description="Compiled Jinja2 template string",
    )


class UPSTargetField(BaseModel):
    """UPS schema field information for mapping guidance.

    Provides metadata about target fields in the UPS API payload to
    help users understand mapping requirements.

    Attributes:
        path: JSONPath in UPS payload (e.g., "ShipTo.Name").
        type: Field data type (e.g., "string", "number", "array").
        required: Whether the field is required for valid payloads.
        max_length: Maximum string length (if applicable).
        description: Human-readable field description.

    Example:
        UPSTargetField(
            path="ShipTo.Name",
            type="string",
            required=True,
            max_length=35,
            description="Recipient name on shipping label"
        )
    """

    model_config = ConfigDict(from_attributes=True)

    path: str = Field(
        ...,
        description="JSONPath in UPS payload",
    )
    type: str = Field(
        ...,
        description="Data type (string, number, array, object)",
    )
    required: bool = Field(
        default=False,
        description="Whether field is required for valid payload",
    )
    max_length: Optional[int] = Field(
        default=None,
        description="Maximum string length (if applicable)",
    )
    description: str = Field(
        default="",
        description="Human-readable field description",
    )


class MappingGenerationError(Exception):
    """Error raised when mapping template generation fails.

    This exception is raised when template compilation fails or
    when there are validation errors in the mapping configuration.

    Attributes:
        message: Human-readable error description.
        source_column: The source column that caused the error (if applicable).
        target_path: The target path that caused the error (if applicable).
    """

    def __init__(
        self,
        message: str,
        source_column: Optional[str] = None,
        target_path: Optional[str] = None,
    ) -> None:
        """Initialize MappingGenerationError.

        Args:
            message: Human-readable error description.
            source_column: The source column that caused the error.
            target_path: The target path that caused the error.
        """
        self.message = message
        self.source_column = source_column
        self.target_path = target_path
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error string."""
        parts = [self.message]
        if self.source_column:
            parts.append(f"Source column: {self.source_column}")
        if self.target_path:
            parts.append(f"Target path: {self.target_path}")
        return "\n".join(parts)
