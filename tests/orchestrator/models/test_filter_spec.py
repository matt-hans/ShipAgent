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
            FilterCondition,
            FilterOperator,
            TypedLiteral,
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
            FilterCondition,
            FilterOperator,
            TypedLiteral,
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
            FilterCondition,
            FilterOperator,
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
            FilterCondition,
            FilterGroup,
            FilterOperator,
            TypedLiteral,
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
            FilterCondition,
            FilterGroup,
            FilterOperator,
            TypedLiteral,
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
            FilterCondition,
            FilterGroup,
            FilterIntent,
            FilterOperator,
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
            FilterCondition,
            FilterGroup,
            FilterOperator,
            ResolutionStatus,
            ResolvedFilterSpec,
            TypedLiteral,
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
            FilterCompilationError,
            FilterErrorCode,
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
