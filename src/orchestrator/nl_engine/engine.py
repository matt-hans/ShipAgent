"""Unified Natural Language Engine for Shipping Commands.

This module provides the NLMappingEngine class that orchestrates Phase 4
components to process natural language shipping commands.

The engine coordinates:
- Intent parsing (NL-01, NL-02)
- SQL filter generation (NL-06)
- Elicitation for ambiguous commands

The LLM acts as a Configuration Engine - it interprets user intent and
generates filters. Column mapping and batch execution are handled by
separate services (ColumnMappingService, BatchEngine).
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

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
from src.orchestrator.nl_engine.elicitation import (
    create_elicitation_context,
    handle_elicitation_response,
    needs_elicitation,
)
from src.orchestrator.nl_engine.filter_generator import generate_filter
from src.orchestrator.nl_engine.intent_parser import IntentParseError, parse_intent


class CommandResult(BaseModel):
    """Result of processing a natural language shipping command.

    Contains all artifacts from the processing pipeline, including
    parsed intent, generated filter, and elicitation questions.

    Attributes:
        command: The original natural language command.
        intent: Parsed ShippingIntent from the command.
        filter_result: Generated SQL filter result (if filter criteria present).
        sql_where: Final SQL WHERE clause (if applicable).
        needs_elicitation: List of questions if clarification is needed.
        success: Whether processing completed successfully.
        error: Error message if processing failed.
    """

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    command: str
    intent: Optional[ShippingIntent] = None
    filter_result: Optional[SQLFilterResult] = None
    sql_where: Optional[str] = None
    needs_elicitation: list[ElicitationQuestion] = []
    success: bool = False
    error: Optional[str] = None


class NLMappingEngine:
    """Unified natural language engine for shipping commands.

    Orchestrates intent parsing, filter generation, and elicitation
    to process natural language shipping commands. Column mapping
    and batch execution are handled by separate services.

    Example:
        >>> engine = NLMappingEngine()
        >>> schema = [ColumnInfo(name="customer_name", type="string"), ...]
        >>> result = await engine.process_command(
        ...     "Ship California orders via Ground",
        ...     source_schema=schema
        ... )
        >>> if result.success:
        ...     print(f"Intent: {result.intent}")
        ...     print(f"SQL: {result.sql_where}")
    """

    def __init__(self) -> None:
        """Initialize the NL Mapping Engine."""
        self._elicitation_responses: dict[str, dict[str, Any]] = {}

    async def process_command(
        self,
        command: str,
        source_schema: list[ColumnInfo],
        available_sources: Optional[list[str]] = None,
    ) -> CommandResult:
        """Process a natural language shipping command.

        This is the main entry point for the NL Mapping Engine. It coordinates
        intent parsing, filter generation, and elicitation.

        Args:
            command: Natural language command like "Ship California orders via Ground".
            source_schema: List of ColumnInfo describing the source data columns.
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

        # Intent + filter are the output; mark success if we have an intent
        if result.intent:
            result.success = True

        return result

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


async def process_command(
    command: str,
    source_schema: list[ColumnInfo],
) -> CommandResult:
    """Convenience function to process a command with default engine settings.

    Creates a new NLMappingEngine instance and processes the command.
    For repeated processing, create an engine instance directly.

    Args:
        command: Natural language command.
        source_schema: Source data schema.

    Returns:
        CommandResult with processing artifacts.
    """
    engine = NLMappingEngine()
    return await engine.process_command(
        command=command,
        source_schema=source_schema,
    )


__all__ = [
    "NLMappingEngine",
    "CommandResult",
    "process_command",
]
