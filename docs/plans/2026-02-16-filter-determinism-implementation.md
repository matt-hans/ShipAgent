# FilterSpec Compiler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace non-deterministic free-form SQL filter generation with a structured FilterSpec JSON compiler that guarantees identical queries for identical inputs.

**Scope:** This plan covers the full deterministic shipment lifecycle — from user intent to row selection (Phases 1-7: FilterSpec compiler) through crash-safe execution with exactly-once semantics (Phase 8: idempotency, in-flight state, replay-safe retries, durable write-back).

**Architecture:** The LLM outputs typed `FilterIntent` JSON (never SQL). A pure-function semantic resolver expands canonical terms (regions, business predicates) into concrete conditions. A pure-function SQL compiler produces parameterized DuckDB queries. Hook-level enforcement denies any raw SQL bypass.

**Tech Stack:** Python 3.12+, Pydantic v2, DuckDB parameterized queries, HMAC (stdlib `hmac`), FastMCP, React + TypeScript (frontend)

**Design Reference:** `docs/plans/2026-02-16-filter-determinism-design.md`

**Cutover Strategy: HARD CUTOVER — NO LEGACY PATH.** There is no dual-path migration. The `where_clause` parameter is removed from all tool definitions and handlers in the same commit that adds `filter_spec`. The `validate_filter_syntax` tool is deleted, not stubbed. Hook enforcement denies raw SQL from day one. All determinism is structural (server-side compiler owns SQL generation) — never prompt-dependent. This is a clean break.

---

## Architectural Invariants

These invariants are **non-negotiable** and must hold at every commit boundary:

1. **No raw SQL in tool contracts.** The `where_clause`, `sql`, `query`, and `raw_sql` keys do not exist in any orchestrator tool input schema. The LLM produces `FilterIntent` JSON — never SQL.
2. **Server-side compiler is sole SQL authority.** `compile_filter_spec()` is the only function that generates SQL. It produces parameterized queries (`$1, $2, ...`). No f-string interpolation of user-influenced values into SQL anywhere.
3. **All parameterized execution, always.** DuckDB `db.execute(sql, params)` is the only query path. Even an empty params list `[]` uses the parameterized path. There is no "raw path" fallback.
4. **Determinism is structurally guaranteed.** Identical `FilterIntent` + identical schema → identical `CompiledFilter` (same `where_sql`, same `params`, same `compiled_hash`). This is enforced by canonicalization (sorted children, sorted IN-lists) and tested by hash-invariant acceptance tests. The `compiled_hash` is computed from the canonical JSON of the exact execution payload (`{"where_sql": ..., "params": [...]}`), preserving parameter order — never from sorted params.
5. **Ambiguity policy is product behavior, not best-effort.** Tier A: auto-expand, zero confirmation. Tier B: expand + mandatory confirmation — no execution without explicit user approval. Tier C: clarification with 2-3 options — no execution, no silent interpretation, no fallback.
6. **Token secret is required, not optional.** `FILTER_TOKEN_SECRET` env var must be set. No random fallback. Tokens must be verifiable across process restarts within their TTL. Validation happens at two levels: (a) FastAPI `lifespan` startup calls `validate_filter_config()` for fail-fast on server boot; (b) `_get_token_secret()` lazy getter raises `FilterConfigError` on first use if still missing. **Not** validated at module import time — import-time errors are too brittle and break unrelated test paths.
7. **Interactive mode does not use FilterSpec.** Interactive shipping uses conversational collection, not data source filtering. `resolve_filter_intent` is a batch-mode-only tool. Interactive mode's tool allowlist is unchanged.
8. **No implicit all-rows.** Omitting `filter_spec` does NOT default to all rows. The caller must explicitly pass `all_rows=true` to bypass filtering. Even then, the existing preview confirmation gate applies — there is no path to autonomous execution of all rows. This prevents accidental broadened execution if the resolver fails upstream.

---

## Phase 1: Foundation — Data Models, Constants, Error Codes

These are leaf modules with zero internal dependencies. Build them first so everything else can import from them.

---

### Task 1: FilterSpec Pydantic Models

**Files:**
- Create: `src/orchestrator/models/filter_spec.py`
- Modify: `src/orchestrator/models/__init__.py`
- Test: `tests/orchestrator/models/test_filter_spec.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/models/test_filter_spec.py`:

```python
"""Tests for FilterSpec Pydantic models."""

import pytest
from pydantic import ValidationError


class TestFilterOperator:
    """Tests for the FilterOperator enum."""

    def test_all_sixteen_operators_exist(self):
        from src.orchestrator.models.filter_spec import FilterOperator

        expected = {
            "eq", "neq", "gt", "gte", "lt", "lte",
            "in", "not_in", "contains_ci", "starts_with_ci", "ends_with_ci",
            "is_null", "is_not_null", "is_blank", "is_not_blank", "between",
        }
        assert {op.value for op in FilterOperator} == expected

    def test_operator_is_str_enum(self):
        from src.orchestrator.models.filter_spec import FilterOperator

        assert isinstance(FilterOperator.eq, str)


class TestResolutionStatus:
    """Tests for the ResolutionStatus enum."""

    def test_three_statuses(self):
        from src.orchestrator.models.filter_spec import ResolutionStatus

        assert {s.value for s in ResolutionStatus} == {
            "RESOLVED", "NEEDS_CONFIRMATION", "UNRESOLVED",
        }


class TestFilterErrorCode:
    """Tests for the FilterErrorCode enum."""

    def test_all_fourteen_error_codes(self):
        from src.orchestrator.models.filter_spec import FilterErrorCode

        assert len(FilterErrorCode) == 14


class TestTypedLiteral:
    """Tests for the TypedLiteral model."""

    def test_string_literal(self):
        from src.orchestrator.models.filter_spec import TypedLiteral

        lit = TypedLiteral(type="string", value="CA")
        assert lit.type == "string"
        assert lit.value == "CA"

    def test_number_literal(self):
        from src.orchestrator.models.filter_spec import TypedLiteral

        lit = TypedLiteral(type="number", value=5.0)
        assert lit.type == "number"

    def test_boolean_literal(self):
        from src.orchestrator.models.filter_spec import TypedLiteral

        lit = TypedLiteral(type="boolean", value=True)
        assert lit.type == "boolean"

    def test_invalid_type_rejected(self):
        from src.orchestrator.models.filter_spec import TypedLiteral

        with pytest.raises(ValidationError):
            TypedLiteral(type="invalid", value="x")


class TestFilterCondition:
    """Tests for the FilterCondition model."""

    def test_basic_eq_condition(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterOperator, TypedLiteral,
        )

        cond = FilterCondition(
            column="state",
            operator=FilterOperator.eq,
            operands=[TypedLiteral(type="string", value="CA")],
        )
        assert cond.column == "state"
        assert cond.operator == FilterOperator.eq
        assert len(cond.operands) == 1

    def test_in_condition_multiple_operands(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterOperator, TypedLiteral,
        )

        cond = FilterCondition(
            column="state",
            operator=FilterOperator.in_,
            operands=[
                TypedLiteral(type="string", value="CA"),
                TypedLiteral(type="string", value="NY"),
            ],
        )
        assert len(cond.operands) == 2

    def test_is_null_zero_operands(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterOperator,
        )

        cond = FilterCondition(
            column="company",
            operator=FilterOperator.is_null,
            operands=[],
        )
        assert len(cond.operands) == 0


class TestSemanticReference:
    """Tests for the SemanticReference model."""

    def test_region_reference(self):
        from src.orchestrator.models.filter_spec import SemanticReference

        ref = SemanticReference(
            semantic_key="NORTHEAST",
            target_column="state",
        )
        assert ref.semantic_key == "NORTHEAST"
        assert ref.target_column == "state"


class TestFilterGroup:
    """Tests for the FilterGroup model."""

    def test_and_group_with_conditions(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterGroup, FilterOperator, TypedLiteral,
        )

        group = FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="state",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value="CA")],
                ),
            ],
        )
        assert group.logic == "AND"
        assert len(group.conditions) == 1

    def test_nested_group(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterGroup, FilterOperator, TypedLiteral,
        )

        inner = FilterGroup(
            logic="OR",
            conditions=[
                FilterCondition(
                    column="state",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value="CA")],
                ),
                FilterCondition(
                    column="state",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value="NY")],
                ),
            ],
        )
        outer = FilterGroup(logic="AND", conditions=[inner])
        assert len(outer.conditions) == 1


class TestFilterIntent:
    """Tests for the FilterIntent model."""

    def test_full_intent(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterGroup, FilterIntent, FilterOperator,
            TypedLiteral,
        )

        intent = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="CA")],
                    ),
                ],
            ),
            service_code="02",
            schema_signature="abc123",
        )
        assert intent.service_code == "02"


class TestResolvedFilterSpec:
    """Tests for the ResolvedFilterSpec model."""

    def test_resolved_spec(self):
        from src.orchestrator.models.filter_spec import (
            FilterCondition, FilterGroup, FilterOperator,
            ResolvedFilterSpec, ResolutionStatus, TypedLiteral,
        )

        spec = ResolvedFilterSpec(
            status=ResolutionStatus.RESOLVED,
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.in_,
                        operands=[TypedLiteral(type="string", value="NY")],
                    ),
                ],
            ),
            explanation="State is NY",
            schema_signature="abc123",
            canonical_dict_version="filter_constants_v1",
        )
        assert spec.status == ResolutionStatus.RESOLVED


class TestCompiledFilter:
    """Tests for the CompiledFilter model."""

    def test_compiled_output(self):
        from src.orchestrator.models.filter_spec import CompiledFilter

        cf = CompiledFilter(
            where_sql='"state" = $1',
            params=["CA"],
            columns_used=["state"],
            explanation="State is CA",
            schema_signature="abc123",
        )
        assert cf.where_sql == '"state" = $1'
        assert cf.params == ["CA"]


class TestFilterCompilationError:
    """Tests for the FilterCompilationError exception."""

    def test_error_carries_code(self):
        from src.orchestrator.models.filter_spec import (
            FilterCompilationError, FilterErrorCode,
        )

        err = FilterCompilationError(
            code=FilterErrorCode.UNKNOWN_COLUMN,
            message="Column 'foo' not in schema",
        )
        assert err.code == FilterErrorCode.UNKNOWN_COLUMN
        assert "foo" in str(err)


class TestStructuralLimits:
    """Tests for the STRUCTURAL_LIMITS constant."""

    def test_defaults(self):
        from src.orchestrator.models.filter_spec import STRUCTURAL_LIMITS

        assert STRUCTURAL_LIMITS["max_depth"] == 4
        assert STRUCTURAL_LIMITS["max_conditions"] == 50
        assert STRUCTURAL_LIMITS["max_in_cardinality"] == 100
        assert STRUCTURAL_LIMITS["max_total_params"] == 500
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/models/test_filter_spec.py -v`
Expected: FAIL with `ModuleNotFoundError` — the module doesn't exist yet.

**Step 3: Write the implementation**

Create `src/orchestrator/models/filter_spec.py`:

```python
"""FilterSpec data models for deterministic NL-to-SQL compilation.

This module defines the type hierarchy for the FilterSpec compiler pipeline:
FilterIntent (LLM output) → ResolvedFilterSpec (after semantic resolution)
→ CompiledFilter (parameterized SQL). All models are Pydantic v2 for
validation and serialization.

See docs/plans/2026-02-16-filter-determinism-design.md for full architecture.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Union

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
    conditions: list[Union[FilterCondition, SemanticReference, "FilterGroup"]] = Field(
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
```

**Step 4: Update the models `__init__.py` to export new types**

Add to `src/orchestrator/models/__init__.py`:

```python
from src.orchestrator.models.filter_spec import (
    CompiledFilter,
    FilterCompilationError,
    FilterCondition,
    FilterErrorCode,
    FilterGroup,
    FilterIntent,
    FilterOperator,
    FilterSpecEnvelope,
    PendingConfirmation,
    ResolvedFilterSpec,
    ResolutionStatus,
    SemanticReference,
    TypedLiteral,
    UnresolvedTerm,
    STRUCTURAL_LIMITS,
)
```

And add the names to the `__all__` list.

**Step 5: Run tests to verify they pass**

Run: `pytest tests/orchestrator/models/test_filter_spec.py -v`
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/orchestrator/models/filter_spec.py src/orchestrator/models/__init__.py tests/orchestrator/models/test_filter_spec.py
git commit -m "feat: add FilterSpec Pydantic models for deterministic filter pipeline"
```

---

### Task 2: Canonical Constants Module

**Files:**
- Create: `src/services/filter_constants.py`
- Test: `tests/services/test_filter_constants.py`

**Step 1: Write the failing test**

Create `tests/services/test_filter_constants.py`:

```python
"""Tests for filter canonical constants."""

import pytest


class TestRegions:
    """Tests for US region maps."""

    def test_all_us_has_52_entries(self):
        """50 states + DC + PR."""
        from src.services.filter_constants import REGIONS

        assert len(REGIONS["ALL_US"]) == 52

    def test_northeast_states(self):
        from src.services.filter_constants import REGIONS

        assert set(REGIONS["NORTHEAST"]) == {
            "NY", "MA", "CT", "PA", "NJ", "ME", "NH", "RI", "VT",
        }

    def test_dc_in_mid_atlantic_only(self):
        """DC is in MID_ATLANTIC and ALL_US but no other region."""
        from src.services.filter_constants import REGIONS

        for name, states in REGIONS.items():
            if name in ("MID_ATLANTIC", "ALL_US"):
                assert "DC" in states, f"DC missing from {name}"
            else:
                assert "DC" not in states, f"DC should not be in {name}"

    def test_pr_in_all_us_only(self):
        from src.services.filter_constants import REGIONS

        for name, states in REGIONS.items():
            if name == "ALL_US":
                assert "PR" in states
            else:
                assert "PR" not in states, f"PR should not be in {name}"

    def test_no_duplicate_states_within_region(self):
        from src.services.filter_constants import REGIONS

        for name, states in REGIONS.items():
            assert len(states) == len(set(states)), f"Duplicates in {name}"

    def test_all_region_states_are_in_all_us(self):
        from src.services.filter_constants import REGIONS

        all_us = set(REGIONS["ALL_US"])
        for name, states in REGIONS.items():
            for state in states:
                assert state in all_us, f"{state} in {name} but not ALL_US"


class TestRegionAliases:
    """Tests for NL → canonical key aliases."""

    def test_northeast_aliases(self):
        from src.services.filter_constants import REGION_ALIASES

        assert REGION_ALIASES["northeast"] == "NORTHEAST"
        assert REGION_ALIASES["the northeast"] == "NORTHEAST"

    def test_the_south_not_in_aliases(self):
        """'the south' is Tier C — deliberately excluded."""
        from src.services.filter_constants import REGION_ALIASES

        assert "the south" not in REGION_ALIASES


class TestBusinessPredicates:
    """Tests for business predicate definitions."""

    def test_business_recipient_exists(self):
        from src.services.filter_constants import BUSINESS_PREDICATES

        pred = BUSINESS_PREDICATES["BUSINESS_RECIPIENT"]
        assert "company" in pred["target_column_patterns"]
        assert pred["expansion"] == "is_not_blank"

    def test_personal_recipient_exists(self):
        from src.services.filter_constants import BUSINESS_PREDICATES

        pred = BUSINESS_PREDICATES["PERSONAL_RECIPIENT"]
        assert pred["expansion"] == "is_blank"


class TestAmbiguityTiers:
    """Tests for tier classification."""

    def test_state_abbreviations_are_tier_a(self):
        from src.services.filter_constants import get_tier

        assert get_tier("california") == "A"

    def test_regions_are_tier_b(self):
        from src.services.filter_constants import get_tier

        assert get_tier("northeast") == "B"

    def test_business_predicates_are_tier_b(self):
        from src.services.filter_constants import get_tier

        assert get_tier("BUSINESS_RECIPIENT") == "B"

    def test_unknown_term_is_tier_c(self):
        from src.services.filter_constants import get_tier

        assert get_tier("the south") == "C"
        assert get_tier("random_garbage") == "C"


class TestNormalization:
    """Tests for the normalize_term function."""

    def test_casefold(self):
        from src.services.filter_constants import normalize_term

        assert normalize_term("NORTHEAST") == "northeast"

    def test_strip_hyphens(self):
        from src.services.filter_constants import normalize_term

        assert normalize_term("Mid-Atlantic") == "mid atlantic"

    def test_strip_extra_spaces(self):
        from src.services.filter_constants import normalize_term

        assert normalize_term("  the   northeast  ") == "the northeast"


class TestColumnPatternMatching:
    """Tests for match_column_pattern."""

    def test_exact_match(self):
        from src.services.filter_constants import match_column_pattern

        result = match_column_pattern(
            patterns=["company", "company_name"],
            schema_columns={"company", "state", "city"},
        )
        assert result == ["company"]

    def test_no_match_returns_empty(self):
        from src.services.filter_constants import match_column_pattern

        result = match_column_pattern(
            patterns=["company", "company_name"],
            schema_columns={"state", "city"},
        )
        assert result == []

    def test_multiple_matches(self):
        from src.services.filter_constants import match_column_pattern

        result = match_column_pattern(
            patterns=["company", "company_name"],
            schema_columns={"company", "company_name", "state"},
        )
        assert set(result) == {"company", "company_name"}


class TestDictVersion:
    """Tests for the canonical dict version."""

    def test_version_format(self):
        from src.services.filter_constants import CANONICAL_DICT_VERSION

        assert CANONICAL_DICT_VERSION.startswith("filter_constants_v")


class TestStateAbbreviations:
    """Tests for state abbreviation lookup."""

    def test_california_resolves(self):
        from src.services.filter_constants import STATE_ABBREVIATIONS

        assert STATE_ABBREVIATIONS["california"] == "CA"

    def test_new_york_resolves(self):
        from src.services.filter_constants import STATE_ABBREVIATIONS

        assert STATE_ABBREVIATIONS["new york"] == "NY"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_filter_constants.py -v`
Expected: FAIL with `ModuleNotFoundError`.

**Step 3: Write the implementation**

Create `src/services/filter_constants.py` with all region maps, aliases, business predicates, state abbreviations, tier classification, normalization, and column pattern matching functions. Follow the pattern of `ups_constants.py` — a single canonical module, many consumers.

The file should contain:
- `REGIONS` dict with all 10 region keys (NORTHEAST, NEW_ENGLAND, MID_ATLANTIC, SOUTHEAST, MIDWEST, SOUTHWEST, WEST, WEST_COAST, PACIFIC, ALL_US with 52 entries)
- `REGION_ALIASES` dict mapping NL phrases to canonical keys
- `STATE_ABBREVIATIONS` dict mapping full state names (casefolded) to 2-letter codes
- `BUSINESS_PREDICATES` dict with BUSINESS_RECIPIENT and PERSONAL_RECIPIENT
- `CANONICAL_DICT_VERSION = "filter_constants_v1"`
- `normalize_term(term: str) -> str` — casefold + strip hyphens + collapse whitespace
- `get_tier(term: str) -> str` — returns "A", "B", or "C"
- `match_column_pattern(patterns: list[str], schema_columns: set[str]) -> list[str]`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_filter_constants.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/services/filter_constants.py tests/services/test_filter_constants.py
git commit -m "feat: add canonical filter constants module (regions, predicates, tiers)"
```

---

### Task 3: Register Filter Error Codes

**Files:**
- Modify: `src/errors/registry.py`
- Test: `tests/errors/test_filter_error_codes.py`

**Step 1: Write the failing test**

Create `tests/errors/test_filter_error_codes.py`:

```python
"""Tests for filter-specific error codes in the registry."""


class TestFilterErrorCodes:
    """Verify E-2030 through E-2043 are registered."""

    def test_unknown_column_registered(self):
        from src.errors.registry import get_error

        err = get_error("E-2030")
        assert err is not None
        assert err.title == "Unknown Filter Column"

    def test_unknown_canonical_term_registered(self):
        from src.errors.registry import get_error

        err = get_error("E-2031")
        assert err is not None
        assert "Canonical Term" in err.title

    def test_all_fourteen_codes_registered(self):
        from src.errors.registry import get_error

        for code_num in range(2030, 2044):
            code = f"E-{code_num}"
            assert get_error(code) is not None, f"{code} not registered"

    def test_codes_are_validation_category(self):
        from src.errors.registry import ErrorCategory, get_error

        for code_num in range(2030, 2044):
            err = get_error(f"E-{code_num}")
            assert err.category == ErrorCategory.VALIDATION
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/errors/test_filter_error_codes.py -v`
Expected: FAIL — `E-2030` not found in registry.

**Step 3: Add error codes to registry**

Add 14 new `ErrorCode` entries to `src/errors/registry.py` in the `ERROR_REGISTRY` dict, using codes `E-2030` through `E-2043`. Each maps to one `FilterErrorCode` enum value from `filter_spec.py`:

| Code | Title | Maps to |
|------|-------|---------|
| E-2030 | Unknown Filter Column | UNKNOWN_COLUMN |
| E-2031 | Unknown Canonical Term | UNKNOWN_CANONICAL_TERM |
| E-2032 | Ambiguous Filter Term | AMBIGUOUS_TERM |
| E-2033 | Invalid Filter Operator | INVALID_OPERATOR |
| E-2034 | Filter Type Mismatch | TYPE_MISMATCH |
| E-2035 | Schema Changed During Filter | SCHEMA_CHANGED |
| E-2036 | Missing Target Column | MISSING_TARGET_COLUMN |
| E-2037 | Invalid Operator Arity | INVALID_ARITY |
| E-2038 | Missing Filter Operand | MISSING_OPERAND |
| E-2039 | Empty IN List | EMPTY_IN_LIST |
| E-2040 | Filter Token Invalid | TOKEN_INVALID_OR_EXPIRED |
| E-2041 | Filter Token Mismatch | TOKEN_HASH_MISMATCH |
| E-2042 | Filter Confirmation Required | CONFIRMATION_REQUIRED |
| E-2043 | Filter Structural Limit | STRUCTURAL_LIMIT_EXCEEDED |

Insert them after the `E-2023` block and before `E-3001`, with a comment header `# FilterSpec compiler errors (E-2030 – E-2043)`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/errors/test_filter_error_codes.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/errors/registry.py tests/errors/test_filter_error_codes.py
git commit -m "feat: register E-2030–E-2043 filter compiler error codes"
```

---

## Phase 2: Core Engine — Semantic Resolver and SQL Compiler

These are pure functions with no side effects. They depend only on Phase 1 models and constants.

---

### Task 4: SQL Compiler

**Files:**
- Create: `src/orchestrator/filter_compiler.py`
- Test: `tests/orchestrator/test_filter_compiler.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/test_filter_compiler.py` with tests covering:

1. **Single `eq` condition** — produces `"state" = $1` with params `["CA"]`
2. **`in_` condition** — produces `"state" IN ($1, $2, $3)` with sorted params
3. **`is_null` condition** — produces `"company" IS NULL` with no params
4. **`is_blank` condition** — produces `("company" IS NULL OR "company" = $1)` with param `""`
5. **`is_not_blank` condition** — produces `("company" IS NOT NULL AND "company" != $1)`
6. **`contains_ci` condition** — produces `"name" ILIKE $1 ESCAPE '\'` with param `%val%` (escaped)
7. **`starts_with_ci` condition** — produces `"name" ILIKE $1 ESCAPE '\'` with param `val%`
8. **`between` condition** — produces `"weight" BETWEEN $1 AND $2`
9. **AND group** — joins conditions with ` AND `
10. **OR group** — joins conditions with ` OR ` and wraps in parens
11. **Nested groups** — correct parenthesization
12. **Canonicalization** — same conditions in different order produce identical SQL
13. **IN-list sorting** — values sorted alphabetically
14. **UNKNOWN_COLUMN error** — column not in schema → `FilterCompilationError`
15. **CONFIRMATION_REQUIRED error** — spec status not RESOLVED → error
16. **SCHEMA_CHANGED error** — signature mismatch → error
17. **STRUCTURAL_LIMIT_EXCEEDED** — depth > 4 → error
18. **EMPTY_IN_LIST error** — `in_` with no operands → error
19. **Wildcard escaping** — `%` and `_` in values escaped before wrapping
20. **columns_used populated** — correct column list in output
21. **explanation populated** — non-empty explanation string

Each test should import `compile_filter_spec` from `src.orchestrator.filter_compiler` and construct input models from `filter_spec.py`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/test_filter_compiler.py -v`
Expected: FAIL — module not found.

**Step 3: Write the implementation**

Create `src/orchestrator/filter_compiler.py` implementing `compile_filter_spec()` as described in design Section 5:

```python
def compile_filter_spec(
    spec: ResolvedFilterSpec,
    schema_columns: set[str],
    column_types: dict[str, str],
    runtime_schema_signature: str,
) -> CompiledFilter:
```

Key implementation details:
- Entry guard: check `spec.status == RESOLVED`, check schema signature match
- Walk the tree recursively with a `_compile_node()` helper
- Track `param_index` as a mutable counter (list of one int) across the tree walk
- Track `depth` and `condition_count` for structural limits
- `_compile_condition()` handles each operator → SQL fragment mapping
- `_escape_like_value(value)` escapes `%`, `_`, `\` characters
- `_canonicalize_group()` sorts children by serialized subtree before emission
- `_build_explanation()` generates human-readable text from the AST
- All column references quoted with double quotes: `"column_name"`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestrator/test_filter_compiler.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/orchestrator/filter_compiler.py tests/orchestrator/test_filter_compiler.py
git commit -m "feat: add FilterSpec SQL compiler with parameterized output"
```

---

### Task 5: Semantic Resolver

**Files:**
- Create: `src/orchestrator/filter_resolver.py`
- Test: `tests/orchestrator/test_filter_resolver.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/test_filter_resolver.py` with tests covering:

1. **Tier A: state abbreviation auto-expand** — `SemanticReference(semantic_key="california", target_column="state")` → `FilterCondition(column="state", operator=eq, operands=[TypedLiteral("string", "CA")])` with `status=RESOLVED`
2. **Tier B: region expansion needs confirmation** — `SemanticReference(semantic_key="NORTHEAST", target_column="state")` → `status=NEEDS_CONFIRMATION`, `pending_confirmations` populated, `resolution_token` non-null
3. **Tier B: confirmed region expands** — pass a prior confirmation token in `session_confirmations` → `status=RESOLVED`, IN condition with 9 states
4. **Tier C: unknown term returns suggestions** — `SemanticReference(semantic_key="the south", target_column="state")` → `status=UNRESOLVED`, `unresolved_terms` with suggestions
5. **Business predicate: BUSINESS_RECIPIENT** — expands to `is_not_blank` on matched company column
6. **Column matching: exact match** — `target_column_patterns=["company"]` matches `company` in schema
7. **Column matching: zero matches** — raises `MISSING_TARGET_COLUMN`
8. **Column matching: multiple matches** — raises `AMBIGUOUS_TERM`
9. **Direct FilterCondition passes through** — validated but unchanged
10. **Unknown column in FilterCondition** — raises `UNKNOWN_COLUMN`
11. **Invalid operator** — raises `INVALID_OPERATOR`
12. **Status precedence: UNRESOLVED > NEEDS_CONFIRMATION > RESOLVED** — mixed group
13. **Schema signature validation** — signature embedded in output
14. **Token is HMAC-signed** — not raw base64, validates with secret
15. **Nested group resolution** — recursive processing
16. **Canonicalization** — IN-lists sorted, commutative children sorted

Each test constructs `FilterIntent` or `FilterGroup` models and calls `resolve_filter_intent()`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/test_filter_resolver.py -v`
Expected: FAIL — module not found.

**Step 3: Write the implementation**

Create `src/orchestrator/filter_resolver.py` implementing `resolve_filter_intent()` as described in design Section 4:

```python
def resolve_filter_intent(
    intent: FilterIntent,
    schema_columns: set[str],
    column_types: dict[str, str],
    schema_signature: str,
    session_confirmations: dict[str, "ResolvedFilterSpec"] | None = None,
) -> ResolvedFilterSpec:
```

Key implementation details:
- Import canonical data from `filter_constants.py`
- `_resolve_node()` recursive helper dispatches on node type
- `_resolve_condition()` validates column, operator, arity
- `_resolve_semantic()` normalizes key, looks up tier, expands or flags
- `_generate_resolution_token()` uses `hmac.new()` with a server secret from **required** env var `FILTER_TOKEN_SECRET` (no random fallback; tokens must be verifiable across restarts within TTL)
- The token secret is **not validated at module import time** (import-time RuntimeError would break unrelated tests and paths). Instead, `_get_token_secret()` is a lazy getter that raises `FilterConfigError` on first use if `FILTER_TOKEN_SECRET` is not set. Additionally, the FastAPI `lifespan` startup in `src/api/main.py` calls `validate_filter_config()` which fails fast at server boot — not at import
- `_validate_resolution_token()` verifies HMAC signature + expiry + session + schema signature + dict version + resolved_spec_hash
- `_match_target_column()` delegates to `filter_constants.match_column_pattern()`
- `_build_explanation()` generates human-readable text from the resolved AST
- Status precedence: accumulate child statuses, return worst (`UNRESOLVED > NEEDS_CONFIRMATION > RESOLVED`)
- `_canonicalize_group()` sorts children deterministically by full subtree serialization
- **Ambiguity policy is mandatory product behavior:**
  - Tier A: auto-expand silently (state abbreviations, service codes)
  - Tier B: expand + set `NEEDS_CONFIRMATION` — agent MUST present expansion to user and await explicit approval before any query execution
  - Tier C: set `UNRESOLVED` with 2-3 suggestions — agent MUST present options and require explicit pick; no silent interpretation, no fallback execution

**Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestrator/test_filter_resolver.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/orchestrator/filter_resolver.py tests/orchestrator/test_filter_resolver.py
git commit -m "feat: add FilterSpec semantic resolver with tier classification"
```

---

## Phase 3: MCP Layer — Parameterized Queries and Column Samples

Update the data source MCP server to accept parameterized queries and provide column samples.

---

### Task 6: Parameterized Query Execution

**Files:**
- Modify: `src/mcp/data_source/tools/query_tools.py:66-144`
- Test: `tests/mcp/data_source/test_parameterized_query.py`

**Step 1: Write the failing test**

Create `tests/mcp/data_source/test_parameterized_query.py`:

```python
"""Tests for parameterized query execution in the data source MCP."""

import duckdb
import pytest


@pytest.fixture
def db_with_data():
    """Create an in-memory DuckDB with test data."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE imported_data (
            _source_row_num INTEGER,
            state VARCHAR,
            company VARCHAR,
            weight DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO imported_data VALUES
        (1, 'CA', 'Acme Corp', 5.0),
        (2, 'NY', 'Beta Inc', 3.0),
        (3, 'CA', NULL, 7.0),
        (4, 'TX', 'Gamma LLC', 2.0)
    """)
    yield conn
    conn.close()


class TestParameterizedExecution:
    """Tests for parameterized SQL execution."""

    def test_parameterized_count(self, db_with_data):
        """Parameterized count query returns correct count."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "state" = $1',
            ["CA"],
        ).fetchone()
        assert result[0] == 2

    def test_parameterized_in_query(self, db_with_data):
        """Parameterized IN query returns correct rows."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "state" IN ($1, $2)',
            ["CA", "NY"],
        ).fetchone()
        assert result[0] == 3

    def test_parameterized_prevents_injection(self, db_with_data):
        """SQL injection attempt is treated as literal string value."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "state" = $1',
            ["CA'; DROP TABLE imported_data; --"],
        ).fetchone()
        assert result[0] == 0
        # Table still exists
        count = db_with_data.execute(
            "SELECT COUNT(*) FROM imported_data"
        ).fetchone()
        assert count[0] == 4

    def test_parameterized_null_handling(self, db_with_data):
        """IS NULL works without parameters."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "company" IS NULL',
        ).fetchone()
        assert result[0] == 1

    def test_parameterized_ilike(self, db_with_data):
        """ILIKE with parameterized pattern works."""
        result = db_with_data.execute(
            """SELECT COUNT(*) FROM imported_data WHERE "company" ILIKE $1 ESCAPE '\\'""",
            ["%Corp%"],
        ).fetchone()
        assert result[0] == 1
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/mcp/data_source/test_parameterized_query.py -v`
Expected: PASS — these test DuckDB's native parameterization, confirming it works before we wire it in.

**Step 3: Modify `query_tools.py` to always use parameterized execution**

In `src/mcp/data_source/tools/query_tools.py`, update `get_rows_by_filter()` (lines 66-144). **Rename** the first parameter from `where_clause` to `where_sql` to eliminate semantic confusion — this is compiler-generated parameterized SQL, not a raw user-supplied clause. The `params` parameter accepts `list[Any] | None` for backward compatibility with existing callers, but is normalized to `[]` internally — all execution paths are parameterized regardless of whether params are empty.

```python
async def get_rows_by_filter(
    where_sql: str,
    ctx: Context,
    limit: int = 100,
    offset: int = 0,
    params: list[Any] | None = None,
) -> dict:
```

Replace the raw f-string interpolation at lines 113-125. **Always pass params to `db.execute()`** — normalize `None` to `[]` so every code path uses parameterized execution (even when there are zero parameters):

```python
# ALWAYS parameterized — no raw interpolation path
query_params = params if params is not None else []

# Count query
total_count = db.execute(
    f'SELECT COUNT(*) FROM imported_data WHERE {where_sql}',
    query_params,
).fetchone()[0]

# Rows query
results = db.execute(f"""
    SELECT {SOURCE_ROW_NUM_COLUMN}, {select_clause}
    FROM imported_data
    WHERE {where_sql}
    ORDER BY {SOURCE_ROW_NUM_COLUMN}
    LIMIT {limit} OFFSET {offset}
""", query_params).fetchall()
```

**Note:** The `where_sql` parameter is compiler-generated parameterized SQL (e.g., `"state" IN ($1, $2)`), not raw user SQL. The f-string interpolation of `where_sql` is safe because it comes from `compile_filter_spec()` which only produces quoted column names and `$N` placeholders. Actual values are always in `params`. The parameter is named `where_sql` (not `where_clause`) to make this distinction clear and prevent semantic confusion.

**Step 4: Run all existing data source tests to verify no regression**

Run: `pytest tests/mcp/data_source/ -v -k "not edi"`
Expected: All tests PASS. Existing callers that pass `params=None` will use `[]` (empty list), which DuckDB handles identically to no-params execution.

**Step 5: Commit**

```bash
git add src/mcp/data_source/tools/query_tools.py tests/mcp/data_source/test_parameterized_query.py
git commit -m "feat: add parameterized query support to data source MCP"
```

---

### Task 7: Column Samples MCP Tool

**Files:**
- Create: `src/mcp/data_source/tools/sample_tools.py`
- Modify: `src/mcp/data_source/server.py`
- Modify: `src/services/data_source_mcp_client.py`
- Test: `tests/mcp/data_source/test_sample_tools.py`

**Step 1: Write the failing test**

Create `tests/mcp/data_source/test_sample_tools.py` testing that `get_column_samples()`:
- Returns sample values for each column
- Limits to N distinct values (default 5)
- Excludes NULL values
- Works with string, numeric, and mixed-type columns

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/data_source/test_sample_tools.py -v`
Expected: FAIL — module not found.

**Step 3: Write the implementation**

Create `src/mcp/data_source/tools/sample_tools.py`:

```python
async def get_column_samples(
    ctx: Context,
    max_samples: int = 5,
) -> dict:
    """Get sample distinct values for each column in the data source.

    Args:
        max_samples: Maximum distinct values per column (default 5).

    Returns:
        Dict mapping column names to lists of sample values.
    """
```

Implementation: For each column, run `SELECT DISTINCT "{col}" FROM imported_data WHERE "{col}" IS NOT NULL LIMIT {max_samples}`.

Register in `src/mcp/data_source/server.py`:
```python
from src.mcp.data_source.tools.sample_tools import get_column_samples
mcp.tool()(get_column_samples)
```

Add `get_column_samples()` method to `src/services/data_source_mcp_client.py`.

**Step 4: Run tests**

Run: `pytest tests/mcp/data_source/test_sample_tools.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/mcp/data_source/tools/sample_tools.py src/mcp/data_source/server.py src/services/data_source_mcp_client.py tests/mcp/data_source/test_sample_tools.py
git commit -m "feat: add get_column_samples MCP tool for filter grounding"
```

---

## Phase 4: Tool Integration — Wire FilterSpec into Agent Tools

Update tool handlers and definitions to use FilterSpec instead of raw `where_clause`.

---

### Task 8: Add `resolve_filter_intent` Tool Handler

**Files:**
- Modify: `src/orchestrator/agent/tools/data.py`
- Test: `tests/orchestrator/agent/test_resolve_filter_intent.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_resolve_filter_intent.py` testing:
- Valid intent with direct conditions returns RESOLVED spec
- Intent with semantic references returns appropriate status
- Missing schema returns error
- Invalid intent structure returns error

**Step 2: Run test to verify it fails**

**Step 3: Add `resolve_filter_intent_tool()` to `data.py`**

```python
async def resolve_filter_intent_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Resolve a structured FilterIntent into a concrete FilterSpec.

    Args:
        args: Dict with 'intent' (FilterIntent JSON).

    Returns:
        Tool response with resolved spec, status, explanation, and optional
        confirmation/clarification data.
    """
```

Implementation:
1. Parse `args["intent"]` into `FilterIntent`
2. Get schema columns and types from data gateway
3. Call `resolve_filter_intent()` from `filter_resolver.py`
4. Return structured response with status, explanation, pending_confirmations, etc.

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/data.py tests/orchestrator/agent/test_resolve_filter_intent.py
git commit -m "feat: add resolve_filter_intent tool handler"
```

---

### Task 9: Update `ship_command_pipeline` — Hard Cutover to `filter_spec`

**Files:**
- Modify: `src/orchestrator/agent/tools/pipeline.py:173-260`
- Modify: `src/services/data_source_mcp_client.py`
- Test: `tests/orchestrator/agent/test_pipeline_filter_spec.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_pipeline_filter_spec.py` testing:
- Pipeline accepts `filter_spec` and calls compiler, passes parameterized SQL to gateway
- Pipeline **rejects** raw `where_clause` — returns error if `where_clause` is passed
- Pipeline requires exactly one of `filter_spec` or `all_rows=true` — rejects calls with neither, and rejects calls with both
- Compiled SQL + params are passed to gateway together
- Audit metadata (`filter_explanation`, `compiled_filter`, `filter_audit`) is attached to preview result
- `filter_audit` contains `spec_hash`, `compiled_hash`, `schema_signature`, `dict_version`

**Step 2: Run test to verify it fails**

**Step 3: Update `ship_command_pipeline_tool()`**

In `src/orchestrator/agent/tools/pipeline.py:173-260`, **hard cutover** — no legacy path:
1. **Remove** `where_clause` from accepted args entirely
2. Accept `filter_spec` dict and/or `all_rows` boolean from args — exactly one must be provided:
   - `filter_spec` present, `all_rows` absent or `false` → compile and filter (normal path)
   - `filter_spec` absent, `all_rows` is `true` → ship all rows (`WHERE 1=1`) with preview confirmation gate
   - **Both** `filter_spec` present AND `all_rows` is `true` → return `_err("Conflicting arguments: provide filter_spec OR all_rows=true, not both.")` — deterministic rejection, no precedence guessing
   - **Neither** present → return `_err("Either filter_spec or all_rows=true is required. Use resolve_filter_intent to create a filter, or set all_rows=true to ship everything.")`
6. If `where_clause` is present in args: return `_err("where_clause is not accepted. Use resolve_filter_intent to create a filter_spec.")`
7. Attach `filter_explanation`, `compiled_filter`, and `filter_audit` metadata to the result before calling `_emit_preview_ready()`
8. Compute `compiled_hash` as SHA-256 of canonical JSON execution payload using a **deterministic serializer** (not `default=str`, which varies by type/locale):
   ```python
   def _canonical_param(v: Any) -> Any:
       """Normalize a param value for deterministic hashing."""
       if isinstance(v, datetime):
           return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
       if isinstance(v, date):
           return v.isoformat()  # YYYY-MM-DD, no timezone ambiguity
       if isinstance(v, Decimal):
           return str(v.normalize())  # Remove trailing zeros: Decimal('1.20') → '1.2'
       if isinstance(v, float):
           return str(v)  # Exact float repr
       return v  # str, int, bool, None — already JSON-safe

   canonical = json.dumps(
       {"where_sql": where_sql, "params": [_canonical_param(p) for p in params]},
       sort_keys=True, separators=(",", ":"),  # compact, deterministic
   )
   compiled_hash = hashlib.sha256(canonical.encode()).hexdigest()
   ```
   Params stay in execution order. The `_canonical_param()` function ensures dates use UTC ISO8601, decimals are normalized, and no type relies on `str()` formatting conventions.

Update `DataSourceMCPClient.get_rows_by_filter()` to rename `where_clause` to `where_sql` and accept `params`:

```python
async def get_rows_by_filter(
    self,
    where_sql: str | None = None,
    limit: int = 100,
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/pipeline.py src/services/data_source_mcp_client.py tests/orchestrator/agent/test_pipeline_filter_spec.py
git commit -m "feat: update ship_command_pipeline to accept filter_spec"
```

---

### Task 10: Update `fetch_rows` — Hard Cutover to `filter_spec`

**Files:**
- Modify: `src/orchestrator/agent/tools/data.py:72-103`
- Test: `tests/orchestrator/agent/test_fetch_rows_filter_spec.py`

**Step 1: Write the failing test**

Test that `fetch_rows_tool()`:
- Accepts `filter_spec`, compiles it, and passes parameterized query to gateway
- **Rejects** `where_clause` — returns error if passed
- Requires exactly one of `filter_spec` or `all_rows=true` — rejects calls with neither, and rejects calls with both

**Step 2: Run test to verify it fails**

**Step 3: Update `fetch_rows_tool()`**

Same hard cutover as pipeline: exactly one of `filter_spec` or `all_rows=true` must be provided. If both are present, return `_err("Conflicting arguments")`. If neither is present, return `_err()`. If `where_clause` is passed, return `_err()`. Never silently default to fetching all rows. Compile via `compile_filter_spec()`, pass `where_sql` + `params` to gateway.

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/data.py tests/orchestrator/agent/test_fetch_rows_filter_spec.py
git commit -m "feat: update fetch_rows to accept filter_spec"
```

---

### Task 11: Update Tool Definitions Registry

**Files:**
- Modify: `src/orchestrator/agent/tools/__init__.py:57-172`
- Test: `tests/orchestrator/agent/test_tool_definitions_filter.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_tool_definitions_filter.py` testing:
- `resolve_filter_intent` tool exists in **batch mode only** (not interactive — interactive uses conversational collection, not data source filtering)
- `ship_command_pipeline` input schema has `filter_spec` and `all_rows` properties and does NOT have `where_clause`
- `fetch_rows` input schema has `filter_spec` and `all_rows` properties and does NOT have `where_clause`
- `validate_filter_syntax` tool does NOT exist (deleted, not stubbed)
- In interactive mode, `resolve_filter_intent` is NOT in the tool list (interactive mode allowlist is unchanged)

**Step 2: Run test to verify it fails**

**Step 3: Update `get_all_tool_definitions()`**

In `src/orchestrator/agent/tools/__init__.py`:
1. Add import: `from src.orchestrator.agent.tools.data import resolve_filter_intent_tool`
2. **Remove** import of `validate_filter_syntax_tool` from data.py
3. Add `resolve_filter_intent` tool definition with `FilterIntent` input schema
4. **Replace** `where_clause` with `filter_spec`, `resolution_token`, and `all_rows` (boolean, default false) in `ship_command_pipeline` definition
5. **Replace** `where_clause` with `filter_spec` and `all_rows` (boolean, default false) in `fetch_rows` definition
6. **Delete** the `validate_filter_syntax` tool definition entirely (hard cutover — no stub)
7. `resolve_filter_intent` is batch-mode only — add it to the batch definitions list, NOT the interactive allowlist (the interactive mode tool filter at lines 651-663 remains unchanged)

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/__init__.py tests/orchestrator/agent/test_tool_definitions_filter.py
git commit -m "feat: register resolve_filter_intent and add filter_spec to tool definitions"
```

---

### Task 12: Update Preview Emission with Filter Metadata

**Files:**
- Modify: `src/orchestrator/agent/tools/core.py:342-363`
- Test: `tests/orchestrator/agent/test_preview_filter_metadata.py`

**Step 1: Write the failing test**

Test that `_emit_preview_ready()` includes `filter_explanation`, `compiled_filter`, and `filter_audit` in its SSE payload and slim LLM response when present in the result dict.

**Step 2: Run test to verify it fails**

**Step 3: Update `_emit_preview_ready()`**

Add ALL three filter metadata fields to both the SSE payload and slim LLM response. Only include if present in `result`:

```python
def _emit_preview_ready(
    result: dict[str, Any],
    rows_with_warnings: int,
    bridge: EventEmitterBridge | None = None,
    job_id_override: str | None = None,
) -> dict[str, Any]:
    """Emit preview SSE payload and return slim LLM tool payload."""
    _emit_event("preview_ready", result, bridge=bridge)
    response = {
        "status": "preview_ready",
        "job_id": job_id_override or result.get("job_id"),
        "total_rows": result.get("total_rows", 0),
        "total_estimated_cost_cents": result.get("total_estimated_cost_cents", 0),
        "rows_with_warnings": rows_with_warnings,
        "message": (
            "Preview card has been displayed to the user. STOP HERE. "
            "Respond with one brief sentence asking the user to review "
            "the preview and click Confirm or Cancel."
        ),
    }
    # Include ALL filter metadata fields for transparency and audit
    for key in ("filter_explanation", "compiled_filter", "filter_audit"):
        if key in result:
            response[key] = result[key]
    return _ok(response)
```

The `filter_audit` dict contains: `spec_hash` (SHA-256 of serialized FilterSpec), `compiled_hash` (SHA-256 of canonical JSON execution payload `{"where_sql": ..., "params": [...]}` with params in execution order), `schema_signature`, and `dict_version`. These travel through the SSE payload to the PreviewCard frontend component for developer-accessible audit trail.

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/core.py tests/orchestrator/agent/test_preview_filter_metadata.py
git commit -m "feat: include filter metadata in preview emission"
```

---

## Phase 5: Enforcement — Hooks, System Prompt, Session

---

### Task 13: Hook Enforcement — Deny Raw SQL

**Files:**
- Modify: `src/orchestrator/agent/hooks.py`
- Test: `tests/orchestrator/agent/test_filter_hooks.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_filter_hooks.py` testing:

1. **`deny_raw_sql_in_filter_tools`** denies `where_clause` key in `ship_command_pipeline` payload
2. **`deny_raw_sql_in_filter_tools`** denies `sql` key in `fetch_rows` payload
3. **`deny_raw_sql_in_filter_tools`** denies nested `query` key
4. **`deny_raw_sql_in_filter_tools`** allows `filter_spec` key (no denial)
5. **`deny_raw_sql_in_filter_tools`** does NOT trigger for unrelated tools (e.g., `create_job`)
6. **`validate_intent_on_resolve`** denies invalid operator in intent
7. **`validate_intent_on_resolve`** allows valid intent
8. **`validate_filter_spec_on_pipeline`** denies pipeline call with Tier-B spec but missing `resolution_token`
9. **`validate_filter_spec_on_pipeline`** denies pipeline call with expired token (TTL exceeded)
10. **`validate_filter_spec_on_pipeline`** denies pipeline call with tampered HMAC signature
11. **`validate_filter_spec_on_pipeline`** denies pipeline call with token whose `resolved_spec_hash` doesn't match incoming `filter_spec`
12. **`validate_filter_spec_on_pipeline`** denies pipeline call with token whose `schema_signature` doesn't match current source
13. **`validate_filter_spec_on_pipeline`** denies pipeline call with token whose `dict_version` doesn't match current canonical dict
14. **`validate_filter_spec_on_pipeline`** allows pipeline call with valid Tier-B token (all bindings match)
15. **`validate_filter_spec_on_pipeline`** allows pipeline call with Tier-A-only spec (no token required)
16. **Hook ordering/finality:** a denied payload CANNOT be later "allowed" by any downstream hook — verify deny is final
17. **Scoped matcher priority:** deny hook fires on scoped tools only; does not interfere with unrelated tool chains
18. **Deny precedence:** when `deny_raw_sql_in_filter_tools` returns deny, no subsequent PreToolUse hook for that tool call is evaluated

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_filter_hooks.py -v`
Expected: FAIL — hook functions not found.

**Step 3: Add hook implementations to `hooks.py`**

Add three new hook functions after the existing validators:

```python
async def deny_raw_sql_in_filter_tools(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny raw SQL keys in filter-related tool payloads.

    Scoped to: resolve_filter_intent, ship_command_pipeline, fetch_rows.
    Inspects payload recursively for banned keys: where_clause, sql, query, raw_sql.
    """

async def validate_filter_spec_on_pipeline(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate filter_spec structure and Tier-B token on pipeline and fetch_rows.

    Enforcement checklist (all must pass or deny):
    1. filter_spec is present and structurally valid (or all_rows=true)
    2. If filter_spec contains Tier-B resolved terms (status was NEEDS_CONFIRMATION):
       a. resolution_token MUST be present — deny if missing
       b. HMAC signature is valid (not tampered)
       c. Token TTL has not expired
       d. Token session_id matches current session
       e. Token schema_signature matches current source schema
       f. Token dict_version matches current canonical dict version
       g. Token resolved_spec_hash matches SHA-256 of incoming filter_spec
    3. Schema signature in filter_spec matches current source
    """

async def validate_intent_on_resolve(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate FilterIntent structure before resolution."""
```

Update `create_hook_matchers()` to include the new hooks in the PreToolUse chain. **Hook ordering invariant:** `deny_raw_sql_in_filter_tools` must be registered first in the matcher list for filter-scoped tools. The Claude SDK processes PreToolUse hooks in registration order — if a deny hook fires, the SDK halts the chain (deny is final, not overridable). Verify this with the test cases above (items 8-10).

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/test_filter_hooks.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/orchestrator/agent/hooks.py tests/orchestrator/agent/test_filter_hooks.py
git commit -m "feat: add deny_raw_sql and filter validation hooks"
```

**Step 6: Add `validate_filter_config()` startup validation**

This step implements the startup-time secret validation referenced in Architectural Invariant #6. Without it, the token secret requirement is only enforced at first use (lazy getter), which is too late for production.

- Create `src/orchestrator/filter_config.py` with:
  ```python
  _MIN_SECRET_LENGTH = 32

  def validate_filter_config() -> None:
      """Validate required filter configuration at startup.

      Called from FastAPI lifespan in src/api/main.py.
      Raises FilterConfigError if FILTER_TOKEN_SECRET is not set or too short.
      """
      import os
      secret = os.environ.get("FILTER_TOKEN_SECRET", "")
      if not secret:
          raise FilterConfigError(
              "FILTER_TOKEN_SECRET env var is required. "
              "Set it to a stable secret (min 32 chars) for HMAC token signing."
          )
      if len(secret) < _MIN_SECRET_LENGTH:
          raise FilterConfigError(
              f"FILTER_TOKEN_SECRET must be at least {_MIN_SECRET_LENGTH} characters. "
              f"Current length: {len(secret)}. Use a cryptographically random value."
          )
  ```
- Modify `src/api/main.py` lifespan to call `validate_filter_config()` at startup (before agent session prewarm)
- Test: `tests/orchestrator/test_filter_config.py` — verify:
  - Raises when env var is missing
  - Raises when env var is too short (e.g., 16 chars)
  - Succeeds when env var is set and >= 32 chars

```bash
git add src/orchestrator/filter_config.py src/api/main.py tests/orchestrator/test_filter_config.py
git commit -m "feat: add validate_filter_config() startup check for FILTER_TOKEN_SECRET"
```

---

### Task 14: Session Manager — Add Confirmed Resolutions

**Files:**
- Modify: `src/services/agent_session_manager.py:24-58`

**Step 1: Add `confirmed_resolutions` field to `AgentSession.__init__`**

```python
self.confirmed_resolutions: dict[str, "ResolvedFilterSpec"] = {}  # token → confirmed ResolvedFilterSpec
```

This is a single-line addition. No separate test file needed — the field is tested implicitly by the resolver integration tests.

**Step 2: Commit**

```bash
git add src/services/agent_session_manager.py
git commit -m "feat: add confirmed_resolutions to AgentSession"
```

---

### Task 15: System Prompt Rewrite — FilterIntent Schema

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py`
- Test: `tests/orchestrator/agent/test_system_prompt_filter.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_system_prompt_filter.py` testing:
1. Batch mode prompt contains "FilterIntent" (not "WHERE clause")
2. Batch mode prompt contains "resolve_filter_intent"
3. Batch mode prompt contains "NEVER generate SQL"
4. Batch mode prompt lists available operators
5. Batch mode prompt lists canonical semantic keys when regions are relevant
6. Interactive mode prompt does NOT contain FilterIntent instructions

**Step 2: Run test to verify it fails**

**Step 3: Rewrite the filter section of the system prompt**

In `src/orchestrator/agent/system_prompt.py`:
1. Replace the SQL filter rules section (lines 173-246 in batch mode) with FilterIntent schema documentation
2. Add `_build_filter_rules()` function that generates schema-aware rules
3. Include available operators from `FilterOperator` enum
4. Include canonical semantic keys relevant to the current schema
5. Add the explicit "NEVER generate SQL" instruction
6. Add example FilterIntent JSON for common patterns
7. Add sample values to `_build_schema_section()` if available

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/test_system_prompt_filter.py -v`
Expected: All tests PASS.

**Step 5: Run existing system prompt tests to verify no regression**

Run: `pytest tests/orchestrator/agent/test_system_prompt.py -v`
Expected: Some existing tests may need updates if they assert on SQL-related content. Update them.

**Step 6: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_system_prompt_filter.py
git commit -m "feat: rewrite system prompt to use FilterIntent schema (no SQL)"
```

---

## Phase 6: Frontend — Filter Transparency

---

### Task 16: Frontend Types

**Files:**
- Modify: `frontend/src/types/api.ts`

**Step 1: Add filter fields to `BatchPreview` interface**

In `frontend/src/types/api.ts`, add to the `BatchPreview` interface:

```typescript
filter_explanation?: string;
compiled_filter?: string;
filter_audit?: {
    spec_hash: string;
    compiled_hash: string;
    schema_signature: string;
    dict_version: string;
};
```

**Step 2: Type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/types/api.ts
git commit -m "feat: add filter transparency fields to BatchPreview type"
```

---

### Task 17: PreviewCard Filter Display

**Files:**
- Modify: `frontend/src/components/command-center/PreviewCard.tsx`

**Step 1: Read the current PreviewCard**

Understand current structure before modifying.

**Step 2: Add filter explanation bar**

Add a collapsible filter section above the row list:
- Always show `filter_explanation` if present (one line, subtle)
- Collapsible "View compiled filter" shows `compiled_filter`
- Store `filter_audit` as `data-*` attributes for dev tools

Use existing design system classes: `text-sm text-muted`, collapsible via `useState`.

**Step 3: Type check and verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 4: Commit**

```bash
git add frontend/src/components/command-center/PreviewCard.tsx
git commit -m "feat: add filter explanation bar to PreviewCard"
```

---

## Phase 7: Integration, Cleanup, and Determinism Acceptance Testing

---

### Task 18: Update Existing Tests — Hard Cutover Assertions

**Files:**
- Modify: `tests/orchestrator/agent/test_tools_v2.py` (if it asserts `where_clause` in tool definitions)
- Modify: `tests/orchestrator/agent/test_system_prompt.py` (update SQL-assertion tests)
- Modify: `src/orchestrator/agent/tools/data.py` — delete `validate_filter_syntax_tool()` handler function and its `sqlglot` import

**Step 1: Run the full test suite to find failures**

Run: `pytest tests/ -v -k "not stream and not sse and not progress and not edi" --tb=short 2>&1 | tail -100`
Expected: Identify any tests that fail due to tool definition changes.

**Step 2: Fix failing tests**

- Update assertions that check for `where_clause` in tool definitions to assert it is **absent** and `filter_spec` is **present**
- Update system prompt tests that assert SQL generation instructions to assert FilterIntent instructions instead
- Remove any tests for `validate_filter_syntax` (tool is deleted, not stubbed)
- Ensure no test imports or references `validate_filter_syntax_tool`

**Step 3: Commit**

```bash
git add tests/ src/orchestrator/agent/tools/data.py
git commit -m "test: update existing tests for FilterSpec hard cutover"
```

---

### Task 19: Conversation Route — Pass Column Samples and Confirmations

**Files:**
- Modify: `src/api/routes/conversations.py`

**Step 1: Update `_ensure_agent()` and `_process_agent_message()`**

When building/rebuilding the agent, fetch column samples and pass them to `build_system_prompt()` for filter grounding. Also wire `session.confirmed_resolutions` through to the resolver tool handler so Tier B confirmations persist within a session.

**Step 2: Commit**

```bash
git add src/api/routes/conversations.py
git commit -m "feat: pass column samples and confirmed resolutions through conversation route"
```

---

### Task 20: End-to-End Determinism Acceptance Tests

**Files:**
- Create: `tests/integration/test_filter_determinism.py`

**Step 1: Write the determinism acceptance test**

This is the **release gate** — the test that proves the system is deterministic. It should:

```python
"""End-to-end determinism acceptance tests.

These tests prove that identical FilterIntent + identical schema always produce
identical CompiledFilter output (same where_sql, same params, same compiled_hash,
same row set, same preview totals). This is the release gate for the FilterSpec
compiler architecture.
"""

class TestDeterministicReproducibility:
    """Same input => same output, every time."""

    def test_identical_intent_produces_identical_compiled_hash(self):
        """Run the same FilterIntent through resolve + compile 5 times.
        Assert all 5 produce identical compiled_hash."""

    def test_reordered_conditions_produce_same_sql(self):
        """FilterGroup with conditions in different order produces identical
        where_sql and params after canonicalization."""

    def test_reordered_in_list_produces_same_sql(self):
        """IN-list with values in different order produces identical
        sorted params and identical where_sql."""

    def test_northeast_business_recipient_always_returns_same_rows(self):
        """The canonical demo query: 'companies in the Northeast'.
        Resolve NORTHEAST + BUSINESS_RECIPIENT, compile, execute against
        test CSV. Assert exactly the expected row set every time."""

    def test_compiled_hash_is_content_addressed(self):
        """Two different FilterIntents that happen to produce the same SQL
        (e.g., state='CA' vs state IN ('CA')) produce different spec_hash
        but could produce same compiled_hash — verify hash is over
        canonical JSON of {"where_sql": ..., "params": [...]}, not the intent."""

    def test_compiled_hash_preserves_param_order(self):
        """BETWEEN with (low, high) vs (high, low) produces different hashes.
        Params are hashed in execution order, not sorted — sorting would
        hide meaningful order differences for non-commutative operators."""
```

**Step 2: Run tests**

Run: `pytest tests/integration/test_filter_determinism.py -v`
Expected: All PASS — this is the proof that the system is deterministic.

**Step 3: Commit**

```bash
git add tests/integration/test_filter_determinism.py
git commit -m "test: add end-to-end determinism acceptance tests (release gate)"
```

---

## Phase 8: Execution Determinism — Idempotency, In-Flight State, Replay Safety

### Problem Statement

The current execution path has a critical window between UPS side effect and DB persistence:

```
batch_engine.py:408  →  result = await self._ups.create_shipment(request_body=api_payload)
    ... (tracking number extraction, label save, cost calculation) ...
batch_engine.py:458  →  self._db.commit()
```

A crash, network split, or process kill between lines 408 and 458 creates a shipment at UPS that is not recorded in the local DB. On retry, the same row produces a **duplicate shipment** with a separate tracking number and charge.

### Design Decisions

1. **UPS `TransactionReference` is advisory-only** — UPS does not deduplicate based on it, and `track_package` only accepts UPS tracking numbers (not custom references). We use `TransactionReference.CustomerContext` strictly for post-hoc audit correlation in UPS Quantum View, not for programmatic dedup. Our dedup layer is local DB state only.
2. **In-flight state is local-first.** Before calling UPS, write `in_flight` status + idempotency key to DB and commit. After UPS responds, update to `completed`/`failed` and commit. The in-flight window is bounded to the UPS API call duration only.
3. **Recovery uses a three-tier strategy based on available state.** When a row is `in_flight` on resume:
   - **Tier 1 (has `ups_transaction_id`):** The UPS tracking number was stored before crash. Call `track_package(tracking_number=ups_transaction_id)` to verify the shipment still exists at UPS. If valid → mark `completed`. If invalid → mark `needs_review`.
   - **Tier 2 (no tracking info):** The UPS call may or may not have succeeded — we cannot determine this programmatically because UPS does not support query-by-custom-reference. Mark as `needs_review` (never auto-retry — prevents duplicate shipments). Emit a recovery report with the idempotency key so the operator can check UPS Quantum View or shipping history.
   - **Tier 3 (UPS lookup fails):** Network or API error during recovery. Leave as `in_flight` for manual resolution on next attempt.
4. **Labels are promoted BEFORE the DB commit, not after.** Write to `labels/staging/{job_id}/{row}.png`, then `os.rename()` to final path, then commit the DB row with the final path. This ensures: if crash occurs after promote but before commit, the label exists at its final location and the in-flight row will be recovered normally. Startup cleanup only removes staging files for job directories that have no `in_flight` or `needs_review` rows.
5. **Write-back uses a durable queue table.** Each successful row writes a `WriteBackTask` row to a new `write_back_queue` table. A background worker processes the queue. Partial failures are retried independently per row.
6. **`needs_review` is a terminal status for safety.** Rows marked `needs_review` during crash recovery are never auto-retried. They require operator action (void duplicate at UPS or manually complete). The `get_job_status` tool reports `needs_review` count.

---

### Task 21: Add `in_flight` Status and Idempotency Columns to JobRow

**Files:**
- Modify: `src/db/models.py` (RowStatus enum + JobRow model)
- Create: `tests/db/test_row_inflight_status.py`

**Step 1: Write the failing test**

```python
"""Tests for in_flight row status and idempotency columns."""

from src.db.models import RowStatus


class TestRowStatusInFlight:
    def test_in_flight_status_exists(self):
        assert hasattr(RowStatus, "in_flight")
        assert RowStatus.in_flight.value == "in_flight"

    def test_needs_review_status_exists(self):
        assert hasattr(RowStatus, "needs_review")
        assert RowStatus.needs_review.value == "needs_review"

    def test_valid_status_transitions(self):
        """pending → in_flight → completed/failed is valid.
        in_flight → needs_review is valid (crash recovery, ambiguous).
        in_flight → pending is NOT valid (never auto-retry ambiguous rows).
        pending → completed directly is NOT valid (must go through in_flight)."""
```

Test that `JobRow` has new columns:
- `idempotency_key: str | None` — `"{job_id}:{row_number}:{row_checksum}"` set before UPS call
- `ups_transaction_id: str | None` — UPS-returned `ShipmentIdentificationNumber` for audit

**Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_row_inflight_status.py -v`
Expected: FAIL — `in_flight` not in RowStatus.

**Step 3: Implement changes**

In `src/db/models.py`:

```python
class RowStatus(str, Enum):
    pending = "pending"
    in_flight = "in_flight"  # NEW: UPS call dispatched, awaiting response
    processing = "processing"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    needs_review = "needs_review"  # NEW: crash recovery — operator must resolve
```

Add columns to `JobRow`:

```python
idempotency_key: Mapped[Optional[str]] = mapped_column(
    String(200), nullable=True, index=True
)
ups_transaction_id: Mapped[Optional[str]] = mapped_column(
    String(50), nullable=True
)
```

Add index: `Index("idx_job_rows_idempotency", "idempotency_key")`

Also fix the `JobRow` docstring — change `row_checksum: SHA-256 hash` to `row_checksum: MD5 hash` (matches actual `core.py:211` implementation which uses `hashlib.md5`).

**Step 4: Add schema migration for existing databases**

In `src/db/connection.py`, add to the `row_migrations` list (after the existing `charge_breakdown` entry):

```python
    # Phase 8: Execution determinism columns
    (
        "idempotency_key",
        "ALTER TABLE job_rows ADD COLUMN idempotency_key VARCHAR(200)",
    ),
    (
        "ups_transaction_id",
        "ALTER TABLE job_rows ADD COLUMN ups_transaction_id VARCHAR(50)",
    ),
```

After the row migrations loop, add idempotency index creation:

```python
# Add idempotency index if column was just created
if "idempotency_key" not in existing_rows:
    try:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_job_rows_idempotency "
            "ON job_rows (idempotency_key)"
        ))
    except OperationalError:
        pass  # Index already exists
```

**Step 5: Run tests**

Run: `pytest tests/db/test_row_inflight_status.py -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add src/db/models.py src/db/connection.py tests/db/test_row_inflight_status.py
git commit -m "feat: add in_flight status, idempotency columns, and schema migration"
```

---

### Task 22: Idempotency Key Generation Utility

**Files:**
- Create: `src/services/idempotency.py`
- Create: `tests/services/test_idempotency.py`

**Step 1: Write the failing test**

```python
"""Tests for idempotency key generation and validation."""

class TestIdempotencyKey:
    def test_generate_key_format(self):
        """Key is '{job_id}:{row_number}:{row_checksum}'."""
        key = generate_idempotency_key("job-123", 5, "abc123hash")
        assert key == "job-123:5:abc123hash"

    def test_same_inputs_produce_same_key(self):
        """Deterministic: identical inputs always produce identical key."""
        k1 = generate_idempotency_key("j1", 1, "hash1")
        k2 = generate_idempotency_key("j1", 1, "hash1")
        assert k1 == k2

    def test_different_inputs_produce_different_keys(self):
        k1 = generate_idempotency_key("j1", 1, "hash1")
        k2 = generate_idempotency_key("j1", 2, "hash1")
        assert k1 != k2

    def test_key_fits_ups_transaction_reference(self):
        """UPS TransactionReference.CustomerContext max is 512 chars."""
        key = generate_idempotency_key("a" * 36, 99999, "b" * 64)
        assert len(key) <= 512
```

**Step 2: Run test to verify it fails**

**Step 3: Implement**

```python
"""Idempotency key generation for exactly-once shipment creation."""


def generate_idempotency_key(job_id: str, row_number: int, row_checksum: str) -> str:
    """Generate a deterministic idempotency key for a shipment row.

    The key uniquely identifies a specific row in a specific job with a specific
    data snapshot. If the row data changes (different checksum), the key changes,
    allowing a new shipment to be created for the updated data.

    Args:
        job_id: UUID of the parent job.
        row_number: 1-based row number in the job.
        row_checksum: MD5 hash of the row's order_data JSON (per core.py:211;
            note: models.py docstring incorrectly says SHA-256 — fix during Task 21).

    Returns:
        Idempotency key string: '{job_id}:{row_number}:{row_checksum}'.
    """
    return f"{job_id}:{row_number}:{row_checksum}"
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/services/idempotency.py tests/services/test_idempotency.py
git commit -m "feat: add idempotency key generation for shipment rows"
```

---

### Task 23: Include TransactionReference in UPS Payload

**Files:**
- Modify: `src/services/ups_payload_builder.py`
- Modify: `tests/services/test_ups_payload_builder.py`

**Step 1: Write the failing test**

Add a test to the existing payload builder test file:

```python
def test_build_ups_api_payload_includes_transaction_reference(self):
    """When idempotency_key is provided, payload includes TransactionReference."""
    payload = build_ups_api_payload(simplified, account_number="X", idempotency_key="job:1:hash")
    ref = payload["ShipmentRequest"]["Request"]["TransactionReference"]
    assert ref["CustomerContext"] == "job:1:hash"

def test_build_ups_api_payload_omits_transaction_reference_when_none(self):
    """When no idempotency_key, no TransactionReference in payload."""
    payload = build_ups_api_payload(simplified, account_number="X")
    assert "TransactionReference" not in payload["ShipmentRequest"]["Request"]
```

**Step 2: Run test to verify it fails**

**Step 3: Add `idempotency_key` parameter to `build_ups_api_payload()`**

In `src/services/ups_payload_builder.py`, add optional `idempotency_key: str | None = None` parameter. When provided, inject into payload:

```python
if idempotency_key:
    request["TransactionReference"] = {"CustomerContext": idempotency_key}
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/services/ups_payload_builder.py tests/services/test_ups_payload_builder.py
git commit -m "feat: include TransactionReference in UPS payload for idempotency audit"
```

---

### Task 24: Rewrite BatchEngine Execute with In-Flight State Machine

**Files:**
- Modify: `src/services/batch_engine.py:362-505`
- Create: `tests/services/test_batch_engine_inflight.py`

**Step 1: Write the failing test**

```python
"""Tests for in-flight state machine in BatchEngine.execute()."""

class TestInFlightStateMachine:
    def test_row_transitions_to_in_flight_before_ups_call(self):
        """Row status is 'in_flight' with idempotency_key set and committed
        BEFORE create_shipment is called."""

    def test_row_transitions_to_completed_after_ups_success(self):
        """After successful create_shipment, row status is 'completed'
        with tracking_number, cost_cents, and ups_transaction_id."""

    def test_row_transitions_to_failed_on_ups_error(self):
        """On UPS error, row status is 'failed' with error_code and error_message.
        The in_flight state is cleared."""

    def test_crash_leaves_row_in_in_flight_state(self):
        """Simulate crash between UPS call and DB commit.
        Row should remain 'in_flight' with idempotency_key set."""

    def test_ups_rejection_marks_row_failed(self):
        """If UPS create_shipment raises UPSServiceError (rejection),
        row is marked failed. This is pre-side-effect — safe to retry."""

    def test_post_ups_failure_marks_needs_review_not_failed(self):
        """If UPS call succeeds but label staging/promote/commit fails,
        row is marked needs_review — NOT failed. Marking failed would
        allow retry to create a duplicate shipment."""

    def test_post_ups_failure_preserves_partial_tracking_info(self):
        """If post-UPS exception occurs, any available ups_transaction_id
        from the UPS response is still written to the row for recovery."""

    def test_pending_to_completed_directly_is_rejected(self):
        """BatchEngine must not skip the in_flight state.
        A row going from pending to completed without in_flight is a bug."""
```

**Step 2: Run test to verify it fails**

**Step 3: Rewrite `_process_row()` in `batch_engine.py`**

Replace the current flow:

```
[current]  pending → create_shipment() → completed/failed (single commit)
```

With the two-phase commit:

```
[new]  pending → in_flight (commit 1: set idempotency_key, status='in_flight')
                → create_shipment(idempotency_key)
                   ├─ UPS rejects → failed (commit 2a: safe to retry)
                   └─ UPS accepts → post-side-effect zone
                       ├─ promote + commit succeeds → completed (commit 2b)
                       └─ any local error → needs_review (commit 2c: never failed)
```

Implementation:

```python
async def _process_row(row: Any) -> None:
    nonlocal successful, failed, total_cost_cents

    async with semaphore:
        try:
            order_data = self._parse_order_data(row)
            # ... (international validation, payload build — unchanged) ...

            # Generate idempotency key
            idem_key = generate_idempotency_key(job_id, row.row_number, row.row_checksum)

            # PHASE 1: Mark in-flight BEFORE UPS call
            async with db_lock:
                row.status = "in_flight"
                row.idempotency_key = idem_key
                self._db.commit()

            # Build payload with idempotency key
            api_payload = build_ups_api_payload(
                simplified, account_number=self._account_number,
                idempotency_key=idem_key,
            )

            # --- UPS CALL BOUNDARY ---
            # Everything BEFORE this line is pre-side-effect (safe to mark failed).
            # Everything AFTER this line is post-side-effect (UPS may have
            # created a shipment — MUST use needs_review, never failed).
            ups_call_succeeded = False
            try:
                result = await self._ups.create_shipment(request_body=api_payload)
                ups_call_succeeded = True
            except (UPSServiceError, Exception) as e:
                # UPS rejected the request — no shipment was created.
                # Safe to mark failed (retryable without duplicate risk).
                async with db_lock:
                    row.status = "failed"
                    row.error_code = getattr(e, "code", "E-3005")
                    row.error_message = str(e)
                    self._db.commit()
                raise  # re-raise to skip Phase 2

            # --- POST-UPS: side effect occurred ---
            # From here on, UPS has (or may have) created a shipment.
            # Any exception must NOT mark row as "failed" — that would
            # allow a retry to create a duplicate. Use "needs_review" instead.
            try:
                tracking_number = ...
                label_path = self._save_label_staged(...)  # staging dir
                cost_cents = ...

                # PHASE 2: Promote label FIRST, then commit
                # Order matters for crash safety: if we commit first and
                # crash before promote, startup cleanup deletes the staging
                # file → completed row with no label. By promoting first:
                # - Crash after promote but before commit: label at final
                #   path, row still in_flight → recovery handles normally
                # - Crash after commit: both label and DB are consistent
                final_label_path = self._promote_label(label_path)

                async with db_lock:
                    row.tracking_number = tracking_number
                    row.label_path = final_label_path  # FINAL path, not staging
                    row.cost_cents = cost_cents
                    row.ups_transaction_id = result.get(
                        "shipmentIdentificationNumber"
                    )
                    row.status = "completed"
                    row.processed_at = datetime.now(UTC).isoformat()
                    self._db.commit()

                    # ... progress emission ...

            except Exception as post_e:
                # Post-UPS failure: shipment may exist at UPS.
                # Mark needs_review — NEVER failed (prevents duplicate on retry).
                logger.error(
                    "Post-UPS failure for row %d (job %s): %s. "
                    "Shipment may exist at UPS — marking needs_review.",
                    row.row_number, job_id, post_e,
                )
                async with db_lock:
                    row.status = "needs_review"
                    row.error_message = f"Post-UPS error: {post_e}"
                    # Preserve any partial tracking info for recovery
                    if hasattr(result, "get"):
                        row.ups_transaction_id = result.get(
                            "shipmentIdentificationNumber"
                        )
                    self._db.commit()

        except (UPSServiceError, ValueError, Exception) as e:
            # Only reaches here for pre-UPS errors (payload build, Phase 1
            # commit, etc.) or the re-raised UPS call error above.
            # Row is already marked failed by the inner handler if UPS
            # rejected; for pre-UPS errors, mark failed here.
            if not ups_call_succeeded:
                async with db_lock:
                    if row.status == "in_flight":
                        row.status = "failed"
                        row.error_code = getattr(e, "code", "E-4001")
                        row.error_message = str(e)
                        self._db.commit()
            # ... error progress emission ...
```

**Step 4: Run tests**

Run: `pytest tests/services/test_batch_engine_inflight.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/services/batch_engine.py src/services/idempotency.py tests/services/test_batch_engine_inflight.py
git commit -m "feat: rewrite batch execute with in-flight state machine"
```

---

### Task 25: Label Staging with Atomic Promote

**Files:**
- Modify: `src/services/batch_engine.py` (add `_save_label_staged`, `_promote_label`, `_cleanup_staging`)
- Create: `tests/services/test_label_staging.py`

**Step 1: Write the failing test**

```python
"""Tests for label staging directory with atomic promote."""

class TestLabelStaging:
    def test_save_label_staged_writes_to_staging_dir(self):
        """Label is saved to labels/staging/{job_id}/{row}.png, not final path."""

    def test_promote_label_moves_to_final_path(self):
        """After promote, label exists at final path and staging file is gone."""

    def test_crash_before_promote_leaves_orphan_in_staging(self):
        """If promote never runs, staging file exists but final path does not."""

    def test_cleanup_staging_skips_jobs_with_in_flight_rows(self):
        """cleanup_staging() does NOT delete staging files for jobs that have
        in_flight or needs_review rows — those labels may be needed for recovery."""

    def test_cleanup_staging_removes_orphans_for_completed_jobs(self):
        """cleanup_staging() removes staging dirs only for jobs where all
        rows are completed, failed, or skipped (no in_flight/needs_review)."""
```

**Step 2: Run test to verify it fails**

**Step 3: Implement staging methods**

```python
def _save_label_staged(self, tracking_number: str, label_data: str,
                        job_id: str, row_number: int) -> str:
    """Save label to staging directory. Returns staging path."""
    staging_dir = LABELS_DIR / "staging" / job_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    filename = f"row_{row_number}_{tracking_number}.png"
    staging_path = staging_dir / filename
    staging_path.write_bytes(base64.b64decode(label_data))
    return str(staging_path)

def _promote_label(self, staging_path: str) -> str:
    """Atomically move label from staging to final location."""
    staging = Path(staging_path)
    final_path = LABELS_DIR / staging.name
    os.rename(str(staging), str(final_path))
    return str(final_path)

@staticmethod
def cleanup_staging(db) -> int:
    """Remove orphaned staging files. Called at startup.

    IMPORTANT: Only removes staging files for jobs where NO rows are
    in_flight or needs_review. Those staging files may contain labels
    for shipments that need recovery/operator resolution.

    Args:
        db: Database session to check row statuses.
    """
    staging_root = LABELS_DIR / "staging"
    if not staging_root.exists():
        return 0

    # Find job IDs that still have unresolved rows
    from src.services.job_service import JobService
    js = JobService(db)

    count = 0
    for job_dir in staging_root.iterdir():
        if not job_dir.is_dir():
            continue
        job_id = job_dir.name
        # Check if this job has any in_flight or needs_review rows
        rows = js.get_rows(job_id)
        has_unresolved = any(
            r.status in ("in_flight", "needs_review") for r in rows
        )
        if has_unresolved:
            continue  # Preserve staging files for recovery

        for f in job_dir.iterdir():
            f.unlink()
            count += 1
        job_dir.rmdir()
    return count
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/services/batch_engine.py tests/services/test_label_staging.py
git commit -m "feat: add label staging with atomic promote for crash safety"
```

---

### Task 26: In-Flight Row Recovery on Resume

**Files:**
- Modify: `src/orchestrator/batch/recovery.py`
- Modify: `src/services/batch_engine.py` (add `recover_in_flight_rows`)
- Create: `tests/orchestrator/batch/test_inflight_recovery.py`

**Step 1: Write the failing test**

```python
"""Tests for in-flight row recovery after crash."""

class TestInFlightRecovery:
    def test_recovery_detects_in_flight_rows(self):
        """check_interrupted_jobs includes in_flight row count."""

    def test_recovery_tier1_verifies_via_ups_transaction_id(self):
        """Row has ups_transaction_id (tracking number stored before crash).
        Recovery calls track_package(tracking_number=ups_transaction_id).
        If UPS confirms → row marked completed."""

    def test_recovery_tier1_marks_needs_review_if_ups_rejects(self):
        """Row has ups_transaction_id but track_package says invalid.
        Row marked needs_review (do not auto-retry — may be a partial state)."""

    def test_recovery_tier2_marks_needs_review_when_no_tracking_info(self):
        """Row is in_flight but has no ups_transaction_id.
        Cannot determine if UPS created shipment (UPS doesn't support
        query-by-custom-reference). Row marked needs_review.
        Recovery report includes idempotency_key for operator lookup."""

    def test_recovery_tier2_never_auto_retries(self):
        """Rows without tracking info are NEVER reset to pending.
        Auto-retry would risk duplicate shipments."""

    def test_recovery_tier3_leaves_in_flight_on_lookup_failure(self):
        """If track_package fails (network error), the row stays in_flight
        for resolution on next startup attempt."""

    def test_recovery_report_includes_all_unresolved_rows(self):
        """Recovery returns structured report with recovered, needs_review,
        and unresolved counts plus per-row details for operator action."""
```

**Step 2: Run test to verify it fails**

**Step 3: Implement recovery**

Add `recover_in_flight_rows()` to `batch_engine.py`:

```python
async def recover_in_flight_rows(
    self, job_id: str, rows: list[Any],
) -> dict[str, Any]:
    """Recover rows stuck in 'in_flight' state after a crash.

    Three-tier recovery based on available state:

    Tier 1 (has ups_transaction_id): UPS tracking number was stored before
        crash. Call track_package(tracking_number=...) to verify. If valid →
        complete. If invalid → needs_review.

    Tier 2 (no tracking info): Cannot determine if UPS created shipment.
        UPS does not support query-by-custom-reference, so we CANNOT
        programmatically check. Mark needs_review (never auto-retry —
        prevents duplicate shipments). Include idempotency_key in report
        for operator to check UPS Quantum View.

    Tier 3 (UPS lookup fails): Network/API error during verification.
        Leave in_flight for next startup attempt.

    Returns:
        {
            "recovered": N,       # Tier 1 success — verified at UPS
            "needs_review": N,    # Tier 1 invalid + all Tier 2 rows
            "unresolved": N,      # Tier 3 — left in_flight
            "details": [          # Per-row report for operator
                {"row_number": N, "action": "...", "idempotency_key": "..."},
            ],
        }
    """
    in_flight = [r for r in rows if r.status == "in_flight"]
    recovered = needs_review = unresolved = 0
    details: list[dict[str, Any]] = []

    for row in in_flight:
        if row.ups_transaction_id:
            # Tier 1: We have a UPS tracking number — verify it
            try:
                raw = await self._ups.track_package(
                    tracking_number=row.ups_transaction_id,
                )
                # Parse nested UPS tracking response (matches tracking.py:50-62):
                #   raw["trackResponse"]["shipment"][0]["package"][0]["trackingNumber"]
                shipment = raw.get("trackResponse", {}).get("shipment", [{}])
                if isinstance(shipment, list):
                    shipment = shipment[0] if shipment else {}
                package = shipment.get("package", [{}])
                if isinstance(package, list):
                    package = package[0] if package else {}
                returned_number = package.get("trackingNumber", "")

                if returned_number:
                    # Shipment confirmed at UPS — complete locally
                    row.tracking_number = returned_number
                    row.status = "completed"
                    row.processed_at = datetime.now(UTC).isoformat()
                    self._db.commit()
                    recovered += 1
                    details.append({
                        "row_number": row.row_number,
                        "action": "recovered",
                        "tracking_number": row.ups_transaction_id,
                    })
                else:
                    # UPS doesn't recognize this tracking number
                    row.status = "needs_review"
                    self._db.commit()
                    needs_review += 1
                    details.append({
                        "row_number": row.row_number,
                        "action": "needs_review",
                        "reason": "UPS returned invalid for stored transaction ID",
                        "ups_transaction_id": row.ups_transaction_id,
                        "idempotency_key": row.idempotency_key,
                    })
            except Exception as e:
                # Tier 3: Lookup failed — leave in_flight
                unresolved += 1
                details.append({
                    "row_number": row.row_number,
                    "action": "unresolved",
                    "reason": f"UPS lookup failed: {e}",
                    "idempotency_key": row.idempotency_key,
                })
        else:
            # Tier 2: No tracking info — ambiguous, mark for operator
            row.status = "needs_review"
            self._db.commit()
            needs_review += 1
            details.append({
                "row_number": row.row_number,
                "action": "needs_review",
                "reason": "No UPS transaction ID — cannot verify programmatically",
                "idempotency_key": row.idempotency_key,
            })

    return {
        "recovered": recovered,
        "needs_review": needs_review,
        "unresolved": unresolved,
        "details": details,
    }
```

Update `recovery.py`:
- `check_interrupted_jobs()`: include `in_flight_count` and `needs_review_count` in `InterruptedJobInfo`.
- Add `RecoveryChoice.REVIEW` option for operator to inspect `needs_review` rows before resuming.

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/services/batch_engine.py src/orchestrator/batch/recovery.py tests/orchestrator/batch/test_inflight_recovery.py
git commit -m "feat: add in-flight row recovery with UPS tracking lookup"
```

---

### Task 27: Write-Back Queue Table and Worker

**Files:**
- Modify: `src/db/models.py` (add `WriteBackTask` model)
- Create: `src/services/write_back_worker.py`
- Create: `tests/services/test_write_back_worker.py`

**Step 1: Write the failing test**

```python
"""Tests for durable write-back queue."""

class TestWriteBackQueue:
    def test_enqueue_creates_pending_task(self):
        """enqueue_write_back() creates a WriteBackTask with status=pending."""

    def test_worker_processes_pending_tasks(self):
        """process_write_back_queue() sends tracking numbers to data source
        and marks tasks as completed."""

    def test_worker_retries_failed_tasks(self):
        """Failed tasks stay in queue with incremented retry_count.
        Tasks exceeding max_retries are marked as dead_letter."""

    def test_per_row_write_back_survives_partial_failure(self):
        """If row 3 write-back fails, rows 1, 2, 4, 5 are still written."""
```

**Step 2: Run test to verify it fails**

**Step 3: Implement**

Add `WriteBackTask` to `src/db/models.py`:

```python
class WriteBackTask(Base):
    """Durable queue for tracking number write-back."""

    __tablename__ = "write_back_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(50), nullable=False)
    shipped_at: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, completed, dead_letter
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    created_at: Mapped[str] = mapped_column(String(50), default=utc_now_iso)

    # Prevent duplicate enqueue — same row can only have one active task
    __table_args__ = (
        UniqueConstraint("job_id", "row_number", name="uq_write_back_job_row"),
        Index("idx_write_back_status", "status"),
    )
```

**Schema migration for existing databases:** In `src/db/connection.py`, after the row migrations section, add table creation:

```python
# Create write_back_queue table if it doesn't exist (Phase 8)
try:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS write_back_queue (
            id VARCHAR(36) PRIMARY KEY,
            job_id VARCHAR(36) NOT NULL REFERENCES jobs(id),
            row_number INTEGER NOT NULL,
            tracking_number VARCHAR(50) NOT NULL,
            shipped_at VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at VARCHAR(50),
            UNIQUE(job_id, row_number)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_write_back_status "
        "ON write_back_queue (status)"
    ))
except OperationalError:
    pass  # Table already exists
```

Create `src/services/write_back_worker.py`:

```python
"""Durable write-back worker for tracking number persistence."""

MAX_RETRIES = 3

async def enqueue_write_back(db, job_id: str, row_number: int,
                              tracking_number: str, shipped_at: str) -> None:
    """Add a write-back task to the durable queue."""

async def process_write_back_queue(db, gateway) -> dict[str, int]:
    """Process all pending write-back tasks.

    Returns:
        {"processed": N, "failed": N, "dead_letter": N}
    """
```

Modify `batch_engine.py` to call `enqueue_write_back()` per row instead of collecting `successful_write_back_updates` dict. The bulk write-back at the end of `execute()` is replaced by the worker.

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/db/models.py src/db/connection.py src/services/write_back_worker.py tests/services/test_write_back_worker.py
git commit -m "feat: add durable write-back queue with per-row retry and schema migration"
```

---

### Task 28: Wire Startup Recovery and Staging Cleanup

**Files:**
- Modify: `src/api/main.py` (lifespan)
- Create: `tests/api/test_startup_recovery.py`

**Step 1: Write the failing test**

```python
"""Tests for startup recovery hooks."""

class TestStartupRecovery:
    def test_lifespan_recovers_in_flight_rows_before_cleanup(self):
        """On startup, recover_in_flight_rows() runs BEFORE cleanup_staging().
        This ensures staging labels for unresolved rows are preserved."""

    def test_lifespan_calls_cleanup_staging_with_db(self):
        """cleanup_staging(db) skips jobs with in_flight/needs_review rows."""

    def test_lifespan_calls_process_write_back_queue(self):
        """On startup, pending write-back tasks from crashed sessions are processed."""

    def test_lifespan_logs_recovery_report(self):
        """If recovery finds needs_review rows, a warning is logged with
        per-row details for operator action."""
```

**Step 2: Run test to verify it fails**

**Step 3: Add to FastAPI lifespan**

In `src/api/main.py`, add to the existing lifespan `async with` block:

```python
# Execution determinism: recovery and cleanup
import os
from src.db.models import JobStatus
from src.services.batch_engine import BatchEngine
from src.services.job_service import JobService
from src.services.write_back_worker import process_write_back_queue

with get_db_context() as db:
    js = JobService(db)

    # 1. Recover in-flight rows from crashed sessions
    #    Must run BEFORE staging cleanup — recovery may need staging labels.
    #    list_jobs() accepts one status at a time, so query both running + paused.
    interrupted: list = []
    for st in (JobStatus.running, JobStatus.paused):
        interrupted.extend(js.list_jobs(status=st, limit=500))

    for job in interrupted:
        rows = js.get_rows(job.id)
        in_flight = [r for r in rows if r.status == "in_flight"]
        if in_flight:
            ups_client = await get_ups_gateway()
            account = os.environ.get("UPS_ACCOUNT_NUMBER", "")
            engine = BatchEngine(
                ups_service=ups_client,
                db_session=db,
                account_number=account,
            )
            recovery_result = await engine.recover_in_flight_rows(
                job.id, rows,
            )
            logger.info(
                "Job %s recovery: %d recovered, %d needs_review, %d unresolved",
                job.id,
                recovery_result["recovered"],
                recovery_result["needs_review"],
                recovery_result["unresolved"],
            )
            if recovery_result["details"]:
                logger.warning(
                    "Rows requiring operator review for job %s: %s",
                    job.id,
                    recovery_result["details"],
                )

    # 2. Clean up orphaned staging labels (skips jobs with in_flight/needs_review)
    orphans = BatchEngine.cleanup_staging(db)
    if orphans:
        logger.info("Cleaned up %d orphaned staging labels", orphans)

    # 3. Process pending write-back tasks from crashed sessions
    wb_result = await process_write_back_queue(db, await get_data_gateway())
    if wb_result["processed"] > 0:
        logger.info(
            "Processed %d pending write-back tasks on startup",
            wb_result["processed"],
        )
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git add src/api/main.py tests/api/test_startup_recovery.py
git commit -m "feat: wire startup recovery for staging cleanup and write-back queue"
```

---

### Task 29: Execution Determinism Acceptance Tests

**Files:**
- Create: `tests/integration/test_execution_determinism.py`

**Step 1: Write the acceptance tests**

```python
"""End-to-end execution determinism acceptance tests.

These tests prove that the shipment execution path is crash-safe
and replay-safe. This is the release gate for Phase 8.
"""

class TestCrashSafeExecution:
    def test_crash_after_ups_call_with_stored_tracking_recovers(self):
        """Simulate: create_shipment succeeds → ups_transaction_id stored →
        crash before final commit. On recovery: Tier 1 — track_package
        verifies tracking number → row marked completed. No duplicate."""

    def test_crash_after_ups_call_without_tracking_marks_needs_review(self):
        """Simulate: create_shipment succeeds → crash before tracking stored.
        On recovery: Tier 2 — no ups_transaction_id → row marked needs_review.
        Never auto-retried (prevents duplicate shipments)."""

    def test_crash_before_ups_call_marks_needs_review(self):
        """Simulate: row set to in_flight → crash before create_shipment.
        On recovery: Tier 2 — no tracking info → needs_review (cannot
        determine if UPS received the request or not)."""

    def test_needs_review_rows_never_auto_retried(self):
        """needs_review is terminal. Resume execution skips these rows.
        Operator must explicitly resolve (void at UPS or manual complete)."""

    def test_concurrent_rows_maintain_independent_state(self):
        """With BATCH_CONCURRENCY=5, each row has independent in_flight state.
        Crash of one row does not affect others."""

class TestWriteBackDurability:
    def test_write_back_survives_process_restart(self):
        """Enqueue write-back tasks → kill process → restart → tasks processed."""

    def test_partial_write_back_failure_retries_independently(self):
        """Row 3 write-back fails → rows 1,2,4,5 succeed → row 3 retried on next cycle."""

class TestLabelAtomicity:
    def test_label_promoted_before_db_commit(self):
        """Label is moved from staging to final path BEFORE the DB commit.
        After promote + commit: label at final path, row.label_path = final path."""

    def test_crash_after_promote_before_commit_preserves_label(self):
        """If crash occurs after label promote but before DB commit:
        label exists at final path, row is still in_flight.
        Recovery handles the row; label is NOT lost."""

    def test_orphaned_staging_labels_cleaned_only_for_resolved_jobs(self):
        """Staging labels are removed only for jobs where all rows are
        completed/failed/skipped. Jobs with in_flight/needs_review rows
        keep their staging files for recovery."""
```

**Step 2: Run tests**

Run: `pytest tests/integration/test_execution_determinism.py -v`
Expected: All PASS.

**Step 3: Commit**

```bash
git add tests/integration/test_execution_determinism.py
git commit -m "test: add execution determinism acceptance tests (Phase 8 release gate)"
```

---

## Verification Checklist

After all tasks are complete, verify:

### Unit & Integration Tests

- [ ] `pytest tests/orchestrator/models/test_filter_spec.py -v` — all pass
- [ ] `pytest tests/services/test_filter_constants.py -v` — all pass
- [ ] `pytest tests/errors/test_filter_error_codes.py -v` — all pass
- [ ] `pytest tests/orchestrator/test_filter_compiler.py -v` — all pass
- [ ] `pytest tests/orchestrator/test_filter_resolver.py -v` — all pass
- [ ] `pytest tests/mcp/data_source/test_parameterized_query.py -v` — all pass
- [ ] `pytest tests/mcp/data_source/test_sample_tools.py -v` — all pass
- [ ] `pytest tests/orchestrator/agent/test_filter_hooks.py -v` — all pass
- [ ] `pytest tests/orchestrator/agent/test_system_prompt_filter.py -v` — all pass
- [ ] `pytest tests/ -k "not stream and not sse and not progress and not edi" --tb=short` — no regressions
- [ ] `cd frontend && npx tsc --noEmit` — no type errors

### Architectural Invariants (must hold at every commit)

- [ ] No tool definition contains `where_clause`, `sql`, `query`, or `raw_sql` as an input parameter
- [ ] `validate_filter_syntax` tool does not exist (deleted, not stubbed)
- [ ] `resolve_filter_intent` is batch-mode only (absent from interactive tool allowlist)
- [ ] System prompt contains "NEVER generate SQL" in batch mode
- [ ] System prompt contains FilterIntent schema documentation with column samples
- [ ] Hook enforcement denies raw `where_clause` on filter tools
- [ ] Hook deny is final — denied payloads cannot be "allowed" by any downstream hook
- [ ] Hook scoped matchers do not interfere with unrelated tool chains
- [ ] All DuckDB execution paths use `db.execute(sql, params)` — no raw interpolation
- [ ] `FILTER_TOKEN_SECRET` env var is required at startup via `validate_filter_config()` (no random fallback)
- [ ] `validate_filter_spec_on_pipeline` enforces Tier-B token binding (HMAC, TTL, session, schema, dict version, spec hash)
- [ ] Pipeline/fetch_rows with Tier-B spec but missing `resolution_token` is denied by hook

### Determinism Release Gate (Task 20 — must pass before merge)

- [ ] `pytest tests/integration/test_filter_determinism.py -v` — all pass
- [ ] Same `FilterIntent` + same schema produces identical `compiled_hash` across 5 runs
- [ ] Reordered conditions produce identical `where_sql` after canonicalization
- [ ] Reordered IN-list values produce identical sorted params
- [ ] Canonical demo query ("companies in the Northeast") returns exact same row set every time
- [ ] `compiled_hash` is content-addressed over canonical JSON `{"where_sql": ..., "params": [...]}` (order-preserving, not sorted)

### Frontend

- [ ] PreviewCard shows filter explanation bar when `filter_explanation` is present
- [ ] Compiled filter is collapsible and shows `compiled_filter` SQL
- [ ] Filter audit metadata (`filter_audit`) is included in preview payload

### Execution Determinism Release Gate (Task 29 — must pass before merge)

- [ ] `pytest tests/db/test_row_inflight_status.py -v` — all pass
- [ ] `pytest tests/services/test_idempotency.py -v` — all pass
- [ ] `pytest tests/services/test_batch_engine_inflight.py -v` — all pass
- [ ] `pytest tests/services/test_label_staging.py -v` — all pass
- [ ] `pytest tests/orchestrator/batch/test_inflight_recovery.py -v` — all pass
- [ ] `pytest tests/services/test_write_back_worker.py -v` — all pass
- [ ] `pytest tests/api/test_startup_recovery.py -v` — all pass
- [ ] `pytest tests/integration/test_execution_determinism.py -v` — all pass
- [ ] No duplicate shipments on crash-retry (tested with injected failures)
- [ ] In-flight rows with `ups_transaction_id` recovered via `track_package(tracking_number=...)` (Tier 1)
- [ ] In-flight rows without tracking info marked `needs_review` — never auto-retried (Tier 2)
- [ ] Recovery report includes per-row details with idempotency keys for operator action
- [ ] `needs_review` status is terminal — requires explicit operator resolution
- [ ] Idempotency key included in UPS payload as `TransactionReference.CustomerContext` (audit only, not dedup)
- [ ] Labels promoted to final path BEFORE DB commit (staging → rename → commit)
- [ ] Write-back survives partial completion via durable queue
- [ ] Orphaned staging labels cleaned on startup (only for jobs without in_flight/needs_review rows)
- [ ] Schema migration adds `idempotency_key`, `ups_transaction_id`, `needs_review` columns to existing DBs
- [ ] Schema migration creates `write_back_queue` table on existing DBs

---

## Dependency Graph

```
Phase 1 (Foundation)
  Task 1: FilterSpec Models ─────────┐
  Task 2: Canonical Constants ───────┤
  Task 3: Error Codes ──────────────┤
                                     │
Phase 2 (Core Engine)                │
  Task 4: SQL Compiler ◄────────────┤
  Task 5: Semantic Resolver ◄───────┘
       │          │
Phase 3 (MCP Layer)
  Task 6: Parameterized Queries
  Task 7: Column Samples
       │          │
Phase 4 (Tool Integration)
  Task 8: resolve_filter_intent ◄──── Task 5
  Task 9: Pipeline + filter_spec ◄─── Task 4, 6
  Task 10: fetch_rows + filter_spec ◄─ Task 4, 6
  Task 11: Tool Definitions ◄──────── Task 8, 9, 10
  Task 12: Preview Emission
       │
Phase 5 (Enforcement)
  Task 13: Hook Enforcement ◄──────── Task 11
  Task 14: Session Manager
  Task 15: System Prompt ◄────────── Task 2
       │
Phase 6 (Frontend)
  Task 16: Frontend Types
  Task 17: PreviewCard ◄──────────── Task 16
       │
Phase 7 (Cleanup)
  Task 18: Update Existing Tests
  Task 19: Conversation Route
  Task 20: Determinism Acceptance Tests (release gate)
       │
Phase 8 (Execution Determinism)
  Task 21: JobRow in_flight status + idempotency columns
  Task 22: Idempotency key generation ◄──── Task 21
  Task 23: TransactionReference in UPS payload ◄── Task 22
  Task 24: BatchEngine in-flight state machine ◄── Task 21, 22, 23
  Task 25: Label staging + atomic promote ◄──── Task 24
  Task 26: In-flight row recovery ◄──────── Task 24
  Task 27: Write-back queue + worker ◄───── Task 24
  Task 28: Startup recovery wiring ◄──────── Task 25, 26, 27
  Task 29: Execution determinism acceptance tests (release gate)
```
