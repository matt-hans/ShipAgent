"""Self-correction loop for fixing template validation errors.

This module implements the automatic self-correction loop that attempts
to fix Jinja2 template validation errors by providing feedback to the LLM.
Per CONTEXT.md Decision 4, the system attempts up to 3 corrections before
escalating to the user with options.
"""

import json
import os
import re
from typing import Any, Optional

from anthropic import Anthropic

from src.orchestrator.nl_engine.config import get_model
from src.orchestrator.models.correction import (
    CorrectionAttempt,
    CorrectionOptions,
    CorrectionResult,
    MaxCorrectionsExceeded,
)
from src.orchestrator.models.filter import ColumnInfo
from src.orchestrator.nl_engine.template_validator import (
    ValidationError,
    ValidationResult,
    validate_template_output,
)


def format_errors_for_llm(errors: list[ValidationError]) -> str:
    """Format validation errors for LLM consumption.

    Creates a clear, actionable error description that helps the LLM
    understand what needs to be fixed in the template.

    Args:
        errors: List of validation errors from template validation.

    Returns:
        Formatted string with errors and fix suggestions.

    Example:
        >>> from src.orchestrator.nl_engine.template_validator import ValidationError
        >>> errors = [
        ...     ValidationError(
        ...         path='ShipTo.Phone.Number',
        ...         message='Too short',
        ...         expected='string with at least 10 character(s)',
        ...         actual='555-1234',
        ...         schema_rule='minLength'
        ...     )
        ... ]
        >>> formatted = format_errors_for_llm(errors)
        >>> 'ShipTo.Phone.Number' in formatted
        True
    """
    if not errors:
        return "No validation errors found."

    lines = [f"Found {len(errors)} validation error(s):", ""]

    for i, error in enumerate(errors, 1):
        lines.append(f"Error {i}:")
        lines.append(f"  Field: {error.path}")
        lines.append(f"  Expected: {error.expected}")
        lines.append(f"  Got: {error.actual!r}")

        # Add fix suggestions based on schema rule
        fix_suggestion = _get_fix_suggestion(error)
        if fix_suggestion:
            lines.append(f"  Fix: {fix_suggestion}")

        lines.append("")

    return "\n".join(lines)


def _get_fix_suggestion(error: ValidationError) -> str:
    """Generate a fix suggestion based on the error type.

    Args:
        error: The validation error to suggest a fix for.

    Returns:
        A human-readable fix suggestion.
    """
    rule = error.schema_rule
    path = error.path

    suggestions = {
        "minLength": f"Ensure the value has enough characters. Check if the source column is being truncated or if a default value is needed.",
        "maxLength": f"Truncate the value using truncate_address() or similar filter. UPS has strict length limits.",
        "required": f"Map a source column to {path} or provide a default value using default_value() filter.",
        "type": f"Ensure the value has the correct type. Use appropriate transformation if needed.",
        "pattern": f"Format the value to match the expected pattern. Check phone/postal code formatting.",
        "minimum": f"Ensure the numeric value meets the minimum requirement.",
        "maximum": f"Ensure the numeric value does not exceed the maximum.",
        "enum": f"Use one of the allowed values. Check lookup_service_code() for service mappings.",
    }

    # Path-specific suggestions
    if "Phone" in path:
        return "Ensure phone numbers include area code and are 10-15 digits. Use to_ups_phone() filter."
    if "PostalCode" in path:
        return "Normalize postal codes using format_us_zip() filter."
    if "Address" in path and rule == "maxLength":
        return "Truncate address lines to 35 characters using truncate_address(35) filter."
    if "Name" in path and rule == "maxLength":
        return "Truncate name to 35 characters using truncate_address(35) filter."
    if "Weight" in path:
        return "Ensure weight is a positive number. Use round_weight() and convert_weight() as needed."

    return suggestions.get(rule, "Review the field mapping and transformation.")


def extract_template_from_response(response_text: str) -> str:
    """Extract Jinja2 template from LLM response.

    Handles various code block formats and extracts the template content.

    Args:
        response_text: The raw text from LLM response.

    Returns:
        Clean template string without markdown formatting.

    Example:
        >>> response = '''Here is the fixed template:
        ... ```jinja2
        ... {{ name | truncate_address(35) }}
        ... ```
        ... '''
        >>> extract_template_from_response(response)
        '{{ name | truncate_address(35) }}'
    """
    # Try to extract from ```jinja2 block first
    jinja2_pattern = r"```jinja2?\s*\n(.*?)\n```"
    match = re.search(jinja2_pattern, response_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try to extract from ```json block
    json_pattern = r"```json\s*\n(.*?)\n```"
    match = re.search(json_pattern, response_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try generic code block
    generic_pattern = r"```\s*\n(.*?)\n```"
    match = re.search(generic_pattern, response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # If no code block, look for JSON-like structure
    json_object_pattern = r"(\{[\s\S]*\})"
    match = re.search(json_object_pattern, response_text)
    if match:
        # Validate it looks like a template (has Jinja2 expressions)
        candidate = match.group(1).strip()
        if "{{" in candidate or candidate.startswith("{"):
            return candidate

    # Return the full response if no pattern matched
    return response_text.strip()


def format_source_schema(schema: list[ColumnInfo]) -> str:
    """Format source schema for LLM context.

    Args:
        schema: List of column info from source data.

    Returns:
        Formatted string describing available columns.
    """
    if not schema:
        return "No source schema provided."

    lines = ["Available source columns:"]
    for col in schema:
        samples = ""
        if col.sample_values:
            samples = f" (examples: {col.sample_values[:3]})"
        lines.append(f"  - {col.name}: {col.type}{samples}")

    return "\n".join(lines)


def attempt_correction(
    template: str,
    errors: list[ValidationError],
    source_schema: list[ColumnInfo],
) -> CorrectionAttempt:
    """Attempt to correct a template using Claude API.

    Calls Claude with the original template, validation errors, and
    source schema context to generate a corrected template.

    Args:
        template: The original Jinja2 template that failed validation.
        errors: List of validation errors to fix.
        source_schema: Schema info for context.

    Returns:
        CorrectionAttempt with the correction result (success determined by caller).

    Note:
        Requires ANTHROPIC_API_KEY environment variable.
    """
    from datetime import datetime

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Return attempt indicating API key missing
        return CorrectionAttempt(
            attempt_number=1,
            original_template=template,
            validation_errors=errors,
            corrected_template=None,
            changes_made=["ANTHROPIC_API_KEY not set - cannot attempt correction"],
            success=False,
            timestamp=datetime.now(),
        )

    client = Anthropic(api_key=api_key)

    # Build the system prompt
    system_prompt = """You are a Jinja2 template correction expert for UPS shipping payloads.
Your job is to fix validation errors in Jinja2 templates.

RULES:
1. Only change what's necessary to fix the validation errors
2. Keep the existing template structure intact
3. Use the available Jinja2 filters: truncate_address(N), format_us_zip, round_weight(N), convert_weight(from, to), lookup_service_code, to_ups_date, to_ups_phone, default_value(val), split_name(part)
4. Apply default_value BEFORE other transformations to handle None values
5. Return ONLY the corrected template in a ```jinja2 code block
6. Do not add explanations outside the code block"""

    # Format errors and schema
    error_text = format_errors_for_llm(errors)
    schema_text = format_source_schema(source_schema)

    user_message = f"""Fix the following Jinja2 template that failed UPS validation.

{error_text}

{schema_text}

Original template:
```jinja2
{template}
```

Return the corrected template:"""

    response = client.messages.create(
        model=get_model(),
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract the corrected template
    response_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            response_text += block.text

    corrected_template = extract_template_from_response(response_text)

    # Extract changes made (look for explanations in response)
    changes_made = _extract_changes_made(response_text, template, corrected_template)

    return CorrectionAttempt(
        attempt_number=1,  # Will be set by caller
        original_template=template,
        validation_errors=errors,
        corrected_template=corrected_template,
        changes_made=changes_made,
        success=False,  # Determined by caller after validation
        timestamp=datetime.now(),
    )


def _extract_changes_made(
    response_text: str,
    original: str,
    corrected: str,
) -> list[str]:
    """Extract description of changes made from LLM response.

    Args:
        response_text: Full LLM response.
        original: Original template.
        corrected: Corrected template.

    Returns:
        List of change descriptions.
    """
    changes = []

    # Simple diff detection
    if original != corrected:
        # Look for added filters
        filters = [
            "truncate_address",
            "format_us_zip",
            "round_weight",
            "convert_weight",
            "to_ups_phone",
            "to_ups_date",
            "default_value",
            "split_name",
            "lookup_service_code",
        ]
        for f in filters:
            if f in corrected and f not in original:
                changes.append(f"Added {f} filter")

        # Look for default values
        if "default_value" in corrected and "default_value" not in original:
            changes.append("Added default values for null fields")

        # If no specific changes detected
        if not changes:
            changes.append("Template modified to address validation errors")

    return changes


def format_user_feedback(attempt: CorrectionAttempt, max_attempts: int) -> str:
    """Format current attempt status for user display.

    Per CONTEXT.md Decision 4, provides detailed feedback showing
    specific validation errors during correction.

    Args:
        attempt: The current correction attempt.
        max_attempts: Maximum number of attempts allowed.

    Returns:
        Formatted string for user display.

    Example:
        Template validation failed (attempt 2 of 3)
        Error: Field 'ShipTo.Phone.Number' invalid format
        Expected: 10-digit US phone number
        Got: "555-1234" (missing area code)
        Attempting correction...
    """
    lines = [
        f"Template validation failed (attempt {attempt.attempt_number} of {max_attempts})"
    ]

    for error in attempt.validation_errors[:3]:  # Show first 3 errors
        lines.append(f"Error: Field '{error.path}' - {error.message}")
        lines.append(f"  Expected: {error.expected}")
        lines.append(f"  Got: {error.actual!r}")

    if len(attempt.validation_errors) > 3:
        remaining = len(attempt.validation_errors) - 3
        lines.append(f"... and {remaining} more error(s)")

    if attempt.success:
        lines.append("")
        lines.append("Correction successful!")
        if attempt.changes_made:
            lines.append("Changes made:")
            for change in attempt.changes_made:
                lines.append(f"  - {change}")
    else:
        lines.append("")
        lines.append("Attempting correction...")

    return "\n".join(lines)


def self_correction_loop(
    template: str,
    source_schema: list[ColumnInfo],
    target_schema: Optional[dict[str, Any]] = None,
    sample_data: Optional[dict[str, Any]] = None,
    max_attempts: int = 3,
) -> CorrectionResult:
    """Execute the self-correction loop for template validation.

    Attempts to fix template validation errors by iteratively calling
    Claude to correct issues, up to max_attempts times per CONTEXT.md
    Decision 4.

    Args:
        template: The Jinja2 template to validate and correct.
        source_schema: List of column info for context.
        target_schema: Optional JSON Schema for validation (defaults to UPS_SHIPMENT_SCHEMA).
        sample_data: Optional sample row data for rendering test.
        max_attempts: Maximum correction attempts (1-5, default 3).

    Returns:
        CorrectionResult with final template if successful.

    Raises:
        MaxCorrectionsExceeded: If max attempts reached without valid template.

    Example:
        >>> from src.orchestrator.models.filter import ColumnInfo
        >>> schema = [ColumnInfo(name="name", type="string")]
        >>> result = self_correction_loop(
        ...     template='{"ShipTo": {"Name": "{{ name }}"}}',
        ...     source_schema=schema,
        ...     max_attempts=3
        ... )
        >>> result.success  # If template was valid
        True
    """
    from src.orchestrator.filters.logistics import get_logistics_environment
    from src.orchestrator.nl_engine.ups_schema import UPS_SHIPMENT_SCHEMA

    # Clamp max_attempts to 1-5
    max_attempts = max(1, min(5, max_attempts))

    if target_schema is None:
        target_schema = UPS_SHIPMENT_SCHEMA

    result = CorrectionResult(
        final_template=None,
        attempts=[],
        success=False,
        total_attempts=0,
        failure_reason=None,
    )

    current_template = template
    env = get_logistics_environment()

    for attempt_num in range(1, max_attempts + 1):
        # Try to render the template with sample data
        try:
            jinja_template = env.from_string(current_template)

            if sample_data:
                rendered_str = jinja_template.render(**sample_data)
            else:
                # Use empty dict - this will test template syntax only
                # Create mock data from schema
                mock_data = {col.name: f"test_{col.name}" for col in source_schema}
                rendered_str = jinja_template.render(**mock_data)

            # Parse rendered output
            rendered_output = json.loads(rendered_str)

        except json.JSONDecodeError as e:
            # Template renders but output is not valid JSON
            attempt = CorrectionAttempt(
                attempt_number=attempt_num,
                original_template=current_template,
                validation_errors=[
                    ValidationError(
                        path="(root)",
                        message=f"Template output is not valid JSON: {e}",
                        expected="valid JSON object",
                        actual=str(e),
                        schema_rule="json",
                    )
                ],
                corrected_template=None,
                changes_made=[],
                success=False,
            )
            result.attempts.append(attempt)
            result.total_attempts = attempt_num

            # Try to correct
            correction = attempt_correction(
                current_template,
                attempt.validation_errors,
                source_schema,
            )
            correction.attempt_number = attempt_num
            if correction.corrected_template:
                current_template = correction.corrected_template
            continue

        except Exception as e:
            # Template rendering failed
            attempt = CorrectionAttempt(
                attempt_number=attempt_num,
                original_template=current_template,
                validation_errors=[
                    ValidationError(
                        path="(root)",
                        message=f"Template rendering failed: {e}",
                        expected="valid Jinja2 template",
                        actual=str(e),
                        schema_rule="jinja2",
                    )
                ],
                corrected_template=None,
                changes_made=[],
                success=False,
            )
            result.attempts.append(attempt)
            result.total_attempts = attempt_num

            # Try to correct
            correction = attempt_correction(
                current_template,
                attempt.validation_errors,
                source_schema,
            )
            correction.attempt_number = attempt_num
            if correction.corrected_template:
                current_template = correction.corrected_template
            continue

        # Validate rendered output against schema
        validation_result = validate_template_output(rendered_output, target_schema)

        if validation_result.valid:
            # Success!
            attempt = CorrectionAttempt(
                attempt_number=attempt_num,
                original_template=current_template,
                validation_errors=[],
                corrected_template=current_template,
                changes_made=["Template passes validation"],
                success=True,
            )
            result.attempts.append(attempt)
            result.final_template = current_template
            result.success = True
            result.total_attempts = attempt_num
            return result

        # Validation failed - record attempt and try to correct
        attempt = CorrectionAttempt(
            attempt_number=attempt_num,
            original_template=current_template,
            validation_errors=validation_result.errors,
            corrected_template=None,
            changes_made=[],
            success=False,
        )
        result.attempts.append(attempt)
        result.total_attempts = attempt_num

        # Don't try to correct on last attempt
        if attempt_num < max_attempts:
            correction = attempt_correction(
                current_template,
                validation_result.errors,
                source_schema,
            )
            correction.attempt_number = attempt_num
            if correction.corrected_template:
                current_template = correction.corrected_template
                # Update the attempt with correction info
                attempt.corrected_template = correction.corrected_template
                attempt.changes_made = correction.changes_made

    # Max attempts reached without success
    result.failure_reason = (
        f"Self-correction failed after {max_attempts} attempts. "
        "Please review the validation errors and choose an option."
    )

    raise MaxCorrectionsExceeded(
        result=result,
        options=[
            CorrectionOptions.CORRECT_SOURCE,
            CorrectionOptions.MANUAL_FIX,
            CorrectionOptions.SKIP_PROBLEMATIC,
            CorrectionOptions.ABORT,
        ],
        message=result.failure_reason,
    )


__all__ = [
    "format_errors_for_llm",
    "extract_template_from_response",
    "attempt_correction",
    "self_correction_loop",
    "format_user_feedback",
    "MaxCorrectionsExceeded",
]
