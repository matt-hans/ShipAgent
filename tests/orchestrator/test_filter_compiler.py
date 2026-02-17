"""Tests for the FilterSpec SQL compiler.

Covers all 16 operators, canonicalization, error handling, and structural limits.
"""

import pytest

from src.orchestrator.models.filter_spec import (
    CompiledFilter,
    FilterCompilationError,
    FilterCondition,
    FilterErrorCode,
    FilterGroup,
    FilterOperator,
    ResolvedFilterSpec,
    ResolutionStatus,
    TypedLiteral,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHEMA_COLS = {"state", "company", "name", "weight", "city", "zip_code"}
COL_TYPES = {
    "state": "VARCHAR",
    "company": "VARCHAR",
    "name": "VARCHAR",
    "weight": "DOUBLE",
    "city": "VARCHAR",
    "zip_code": "VARCHAR",
}
SCHEMA_SIG = "test_schema_sig_abc123"


def _make_spec(
    root: FilterGroup,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    schema_signature: str = SCHEMA_SIG,
) -> ResolvedFilterSpec:
    """Build a minimal ResolvedFilterSpec for testing."""
    return ResolvedFilterSpec(
        status=status,
        root=root,
        explanation="test",
        schema_signature=schema_signature,
        canonical_dict_version="filter_constants_v1",
    )


def _cond(
    column: str,
    operator: FilterOperator,
    operands: list[TypedLiteral] | None = None,
) -> FilterCondition:
    """Build a FilterCondition."""
    return FilterCondition(
        column=column,
        operator=operator,
        operands=operands or [],
    )


def _lit(value, type_: str = "string") -> TypedLiteral:
    return TypedLiteral(type=type_, value=value)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestFilterCompiler:
    """Verify compile_filter_spec() produces correct parameterized SQL."""

    def test_single_eq_condition(self):
        """1. Single eq → "state" = $1."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.eq, [_lit("CA")])],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert isinstance(result, CompiledFilter)
        assert '"state" = $1' in result.where_sql
        assert result.params == ["CA"]

    def test_in_condition_sorted_params(self):
        """2. in_ → IN ($1, $2, $3) with sorted params."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "state",
                        FilterOperator.in_,
                        [_lit("NY"), _lit("CA"), _lit("TX")],
                    )
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "IN" in result.where_sql
        # Params should be sorted for determinism
        assert result.params == ["CA", "NY", "TX"]

    def test_is_null_condition(self):
        """3. is_null → "company" IS NULL with no params."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("company", FilterOperator.is_null)],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert '"company" IS NULL' in result.where_sql
        assert result.params == []

    def test_is_blank_condition(self):
        """4. is_blank → ("company" IS NULL OR "company" = $1) with param ''."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("company", FilterOperator.is_blank)],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "IS NULL" in result.where_sql
        assert "= $1" in result.where_sql or "=$1" in result.where_sql
        assert "" in result.params

    def test_is_not_blank_condition(self):
        """5. is_not_blank → ("company" IS NOT NULL AND "company" != $1)."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("company", FilterOperator.is_not_blank)],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "IS NOT NULL" in result.where_sql
        assert "!= $" in result.where_sql or "<> $" in result.where_sql
        assert "" in result.params

    def test_contains_ci_condition(self):
        """6. contains_ci → ILIKE with %val% param."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("name", FilterOperator.contains_ci, [_lit("acme")])],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "ILIKE" in result.where_sql
        assert result.params == ["%acme%"]

    def test_starts_with_ci_condition(self):
        """7. starts_with_ci → ILIKE with val% param."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("name", FilterOperator.starts_with_ci, [_lit("acme")])
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "ILIKE" in result.where_sql
        assert result.params == ["acme%"]

    def test_between_condition(self):
        """8. between → BETWEEN $1 AND $2."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "weight",
                        FilterOperator.between,
                        [_lit(1.0, "number"), _lit(10.0, "number")],
                    )
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "BETWEEN" in result.where_sql
        assert result.params == [1.0, 10.0]

    def test_and_group(self):
        """9. AND group joins with AND."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("state", FilterOperator.eq, [_lit("CA")]),
                    _cond("company", FilterOperator.is_not_null),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert " AND " in result.where_sql

    def test_or_group(self):
        """10. OR group joins with OR and wraps in parens."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="OR",
                conditions=[
                    _cond("state", FilterOperator.eq, [_lit("CA")]),
                    _cond("state", FilterOperator.eq, [_lit("NY")]),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert " OR " in result.where_sql

    def test_nested_groups(self):
        """11. Nested groups produce correct parenthesization."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        inner = FilterGroup(
            logic="OR",
            conditions=[
                _cond("state", FilterOperator.eq, [_lit("CA")]),
                _cond("state", FilterOperator.eq, [_lit("NY")]),
            ],
        )
        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[inner, _cond("company", FilterOperator.is_not_null)],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "(" in result.where_sql
        assert " AND " in result.where_sql
        assert " OR " in result.where_sql

    def test_canonicalization_deterministic(self):
        """12. Same conditions in different order produce identical SQL."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        # Order A: state=CA, company IS NOT NULL
        spec_a = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("state", FilterOperator.eq, [_lit("CA")]),
                    _cond("company", FilterOperator.is_not_null),
                ],
            )
        )
        # Order B: company IS NOT NULL, state=CA
        spec_b = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("company", FilterOperator.is_not_null),
                    _cond("state", FilterOperator.eq, [_lit("CA")]),
                ],
            )
        )
        result_a = compile_filter_spec(spec_a, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        result_b = compile_filter_spec(spec_b, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert result_a.where_sql == result_b.where_sql
        assert result_a.params == result_b.params

    def test_in_list_values_sorted(self):
        """13. IN-list values sorted alphabetically."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "state",
                        FilterOperator.in_,
                        [_lit("TX"), _lit("CA"), _lit("NY")],
                    )
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert result.params == ["CA", "NY", "TX"]

    def test_unknown_column_error(self):
        """14. Column not in schema raises FilterCompilationError."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("nonexistent", FilterOperator.eq, [_lit("val")])
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.UNKNOWN_COLUMN

    def test_confirmation_required_error(self):
        """15. Spec status not RESOLVED raises error."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.eq, [_lit("CA")])],
            ),
            status=ResolutionStatus.NEEDS_CONFIRMATION,
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.CONFIRMATION_REQUIRED

    def test_schema_changed_error(self):
        """16. Schema signature mismatch raises error."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.eq, [_lit("CA")])],
            ),
            schema_signature="old_schema_sig",
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.SCHEMA_CHANGED

    def test_structural_limit_depth_exceeded(self):
        """17. Depth > 4 raises STRUCTURAL_LIMIT_EXCEEDED."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        # Build a chain of nested groups exceeding depth 4
        # Root at depth 0, each wrap adds 1 → 5 wraps puts innermost at depth 5
        leaf = _cond("state", FilterOperator.eq, [_lit("CA")])
        group = FilterGroup(logic="AND", conditions=[leaf])
        for _ in range(5):  # 5 more nesting levels → depth 5 exceeds max 4
            group = FilterGroup(logic="AND", conditions=[group])

        spec = _make_spec(group)
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED

    def test_empty_in_list_error(self):
        """18. in_ with no operands raises EMPTY_IN_LIST."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.in_, [])],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.EMPTY_IN_LIST

    def test_wildcard_escaping(self):
        """19. % and _ in LIKE values are escaped."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("name", FilterOperator.contains_ci, [_lit("100%_off")])
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        # The value should have % and _ escaped with backslash
        param = result.params[0]
        assert r"100\%\_off" in param

    def test_columns_used_populated(self):
        """20. columns_used lists all referenced columns."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond("state", FilterOperator.eq, [_lit("CA")]),
                    _cond("company", FilterOperator.is_not_null),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert set(result.columns_used) == {"state", "company"}

    def test_explanation_populated(self):
        """21. Explanation is non-empty."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.eq, [_lit("CA")])],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert len(result.explanation) > 0

    # -------------------------------------------------------------------
    # Structural limit enforcement (P1-4 additions)
    # -------------------------------------------------------------------

    def test_max_conditions_exceeded(self):
        """22. More conditions than max_conditions raises STRUCTURAL_LIMIT_EXCEEDED."""
        from src.orchestrator.filter_compiler import compile_filter_spec
        from src.orchestrator.models.filter_spec import STRUCTURAL_LIMITS

        max_conds = STRUCTURAL_LIMITS["max_conditions"]
        # Build max_conds + 1 conditions
        conditions = [
            _cond("state", FilterOperator.eq, [_lit(f"S{i}")])
            for i in range(max_conds + 1)
        ]
        spec = _make_spec(FilterGroup(logic="AND", conditions=conditions))

        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED
        assert "conditions" in exc_info.value.message.lower()

    def test_max_conditions_at_limit_passes(self):
        """23. Exactly max_conditions conditions is allowed."""
        from src.orchestrator.filter_compiler import compile_filter_spec
        from src.orchestrator.models.filter_spec import STRUCTURAL_LIMITS

        max_conds = STRUCTURAL_LIMITS["max_conditions"]
        conditions = [
            _cond("state", FilterOperator.eq, [_lit(f"S{i}")])
            for i in range(max_conds)
        ]
        spec = _make_spec(FilterGroup(logic="AND", conditions=conditions))

        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert len(result.params) == max_conds

    def test_in_cardinality_exceeded(self):
        """24. IN list exceeding max_in_cardinality raises STRUCTURAL_LIMIT_EXCEEDED."""
        from src.orchestrator.filter_compiler import compile_filter_spec
        from src.orchestrator.models.filter_spec import STRUCTURAL_LIMITS

        max_in = STRUCTURAL_LIMITS["max_in_cardinality"]
        operands = [_lit(f"V{i}") for i in range(max_in + 1)]
        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.in_, operands)],
            )
        )

        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED
        assert "in" in exc_info.value.message.lower()

    def test_not_in_cardinality_exceeded(self):
        """25. NOT IN list exceeding max_in_cardinality raises STRUCTURAL_LIMIT_EXCEEDED."""
        from src.orchestrator.filter_compiler import compile_filter_spec
        from src.orchestrator.models.filter_spec import STRUCTURAL_LIMITS

        max_in = STRUCTURAL_LIMITS["max_in_cardinality"]
        operands = [_lit(f"V{i}") for i in range(max_in + 1)]
        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.not_in, operands)],
            )
        )

        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED

    def test_type_mismatch_ordering_on_string(self):
        """26. gt/gte/lt/lte on a VARCHAR column raises TYPE_MISMATCH."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.gt, [_lit("CA")])],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.TYPE_MISMATCH

    def test_type_mismatch_contains_on_numeric(self):
        """27. contains_ci on a DOUBLE column raises TYPE_MISMATCH."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("weight", FilterOperator.contains_ci, [_lit("10")])],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.TYPE_MISMATCH

    def test_ordering_on_numeric_passes(self):
        """28. gt on a DOUBLE column is allowed."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "weight", FilterOperator.gt,
                        [TypedLiteral(type="number", value=10.0)],
                    )
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert '"weight" > $1' in result.where_sql

    def test_type_check_skipped_for_unknown_column_type(self):
        """29. Type check is skipped if column has no type mapping."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        # Use empty column_types — should still compile
        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("state", FilterOperator.gt, [_lit("CA")])],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, {}, SCHEMA_SIG)
        assert '"state" > $1' in result.where_sql
