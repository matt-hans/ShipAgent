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

SCHEMA_COLS = {
    "state",
    "company",
    "name",
    "weight",
    "city",
    "zip_code",
    "total_price",
}
COL_TYPES = {
    "state": "VARCHAR",
    "company": "VARCHAR",
    "name": "VARCHAR",
    "weight": "DOUBLE",
    "city": "VARCHAR",
    "zip_code": "VARCHAR",
    "total_price": "VARCHAR",
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
        """4. is_blank treats null/empty/whitespace as blank with param ''."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("company", FilterOperator.is_blank)],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "TRIM(CAST(COALESCE(\"company\", '') AS VARCHAR))" in result.where_sql
        assert "= $1" in result.where_sql or "=$1" in result.where_sql
        assert "" in result.params

    def test_is_not_blank_condition(self):
        """5. is_not_blank excludes null/empty/whitespace-only values."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("company", FilterOperator.is_not_blank)],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "TRIM(CAST(COALESCE(\"company\", '') AS VARCHAR))" in result.where_sql
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

    def test_ordering_on_numeric_like_varchar_passes(self):
        """29. gt on numeric-like VARCHAR column uses TRY_CAST and numeric param."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[_cond("total_price", FilterOperator.gt, [_lit("$50")])],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "TRY_CAST" in result.where_sql
        assert '"total_price"' in result.where_sql
        assert result.params == [50.0]

    def test_between_on_numeric_like_varchar_passes(self):
        """30. between on numeric-like VARCHAR column compiles with coerced params."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "total_price",
                        FilterOperator.between,
                        [_lit("50"), _lit("500")],
                    )
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "TRY_CAST" in result.where_sql
        assert "BETWEEN $1 AND $2" in result.where_sql
        assert result.params == [50.0, 500.0]

    def test_type_check_skipped_for_unknown_column_type(self):
        """31. Type check is skipped if column has no type mapping."""
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


class TestExplanationOperators:
    """Verify that compiled explanations preserve AND/OR logic."""

    def test_single_condition_explanation(self):
        """Single condition produces no operator in explanation."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="NY")],
                    ),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert result.explanation == "Filter: state equals NY."

    def test_multi_condition_and_explanation(self):
        """Multi-condition AND uses 'AND' in explanation, not semicolons."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="NY")],
                    ),
                    FilterCondition(
                        column="weight",
                        operator=FilterOperator.gt,
                        operands=[TypedLiteral(type="number", value=10)],
                    ),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "AND" in result.explanation
        assert ";" not in result.explanation

    def test_multi_condition_or_explanation(self):
        """Multi-condition OR uses 'OR' in explanation."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="OR",
                conditions=[
                    FilterCondition(
                        column="weight",
                        operator=FilterOperator.gt,
                        operands=[TypedLiteral(type="number", value=24)],
                    ),
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="CA")],
                    ),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "OR" in result.explanation
        assert ";" not in result.explanation

    def test_nested_mixed_explanation(self):
        """Nested mixed AND/OR preserves grouping with parentheses."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterGroup(
                        logic="OR",
                        conditions=[
                            FilterCondition(
                                column="state",
                                operator=FilterOperator.in_,
                                operands=[
                                    TypedLiteral(type="string", value="CA"),
                                    TypedLiteral(type="string", value="TX"),
                                ],
                            ),
                            FilterCondition(
                                column="weight",
                                operator=FilterOperator.gt,
                                operands=[TypedLiteral(type="number", value=10)],
                            ),
                        ],
                    ),
                    FilterCondition(
                        column="total_price",
                        operator=FilterOperator.gt,
                        operands=[TypedLiteral(type="number", value=200)],
                    ),
                ],
            )
        )
        result = compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert "OR" in result.explanation
        assert "AND" in result.explanation
        assert "(" in result.explanation
        assert ";" not in result.explanation


class TestCustomAttributesFiltering:
    """JSON path filtering for custom_attributes column."""

    def test_custom_attributes_dot_path_compiles(self):
        """custom_attributes.gift_message generates json_extract SQL."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="custom_attributes.gift_message",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="yes")],
                    ),
                ],
            )
        )
        schema = SCHEMA_COLS | {"custom_attributes"}
        col_types = {**COL_TYPES, "custom_attributes": "VARCHAR"}
        result = compile_filter_spec(spec, schema, col_types, SCHEMA_SIG)
        assert "json_extract_string" in result.where_sql
        assert "gift_message" in result.where_sql

    def test_custom_attributes_missing_base_column_raises(self):
        """custom_attributes.key raises error when custom_attributes not in schema."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="custom_attributes.some_key",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="x")],
                    ),
                ],
            )
        )
        # Schema does NOT include custom_attributes
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(spec, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG)
        assert exc_info.value.code == FilterErrorCode.UNKNOWN_COLUMN

    def test_custom_attributes_tracks_column_usage(self):
        """custom_attributes.key adds 'custom_attributes' to columns_used."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="custom_attributes.priority_flag",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="true")],
                    ),
                ],
            )
        )
        schema = SCHEMA_COLS | {"custom_attributes"}
        col_types = {**COL_TYPES, "custom_attributes": "VARCHAR"}
        result = compile_filter_spec(spec, schema, col_types, SCHEMA_SIG)
        assert "custom_attributes" in result.columns_used


class TestCustomAttributeJsonPath:
    """Verify JSON path ordering operators and key sanitizer for custom_attributes."""

    # Shared schema that includes custom_attributes
    _SCHEMA = SCHEMA_COLS | {"custom_attributes"}
    _COL_TYPES = {**COL_TYPES, "custom_attributes": "VARCHAR"}

    # -------------------------------------------------------------------
    # Fix 1 — Ordering operators use json_extract_string, not raw col ref
    # -------------------------------------------------------------------

    def test_gt_uses_json_extract_string(self):
        """custom_attributes.priority gt 5 uses json_extract_string, not raw column."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.priority",
                        FilterOperator.gt,
                        [_lit(5, "number")],
                    )
                ],
            )
        )
        result = compile_filter_spec(
            spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
        )
        assert "json_extract_string" in result.where_sql
        # Must NOT contain the dotted column name as a quoted identifier
        assert '"custom_attributes.priority"' not in result.where_sql

    def test_between_uses_json_extract_string(self):
        """custom_attributes.score between 1 and 10 uses json_extract_string."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.score",
                        FilterOperator.between,
                        [_lit(1, "number"), _lit(10, "number")],
                    )
                ],
            )
        )
        result = compile_filter_spec(
            spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
        )
        assert "json_extract_string" in result.where_sql
        assert "BETWEEN" in result.where_sql
        assert '"custom_attributes.score"' not in result.where_sql

    def test_eq_still_works_for_json_path(self):
        """custom_attributes.priority eq 'high' compiles correctly (equality path)."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.priority",
                        FilterOperator.eq,
                        [_lit("high")],
                    )
                ],
            )
        )
        result = compile_filter_spec(
            spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
        )
        assert "json_extract_string" in result.where_sql
        assert result.params == ["high"]

    # -------------------------------------------------------------------
    # Fix 5 — JSON key sanitizer allows hyphens and dots
    # -------------------------------------------------------------------

    def test_hyphenated_key_compiles(self):
        """custom_attributes.gift-message compiles successfully."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.gift-message",
                        FilterOperator.eq,
                        [_lit("Happy birthday")],
                    )
                ],
            )
        )
        result = compile_filter_spec(
            spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
        )
        assert "json_extract_string" in result.where_sql
        assert "gift-message" in result.where_sql

    def test_dotted_nested_key_compiles(self):
        """custom_attributes.some.nested.key compiles successfully."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.some.nested.key",
                        FilterOperator.eq,
                        [_lit("val")],
                    )
                ],
            )
        )
        result = compile_filter_spec(
            spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
        )
        assert "json_extract_string" in result.where_sql
        assert "some.nested.key" in result.where_sql

    def test_semicolon_in_key_raises(self):
        """custom_attributes.bad;key raises FilterCompilationError (SQL injection)."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.bad;key",
                        FilterOperator.eq,
                        [_lit("x")],
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(
                spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
            )
        assert exc_info.value.code == FilterErrorCode.UNKNOWN_COLUMN

    def test_single_quote_in_key_raises(self):
        """custom_attributes.bad'key raises FilterCompilationError (SQL injection)."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.bad'key",
                        FilterOperator.eq,
                        [_lit("x")],
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(
                spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
            )
        assert exc_info.value.code == FilterErrorCode.UNKNOWN_COLUMN

    def test_non_numeric_ordering_on_json_path_raises(self):
        """custom_attributes.priority > 'high' raises TYPE_MISMATCH at compile time."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.priority",
                        FilterOperator.gt,
                        [_lit("high")],
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(
                spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
            )
        assert exc_info.value.code == FilterErrorCode.TYPE_MISMATCH

    def test_non_numeric_between_on_json_path_raises(self):
        """custom_attributes.score BETWEEN 'low' AND 'high' raises TYPE_MISMATCH."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.score",
                        FilterOperator.between,
                        [_lit("low"), _lit("high")],
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            compile_filter_spec(
                spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
            )
        assert exc_info.value.code == FilterErrorCode.TYPE_MISMATCH

    def test_numeric_string_ordering_on_json_path_accepted(self):
        """custom_attributes.priority > '5' compiles (numeric string is valid)."""
        from src.orchestrator.filter_compiler import compile_filter_spec

        spec = _make_spec(
            FilterGroup(
                logic="AND",
                conditions=[
                    _cond(
                        "custom_attributes.priority",
                        FilterOperator.gt,
                        [_lit("5")],
                    )
                ],
            )
        )
        result = compile_filter_spec(
            spec, self._SCHEMA, self._COL_TYPES, SCHEMA_SIG,
        )
        assert result.params == [5.0]
