"""Orchestration layer for ShipAgent.

The orchestration layer uses the Claude Agent SDK as its primary
orchestration engine. The agent's system prompt and deterministic
tools handle intent parsing, filter generation, and batch execution
within the SDK agent loop.

Supporting Models:
    ServiceCode/SERVICE_ALIASES: Canonical UPS service code definitions.
    ElicitationQuestion/Response: User clarification interface.
"""

# Intent models
# Elicitation models
from src.orchestrator.models.elicitation import (
    ElicitationContext,
    ElicitationOption,
    ElicitationQuestion,
    ElicitationResponse,
)

# Filter models
from src.orchestrator.models.filter import (
    ColumnInfo,
    SQLFilterResult,
)
from src.orchestrator.models.intent import (
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    ServiceCode,
)

__all__ = [
    # Intent models
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
