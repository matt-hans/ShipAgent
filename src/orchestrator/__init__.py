"""Orchestration layer for ShipAgent.

The orchestration layer uses the Claude Agent SDK as its primary
orchestration engine. The agent's system prompt and deterministic
tools handle intent parsing, filter generation, and batch execution
within the SDK agent loop.

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

__all__ = [
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
