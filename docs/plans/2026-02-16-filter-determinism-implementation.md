# FilterSpec Compiler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace non-deterministic free-form SQL filter generation with a structured FilterSpec JSON compiler that guarantees identical queries for identical inputs.

**Architecture:** The LLM outputs typed `FilterIntent` JSON (never SQL). A pure-function semantic resolver expands canonical terms (regions, business predicates) into concrete conditions. A pure-function SQL compiler produces parameterized DuckDB queries. Hook-level enforcement denies any raw SQL bypass.

**Tech Stack:** Python 3.12+, Pydantic v2, DuckDB parameterized queries, HMAC (stdlib `hmac`), FastMCP, React + TypeScript (frontend)

**Design Reference:** `docs/plans/2026-02-16-filter-determinism-design.md`

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
            "in_", "not_in", "contains_ci", "starts_with_ci", "ends_with_ci",
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
    in_ = "in_"
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
    session_confirmations: dict[str, str] | None = None,
) -> ResolvedFilterSpec:
```

Key implementation details:
- Import canonical data from `filter_constants.py`
- `_resolve_node()` recursive helper dispatches on node type
- `_resolve_condition()` validates column, operator, arity
- `_resolve_semantic()` normalizes key, looks up tier, expands or flags
- `_generate_resolution_token()` uses `hmac.new()` with a server secret (from env `FILTER_TOKEN_SECRET` or random fallback)
- `_validate_resolution_token()` verifies HMAC + expiry
- `_match_target_column()` delegates to `filter_constants.match_column_pattern()`
- `_build_explanation()` generates human-readable text
- Status precedence: accumulate child statuses, return worst
- `_canonicalize_group()` sorts children deterministically

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

**Step 3: Modify `query_tools.py` to accept parameterized queries**

In `src/mcp/data_source/tools/query_tools.py`, update `get_rows_by_filter()` (lines 66-144) to accept optional `params: list[Any] = None`. When `params` is provided, use parameterized execution:

```python
async def get_rows_by_filter(
    where_clause: str,
    ctx: Context,
    limit: int = 100,
    offset: int = 0,
    params: list[Any] | None = None,
) -> dict:
```

Replace the raw f-string interpolation at lines 113-125 with:

```python
# Lines 113-116: Parameterized count
if params:
    total_count = db.execute(
        f'SELECT COUNT(*) FROM imported_data WHERE {where_clause}',
        params,
    ).fetchone()[0]
else:
    total_count = db.execute(
        f'SELECT COUNT(*) FROM imported_data WHERE {where_clause}',
    ).fetchone()[0]

# Lines 119-125: Parameterized rows query
if params:
    results = db.execute(f"""
        SELECT {SOURCE_ROW_NUM_COLUMN}, {select_clause}
        FROM imported_data
        WHERE {where_clause}
        ORDER BY {SOURCE_ROW_NUM_COLUMN}
        LIMIT {limit} OFFSET {offset}
    """, params).fetchall()
else:
    results = db.execute(f"""
        SELECT {SOURCE_ROW_NUM_COLUMN}, {select_clause}
        FROM imported_data
        WHERE {where_clause}
        ORDER BY {SOURCE_ROW_NUM_COLUMN}
        LIMIT {limit} OFFSET {offset}
    """).fetchall()
```

**Step 4: Run all existing data source tests to verify no regression**

Run: `pytest tests/mcp/data_source/ -v -k "not edi"`
Expected: All tests PASS (existing tests pass `params=None` and use the old path).

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

### Task 9: Update `ship_command_pipeline` to Accept `filter_spec`

**Files:**
- Modify: `src/orchestrator/agent/tools/pipeline.py:173-260`
- Modify: `src/services/data_source_mcp_client.py`
- Test: `tests/orchestrator/agent/test_pipeline_filter_spec.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_pipeline_filter_spec.py` testing:
- Pipeline accepts `filter_spec` and calls compiler
- Pipeline rejects raw `where_clause` when `filter_spec` is present
- Compiled SQL is passed to gateway with params
- Audit metadata is attached to preview result

**Step 2: Run test to verify it fails**

**Step 3: Update `ship_command_pipeline_tool()`**

In `src/orchestrator/agent/tools/pipeline.py:173-260`, update to:
1. Accept `filter_spec` dict from args
2. If `filter_spec` present: parse into `ResolvedFilterSpec`, compile via `compile_filter_spec()`, pass `where_sql` + `params` to gateway
3. If `filter_spec` absent but `where_clause` present: use legacy path (temporary migration)
4. Attach `filter_explanation`, `compiled_filter`, and `filter_audit` metadata to the result before calling `_emit_preview_ready()`

Update `DataSourceMCPClient.get_rows_by_filter()` to accept and forward `params`:

```python
async def get_rows_by_filter(
    self,
    where_clause: str | None = None,
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

### Task 10: Update `fetch_rows` to Accept `filter_spec`

**Files:**
- Modify: `src/orchestrator/agent/tools/data.py:72-103`
- Test: `tests/orchestrator/agent/test_fetch_rows_filter_spec.py`

**Step 1: Write the failing test**

Test that `fetch_rows_tool()` accepts `filter_spec`, compiles it, and passes parameterized query to gateway.

**Step 2: Run test to verify it fails**

**Step 3: Update `fetch_rows_tool()`**

Same pattern as pipeline: accept `filter_spec`, compile, pass `where_sql` + `params` to gateway. Fall back to `where_clause` for migration.

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
- `resolve_filter_intent` tool exists in batch mode
- `ship_command_pipeline` input schema has `filter_spec` property
- `fetch_rows` input schema has `filter_spec` property
- `validate_filter_syntax` still exists (migration stub)
- `resolve_filter_intent` is available in interactive mode too

**Step 2: Run test to verify it fails**

**Step 3: Update `get_all_tool_definitions()`**

In `src/orchestrator/agent/tools/__init__.py`:
1. Add import: `from src.orchestrator.agent.tools.data import resolve_filter_intent_tool`
2. Add `resolve_filter_intent` tool definition with `FilterIntent` input schema
3. Add `filter_spec` and `resolution_token` properties to `ship_command_pipeline` definition
4. Add `filter_spec` property to `fetch_rows` definition
5. Keep `validate_filter_syntax` as migration stub (will remove in Phase 7)

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

Add filter metadata to the SSE payload and slim LLM response. Only include if present in `result`:

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
    # Include filter metadata if available
    if "filter_explanation" in result:
        response["filter_explanation"] = result["filter_explanation"]
    return _ok(response)
```

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
    """Validate filter_spec structure on pipeline and fetch_rows."""

async def validate_intent_on_resolve(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate FilterIntent structure before resolution."""
```

Update `create_hook_matchers()` to include the new hooks in the PreToolUse chain.

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/test_filter_hooks.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/orchestrator/agent/hooks.py tests/orchestrator/agent/test_filter_hooks.py
git commit -m "feat: add deny_raw_sql and filter validation hooks"
```

---

### Task 14: Session Manager — Add Confirmed Resolutions

**Files:**
- Modify: `src/services/agent_session_manager.py:24-58`

**Step 1: Add `confirmed_resolutions` field to `AgentSession.__init__`**

```python
self.confirmed_resolutions: dict[str, Any] = {}  # token → confirmed ResolvedFilterSpec
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

## Phase 7: Migration Cleanup and Integration Testing

---

### Task 18: Update Existing Tests

**Files:**
- Modify: `tests/orchestrator/agent/test_tools_v2.py` (if it asserts `where_clause` in tool definitions)
- Modify: `tests/orchestrator/agent/test_system_prompt.py` (update SQL-assertion tests)

**Step 1: Run the full test suite to find failures**

Run: `pytest tests/ -v -k "not stream and not sse and not progress and not edi" --tb=short 2>&1 | tail -100`
Expected: Identify any tests that fail due to tool definition changes.

**Step 2: Fix failing tests**

Update assertions that check for `where_clause` in tool definitions to expect `filter_spec` alongside it. Update system prompt tests that assert SQL generation instructions.

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: update existing tests for FilterSpec migration"
```

---

### Task 19: Conversation Route — Pass Column Samples

**Files:**
- Modify: `src/api/routes/conversations.py`

**Step 1: Update `_ensure_agent()` and `_process_agent_message()`**

When building/rebuilding the agent, fetch column samples and pass them to `build_system_prompt()` for filter grounding. Also wire `session.confirmed_resolutions` through to the resolver tool.

**Step 2: Commit**

```bash
git add src/api/routes/conversations.py
git commit -m "feat: pass column samples and confirmed resolutions through conversation route"
```

---

### Task 20: Remove `validate_filter_syntax` (Post-Migration)

**Files:**
- Modify: `src/orchestrator/agent/tools/__init__.py` — remove tool definition
- Modify: `src/orchestrator/agent/tools/data.py` — remove handler
- Delete import from `__init__.py`

This task should be executed AFTER the FilterSpec pipeline is fully operational and tested end-to-end. Do NOT execute this during initial rollout.

**Step 1: Remove tool definition from registry**

**Step 2: Remove handler function**

**Step 3: Run full test suite**

**Step 4: Commit**

```bash
git add src/orchestrator/agent/tools/__init__.py src/orchestrator/agent/tools/data.py
git commit -m "refactor: remove deprecated validate_filter_syntax tool"
```

---

## Verification Checklist

After all tasks are complete, verify:

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
- [ ] System prompt contains "NEVER generate SQL" in batch mode
- [ ] System prompt contains FilterIntent schema documentation
- [ ] Hook enforcement denies raw `where_clause` on filter tools
- [ ] PreviewCard shows filter explanation when available

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
  Task 20: Remove validate_filter_syntax (deferred)
```
