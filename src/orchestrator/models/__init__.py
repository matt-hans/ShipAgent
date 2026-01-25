"""Pydantic models for the Orchestration Agent.

This module exports models used for intent parsing, filter generation,
mapping templates, elicitation, and self-correction tracking.
"""

from src.orchestrator.models.correction import (
    CorrectionAttempt,
    CorrectionOptions,
    CorrectionResult,
    MaxCorrectionsExceeded,
)
from src.orchestrator.models.elicitation import (
    ElicitationContext,
    ElicitationOption,
    ElicitationQuestion,
    ElicitationResponse,
)
from src.orchestrator.models.filter import (
    ColumnInfo,
    FilterGenerationError,
    SQLFilterResult,
)
from src.orchestrator.models.intent import (
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    FilterCriteria,
    RowQualifier,
    ServiceCode,
    ShippingIntent,
)
from src.orchestrator.models.mapping import (
    FieldMapping,
    MappingGenerationError,
    MappingTemplate,
    UPSTargetField,
)

__all__ = [
    # Correction models
    "CorrectionAttempt",
    "CorrectionResult",
    "CorrectionOptions",
    "MaxCorrectionsExceeded",
    # Elicitation models
    "ElicitationContext",
    "ElicitationOption",
    "ElicitationQuestion",
    "ElicitationResponse",
    # Filter models
    "ColumnInfo",
    "SQLFilterResult",
    "FilterGenerationError",
    # Intent models
    "ShippingIntent",
    "FilterCriteria",
    "RowQualifier",
    "ServiceCode",
    "SERVICE_ALIASES",
    "CODE_TO_SERVICE",
    # Mapping models
    "FieldMapping",
    "MappingTemplate",
    "UPSTargetField",
    "MappingGenerationError",
]
