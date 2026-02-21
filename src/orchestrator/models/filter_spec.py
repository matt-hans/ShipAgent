"""FilterSpec data models for deterministic NL-to-SQL compilation.

This module defines the type hierarchy for the FilterSpec compiler pipeline:
FilterIntent (LLM output) → ResolvedFilterSpec (after semantic resolution)
→ CompiledFilter (parameterized SQL). All models are Pydantic v2 for
validation and serialization.

See docs/plans/2026-02-16-filter-determinism-design.md for full architecture.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class FilterOperator(str, Enum):
    """Allowed filter operators — exhaustive. Compiler rejects anything else."""

    eq = "eq"
    neq = "neq"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    in_ = "in"        # Python attribute is `in_` (reserved word); VALUE is "in" (LLM-facing)
    not_in = "not_in"
    contains_ci = "contains_ci"
    starts_with_ci = "starts_with_ci"
    ends_with_ci = "ends_with_ci"
    is_null = "is_null"
    is_not_null = "is_not_null"
    is_blank = "is_blank"
    is_not_blank = "is_not_blank"
    between = "between"


class ResolutionStatus(str, Enum):
    """Status of semantic resolution."""

    RESOLVED = "RESOLVED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    UNRESOLVED = "UNRESOLVED"


class FilterErrorCode(str, Enum):
    """Deterministic error codes for filter compilation failures."""

    UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
    UNKNOWN_CANONICAL_TERM = "UNKNOWN_CANONICAL_TERM"
    AMBIGUOUS_TERM = "AMBIGUOUS_TERM"
    INVALID_OPERATOR = "INVALID_OPERATOR"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    MISSING_TARGET_COLUMN = "MISSING_TARGET_COLUMN"
    INVALID_ARITY = "INVALID_ARITY"
    MISSING_OPERAND = "MISSING_OPERAND"
    EMPTY_IN_LIST = "EMPTY_IN_LIST"
    TOKEN_INVALID_OR_EXPIRED = "TOKEN_INVALID_OR_EXPIRED"
    TOKEN_HASH_MISMATCH = "TOKEN_HASH_MISMATCH"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    STRUCTURAL_LIMIT_EXCEEDED = "STRUCTURAL_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Structural limits
# ---------------------------------------------------------------------------

STRUCTURAL_LIMITS: dict[str, int] = {
    "max_depth": 4,
    "max_conditions": 50,
    "max_in_cardinality": 100,
    "max_total_params": 500,
}


# ---------------------------------------------------------------------------
# Typed literals
# ---------------------------------------------------------------------------

class TypedLiteral(BaseModel):
    """A value with an explicit type tag for deterministic coercion."""

    type: Literal["string", "number", "boolean", "date"] = Field(
        ..., description="Type tag for the literal value."
    )
    value: Any = Field(..., description="The literal value.")


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------

class FilterCondition(BaseModel):
    """A direct column filter condition."""

    column: str = Field(..., description="Column name to filter on.")
    operator: FilterOperator = Field(..., description="Comparison operator.")
    operands: list[TypedLiteral] = Field(
        default_factory=list,
        description="Typed operand values. Count must match operator arity.",
    )


class SemanticReference(BaseModel):
    """A reference to a canonical term that the resolver expands."""

    semantic_key: str = Field(
        ..., description="Canonical key (e.g., 'NORTHEAST', 'BUSINESS_RECIPIENT')."
    )
    target_column: str = Field(
        ..., description="Which column to apply the expansion to."
    )


class FilterGroup(BaseModel):
    """A logical group of conditions joined by AND/OR."""

    logic: Literal["AND", "OR"] = Field(
        ..., description="Logical operator joining conditions."
    )
    conditions: list[FilterCondition | SemanticReference | FilterGroup] = Field(
        ..., description="Child conditions, semantic references, or nested groups."
    )


# Rebuild for forward reference resolution
FilterGroup.model_rebuild()


# ---------------------------------------------------------------------------
# Top-level intent and envelope
# ---------------------------------------------------------------------------

class FilterIntent(BaseModel):
    """Structured filter intent produced by the LLM (never SQL)."""

    root: FilterGroup = Field(..., description="Root filter group.")
    service_code: str | None = Field(
        default=None, description="Optional UPS service code."
    )
    schema_signature: str = Field(
        default="", description="Schema hash for staleness detection."
    )


class FilterSpecEnvelope(BaseModel):
    """Metadata wrapper for a filter spec."""

    schema_signature: str = Field(..., description="Hash of the current schema.")
    canonical_dict_version: str = Field(
        ..., description="Version of the canonical dictionaries used."
    )
    locale: str = Field(default="en-US", description="Locale for normalization.")
    source_id: str = Field(default="", description="Data source identifier.")


# ---------------------------------------------------------------------------
# Resolution output
# ---------------------------------------------------------------------------

class PendingConfirmation(BaseModel):
    """A Tier B term awaiting user confirmation."""

    term: str = Field(..., description="The semantic term.")
    expansion: str = Field(..., description="Human-readable expansion description.")
    tier: str = Field(default="B", description="Ambiguity tier.")


class UnresolvedTerm(BaseModel):
    """A Tier C term that could not be resolved."""

    phrase: str = Field(..., description="The unresolved phrase.")
    suggestions: list[dict[str, str]] = Field(
        default_factory=list,
        description="Candidate suggestions [{key, expansion}].",
    )


class ResolvedFilterSpec(BaseModel):
    """Output of the semantic resolver — all references expanded."""

    status: ResolutionStatus = Field(..., description="Resolution status.")
    root: FilterGroup = Field(
        ..., description="Resolved AST (SemanticReferences replaced)."
    )
    explanation: str = Field(
        default="", description="Human-readable explanation."
    )
    resolution_token: str | None = Field(
        default=None, description="HMAC-signed token for Tier B confirmation."
    )
    pending_confirmations: list[PendingConfirmation] | None = Field(
        default=None, description="Tier B terms awaiting confirmation."
    )
    unresolved_terms: list[UnresolvedTerm] | None = Field(
        default=None, description="Tier C terms with suggestions."
    )
    schema_signature: str = Field(
        default="", description="Schema hash at resolution time."
    )
    canonical_dict_version: str = Field(
        default="", description="Dict version at resolution time."
    )
    source_fingerprint: str = Field(
        default="",
        description="Deterministic source fingerprint bound at resolution time.",
    )
    compiler_version: str = Field(
        default="",
        description="Compiler version bound at resolution time.",
    )
    mapping_version: str = Field(
        default="",
        description="Mapping cache/rules version bound at resolution time.",
    )
    normalizer_version: str = Field(
        default="",
        description="Row normalization version bound at resolution time.",
    )


# ---------------------------------------------------------------------------
# Compilation output
# ---------------------------------------------------------------------------

class CompiledFilter(BaseModel):
    """Output of the SQL compiler — parameterized query ready for DuckDB."""

    where_sql: str = Field(
        ..., description="Parameterized WHERE clause ($1, $2, ...)."
    )
    params: list[Any] = Field(
        default_factory=list, description="Positional parameter values."
    )
    columns_used: list[str] = Field(
        default_factory=list, description="Columns referenced in the query."
    )
    explanation: str = Field(
        default="", description="Human-readable filter explanation."
    )
    schema_signature: str = Field(
        default="", description="Schema hash at compile time."
    )


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class FilterCompilationError(Exception):
    """Deterministic error raised during filter resolution or compilation."""

    def __init__(self, code: FilterErrorCode, message: str) -> None:
        """Initialize with a deterministic error code and message.

        Args:
            code: The specific error code from FilterErrorCode enum.
            message: Human-readable description of the failure.
        """
        self.code = code
        self.message = message
        super().__init__(f"[{code.value}] {message}")
