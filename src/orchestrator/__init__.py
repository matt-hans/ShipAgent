"""Orchestration Agent for ShipAgent.

This module contains the natural language engine that powers the
ShipAgent orchestration layer.

Main Entry Points:
    NLMappingEngine: Unified engine for processing NL shipping commands.
    process_command: Convenience function for single command processing.

Supporting Models:
    ShippingIntent: Parsed intent from NL command.
    ElicitationQuestion/Response: User clarification interface.
"""

# Intent models
from src.orchestrator.models.intent import (
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    FilterCriteria,
    RowQualifier,
    ServiceCode,
    ShippingIntent,
)

# Filter models
from src.orchestrator.models.filter import (
    ColumnInfo,
    SQLFilterResult,
)

# Elicitation models
from src.orchestrator.models.elicitation import (
    ElicitationContext,
    ElicitationOption,
    ElicitationQuestion,
    ElicitationResponse,
)

# Main engine
from src.orchestrator.nl_engine.engine import (
    CommandResult,
    NLMappingEngine,
    process_command,
)

__all__ = [
    # Main engine (primary entry points)
    "NLMappingEngine",
    "CommandResult",
    "process_command",
    # Intent models
    "ShippingIntent",
    "FilterCriteria",
    "RowQualifier",
    "ServiceCode",
    "SERVICE_ALIASES",
    "CODE_TO_SERVICE",
    # Filter models
    "ColumnInfo",
    "SQLFilterResult",
    # Elicitation models
    "ElicitationQuestion",
    "ElicitationResponse",
    "ElicitationOption",
    "ElicitationContext",
]
