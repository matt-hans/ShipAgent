"""Natural Language Engine for parsing shipping commands.

This module provides intent parsing, filter generation, and
elicitation using Claude's structured outputs.

The main entry point is the NLMappingEngine class which orchestrates
all components to process natural language shipping commands end-to-end.
"""

from src.orchestrator.nl_engine.elicitation import (
    ELICITATION_TEMPLATES,
    create_elicitation_context,
    create_elicitation_question,
    handle_elicitation_response,
    needs_elicitation,
)
from src.orchestrator.nl_engine.filter_generator import (
    FilterGenerationError,
    generate_filter,
    validate_sql_syntax,
)
from src.orchestrator.nl_engine.intent_parser import (
    IntentParseError,
    parse_intent,
    resolve_service_code,
)

# Import engine last to ensure all dependencies are loaded
from src.orchestrator.nl_engine.engine import (
    CommandResult,
    NLMappingEngine,
    process_command,
)

__all__ = [
    # Engine (main entry point)
    "NLMappingEngine",
    "CommandResult",
    "process_command",
    # Elicitation
    "ELICITATION_TEMPLATES",
    "create_elicitation_question",
    "handle_elicitation_response",
    "needs_elicitation",
    "create_elicitation_context",
    # Intent parsing
    "parse_intent",
    "resolve_service_code",
    "IntentParseError",
    # Filter generation
    "generate_filter",
    "validate_sql_syntax",
    "FilterGenerationError",
]
