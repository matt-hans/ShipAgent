"""Intent parser for natural language shipping commands.

.. deprecated::
    Use the Claude SDK orchestration path via
    ``/api/v1/conversations/`` endpoints instead.
    Intent parsing is now handled by the agent's unified system
    prompt (``system_prompt.py``) within the SDK agent loop,
    rather than by direct ``Anthropic()`` API calls in this module.

This module parses natural language shipping commands into structured
ShippingIntent objects using Claude's structured outputs feature.

Per CONTEXT.md Decision 1:
- Service aliases (ground, overnight, 2-day) resolve to UPS codes
- Ambiguous commands trigger clarification (never guess)
- Missing information uses elicitation pattern
"""

from datetime import datetime
from typing import Optional

from anthropic import Anthropic

from src.orchestrator.nl_engine.config import get_model
from src.orchestrator.models.intent import (
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    FilterCriteria,
    RowQualifier,
    ServiceCode,
    ShippingIntent,
)


class IntentParseError(Exception):
    """Error raised when intent parsing fails.

    This exception is raised when the LLM cannot parse the user command
    or when the command is too ambiguous to process.

    Attributes:
        message: Human-readable error description.
        original_command: The command that failed to parse.
        suggestions: Optional list of suggested valid commands.
    """

    def __init__(
        self,
        message: str,
        original_command: str,
        suggestions: Optional[list[str]] = None,
    ) -> None:
        """Initialize IntentParseError.

        Args:
            message: Human-readable error description.
            original_command: The command that failed to parse.
            suggestions: Optional list of suggested valid commands.
        """
        self.message = message
        self.original_command = original_command
        self.suggestions = suggestions or []
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error string."""
        result = f"{self.message}\nCommand: {self.original_command}"
        if self.suggestions:
            result += f"\nSuggestions: {', '.join(self.suggestions)}"
        return result


def resolve_service_code(user_input: str) -> ServiceCode:
    """Resolve a user service description to a UPS ServiceCode.

    Handles common aliases like "ground", "overnight", "2-day" and also
    accepts direct UPS service codes like "03", "01".

    Args:
        user_input: User's service description (e.g., "ground", "overnight", "03").

    Returns:
        The corresponding ServiceCode enum value.

    Raises:
        ValueError: If the service is unknown.
    """
    normalized = user_input.lower().strip()

    # Check alias lookup first
    if normalized in SERVICE_ALIASES:
        return SERVICE_ALIASES[normalized]

    # Check direct code (e.g., "03", "01")
    if normalized in CODE_TO_SERVICE:
        return CODE_TO_SERVICE[normalized]

    # List valid options in error message
    valid_aliases = list(SERVICE_ALIASES.keys())
    valid_codes = list(CODE_TO_SERVICE.keys())
    raise ValueError(
        f"Unknown service: '{user_input}'. "
        f"Valid aliases: {', '.join(valid_aliases[:5])}... "
        f"Valid codes: {', '.join(valid_codes)}"
    )


def _build_service_aliases_context() -> str:
    """Build service alias reference for the LLM prompt.

    Returns:
        Formatted string listing all service aliases and their codes.
    """
    # Group aliases by service code
    code_to_aliases: dict[str, list[str]] = {}
    for alias, code in SERVICE_ALIASES.items():
        if code.value not in code_to_aliases:
            code_to_aliases[code.value] = []
        code_to_aliases[code.value].append(alias)

    lines = []
    for code_enum in ServiceCode:
        aliases = code_to_aliases.get(code_enum.value, [])
        lines.append(f"- {code_enum.name} ({code_enum.value}): {', '.join(aliases)}")

    return "\n".join(lines)


def parse_intent(
    user_command: str,
    available_sources: Optional[list[str]] = None,
) -> ShippingIntent:
    """Parse a natural language shipping command into structured intent.

    Uses Claude structured outputs to extract action, data source, service,
    filter criteria, and row qualifiers from the command.

    Args:
        user_command: Natural language command like "Ship California orders via Ground".
        available_sources: Optional list of available data sources to reference.

    Returns:
        Parsed ShippingIntent with extracted fields.

    Raises:
        IntentParseError: If the command cannot be parsed or is too ambiguous.
    """
    if not user_command or not user_command.strip():
        raise IntentParseError(
            message="Command cannot be empty",
            original_command=user_command,
            suggestions=["Ship orders via Ground", "Rate my orders", "Validate addresses"],
        )

    # Build context for the LLM
    service_context = _build_service_aliases_context()
    current_date = datetime.now().strftime("%Y-%m-%d")
    sources_context = (
        f"Available data sources: {', '.join(available_sources)}"
        if available_sources
        else "No data sources currently loaded."
    )

    # System prompt with structured output schema
    system_prompt = f"""You parse natural language shipping commands into structured intents.

CURRENT CONTEXT:
- Current date: {current_date}
- {sources_context}

SERVICE ALIASES (map user terms to UPS codes):
{service_context}

SUPPORTED ACTIONS:
- "ship": Create shipment labels
- "rate": Get shipping quotes
- "validate_address": Validate addresses

FILTER TYPES:
- "state": Geographic filter (e.g., "California orders")
- "date": Temporal filter (e.g., "today's orders", "from this week")
- "numeric": Value-based filter (e.g., "over 5 lbs", "above $100")
- "compound": Multiple conditions (e.g., "California orders over 5 lbs")
- "none": No filter applied

ROW QUALIFIERS:
- "first N": First N rows (e.g., "first 10 orders")
- "last N": Last N rows
- "random N": Random sample of N rows
- "every_nth": Every Nth row (e.g., "every other row" = nth=2)
- "all": All matching rows (default)

INSTRUCTIONS:
1. Extract the action (ship, rate, validate_address) from the command
2. Identify any data source references (file paths, table names)
3. Resolve service descriptions to service_code using the alias list
4. Extract filter criteria and classify the filter type
5. Identify row qualifiers (first N, random sample, etc.)
6. If the command is ambiguous, set needs_clarification=True and explain why

IMPORTANT:
- For service_code, use the enum value (e.g., "03" for ground, "01" for overnight)
- If no service specified, leave service_code as null
- If filter is vague or unclear, set filter_criteria.needs_clarification=True
"""

    user_prompt = f"""Parse this shipping command into structured intent:

"{user_command}"

Extract all relevant fields. If ambiguous, mark needs_clarification=True."""

    # Call Claude with tool use for structured output
    client = Anthropic()

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": "create_shipping_intent",
                    "description": "Create a structured shipping intent from parsed command",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["ship", "rate", "validate_address"],
                                "description": "The shipping action to perform",
                            },
                            "data_source": {
                                "type": "string",
                                "nullable": True,
                                "description": "File path or table reference",
                            },
                            "service_code": {
                                "type": "string",
                                "nullable": True,
                                "description": "UPS service code (03, 01, 02, 12, 13)",
                            },
                            "filter_criteria": {
                                "type": "object",
                                "nullable": True,
                                "properties": {
                                    "raw_expression": {
                                        "type": "string",
                                        "description": "Original filter text",
                                    },
                                    "filter_type": {
                                        "type": "string",
                                        "enum": ["state", "date", "numeric", "compound", "none"],
                                    },
                                    "needs_clarification": {
                                        "type": "boolean",
                                    },
                                    "clarification_reason": {
                                        "type": "string",
                                        "nullable": True,
                                    },
                                },
                                "required": ["raw_expression", "filter_type"],
                            },
                            "row_qualifier": {
                                "type": "object",
                                "nullable": True,
                                "properties": {
                                    "qualifier_type": {
                                        "type": "string",
                                        "enum": ["first", "last", "random", "every_nth", "all"],
                                    },
                                    "count": {
                                        "type": "integer",
                                        "nullable": True,
                                    },
                                    "nth": {
                                        "type": "integer",
                                        "nullable": True,
                                    },
                                },
                                "required": ["qualifier_type"],
                            },
                            "package_defaults": {
                                "type": "object",
                                "nullable": True,
                                "description": "Default package dimensions",
                            },
                        },
                        "required": ["action"],
                    },
                }
            ],
            tool_choice={"type": "tool", "name": "create_shipping_intent"},
        )
    except Exception as e:
        raise IntentParseError(
            message=f"API call failed: {e}",
            original_command=user_command,
        ) from e

    # Extract tool use result
    tool_use = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "create_shipping_intent":
            tool_use = block
            break

    if not tool_use:
        raise IntentParseError(
            message="Failed to parse command into structured intent",
            original_command=user_command,
            suggestions=["Ship orders via Ground", "Rate my orders", "Validate addresses"],
        )

    # Parse the result
    result_data = tool_use.input

    # Build filter criteria if present
    filter_criteria = None
    if result_data.get("filter_criteria"):
        fc = result_data["filter_criteria"]
        filter_criteria = FilterCriteria(
            raw_expression=fc.get("raw_expression", ""),
            filter_type=fc.get("filter_type", "none"),
            needs_clarification=fc.get("needs_clarification", False),
            clarification_reason=fc.get("clarification_reason"),
        )

    # Build row qualifier if present
    row_qualifier = None
    if result_data.get("row_qualifier"):
        rq = result_data["row_qualifier"]
        row_qualifier = RowQualifier(
            qualifier_type=rq.get("qualifier_type", "all"),
            count=rq.get("count"),
            nth=rq.get("nth"),
        )

    # Resolve service code
    service_code = None
    if result_data.get("service_code"):
        try:
            service_code = resolve_service_code(result_data["service_code"])
        except ValueError:
            # If LLM returned an invalid code, try to resolve it
            # This shouldn't happen with the enum constraint, but handle gracefully
            pass

    # Handle package_defaults - LLM sometimes returns "null" string instead of None
    package_defaults = result_data.get("package_defaults")
    if package_defaults == "null" or package_defaults == "None":
        package_defaults = None

    # Build ShippingIntent
    intent = ShippingIntent(
        action=result_data.get("action", "ship"),
        data_source=result_data.get("data_source"),
        service_code=service_code,
        filter_criteria=filter_criteria,
        row_qualifier=row_qualifier,
        package_defaults=package_defaults,
    )

    return intent


__all__ = [
    "parse_intent",
    "resolve_service_code",
    "IntentParseError",
]
