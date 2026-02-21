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
from src.orchestrator.models.filter_spec import (
    STRUCTURAL_LIMITS,
    CompiledFilter,
    FilterCompilationError,
    FilterCondition,
    FilterErrorCode,
    FilterGroup,
    FilterIntent,
    FilterOperator,
    FilterSpecEnvelope,
    PendingConfirmation,
    ResolutionStatus,
    ResolvedFilterSpec,
    SemanticReference,
    TypedLiteral,
    UnresolvedTerm,
)
from src.orchestrator.models.intent import (
    CODE_TO_SERVICE,
    SERVICE_ALIASES,
    ServiceCode,
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
    "ServiceCode",
    "SERVICE_ALIASES",
    "CODE_TO_SERVICE",
    # FilterSpec models
    "CompiledFilter",
    "FilterCompilationError",
    "FilterCondition",
    "FilterErrorCode",
    "FilterGroup",
    "FilterIntent",
    "FilterOperator",
    "FilterSpecEnvelope",
    "PendingConfirmation",
    "ResolvedFilterSpec",
    "ResolutionStatus",
    "SemanticReference",
    "TypedLiteral",
    "UnresolvedTerm",
    "STRUCTURAL_LIMITS",
    # Mapping models
    "FieldMapping",
    "MappingTemplate",
    "UPSTargetField",
    "MappingGenerationError",
]
