"""Template output validation against UPS JSON schemas.

This module validates rendered Jinja2 template outputs against UPS API
schema requirements, catching issues like missing required fields,
incorrect types, or values exceeding length limits before attempting
API calls.

Per CONTEXT.md Decision 4: Include specific field, expected format,
actual value in error output.
"""

from typing import Any

import jsonschema
from jsonschema import Draft7Validator
from pydantic import BaseModel

from src.orchestrator.nl_engine.ups_schema import (
    UPS_SHIPMENT_SCHEMA,
    get_schema_for_path,
)


class ValidationError(BaseModel):
    """A single validation error with full context.

    Attributes:
        path: JSONPath to the failing field (e.g., "ShipTo.Phone.Number").
        message: Human-readable error description.
        expected: What was expected (type, format, etc.).
        actual: What was received.
        schema_rule: Which schema rule was violated (e.g., "required",
            "maxLength", "type").
    """

    path: str
    message: str
    expected: str
    actual: Any
    schema_rule: str


class ValidationResult(BaseModel):
    """Validation outcome with all errors and warnings.

    Attributes:
        valid: Whether the output passed validation.
        errors: List of validation errors found.
        warnings: List of non-blocking warnings.
    """

    valid: bool
    errors: list[ValidationError] = []
    warnings: list[str] = []


class TemplateValidationError(Exception):
    """Exception raised when template validation fails.

    Attributes:
        result: The ValidationResult with all errors.
        template_name: Name of the template that failed.
    """

    def __init__(self, result: ValidationResult, template_name: str = "unknown"):
        """Initialize the exception.

        Args:
            result: The ValidationResult containing errors.
            template_name: Name of the template that failed validation.
        """
        self.result = result
        self.template_name = template_name
        error_count = len(result.errors)
        super().__init__(
            f"Template '{template_name}' validation failed with {error_count} error(s)"
        )


def _extract_expected(error: jsonschema.ValidationError) -> str:
    """Extract a human-readable expected value from a jsonschema error.

    Args:
        error: The jsonschema validation error.

    Returns:
        Human-readable description of what was expected.
    """
    validator = error.validator
    validator_value = error.validator_value
    schema = error.schema

    if validator == "required":
        return f"required field (missing: {validator_value})"
    elif validator == "type":
        return f"type '{validator_value}'"
    elif validator == "minLength":
        return f"string with at least {validator_value} character(s)"
    elif validator == "maxLength":
        return f"string with at most {validator_value} character(s)"
    elif validator == "minItems":
        return f"array with at least {validator_value} item(s)"
    elif validator == "maxItems":
        return f"array with at most {validator_value} item(s)"
    elif validator == "pattern":
        return f"string matching pattern '{validator_value}'"
    elif validator == "enum":
        return f"one of: {', '.join(repr(v) for v in validator_value)}"
    elif validator == "minimum":
        return f"value >= {validator_value}"
    elif validator == "maximum":
        return f"value <= {validator_value}"
    elif validator == "oneOf":
        return "value matching one of the allowed schemas"
    elif validator == "anyOf":
        return "value matching at least one of the allowed schemas"
    elif validator == "additionalProperties":
        return "object with no additional properties"

    # Fallback: use schema info
    if "type" in schema:
        return f"type '{schema['type']}'"
    return str(validator_value)


def _format_path(error: jsonschema.ValidationError) -> str:
    """Convert jsonschema error path to dot-notation string.

    Args:
        error: The jsonschema validation error.

    Returns:
        Dot-separated path string (e.g., "ShipTo.Address.City").
    """
    path_parts = list(error.absolute_path)
    if not path_parts:
        return "(root)"
    return ".".join(str(part) for part in path_parts)


def _convert_jsonschema_error(error: jsonschema.ValidationError) -> ValidationError:
    """Convert a jsonschema error to our ValidationError model.

    Args:
        error: The jsonschema validation error.

    Returns:
        ValidationError with full context.
    """
    path = _format_path(error)
    expected = _extract_expected(error)

    # Get the actual value
    actual = error.instance
    if isinstance(actual, dict):
        actual = f"object with keys: {list(actual.keys())}"
    elif isinstance(actual, list):
        actual = f"array with {len(actual)} items"

    return ValidationError(
        path=path,
        message=error.message,
        expected=expected,
        actual=actual,
        schema_rule=error.validator,
    )


def validate_template_output(
    rendered_output: dict[str, Any],
    target_schema: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate rendered template output against a UPS JSON schema.

    Uses jsonschema.Draft7Validator to validate the output and collect
    ALL errors (not just the first one).

    Args:
        rendered_output: The rendered Jinja2 template output as a dict.
        target_schema: The JSON Schema to validate against. If None,
            defaults to UPS_SHIPMENT_SCHEMA.

    Returns:
        ValidationResult with all errors collected.

    Examples:
        >>> from src.orchestrator.nl_engine.ups_schema import UPS_SHIPTO_SCHEMA
        >>> result = validate_template_output(
        ...     {"Name": "John", "Address": {"AddressLine": ["123 Main"], "City": "LA", "CountryCode": "US"}},
        ...     UPS_SHIPTO_SCHEMA
        ... )
        >>> result.valid
        True

        >>> result = validate_template_output({"Name": "John"}, UPS_SHIPTO_SCHEMA)
        >>> result.valid
        False
        >>> len(result.errors) > 0
        True
    """
    if target_schema is None:
        target_schema = UPS_SHIPMENT_SCHEMA

    validator = Draft7Validator(target_schema)
    errors: list[ValidationError] = []
    warnings: list[str] = []

    # Collect all errors
    for error in validator.iter_errors(rendered_output):
        # Convert nested errors to flat list
        if error.context:
            # For oneOf/anyOf failures, include context from all sub-schemas
            for sub_error in error.context:
                errors.append(_convert_jsonschema_error(sub_error))
        else:
            errors.append(_convert_jsonschema_error(error))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def validate_field_value(
    value: Any,
    target_path: str,
) -> ValidationResult:
    """Validate a single field value against its target schema.

    Useful for incremental validation during template building.

    Args:
        value: The field value to validate.
        target_path: Path to the schema element (e.g., "ShipTo.Phone").

    Returns:
        ValidationResult for the single field.

    Raises:
        ValueError: If the target_path is not found in the schema registry.

    Examples:
        >>> result = validate_field_value(
        ...     {"Number": "5551234567"},
        ...     "Phone"
        ... )
        >>> result.valid
        True

        >>> result = validate_field_value(
        ...     {"Number": ""},
        ...     "Phone"
        ... )
        >>> result.valid
        False
    """
    schema = get_schema_for_path(target_path)
    return validate_template_output(value, schema)


def format_validation_errors(result: ValidationResult) -> str:
    """Format validation errors for display to user or LLM.

    Per CONTEXT.md Decision 4: Format includes specific field,
    expected format, actual value.

    Args:
        result: The ValidationResult to format.

    Returns:
        Formatted string with all errors, suitable for display.

    Examples:
        >>> result = ValidationResult(valid=True, errors=[])
        >>> format_validation_errors(result)
        'Validation passed with no errors.'

        >>> from src.orchestrator.nl_engine.ups_schema import UPS_SHIPTO_SCHEMA
        >>> result = validate_template_output({"Name": "John"}, UPS_SHIPTO_SCHEMA)
        >>> output = format_validation_errors(result)
        >>> "Validation failed" in output
        True
    """
    lines = []

    if result.valid:
        lines.append("Validation passed with no errors.")
    else:
        error_count = len(result.errors)
        lines.append(f"Validation failed with {error_count} error(s):")
        lines.append("")

        for i, error in enumerate(result.errors, 1):
            lines.append(f"Error {i}: {error.path}")
            lines.append(f"  Expected: {error.expected}")
            lines.append(f"  Got: {error.actual!r}")
            lines.append(f"  Rule: {error.schema_rule}")
            lines.append("")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)


__all__ = [
    "ValidationError",
    "ValidationResult",
    "TemplateValidationError",
    "validate_template_output",
    "validate_field_value",
    "format_validation_errors",
]
