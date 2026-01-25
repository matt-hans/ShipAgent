"""Unified Natural Language to UPS Mapping Engine.

This module provides the NLMappingEngine class that orchestrates all Phase 4
components to process natural language shipping commands end-to-end.

The engine coordinates:
- Intent parsing (NL-01, NL-02)
- SQL filter generation (NL-06)
- Jinja2 template generation (NL-03)
- UPS schema validation (NL-04)
- Self-correction loop (NL-05)
- Elicitation for ambiguous commands

Per CONTEXT.md: The LLM acts as a Configuration Engine - it generates templates
and transformation rules, but deterministic code executes those rules on actual
shipping data.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from src.orchestrator.filters.logistics import get_logistics_environment
from src.orchestrator.models.correction import (
    CorrectionAttempt,
    CorrectionResult,
    MaxCorrectionsExceeded,
)
from src.orchestrator.models.elicitation import (
    ElicitationQuestion,
    ElicitationResponse,
)
from src.orchestrator.models.filter import ColumnInfo, SQLFilterResult
from src.orchestrator.models.intent import (
    FilterCriteria,
    RowQualifier,
    ServiceCode,
    ShippingIntent,
)
from src.orchestrator.models.mapping import FieldMapping, MappingTemplate
from src.orchestrator.nl_engine.elicitation import (
    create_elicitation_context,
    handle_elicitation_response,
    needs_elicitation,
)
from src.orchestrator.nl_engine.filter_generator import generate_filter
from src.orchestrator.nl_engine.intent_parser import IntentParseError, parse_intent
from src.orchestrator.nl_engine.mapping_generator import (
    generate_mapping_template,
    render_template,
    suggest_mappings,
)
from src.orchestrator.nl_engine.self_correction import (
    format_user_feedback,
    self_correction_loop,
)
from src.orchestrator.nl_engine.template_validator import (
    ValidationResult,
    validate_template_output,
)
from src.orchestrator.nl_engine.ups_schema import UPS_SHIPMENT_SCHEMA


class CommandResult(BaseModel):
    """Result of processing a natural language shipping command.

    Contains all artifacts from the processing pipeline, including
    parsed intent, generated filter, mapping template, and validation results.

    Attributes:
        command: The original natural language command.
        intent: Parsed ShippingIntent from the command.
        filter_result: Generated SQL filter result (if filter criteria present).
        sql_where: Final SQL WHERE clause (if applicable).
        mapping_template: Generated Jinja2 mapping template.
        validation_result: Result of template validation against UPS schema.
        corrections_made: List of correction attempts if self-correction ran.
        needs_elicitation: List of questions if clarification is needed.
        success: Whether processing completed successfully.
        error: Error message if processing failed.
    """

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    command: str
    intent: Optional[ShippingIntent] = None
    filter_result: Optional[SQLFilterResult] = None
    sql_where: Optional[str] = None
    mapping_template: Optional[MappingTemplate] = None
    validation_result: Optional[ValidationResult] = None
    corrections_made: list[CorrectionAttempt] = []
    needs_elicitation: list[ElicitationQuestion] = []
    success: bool = False
    error: Optional[str] = None


class NLMappingEngine:
    """Unified natural language to UPS mapping engine.

    Orchestrates intent parsing, filter generation, template mapping,
    validation, self-correction, and elicitation to process natural
    language shipping commands end-to-end.

    Args:
        max_correction_attempts: Maximum self-correction attempts (1-5, default 3).

    Example:
        >>> engine = NLMappingEngine()
        >>> schema = [ColumnInfo(name="customer_name", type="string"), ...]
        >>> result = await engine.process_command(
        ...     "Ship California orders via Ground",
        ...     source_schema=schema
        ... )
        >>> if result.success:
        ...     print(f"SQL: {result.sql_where}")
        ...     print(f"Template: {result.mapping_template.jinja_template}")
    """

    def __init__(self, max_correction_attempts: int = 3) -> None:
        """Initialize the NL Mapping Engine.

        Args:
            max_correction_attempts: Maximum self-correction attempts (1-5, default 3).
        """
        # Clamp to valid range
        self.max_correction_attempts = max(1, min(5, max_correction_attempts))
        self._jinja_env = get_logistics_environment()
        self._elicitation_responses: dict[str, dict[str, Any]] = {}

    async def process_command(
        self,
        command: str,
        source_schema: list[ColumnInfo],
        example_row: Optional[dict[str, Any]] = None,
        user_mappings: Optional[list[FieldMapping]] = None,
        available_sources: Optional[list[str]] = None,
    ) -> CommandResult:
        """Process a natural language shipping command.

        This is the main entry point for the NL Mapping Engine. It coordinates
        all processing steps from intent parsing through validation.

        Args:
            command: Natural language command like "Ship California orders via Ground".
            source_schema: List of ColumnInfo describing the source data columns.
            example_row: Optional example row data for template rendering tests.
            user_mappings: Optional user-confirmed field mappings. If not provided,
                the engine will suggest mappings that require confirmation.
            available_sources: Optional list of available data source names.

        Returns:
            CommandResult with all processing artifacts. Check `success` to determine
            if processing completed, and `needs_elicitation` for any required
            clarification questions.

        Example:
            >>> engine = NLMappingEngine()
            >>> result = await engine.process_command(
            ...     "Ship California orders via Ground",
            ...     source_schema=[ColumnInfo(name="state", type="string"), ...],
            ... )
        """
        result = CommandResult(command=command)

        # Step 1: Parse intent from command
        try:
            result.intent = parse_intent(command, available_sources)
        except IntentParseError as e:
            result.error = f"Failed to parse command: {e.message}"
            return result

        # Step 2: Check if elicitation needed for intent
        elicitation_questions = self._check_elicitation_needed(
            result.intent, None, source_schema
        )
        if elicitation_questions:
            result.needs_elicitation = elicitation_questions
            return result

        # Step 3: Generate SQL filter if filter criteria present
        if result.intent.filter_criteria and result.intent.filter_criteria.raw_expression:
            try:
                result.filter_result = generate_filter(
                    result.intent.filter_criteria.raw_expression,
                    source_schema,
                )
                result.sql_where = result.filter_result.where_clause

                # Check if filter needs clarification
                if result.filter_result.needs_clarification:
                    filter_questions = self._check_elicitation_needed(
                        None, result.filter_result, source_schema
                    )
                    if filter_questions:
                        result.needs_elicitation.extend(filter_questions)
                        return result

            except Exception as e:
                result.error = f"Failed to generate filter: {e}"
                return result

        # Step 4: Generate or validate mapping template
        if user_mappings:
            # User has provided mappings - generate template
            try:
                result.mapping_template = generate_mapping_template(
                    source_schema,
                    user_mappings,
                    template_name=f"command_{id(command)}",
                )
            except Exception as e:
                result.error = f"Failed to generate mapping template: {e}"
                return result
        else:
            # No mappings provided - suggest mappings and require confirmation
            # For now, we indicate that mappings are needed
            result.error = (
                "Field mappings are required. Please provide user_mappings or call "
                "suggest_mappings() to get suggestions that need confirmation."
            )
            return result

        # Step 5: Render template with example row and validate
        if result.mapping_template and result.mapping_template.jinja_template:
            render_data = example_row or self._create_mock_data(source_schema)

            try:
                rendered_output = render_template(result.mapping_template, render_data)
                result.validation_result = validate_template_output(
                    rendered_output, UPS_SHIPMENT_SCHEMA
                )

                # Step 6: Self-correction if validation fails
                if not result.validation_result.valid:
                    try:
                        correction_result = self._run_self_correction(
                            result.mapping_template.jinja_template,
                            source_schema,
                            render_data,
                        )
                        result.corrections_made = correction_result.attempts

                        if correction_result.success and correction_result.final_template:
                            # Update template with corrected version
                            result.mapping_template.jinja_template = correction_result.final_template
                            # Re-validate
                            rendered_output = render_template(result.mapping_template, render_data)
                            result.validation_result = validate_template_output(
                                rendered_output, UPS_SHIPMENT_SCHEMA
                            )

                    except MaxCorrectionsExceeded as e:
                        result.corrections_made = e.result.attempts
                        result.error = (
                            f"Self-correction failed after {e.result.total_attempts} attempts. "
                            "Please review the validation errors."
                        )
                        return result

            except Exception as e:
                result.error = f"Template rendering/validation failed: {e}"
                return result

        # Step 7: Mark success if we have a valid template
        if result.mapping_template and result.validation_result and result.validation_result.valid:
            result.success = True
        elif result.mapping_template:
            # Have template but validation failed
            result.error = "Template validation failed"

        return result

    def render_with_validation(
        self,
        template: MappingTemplate,
        row_data: dict[str, Any],
        target_schema: Optional[dict[str, Any]] = None,
    ) -> tuple[dict[str, Any], ValidationResult]:
        """Render a template with row data and validate the output.

        Convenience method that combines template rendering and validation
        in a single call.

        Args:
            template: MappingTemplate with jinja_template populated.
            row_data: Dictionary of column name -> value from source row.
            target_schema: Optional JSON Schema (defaults to UPS_SHIPMENT_SCHEMA).

        Returns:
            Tuple of (rendered_dict, validation_result).

        Raises:
            MappingGenerationError: If template rendering fails.
        """
        if target_schema is None:
            target_schema = UPS_SHIPMENT_SCHEMA

        rendered = render_template(template, row_data)
        validation = validate_template_output(rendered, target_schema)

        return rendered, validation

    def apply_elicitation_responses(
        self,
        responses: list[ElicitationResponse],
    ) -> dict[str, Any]:
        """Apply user responses to elicitation questions.

        Processes the user's responses and returns resolved values
        that can be used to update the intent or filter.

        Args:
            responses: List of user responses to elicitation questions.

        Returns:
            Dictionary of resolved values to merge into intent/filter.
        """
        resolved: dict[str, Any] = {}

        for response in responses:
            result = handle_elicitation_response(response)
            resolved.update(result)
            # Store for later reference
            self._elicitation_responses[response.question_id] = result

        return resolved

    def _check_elicitation_needed(
        self,
        intent: Optional[ShippingIntent],
        filter_result: Optional[SQLFilterResult],
        source_schema: list[ColumnInfo],
    ) -> list[ElicitationQuestion]:
        """Check if elicitation is needed and build questions.

        Args:
            intent: Parsed shipping intent.
            filter_result: Generated SQL filter result.
            source_schema: Source data schema for customizing questions.

        Returns:
            List of elicitation questions to ask the user.
        """
        template_ids = needs_elicitation(intent=intent, filter_result=filter_result)

        if not template_ids:
            return []

        context = create_elicitation_context(template_ids, source_schema)
        return context.questions

    def _run_self_correction(
        self,
        template: str,
        source_schema: list[ColumnInfo],
        sample_data: dict[str, Any],
    ) -> CorrectionResult:
        """Run the self-correction loop on a template.

        Args:
            template: Jinja2 template string to correct.
            source_schema: Source data schema for context.
            sample_data: Sample row data for rendering tests.

        Returns:
            CorrectionResult with correction attempts and final template.

        Raises:
            MaxCorrectionsExceeded: If max attempts reached without valid template.
        """
        return self_correction_loop(
            template=template,
            source_schema=source_schema,
            target_schema=UPS_SHIPMENT_SCHEMA,
            sample_data=sample_data,
            max_attempts=self.max_correction_attempts,
        )

    def _create_mock_data(self, schema: list[ColumnInfo]) -> dict[str, Any]:
        """Create mock data from schema for template testing.

        Args:
            schema: Source data schema.

        Returns:
            Dictionary with mock values for each column.
        """
        mock_data: dict[str, Any] = {}

        for col in schema:
            col_type = col.type.lower()
            if col_type in ("string", "text", "varchar"):
                mock_data[col.name] = f"test_{col.name}"
            elif col_type in ("integer", "int"):
                mock_data[col.name] = 1
            elif col_type in ("float", "decimal", "number"):
                mock_data[col.name] = 1.0
            elif col_type in ("date", "datetime", "timestamp"):
                mock_data[col.name] = "2026-01-25"
            elif col_type == "boolean":
                mock_data[col.name] = True
            else:
                mock_data[col.name] = f"test_{col.name}"

        return mock_data


async def process_command(
    command: str,
    source_schema: list[ColumnInfo],
    example_row: Optional[dict[str, Any]] = None,
    user_mappings: Optional[list[FieldMapping]] = None,
    max_correction_attempts: int = 3,
) -> CommandResult:
    """Convenience function to process a command with default engine settings.

    Creates a new NLMappingEngine instance and processes the command.
    For repeated processing, create an engine instance directly.

    Args:
        command: Natural language command.
        source_schema: Source data schema.
        example_row: Optional example row for validation.
        user_mappings: Optional user-confirmed field mappings.
        max_correction_attempts: Max self-correction attempts (1-5, default 3).

    Returns:
        CommandResult with processing artifacts.
    """
    engine = NLMappingEngine(max_correction_attempts=max_correction_attempts)
    return await engine.process_command(
        command=command,
        source_schema=source_schema,
        example_row=example_row,
        user_mappings=user_mappings,
    )


__all__ = [
    "NLMappingEngine",
    "CommandResult",
    "process_command",
]
