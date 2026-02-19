"""FilterSpec SQL compiler — deterministic parameterized query generation.

Compiles a ResolvedFilterSpec AST into a parameterized DuckDB WHERE clause.
Guarantees: identical ResolvedFilterSpec + identical schema → identical SQL output.

See docs/plans/2026-02-16-filter-determinism-design.md Section 5.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Union

from src.orchestrator.models.filter_spec import (
    CompiledFilter,
    FilterCompilationError,
    FilterCondition,
    FilterErrorCode,
    FilterGroup,
    FilterOperator,
    ResolvedFilterSpec,
    ResolutionStatus,
    SemanticReference,
    STRUCTURAL_LIMITS,
    TypedLiteral,
)

COMPILER_VERSION = "filter_compiler_v2"


def compile_filter_spec(
    spec: ResolvedFilterSpec,
    schema_columns: set[str],
    column_types: dict[str, str],
    runtime_schema_signature: str,
) -> CompiledFilter:
    """Compile a resolved filter spec into parameterized SQL.

    Args:
        spec: Fully resolved filter spec (status must be RESOLVED).
        schema_columns: Set of valid column names in the data source.
        column_types: Mapping of column name → DuckDB type string.
        runtime_schema_signature: Current schema hash for staleness detection.

    Returns:
        CompiledFilter with parameterized WHERE clause and params.

    Raises:
        FilterCompilationError: On any compilation failure with deterministic code.
    """
    # Entry guards
    if spec.status != ResolutionStatus.RESOLVED:
        raise FilterCompilationError(
            FilterErrorCode.CONFIRMATION_REQUIRED,
            f"Cannot compile spec with status {spec.status.value}; "
            f"resolution must be RESOLVED.",
        )

    if spec.schema_signature and spec.schema_signature != runtime_schema_signature:
        raise FilterCompilationError(
            FilterErrorCode.SCHEMA_CHANGED,
            f"Schema changed since resolution. "
            f"Expected {spec.schema_signature!r}, got {runtime_schema_signature!r}.",
        )

    # Pre-flight structural checks (before compilation)
    condition_count = _count_conditions(spec.root)
    max_conditions = STRUCTURAL_LIMITS["max_conditions"]
    if condition_count > max_conditions:
        raise FilterCompilationError(
            FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED,
            f"Filter has {condition_count} conditions, exceeding maximum {max_conditions}.",
        )

    # Mutable state for tree walk
    param_counter = [0]  # mutable int via list
    params: list = []
    columns_used: set[str] = set()

    # Canonicalize and compile
    canonicalized_root = _canonicalize_group(spec.root)
    where_sql = _compile_group(
        canonicalized_root,
        schema_columns,
        column_types,
        param_counter,
        params,
        columns_used,
        depth=0,
    )

    # Post-flight structural check
    max_total_params = STRUCTURAL_LIMITS["max_total_params"]
    if len(params) > max_total_params:
        raise FilterCompilationError(
            FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED,
            f"Filter produces {len(params)} parameters, exceeding maximum {max_total_params}.",
        )

    return CompiledFilter(
        where_sql=where_sql,
        params=params,
        columns_used=sorted(columns_used),
        explanation=_build_explanation_from_ast(canonicalized_root),
        schema_signature=runtime_schema_signature,
    )


# ---------------------------------------------------------------------------
# Canonicalization — ensures deterministic output for commutative operations
# ---------------------------------------------------------------------------


def _serialize_node(
    node: Union[FilterCondition, SemanticReference, FilterGroup],
) -> str:
    """Serialize a node to a stable string for sorting."""
    if isinstance(node, FilterCondition):
        operand_values = sorted(
            [json.dumps(o.value, sort_keys=True, default=str) for o in node.operands]
        )
        return f"C:{node.column}:{node.operator.value}:{operand_values}"
    if isinstance(node, SemanticReference):
        return f"S:{node.semantic_key}:{node.target_column}"
    if isinstance(node, FilterGroup):
        children = sorted([_serialize_node(c) for c in node.conditions])
        return f"G:{node.logic}:{children}"
    return str(node)


def _canonicalize_group(group: FilterGroup) -> FilterGroup:
    """Sort children of commutative groups for deterministic output."""
    canonicalized_children = []
    for child in group.conditions:
        if isinstance(child, FilterGroup):
            canonicalized_children.append(_canonicalize_group(child))
        else:
            canonicalized_children.append(child)

    # Sort children by their serialized form
    sorted_children = sorted(canonicalized_children, key=_serialize_node)
    return FilterGroup(logic=group.logic, conditions=sorted_children)


# ---------------------------------------------------------------------------
# Compilation — recursive tree walk
# ---------------------------------------------------------------------------


def _compile_group(
    group: FilterGroup,
    schema_columns: set[str],
    column_types: dict[str, str],
    param_counter: list[int],
    params: list,
    columns_used: set[str],
    depth: int,
) -> str:
    """Compile a FilterGroup into a SQL fragment.

    Args:
        group: The filter group to compile.
        schema_columns: Valid column names.
        column_types: Mapping of column name to DuckDB type string.
        param_counter: Mutable parameter index counter.
        params: Accumulator for parameter values.
        columns_used: Accumulator for referenced columns.
        depth: Current nesting depth for structural limit checks.

    Returns:
        SQL WHERE clause fragment.

    Raises:
        FilterCompilationError: On structural limit violation or invalid nodes.
    """
    max_depth = STRUCTURAL_LIMITS["max_depth"]
    if depth > max_depth:
        raise FilterCompilationError(
            FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED,
            f"Nesting depth {depth} exceeds maximum {max_depth}.",
        )

    fragments = []
    for child in group.conditions:
        if isinstance(child, FilterCondition):
            sql = _compile_condition(
                child, schema_columns, column_types,
                param_counter, params, columns_used,
            )
            fragments.append(sql)
        elif isinstance(child, FilterGroup):
            sql = _compile_group(
                child,
                schema_columns,
                column_types,
                param_counter,
                params,
                columns_used,
                depth + 1,
            )
            # Wrap nested groups in parens for correct precedence
            fragments.append(f"({sql})")
        elif isinstance(child, SemanticReference):
            # Should have been resolved; this is an internal error
            raise FilterCompilationError(
                FilterErrorCode.CONFIRMATION_REQUIRED,
                f"Unresolved semantic reference {child.semantic_key!r} found in "
                f"compilation. Spec must be fully resolved before compilation.",
            )

    if not fragments:
        raise FilterCompilationError(
            FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED,
            "Filter group compiled to zero conditions. "
            "This can happen when all children are unresolved semantic references.",
        )

    joiner = f" {group.logic} "
    return joiner.join(fragments)


def _compile_condition(
    cond: FilterCondition,
    schema_columns: set[str],
    column_types: dict[str, str],
    param_counter: list[int],
    params: list,
    columns_used: set[str],
) -> str:
    """Compile a single FilterCondition into a SQL fragment.

    Args:
        cond: The condition to compile.
        schema_columns: Valid column names.
        column_types: Mapping of column name to DuckDB type string.
        param_counter: Mutable parameter index counter.
        params: Accumulator for parameter values.
        columns_used: Accumulator for referenced columns.

    Returns:
        SQL fragment string.

    Raises:
        FilterCompilationError: On unknown column, empty IN list, type mismatch, etc.
    """
    # Validate column
    if cond.column not in schema_columns:
        raise FilterCompilationError(
            FilterErrorCode.UNKNOWN_COLUMN,
            f"Column {cond.column!r} not found in schema. "
            f"Available: {sorted(schema_columns)}.",
        )

    # Type-check operator/column compatibility
    _check_operator_type_compat(cond.column, cond.operator, column_types)

    columns_used.add(cond.column)
    col = f'"{cond.column}"'
    op = cond.operator
    blank_normalized_col = f"TRIM(CAST(COALESCE({col}, '') AS VARCHAR))"

    # Dispatch by operator
    if op == FilterOperator.eq:
        idx = _next_param(param_counter, params, _extract_value(cond.operands[0]))
        return f"{col} = ${idx}"

    elif op == FilterOperator.neq:
        idx = _next_param(param_counter, params, _extract_value(cond.operands[0]))
        return f"{col} != ${idx}"

    elif op == FilterOperator.gt:
        idx = _next_param(
            param_counter,
            params,
            _extract_ordering_value(cond.operands[0], cond.column, column_types),
        )
        ordering_col = _ordering_column_sql(cond.column, column_types)
        return f"{ordering_col} > ${idx}"

    elif op == FilterOperator.gte:
        idx = _next_param(
            param_counter,
            params,
            _extract_ordering_value(cond.operands[0], cond.column, column_types),
        )
        ordering_col = _ordering_column_sql(cond.column, column_types)
        return f"{ordering_col} >= ${idx}"

    elif op == FilterOperator.lt:
        idx = _next_param(
            param_counter,
            params,
            _extract_ordering_value(cond.operands[0], cond.column, column_types),
        )
        ordering_col = _ordering_column_sql(cond.column, column_types)
        return f"{ordering_col} < ${idx}"

    elif op == FilterOperator.lte:
        idx = _next_param(
            param_counter,
            params,
            _extract_ordering_value(cond.operands[0], cond.column, column_types),
        )
        ordering_col = _ordering_column_sql(cond.column, column_types)
        return f"{ordering_col} <= ${idx}"

    elif op == FilterOperator.in_:
        if not cond.operands:
            raise FilterCompilationError(
                FilterErrorCode.EMPTY_IN_LIST,
                f"IN operator on {cond.column!r} has no values.",
            )
        max_in = STRUCTURAL_LIMITS["max_in_cardinality"]
        if len(cond.operands) > max_in:
            raise FilterCompilationError(
                FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED,
                f"IN list on {cond.column!r} has {len(cond.operands)} values, "
                f"exceeding maximum {max_in}.",
            )
        # Sort operands for determinism
        sorted_operands = sorted(cond.operands, key=lambda o: str(o.value))
        placeholders = []
        for operand in sorted_operands:
            idx = _next_param(param_counter, params, _extract_value(operand))
            placeholders.append(f"${idx}")
        return f"{col} IN ({', '.join(placeholders)})"

    elif op == FilterOperator.not_in:
        if not cond.operands:
            raise FilterCompilationError(
                FilterErrorCode.EMPTY_IN_LIST,
                f"NOT IN operator on {cond.column!r} has no values.",
            )
        max_in = STRUCTURAL_LIMITS["max_in_cardinality"]
        if len(cond.operands) > max_in:
            raise FilterCompilationError(
                FilterErrorCode.STRUCTURAL_LIMIT_EXCEEDED,
                f"NOT IN list on {cond.column!r} has {len(cond.operands)} values, "
                f"exceeding maximum {max_in}.",
            )
        sorted_operands = sorted(cond.operands, key=lambda o: str(o.value))
        placeholders = []
        for operand in sorted_operands:
            idx = _next_param(param_counter, params, _extract_value(operand))
            placeholders.append(f"${idx}")
        return f"{col} NOT IN ({', '.join(placeholders)})"

    elif op == FilterOperator.contains_ci:
        raw_val = str(cond.operands[0].value)
        escaped = _escape_like_value(raw_val)
        idx = _next_param(param_counter, params, f"%{escaped}%")
        return f"{col} ILIKE ${idx} ESCAPE '\\'"

    elif op == FilterOperator.starts_with_ci:
        raw_val = str(cond.operands[0].value)
        escaped = _escape_like_value(raw_val)
        idx = _next_param(param_counter, params, f"{escaped}%")
        return f"{col} ILIKE ${idx} ESCAPE '\\'"

    elif op == FilterOperator.ends_with_ci:
        raw_val = str(cond.operands[0].value)
        escaped = _escape_like_value(raw_val)
        idx = _next_param(param_counter, params, f"%{escaped}")
        return f"{col} ILIKE ${idx} ESCAPE '\\'"

    elif op == FilterOperator.is_null:
        return f"{col} IS NULL"

    elif op == FilterOperator.is_not_null:
        return f"{col} IS NOT NULL"

    elif op == FilterOperator.is_blank:
        idx = _next_param(param_counter, params, "")
        return f"({blank_normalized_col} = ${idx})"

    elif op == FilterOperator.is_not_blank:
        idx = _next_param(param_counter, params, "")
        return f"({blank_normalized_col} != ${idx})"

    elif op == FilterOperator.between:
        idx_lo = _next_param(
            param_counter,
            params,
            _extract_ordering_value(cond.operands[0], cond.column, column_types),
        )
        idx_hi = _next_param(
            param_counter,
            params,
            _extract_ordering_value(cond.operands[1], cond.column, column_types),
        )
        ordering_col = _ordering_column_sql(cond.column, column_types)
        return f"{ordering_col} BETWEEN ${idx_lo} AND ${idx_hi}"

    else:
        raise FilterCompilationError(
            FilterErrorCode.INVALID_OPERATOR,
            f"Unknown operator {op!r}.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_conditions(
    node: Union[FilterGroup, FilterCondition, SemanticReference],
) -> int:
    """Count total leaf conditions in the AST.

    Args:
        node: Root node to count from.

    Returns:
        Total number of FilterCondition leaves.
    """
    if isinstance(node, FilterCondition):
        return 1
    if isinstance(node, FilterGroup):
        return sum(_count_conditions(c) for c in node.conditions)
    return 0  # SemanticReference


# Operators that require numeric or date columns (ordering comparisons)
_ORDERING_OPS = {
    FilterOperator.gt, FilterOperator.gte,
    FilterOperator.lt, FilterOperator.lte,
    FilterOperator.between,
}

# Operators that require string columns (pattern matching)
_STRING_OPS = {
    FilterOperator.contains_ci,
    FilterOperator.starts_with_ci,
    FilterOperator.ends_with_ci,
}

# DuckDB types considered numeric
_NUMERIC_TYPES = {"INTEGER", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "HUGEINT"}

# DuckDB types compatible with ordering operators
_ORDERABLE_TYPES = _NUMERIC_TYPES | {"DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE"}

# DuckDB types compatible with string pattern operators
_STRING_TYPES = {"VARCHAR", "TEXT", "STRING"}
_NUMERIC_TEXT_HINTS = {
    "amount",
    "price",
    "total",
    "subtotal",
    "cost",
    "value",
    "tax",
    "discount",
    "balance",
}


def _check_operator_type_compat(
    column: str,
    operator: FilterOperator,
    column_types: dict[str, str],
) -> None:
    """Check operator/column type compatibility.

    Silently passes if column type is unknown (not in column_types dict).

    Args:
        column: Column name.
        operator: The filter operator being applied.
        column_types: Mapping of column name to DuckDB type string.

    Raises:
        FilterCompilationError: On type mismatch.
    """
    raw_type = column_types.get(column, "").upper()
    if not raw_type:
        return  # Unknown type — skip check

    # Normalize parameterized types: DECIMAL(10,2) → DECIMAL, VARCHAR(255) → VARCHAR
    col_type = raw_type.split("(")[0].strip()

    if operator in _ORDERING_OPS:
        if col_type in _ORDERABLE_TYPES:
            return
        if _is_numeric_text_column(column, col_type):
            return
        raise FilterCompilationError(
            FilterErrorCode.TYPE_MISMATCH,
            f"Operator {operator.value!r} requires a numeric or date column, "
            f"but {column!r} has type {col_type!r}.",
        )

    if operator in _STRING_OPS and col_type not in _STRING_TYPES:
        raise FilterCompilationError(
            FilterErrorCode.TYPE_MISMATCH,
            f"Operator {operator.value!r} requires a string column, "
            f"but {column!r} has type {col_type!r}.",
        )


def _is_numeric_text_column(column: str, col_type: str) -> bool:
    """Return True when a string column is likely to contain numeric values."""
    if col_type not in _STRING_TYPES:
        return False
    lowered = column.casefold()
    return any(hint in lowered for hint in _NUMERIC_TEXT_HINTS)


def _ordering_column_sql(column: str, column_types: dict[str, str]) -> str:
    """Return SQL expression used for ordering comparisons on a column."""
    col = f'"{column}"'
    raw_type = column_types.get(column, "").upper()
    col_type = raw_type.split("(")[0].strip() if raw_type else ""
    if _is_numeric_text_column(column, col_type):
        # Accept numeric-like text such as "$123.45" or "1,234.56".
        return (
            f"TRY_CAST(REPLACE(REPLACE(TRIM(COALESCE({col}, '')), '$', ''), ',', '') "
            "AS DOUBLE)"
        )
    return col


def _extract_ordering_value(
    literal: TypedLiteral,
    column: str,
    column_types: dict[str, str],
) -> object:
    """Extract value for ordering operations with deterministic coercion."""
    raw_type = column_types.get(column, "").upper()
    col_type = raw_type.split("(")[0].strip() if raw_type else ""
    value = _extract_value(literal)

    if not _is_numeric_text_column(column, col_type):
        return value
    return _coerce_numeric_literal(value, column)


def _coerce_numeric_literal(value: object, column: str) -> float:
    """Coerce an operand into a float for numeric-text column comparison."""
    if isinstance(value, bool):
        raise FilterCompilationError(
            FilterErrorCode.TYPE_MISMATCH,
            f"Column {column!r} expects numeric literal for ordering comparison.",
        )
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", "").replace("$", "")
        if not normalized:
            raise FilterCompilationError(
                FilterErrorCode.TYPE_MISMATCH,
                f"Column {column!r} expects numeric literal for ordering comparison.",
            )
        try:
            return float(normalized)
        except ValueError as exc:
            raise FilterCompilationError(
                FilterErrorCode.TYPE_MISMATCH,
                f"Column {column!r} expects numeric literal for ordering comparison.",
            ) from exc
    raise FilterCompilationError(
        FilterErrorCode.TYPE_MISMATCH,
        f"Column {column!r} expects numeric literal for ordering comparison.",
    )


def _next_param(param_counter: list[int], params: list, value: object) -> int:
    """Add a parameter and return its 1-based index.

    Args:
        param_counter: Mutable counter (single-element list).
        params: Parameter accumulator.
        value: The parameter value to add.

    Returns:
        1-based parameter index for use in $N placeholder.
    """
    param_counter[0] += 1
    params.append(value)
    return param_counter[0]


def _extract_value(literal: TypedLiteral) -> object:
    """Extract the raw value from a TypedLiteral.

    Args:
        literal: The typed literal to extract from.

    Returns:
        The raw value.
    """
    return literal.value


def _escape_like_value(value: str) -> str:
    """Escape special LIKE/ILIKE characters in a value.

    Escapes backslash, percent, and underscore with a backslash escape character.

    Args:
        value: Raw string value.

    Returns:
        Escaped string safe for ILIKE patterns.
    """
    result = value.replace("\\", "\\\\")
    result = result.replace("%", "\\%")
    result = result.replace("_", "\\_")
    return result


def _explain_condition_label(cond: FilterCondition) -> str:
    """Generate a human-readable label for a single filter condition.

    Args:
        cond: The condition to describe.

    Returns:
        Human-readable description string.
    """
    op = cond.operator
    if op == FilterOperator.eq:
        return f"{cond.column} equals {cond.operands[0].value}"
    elif op == FilterOperator.neq:
        return f"{cond.column} not equal to {cond.operands[0].value}"
    elif op == FilterOperator.gt:
        return f"{cond.column} greater than {cond.operands[0].value}"
    elif op == FilterOperator.gte:
        return f"{cond.column} >= {cond.operands[0].value}"
    elif op == FilterOperator.lt:
        return f"{cond.column} less than {cond.operands[0].value}"
    elif op == FilterOperator.lte:
        return f"{cond.column} <= {cond.operands[0].value}"
    elif op == FilterOperator.in_:
        sorted_ops = sorted(cond.operands, key=lambda o: str(o.value))
        values = [str(o.value) for o in sorted_ops]
        return f"{cond.column} in [{', '.join(values)}]"
    elif op == FilterOperator.not_in:
        sorted_ops = sorted(cond.operands, key=lambda o: str(o.value))
        values = [str(o.value) for o in sorted_ops]
        return f"{cond.column} not in [{', '.join(values)}]"
    elif op == FilterOperator.contains_ci:
        return f"{cond.column} contains '{cond.operands[0].value}' (case-insensitive)"
    elif op == FilterOperator.starts_with_ci:
        return f"{cond.column} starts with '{cond.operands[0].value}' (case-insensitive)"
    elif op == FilterOperator.ends_with_ci:
        return f"{cond.column} ends with '{cond.operands[0].value}' (case-insensitive)"
    elif op == FilterOperator.is_null:
        return f"{cond.column} is null"
    elif op == FilterOperator.is_not_null:
        return f"{cond.column} is not null"
    elif op == FilterOperator.is_blank:
        return f"{cond.column} is blank (null or empty)"
    elif op == FilterOperator.is_not_blank:
        return f"{cond.column} is not blank"
    elif op == FilterOperator.between:
        return f"{cond.column} between {cond.operands[0].value} and {cond.operands[1].value}"
    return f"{cond.column} {op.value} ..."


def _explain_ast(node: Union[FilterCondition, FilterGroup]) -> str:
    """Recursively build explanation from the canonicalized AST.

    Preserves AND/OR logic and nesting structure.

    Args:
        node: AST node (condition or group).

    Returns:
        Human-readable explanation string.
    """
    if isinstance(node, FilterCondition):
        return _explain_condition_label(node)
    elif isinstance(node, FilterGroup):
        parts = [_explain_ast(child) for child in node.conditions
                 if isinstance(child, (FilterCondition, FilterGroup))]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        joiner = f" {node.logic.upper()} "
        inner = joiner.join(parts)
        return f"({inner})"
    return ""


def _build_explanation_from_ast(root: FilterGroup) -> str:
    """Build the final explanation string from the canonicalized AST.

    Args:
        root: Root filter group of the canonicalized AST.

    Returns:
        Complete explanation string prefixed with 'Filter: '.
    """
    result = _explain_ast(root)
    if not result:
        return "No filter conditions."
    # Strip outer parens on the root group
    if result.startswith("(") and result.endswith(")"):
        result = result[1:-1]
    return f"Filter: {result}."
