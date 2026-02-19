# GitHub Issues #8, #9, #10, #11 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve all four open GitHub issues in a single branch with atomic commits per issue.

**Architecture:** Sequential resolution in dependency order (#10 → #9 → #11 → #8). Issue #10 is an isolated filter fix. Issue #9 establishes compatibility matrices used by #11. Issue #11 expands models and payload builder. Issue #8 is orthogonal CLI work.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, DuckDB (json_extract), Typer/Rich (CLI), pytest

---

## Task 1: Fix filter explanation AND/OR — add `_explain_condition_label()` helper

**Files:**
- Modify: `src/orchestrator/filter_compiler.py:643-656`
- Test: `tests/orchestrator/test_filter_compiler.py`

**Step 1: Write the failing test**

Add to `tests/orchestrator/test_filter_compiler.py`:

```python
from src.orchestrator.filter_compiler import compile_filter_spec


class TestExplanationOperators:
    """Verify that compiled explanations preserve AND/OR logic."""

    def test_single_condition_explanation(self):
        """Single condition produces no operator in explanation."""
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestrator/test_filter_compiler.py::TestExplanationOperators -v`
Expected: FAIL — current implementation uses semicolons, not AND/OR.

**Step 3: Implement the fix**

In `src/orchestrator/filter_compiler.py`:

1. Add `_explain_condition_label(cond: FilterCondition) -> str` function after line 429 (after `_compile_condition`). This is a standalone function that returns the human-readable label for a condition — the same text that the old `explanation_parts.append()` calls generated:

```python
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
```

2. Add `_explain_ast(node)` and `_build_explanation_from_ast(root)` after the label function:

```python
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
```

3. Remove all `explanation_parts.append(...)` calls from `_compile_condition()` (lines 273, 278, 288, 298, 308, 318, 342, 365, 372, 379, 386, 390, 394, 399, 404, 419-421). The `_compile_condition` function no longer needs the `explanation_parts` parameter.

4. Remove `explanation_parts` from:
   - `_compile_group()` signature (line 160) and all recursive calls (lines 193, 204)
   - `_compile_condition()` signature (line 235)
   - `compile_filter_spec()` initialization (line 80) and call site (line 91)

5. Replace line 107: `explanation=_build_explanation(explanation_parts)` → `explanation=_build_explanation_from_ast(canonicalized_root)`

6. Delete old `_build_explanation(parts: list[str])` function (lines 643-656).

**Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestrator/test_filter_compiler.py -v`
Expected: ALL PASS (both new and existing tests).

**Step 5: Commit**

```bash
git add src/orchestrator/filter_compiler.py tests/orchestrator/test_filter_compiler.py
git commit -m "fix(#10): replace flat explanation accumulator with AST-based explanation builder

Removes the explanation_parts flat accumulator pattern from filter_compiler.py
and replaces it with _explain_ast() that recursively walks the canonicalized
AST, preserving AND/OR logic and nesting structure.

Before: 'Filter: col1 greater than 24; col2 greater than 24.'
After:  'Filter: col1 greater than 24 OR col2 greater than 24.'

Closes #10"
```

---

## Task 2: Fix filter_resolver.py explanation (root AND nested groups)

**Files:**
- Modify: `src/orchestrator/filter_resolver.py:843-876`
- Test: `tests/orchestrator/test_filter_resolver.py` (existing file, add tests)

**Step 1: Write the failing tests**

Add to `tests/orchestrator/test_filter_resolver.py`:

```python
from src.orchestrator.filter_resolver import _build_explanation
from src.orchestrator.models.filter_spec import (
    FilterCondition, FilterGroup, FilterOperator, TypedLiteral,
)


class TestResolverExplanationOperators:
    """Verify that resolver explanations preserve AND/OR logic."""

    def test_root_or_uses_or_joiner(self):
        """Root-level OR groups use 'OR' not semicolons in explanation."""
        root = FilterGroup(
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
        result = _build_explanation(root)
        assert "OR" in result or "or" in result
        assert ";" not in result

    def test_nested_or_inside_and_preserves_child_logic(self):
        """Nested OR group inside AND parent uses OR joiner, not parent's AND."""
        root = FilterGroup(
            logic="AND",
            conditions=[
                FilterGroup(
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
                            operands=[TypedLiteral(type="string", value="TX")],
                        ),
                    ],
                ),
                FilterCondition(
                    column="weight",
                    operator=FilterOperator.gt,
                    operands=[TypedLiteral(type="number", value=10)],
                ),
            ],
        )
        result = _build_explanation(root)
        # The nested OR group must use "or" joiner, not parent's "and"
        assert "or" in result.lower()
        assert "and" in result.lower()
        assert ";" not in result

    def test_nested_and_inside_or_preserves_child_logic(self):
        """Nested AND group inside OR parent uses AND joiner, not parent's OR."""
        root = FilterGroup(
            logic="OR",
            conditions=[
                FilterGroup(
                    logic="AND",
                    conditions=[
                        FilterCondition(
                            column="state",
                            operator=FilterOperator.eq,
                            operands=[TypedLiteral(type="string", value="CA")],
                        ),
                        FilterCondition(
                            column="weight",
                            operator=FilterOperator.gt,
                            operands=[TypedLiteral(type="number", value=10)],
                        ),
                    ],
                ),
                FilterCondition(
                    column="value",
                    operator=FilterOperator.gt,
                    operands=[TypedLiteral(type="number", value=200)],
                ),
            ],
        )
        result = _build_explanation(root)
        assert "and" in result.lower()
        assert "or" in result.lower()
        assert ";" not in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestrator/test_filter_resolver.py::TestResolverExplanationOperators -v`
Expected: FAIL — root uses `"; ".join` and nested groups use parent's logic.

**Step 3: Fix both `_build_explanation` AND `_explain_group` in filter_resolver.py**

Two bugs require two fixes:

Fix 1: Replace lines 843-855 (`_build_explanation`):

```python
def _build_explanation(root: FilterGroup) -> str:
    """Build a human-readable explanation from the resolved AST.

    Args:
        root: The resolved and canonicalized AST.

    Returns:
        Human-readable filter description.
    """
    parts = _explain_group(root)
    if not parts:
        return "No filter conditions."
    if len(parts) == 1:
        return f"Filter: {parts[0]}."
    joiner = f" {root.logic.upper()} "
    return "Filter: " + joiner.join(parts) + "."
```

Fix 2: Replace line 874 in `_explain_group` — change `group.logic` to `child.logic`:

```python
def _explain_group(group: FilterGroup) -> list[str]:
    """Recursively explain a filter group.

    Args:
        group: The group to explain.

    Returns:
        List of explanation strings.
    """
    parts = []
    for child in group.conditions:
        if isinstance(child, FilterCondition):
            parts.append(_explain_condition(child))
        elif isinstance(child, FilterGroup):
            sub = _explain_group(child)
            if sub:
                joiner = f" {child.logic.lower()} "  # BUG FIX: was group.logic (parent), now child.logic
                parts.append(f"({joiner.join(sub)})")
    return parts
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestrator/test_filter_resolver.py -v`
Expected: ALL PASS.

**Step 5: Run full filter test suite**

Run: `pytest tests/orchestrator/test_filter_compiler.py tests/orchestrator/test_filter_resolver.py -v`
Expected: ALL PASS.

**Step 6: Commit**

```bash
git add src/orchestrator/filter_resolver.py tests/orchestrator/test_filter_resolver.py
git commit -m "fix(#10): preserve AND/OR logic in filter_resolver explanation

Two fixes:
1. _build_explanation: semicolons -> root.logic joiner at root level
2. _explain_group: group.logic (parent) -> child.logic (child) for nested groups

Before: OR-inside-AND rendered as '(state equals CA and state equals TX)'
After:  OR-inside-AND renders as '(state equals CA or state equals TX)'"
```

---

## Task 3: Add compatibility matrices to ups_constants.py

**Files:**
- Modify: `src/services/ups_constants.py` (after line 104)
- Test: `tests/services/test_ups_constants.py` (new file)

**Step 1: Write the failing test**

Create `tests/services/test_ups_constants.py`:

```python
"""Tests for UPS canonical constants — compatibility matrices."""

from src.services.ups_constants import (
    EXPRESS_CLASS_SERVICES,
    EXPRESS_ONLY_PACKAGING,
    INTERNATIONAL_ONLY_PACKAGING,
    LETTER_MAX_WEIGHT_LBS,
    PackagingCode,
    SATURDAY_DELIVERY_SERVICES,
    SERVICE_WEIGHT_LIMITS_LBS,
)


class TestCompatibilityMatrices:
    """Verify compatibility matrices match UPS spec."""

    def test_express_only_packaging_contains_letter(self):
        assert PackagingCode.LETTER.value in EXPRESS_ONLY_PACKAGING

    def test_express_only_packaging_contains_pak(self):
        assert PackagingCode.PAK.value in EXPRESS_ONLY_PACKAGING

    def test_express_only_packaging_contains_tube(self):
        assert PackagingCode.TUBE.value in EXPRESS_ONLY_PACKAGING

    def test_express_only_packaging_contains_all_express_box_variants(self):
        assert PackagingCode.EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING
        assert PackagingCode.SMALL_EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING
        assert PackagingCode.MEDIUM_EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING
        assert PackagingCode.LARGE_EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING

    def test_customer_supplied_not_in_express_only(self):
        assert PackagingCode.CUSTOMER_SUPPLIED.value not in EXPRESS_ONLY_PACKAGING

    def test_ground_not_in_express_class_services(self):
        assert "03" not in EXPRESS_CLASS_SERVICES

    def test_next_day_air_in_express_class(self):
        assert "01" in EXPRESS_CLASS_SERVICES

    def test_worldwide_express_in_express_class(self):
        assert "07" in EXPRESS_CLASS_SERVICES

    def test_saturday_delivery_services_subset_of_express(self):
        assert SATURDAY_DELIVERY_SERVICES.issubset(EXPRESS_CLASS_SERVICES)

    def test_international_only_packaging(self):
        assert PackagingCode.BOX_25KG.value in INTERNATIONAL_ONLY_PACKAGING
        assert PackagingCode.BOX_10KG.value in INTERNATIONAL_ONLY_PACKAGING

    def test_letter_weight_limit_reasonable(self):
        assert 1.0 < LETTER_MAX_WEIGHT_LBS < 1.5

    def test_all_services_have_weight_limits(self):
        for svc in ["01", "02", "03", "12", "13", "14", "59"]:
            assert svc in SERVICE_WEIGHT_LIMITS_LBS
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_constants.py -v`
Expected: FAIL — `ImportError: cannot import name 'EXPRESS_CLASS_SERVICES'`

**Step 3: Add constants to ups_constants.py**

Add after the `PACKAGING_ALIASES` dict (after line 104) in `src/services/ups_constants.py`:

```python
# ---------------------------------------------------------------------------
# Service-packaging compatibility matrices
# ---------------------------------------------------------------------------

# Packaging codes restricted to express-class services
EXPRESS_ONLY_PACKAGING: frozenset[str] = frozenset({
    PackagingCode.LETTER.value,              # "01"
    PackagingCode.PAK.value,                 # "04"
    PackagingCode.TUBE.value,                # "03"
    PackagingCode.EXPRESS_BOX.value,         # "21"
    PackagingCode.SMALL_EXPRESS_BOX.value,   # "2a"
    PackagingCode.MEDIUM_EXPRESS_BOX.value,  # "2b"
    PackagingCode.LARGE_EXPRESS_BOX.value,   # "2c"
})

# Services compatible with express-only packaging
EXPRESS_CLASS_SERVICES: frozenset[str] = frozenset({
    "01",  # Next Day Air
    "02",  # 2nd Day Air
    "13",  # Next Day Air Saver
    "14",  # Next Day Air Early
    "59",  # 2nd Day Air A.M.
    "07",  # Worldwide Express
    "54",  # Worldwide Express Plus
    "65",  # Worldwide Saver
})

# Services supporting Saturday Delivery
SATURDAY_DELIVERY_SERVICES: frozenset[str] = frozenset({
    "01",  # Next Day Air
    "02",  # 2nd Day Air
    "13",  # Next Day Air Saver
    "14",  # Next Day Air Early
    "59",  # 2nd Day Air A.M.
})

# Per-service weight limits (lbs)
SERVICE_WEIGHT_LIMITS_LBS: dict[str, float] = {
    "01": 150.0, "02": 150.0, "03": 150.0, "07": 150.0,
    "12": 150.0, "13": 150.0, "14": 150.0, "54": 150.0,
    "59": 150.0, "65": 150.0,
}
DEFAULT_WEIGHT_LIMIT_LBS: float = 150.0

# UPS Letter weight limit (~0.5 kg)
LETTER_MAX_WEIGHT_LBS: float = 1.1

# International-only packaging
INTERNATIONAL_ONLY_PACKAGING: frozenset[str] = frozenset({
    PackagingCode.BOX_25KG.value,   # "24"
    PackagingCode.BOX_10KG.value,   # "25"
})
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_ups_constants.py -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/services/ups_constants.py tests/services/test_ups_constants.py
git commit -m "feat(#9): add service-packaging compatibility matrices to ups_constants.py

Adds EXPRESS_ONLY_PACKAGING, EXPRESS_CLASS_SERVICES, SATURDAY_DELIVERY_SERVICES,
SERVICE_WEIGHT_LIMITS_LBS, LETTER_MAX_WEIGHT_LBS, INTERNATIONAL_ONLY_PACKAGING
canonical frozensets for pre-flight validation."
```

---

## Task 4: Add `validate_domestic_payload()` to payload builder

**Files:**
- Modify: `src/services/ups_payload_builder.py`
- Test: `tests/services/test_ups_payload_builder.py`

**Step 1: Write the failing tests**

Add to `tests/services/test_ups_payload_builder.py`:

```python
from src.services.ups_payload_builder import validate_domestic_payload, ValidationIssue


class TestValidateDomesticPayload:
    """Pre-flight domestic validation checks."""

    def test_letter_with_ground_returns_error(self):
        """UPS Letter is incompatible with Ground."""
        order_data = {"packaging_type": "01"}
        issues = validate_domestic_payload(order_data, "03")
        assert any(i.severity == "error" and "packaging" in i.message.lower() for i in issues)

    def test_letter_with_next_day_air_passes(self):
        """UPS Letter is compatible with Next Day Air."""
        order_data = {"packaging_type": "01"}
        issues = validate_domestic_payload(order_data, "01")
        assert not any(i.severity == "error" and "packaging" in i.message.lower() for i in issues)

    def test_customer_supplied_with_ground_passes(self):
        """Customer Supplied packaging is always valid."""
        order_data = {"packaging_type": "02"}
        issues = validate_domestic_payload(order_data, "03")
        assert not any(i.severity == "error" for i in issues)

    def test_letter_overweight_returns_error(self):
        """UPS Letter over 1.1 lbs is rejected."""
        order_data = {"packaging_type": "01", "weight": "2.0"}
        issues = validate_domestic_payload(order_data, "01")
        assert any(i.severity == "error" and "weight" in i.message.lower() for i in issues)

    def test_saturday_delivery_with_ground_returns_warning(self):
        """Saturday Delivery with Ground produces a warning."""
        order_data = {"saturday_delivery": "true"}
        issues = validate_domestic_payload(order_data, "03")
        assert any(i.severity == "warning" and "saturday" in i.message.lower() for i in issues)

    def test_saturday_delivery_with_next_day_passes(self):
        """Saturday Delivery with Next Day Air is valid."""
        order_data = {"saturday_delivery": "true"}
        issues = validate_domestic_payload(order_data, "01")
        assert not any("saturday" in i.message.lower() for i in issues)

    def test_no_issues_for_clean_payload(self):
        """Standard payload with no flags returns no issues."""
        order_data = {"packaging_type": "02", "weight": "5.0"}
        issues = validate_domestic_payload(order_data, "03")
        assert len(issues) == 0

    def test_express_box_with_3day_select_returns_error(self):
        """Express Box is incompatible with 3 Day Select."""
        order_data = {"packaging_type": "21"}
        issues = validate_domestic_payload(order_data, "12")
        assert any(i.severity == "error" for i in issues)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_ups_payload_builder.py::TestValidateDomesticPayload -v`
Expected: FAIL — `ImportError: cannot import name 'validate_domestic_payload'`

**Step 3: Implement `validate_domestic_payload()` and `apply_compatibility_corrections()`**

Add to `src/services/ups_payload_builder.py` (after imports, before `resolve_packaging_code`):

```python
from dataclasses import dataclass, field as dc_field

from src.services.ups_constants import (
    EXPRESS_CLASS_SERVICES,
    EXPRESS_ONLY_PACKAGING,
    INTERNATIONAL_ONLY_PACKAGING,
    LETTER_MAX_WEIGHT_LBS,
    SATURDAY_DELIVERY_SERVICES,
    SERVICE_WEIGHT_LIMITS_LBS,
    DEFAULT_WEIGHT_LIMIT_LBS,
    PackagingCode,
)


@dataclass
class ValidationIssue:
    """A pre-flight validation issue detected before UPS API call."""

    field: str
    message: str
    severity: str  # "error" | "warning"
    auto_corrected: bool = False


def validate_domestic_payload(
    order_data: dict[str, Any],
    service_code: str,
) -> list[ValidationIssue]:
    """Pre-flight validation for service-packaging-weight compatibility.

    Checks field interdependencies that cause UPS API rejections.

    Args:
        order_data: Order data dict.
        service_code: Effective UPS service code.

    Returns:
        List of ValidationIssue objects. Empty list means payload is valid.
    """
    issues: list[ValidationIssue] = []
    pkg_code = resolve_packaging_code(order_data.get("packaging_type"))

    # 1. Packaging-service compatibility
    if pkg_code in EXPRESS_ONLY_PACKAGING and service_code not in EXPRESS_CLASS_SERVICES:
        pkg_name = order_data.get("packaging_type", pkg_code)
        issues.append(ValidationIssue(
            field="packaging_type",
            message=(
                f"Packaging '{pkg_name}' (code {pkg_code}) is only valid with "
                f"express-class services. Current service: {service_code}. "
                f"Use Customer Supplied (02) or change service."
            ),
            severity="error",
        ))

    # 2. International-only packaging with domestic service
    from src.services.ups_service_codes import DOMESTIC_ONLY_SERVICES
    if pkg_code in INTERNATIONAL_ONLY_PACKAGING and service_code in DOMESTIC_ONLY_SERVICES:
        issues.append(ValidationIssue(
            field="packaging_type",
            message=(
                f"Packaging code {pkg_code} is only valid with international services."
            ),
            severity="error",
        ))

    # 3. Letter weight limit
    if pkg_code == PackagingCode.LETTER.value:
        weight = _get_weight_lbs(order_data)
        if weight and weight > LETTER_MAX_WEIGHT_LBS:
            issues.append(ValidationIssue(
                field="weight",
                message=(
                    f"UPS Letter max weight is {LETTER_MAX_WEIGHT_LBS} lbs. "
                    f"Current weight: {weight:.1f} lbs."
                ),
                severity="error",
            ))

    # 4. Saturday Delivery compatibility
    if _is_truthy(order_data.get("saturday_delivery")):
        if service_code not in SATURDAY_DELIVERY_SERVICES:
            issues.append(ValidationIssue(
                field="saturday_delivery",
                message=(
                    f"Saturday Delivery is not supported by service {service_code}. "
                    f"Flag will be stripped."
                ),
                severity="warning",
                auto_corrected=True,
            ))

    # 5. Per-service weight limit
    weight = _get_weight_lbs(order_data)
    if weight:
        limit = SERVICE_WEIGHT_LIMITS_LBS.get(service_code, DEFAULT_WEIGHT_LIMIT_LBS)
        if weight > limit:
            issues.append(ValidationIssue(
                field="weight",
                message=(
                    f"Package weight {weight:.1f} lbs exceeds service "
                    f"{service_code} limit of {limit:.0f} lbs."
                ),
                severity="error",
            ))

    return issues


def _get_weight_lbs(order_data: dict[str, Any]) -> float | None:
    """Extract weight in lbs from order_data, handling grams conversion."""
    weight = order_data.get("weight") or order_data.get("total_weight")
    if weight:
        try:
            return float(weight)
        except (ValueError, TypeError):
            return None
    weight_grams = order_data.get("total_weight_grams")
    if weight_grams:
        try:
            return float(weight_grams) / GRAMS_PER_LB
        except (ValueError, TypeError):
            return None
    return None
```

Also add `apply_compatibility_corrections()` — the shared function that BOTH core.py (preview) and batch_engine.py (execute) will call:

```python
def apply_compatibility_corrections(
    order_data: dict[str, Any],
    service_code: str,
) -> list[ValidationIssue]:
    """Validate and auto-correct compatibility issues in-place.

    This is the SINGLE shared validation path called from both:
    - core.py._build_job_row_data_with_metadata() (preview-time)
    - batch_engine._process_row() (execution-time, including confirm-time overrides)

    Auto-correctable issues are fixed in order_data in-place.
    Non-correctable errors are returned for the caller to handle.

    Args:
        order_data: Order data dict (mutated in-place for auto-corrections).
        service_code: Effective UPS service code.

    Returns:
        List of ValidationIssue objects.
    """
    issues = validate_domestic_payload(order_data, service_code)
    warnings: list[str] = []

    for issue in issues:
        if issue.field == "packaging_type" and issue.severity == "error":
            # Auto-correct express-only packaging to Customer Supplied
            pkg_code = resolve_packaging_code(order_data.get("packaging_type"))
            if pkg_code in EXPRESS_ONLY_PACKAGING and service_code not in EXPRESS_CLASS_SERVICES:
                original = order_data.get("packaging_type", pkg_code)
                order_data["packaging_type"] = DEFAULT_PACKAGING_CODE.value
                order_data["_packaging_auto_reset"] = (
                    f"Packaging reset from '{original}' to Customer Supplied: "
                    f"incompatible with service {service_code}"
                )
                issue.auto_corrected = True
                issue.severity = "warning"
                warnings.append(order_data["_packaging_auto_reset"])

        if issue.field == "saturday_delivery" and issue.auto_corrected:
            # Clear Saturday Delivery flag
            order_data["saturday_delivery"] = ""
            order_data["_saturday_delivery_stripped"] = (
                f"Saturday Delivery removed: not supported by service {service_code}"
            )
            warnings.append(order_data["_saturday_delivery_stripped"])

    # Surface auto-corrections as row warnings for preview display
    existing_warnings = order_data.get("_validation_warnings", [])
    if isinstance(existing_warnings, str):
        existing_warnings = [existing_warnings] if existing_warnings else []
    order_data["_validation_warnings"] = existing_warnings + warnings

    return issues
```

And add tests for `apply_compatibility_corrections`:

```python
class TestApplyCompatibilityCorrections:
    """Shared validation + auto-correction function."""

    def test_letter_with_ground_auto_corrected(self):
        """Letter packaging auto-corrected to Customer Supplied for Ground."""
        from src.services.ups_payload_builder import apply_compatibility_corrections
        order_data = {"packaging_type": "01"}
        issues = apply_compatibility_corrections(order_data, "03")
        assert order_data["packaging_type"] == "02"  # Customer Supplied
        assert "_packaging_auto_reset" in order_data
        assert any(i.auto_corrected for i in issues)

    def test_saturday_delivery_stripped_for_ground(self):
        """Saturday Delivery auto-stripped for Ground."""
        from src.services.ups_payload_builder import apply_compatibility_corrections
        order_data = {"saturday_delivery": "true"}
        issues = apply_compatibility_corrections(order_data, "03")
        assert not order_data.get("saturday_delivery")
        assert "_saturday_delivery_stripped" in order_data

    def test_overweight_not_auto_corrected(self):
        """Overweight errors are NOT auto-corrected."""
        from src.services.ups_payload_builder import apply_compatibility_corrections
        order_data = {"packaging_type": "01", "weight": "5.0"}
        issues = apply_compatibility_corrections(order_data, "01")
        errors = [i for i in issues if i.severity == "error" and not i.auto_corrected]
        assert any("weight" in i.message.lower() for i in errors)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_ups_payload_builder.py::TestValidateDomesticPayload tests/services/test_ups_payload_builder.py::TestApplyCompatibilityCorrections -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/services/ups_payload_builder.py tests/services/test_ups_payload_builder.py
git commit -m "feat(#9): add validate_domestic_payload() + apply_compatibility_corrections()

validate_domestic_payload: pre-flight validation for service-packaging-weight.
apply_compatibility_corrections: shared auto-correct path called from both
core.py (preview) and batch_engine._process_row (execute). Auto-corrects
express-only packaging and Saturday Delivery for non-express services."
```

---

## Task 5: Integrate shared validation in core.py (preview-time path)

**Files:**
- Modify: `src/orchestrator/agent/tools/core.py:259-262`
- Test: `tests/orchestrator/agent/test_tools_core.py` (new file, follows existing `test_tools_*.py` pattern)

**Step 1: Write the failing test**

Create `tests/orchestrator/agent/test_tools_core.py`:

```python
"""Tests for service override auto-reset in core.py."""

import json
from src.orchestrator.agent.tools.core import _build_job_row_data_with_metadata


class TestServiceOverrideAutoReset:
    """Auto-reset packaging when service override creates incompatibility."""

    def test_letter_reset_to_customer_supplied_on_ground_override(self):
        """UPS Letter packaging auto-resets to Customer Supplied for Ground."""
        rows = [{"ship_to_name": "Test", "packaging_type": "01", "weight": "0.5"}]
        result, _ = _build_job_row_data_with_metadata(rows, service_code_override="03")
        order_data = json.loads(result[0]["order_data"])
        assert order_data.get("packaging_type") != "01"
        assert order_data.get("_packaging_auto_reset") is not None

    def test_customer_supplied_unchanged_on_ground_override(self):
        """Customer Supplied packaging is not touched on Ground override."""
        rows = [{"ship_to_name": "Test", "packaging_type": "02", "weight": "5.0"}]
        result, _ = _build_job_row_data_with_metadata(rows, service_code_override="03")
        order_data = json.loads(result[0]["order_data"])
        assert "_packaging_auto_reset" not in order_data

    def test_saturday_delivery_stripped_for_ground(self):
        """Saturday Delivery flag is stripped when overriding to Ground."""
        rows = [{"ship_to_name": "Test", "saturday_delivery": "true"}]
        result, _ = _build_job_row_data_with_metadata(rows, service_code_override="03")
        order_data = json.loads(result[0]["order_data"])
        assert not order_data.get("saturday_delivery")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestrator/agent/test_tools_core.py::TestServiceOverrideAutoReset -v`
Expected: FAIL — no auto-reset logic exists.

**Step 3: Implement using shared `apply_compatibility_corrections()`**

In `src/orchestrator/agent/tools/core.py`, in `_build_job_row_data_with_metadata()`, after line 262 (`row["service_code"] = service_code_override`):

```python
    if service_code_override:
        from src.services.ups_payload_builder import apply_compatibility_corrections
        for row in normalized_rows:
            if isinstance(row, dict):
                row["service_code"] = service_code_override
                # Shared validation + auto-correction (same function used by batch_engine)
                apply_compatibility_corrections(row, service_code_override)
```

This delegates ALL compatibility logic to the shared `apply_compatibility_corrections()` function from Task 4. No inline auto-reset logic in core.py — it calls the same function that batch_engine will call in Task 6.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestrator/agent/test_tools_core.py::TestServiceOverrideAutoReset -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/core.py tests/orchestrator/agent/test_tools_core.py
git commit -m "feat(#9): integrate shared compatibility validation in core.py preview path

Calls apply_compatibility_corrections() from ups_payload_builder for
service override validation. Same function used by batch_engine (Task 6)
ensuring identical validation in both preview and execute paths."
```

---

## Task 6: Integrate shared validation into batch_engine.py (execute-time path)

**Files:**
- Modify: `src/services/batch_engine.py` (after international validation ~line 524)
- Test: `tests/services/test_batch_engine.py` (existing file, add new test class)

This is the **critical second integration point** for the shared validation. The confirm endpoint (`preview.py:231`) passes `selected_service_code` to `batch_executor.py:196` which passes it to `BatchEngine.execute()` as `service_code`. At line 503 of `_process_row()`, `eff_service = service_code or order_data.get("service_code", ...)` — this means the confirm-time service override is applied HERE, bypassing core.py entirely. We MUST validate here too.

**Step 1: Write the failing test**

Add to `tests/services/test_batch_engine.py`:

```python
class TestDomesticValidation:
    """Domestic pre-flight validation in _process_row."""

    def test_letter_with_ground_detected(self):
        """Shared validation detects Letter+Ground incompatibility."""
        from src.services.ups_payload_builder import apply_compatibility_corrections
        order_data = {"packaging_type": "01"}
        issues = apply_compatibility_corrections(order_data, "03")
        # Should auto-correct packaging
        assert order_data["packaging_type"] == "02"
        assert "_packaging_auto_reset" in order_data

    def test_overweight_letter_not_auto_corrected(self):
        """Overweight Letter is not auto-correctable — returns hard error."""
        from src.services.ups_payload_builder import apply_compatibility_corrections
        order_data = {"packaging_type": "01", "weight": "5.0"}
        issues = apply_compatibility_corrections(order_data, "01")
        errors = [i for i in issues if i.severity == "error" and not i.auto_corrected]
        assert any("weight" in i.message.lower() for i in errors)
```

**Step 2: Implement integration**

In `src/services/batch_engine.py`, add import:

```python
from src.services.ups_payload_builder import apply_compatibility_corrections
```

In `_process_row()`, after the international validation block (after the block that calls `validate_international_readiness` ~line 524), and AFTER `eff_service` is resolved at line 503, add:

```python
        # Shared domestic pre-flight validation + auto-correction
        # This covers confirm-time service overrides (selected_service_code
        # from preview.py:231 → batch_executor → BatchEngine.execute)
        domestic_issues = apply_compatibility_corrections(order_data, eff_service)
        domestic_errors = [
            i for i in domestic_issues
            if i.severity == "error" and not i.auto_corrected
        ]
        if domestic_errors:
            raise ValueError(
                "Pre-flight validation failed: "
                + "; ".join(i.message for i in domestic_errors)
            )
```

This calls the **same shared function** as core.py (Task 5), ensuring identical validation whether the service code was set at preview time or at confirm time.

**Step 3: Run tests**

Run: `pytest tests/services/test_batch_engine.py -v -k "not stream and not sse"`
Expected: ALL PASS.

**Step 4: Commit**

```bash
git add src/services/batch_engine.py tests/services/test_batch_engine.py
git commit -m "feat(#9): integrate shared validation into batch_engine execute path

Calls apply_compatibility_corrections() after eff_service resolution
in _process_row(). Covers confirm-time selected_service_code overrides
from preview.py → batch_executor → BatchEngine. Same shared function
as core.py preview path."
```

---

## Task 7: Add multi-field override support to pipeline.py + system prompt

**Files:**
- Modify: `src/orchestrator/agent/tools/pipeline.py` (~line 820-835)
- Modify: `src/orchestrator/agent/system_prompt.py`

**Step 1: Implement pipeline packaging override**

In `src/orchestrator/agent/tools/pipeline.py`, extend the tool definition for `ship_command_pipeline` to accept `packaging_type` as an optional parameter. In the override extraction block:

```python
# After service_code override extraction (~line 835)
raw_packaging = args.get("packaging_type")
packaging_override: str | None = None
if raw_packaging:
    packaging_override = resolve_packaging_code(str(raw_packaging))
```

Then pass `packaging_override` through to `_build_job_row_data_with_metadata` or apply directly to rows before the service override check.

**Step 2: Update system prompt**

In `src/orchestrator/agent/system_prompt.py`, add guidance:

```
When overriding service for a batch, the system auto-resets incompatible packaging
(Letter, PAK, Express Box, Tube → Customer Supplied for Ground/3 Day Select).
Saturday Delivery is also auto-stripped for non-express services. If specific
packaging is needed, include packaging_type in the tool call.

Auto-corrections appear as warnings in the preview card — no separate
"adjustments" field. The existing warning rendering handles this.
```

**Note on UX:** Auto-corrections surface through the **existing `warnings` field** on `PreviewRowResponse` and `rows_with_warnings` counter. No new `adjustments` API field, TypeScript type, or PreviewCard rendering is needed. The `_validation_warnings` list added by `apply_compatibility_corrections()` is included in the row's warnings during preview response construction.

**Step 3: Run tests**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream and not sse"`
Expected: ALL PASS.

**Step 4: Commit**

```bash
git add src/orchestrator/agent/tools/pipeline.py src/orchestrator/agent/system_prompt.py
git commit -m "feat(#9): add packaging_type override to pipeline tool + system prompt guidance

Allows agent to specify packaging alongside service in ship_command_pipeline.
System prompt documents auto-reset behavior and that auto-corrections
surface as warnings in the existing preview card warning system.

Closes #9"
```

---

## Task 8: Expand ExternalOrder model with promoted fields

**Files:**
- Modify: `src/mcp/external_sources/models.py:47-94`
- Test: `tests/mcp/external_sources/test_clients.py` (existing file, add new ExternalOrder test class)

**Step 1: Write the failing test**

```python
"""Tests for expanded ExternalOrder model."""

from src.mcp.external_sources.models import ExternalOrder


class TestExternalOrderExpansion:
    """Verify new optional fields on ExternalOrder."""

    def test_new_fields_default_to_none(self):
        """New optional fields default to None."""
        order = ExternalOrder(
            platform="shopify",
            order_id="123",
            status="open",
            created_at="2026-01-01",
            customer_name="Test",
            ship_to_name="Test",
            ship_to_address1="123 Main St",
            ship_to_city="New York",
            ship_to_state="NY",
            ship_to_postal_code="10001",
        )
        assert order.customer_tags is None
        assert order.order_note is None
        assert order.risk_level is None
        assert order.shipping_rate_code is None
        assert order.line_item_types is None
        assert order.discount_codes is None
        assert order.customer_order_count is None
        assert order.customer_total_spent is None
        assert order.custom_attributes == {}

    def test_custom_attributes_populated(self):
        """custom_attributes accepts arbitrary dict."""
        order = ExternalOrder(
            platform="shopify",
            order_id="123",
            status="open",
            created_at="2026-01-01",
            customer_name="Test",
            ship_to_name="Test",
            ship_to_address1="123 Main St",
            ship_to_city="New York",
            ship_to_state="NY",
            ship_to_postal_code="10001",
            custom_attributes={"gift_message": "Happy Birthday", "priority": "high"},
        )
        assert order.custom_attributes["gift_message"] == "Happy Birthday"

    def test_backward_compat_without_new_fields(self):
        """ExternalOrder constructed without new fields still works (backward compat).

        This validates that WooCommerce, SAP, and Oracle clients won't break
        since they don't pass the new fields.
        """
        order = ExternalOrder(
            platform="woocommerce",
            order_id="456",
            status="processing",
            created_at="2026-01-15",
            customer_name="Existing Customer",
            ship_to_name="Existing Customer",
            ship_to_address1="789 Oak Ave",
            ship_to_city="Chicago",
            ship_to_state="IL",
            ship_to_postal_code="60601",
        )
        # All new fields should have safe defaults
        assert order.customer_tags is None
        assert order.order_note is None
        assert order.custom_attributes == {}
```

**Step 2: Run test to verify it fails**

Expected: FAIL — `ExternalOrder` doesn't have `customer_tags` yet.

**Step 3: Add fields to ExternalOrder**

In `src/mcp/external_sources/models.py`, add after `item_count` (before `items`):

```python
    # Customer enrichment (enables VIP routing, customer-tier filtering)
    customer_tags: str | None = Field(None, description="Customer tags (comma-separated)")
    customer_order_count: int | None = Field(None, description="Customer historical order count")
    customer_total_spent: str | None = Field(None, description="Customer lifetime spend as decimal string")

    # Order enrichment (enables note-based routing, risk filtering)
    order_note: str | None = Field(None, description="Order note from customer/merchant")
    risk_level: str | None = Field(None, description="Platform risk assessment (LOW/MEDIUM/HIGH)")

    # Shipping enrichment (enables rate-code-based routing)
    shipping_rate_code: str | None = Field(None, description="Checkout-selected shipping rate code")

    # Product enrichment
    line_item_types: str | None = Field(None, description="Distinct product types (comma-separated)")
    discount_codes: str | None = Field(None, description="Applied discount codes (comma-separated)")

    # Arbitrary extensibility
    custom_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Platform-specific custom fields for filtering (e.g., note_attributes)",
    )
```

**Step 4: Run tests**

Run: `pytest tests/mcp/external_sources/ -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/mcp/external_sources/models.py tests/mcp/external_sources/test_clients.py
git commit -m "feat(#11): expand ExternalOrder with 9 new fields + custom_attributes

Adds customer_tags, customer_order_count, customer_total_spent, order_note,
risk_level, shipping_rate_code, line_item_types, discount_codes (all optional),
and custom_attributes dict for arbitrary platform extensibility."
```

---

## Task 9: Update Shopify normalization for new fields

**Files:**
- Modify: `src/mcp/external_sources/clients/shopify.py` (`_normalize_order()`)
- Test: `tests/mcp/external_sources/test_shopify_normalize.py`

**Step 1: Write the failing test**

```python
"""Tests for Shopify normalization with new ExternalOrder fields."""


class TestShopifyNewFields:
    """Verify Shopify client populates new ExternalOrder fields."""

    def test_customer_tags_populated(self):
        """customer_tags extracted from customer.tags."""
        shopify_order = _make_shopify_order(customer={"tags": "VIP, wholesale"})
        order = _normalize_order(shopify_order)
        assert order.customer_tags == "VIP, wholesale"

    def test_order_note_populated(self):
        """order_note extracted from note field."""
        shopify_order = _make_shopify_order(note="Please ship priority")
        order = _normalize_order(shopify_order)
        assert order.order_note == "Please ship priority"

    def test_shipping_rate_code_from_shipping_lines(self):
        """shipping_rate_code from shipping_lines[0].code."""
        shopify_order = _make_shopify_order(
            shipping_lines=[{"code": "STANDARD", "title": "Standard Shipping"}]
        )
        order = _normalize_order(shopify_order)
        assert order.shipping_rate_code == "STANDARD"

    def test_custom_attributes_from_note_attributes(self):
        """custom_attributes populated from note_attributes."""
        shopify_order = _make_shopify_order(
            note_attributes=[
                {"name": "gift_message", "value": "Happy Birthday"},
                {"name": "priority_flag", "value": "true"},
            ]
        )
        order = _normalize_order(shopify_order)
        assert order.custom_attributes["gift_message"] == "Happy Birthday"

    def test_discount_codes_populated(self):
        """discount_codes from discount_codes array."""
        shopify_order = _make_shopify_order(
            discount_codes=[{"code": "SAVE10"}, {"code": "FREESHIP"}]
        )
        order = _normalize_order(shopify_order)
        assert "SAVE10" in order.discount_codes
        assert "FREESHIP" in order.discount_codes
```

Note: You will need to create a `_make_shopify_order()` test helper that builds a minimal valid Shopify order dict. Check the existing test file for patterns.

**Step 2: Run test — expected FAIL**

**Step 3: Update `_normalize_order()` in shopify.py**

**CRITICAL**: Also update `_prepare_shopify_import_rows()` in `src/orchestrator/agent/tools/data.py:743-769` to serialize `custom_attributes` as valid JSON before it reaches `import_records()`. The import pipeline (`source_info_tools.py:109`) calls `str(record.get(col, ""))` on every value, which converts a Python dict to repr format (e.g., `"{'gift_message': 'yes'}"`) — NOT valid JSON. DuckDB's `json_extract_string()` will fail on this.

In `_prepare_shopify_import_rows()`, after building the row dict (around line 755):

```python
import json

# Serialize custom_attributes as valid JSON for DuckDB json_extract_string()
custom_attrs = row.get("custom_attributes")
if isinstance(custom_attrs, dict):
    row["custom_attributes"] = json.dumps(custom_attrs)
elif custom_attrs is None:
    row["custom_attributes"] = "{}"
```

Add test for this serialization:

```python
def test_custom_attributes_serialized_as_json(self):
    """custom_attributes dict is serialized as valid JSON string, not Python repr."""
    import json
    shopify_order = _make_shopify_order(
        note_attributes=[{"name": "gift_message", "value": "Happy Birthday"}]
    )
    order = _normalize_order(shopify_order)
    # Simulate what _prepare_shopify_import_rows does
    row = {k: v for k, v in order.dict().items() if k not in ("items", "raw_data")}
    if isinstance(row.get("custom_attributes"), dict):
        row["custom_attributes"] = json.dumps(row["custom_attributes"])
    # Verify it's valid JSON
    parsed = json.loads(row["custom_attributes"])
    assert parsed["gift_message"] == "Happy Birthday"
```

Now, add new field population in `_normalize_order()`:

```python
# Customer enrichment
customer = shopify_order.get("customer", {})
customer_tags = customer.get("tags") or None
customer_order_count = customer.get("orders_count")
customer_total_spent = customer.get("total_spent")

# Order enrichment
order_note = shopify_order.get("note") or None

# Risk level
risk_assessments = shopify_order.get("risk", []) or []
risk_level = None
if risk_assessments:
    # Take highest risk level
    risk_map = {"low": 1, "medium": 2, "high": 3}
    max_risk = max(risk_assessments, key=lambda r: risk_map.get(
        r.get("recommendation", "").lower().replace("accept", "low"), 0
    ))
    rec = max_risk.get("recommendation", "").upper()
    if "CANCEL" in rec:
        risk_level = "HIGH"
    elif "INVESTIGATE" in rec:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

# Shipping rate code
shipping_lines = shopify_order.get("shipping_lines", [])
shipping_rate_code = shipping_lines[0].get("code") if shipping_lines else None

# Product types
line_items = shopify_order.get("line_items", [])
product_types = {li.get("product_type", "") for li in line_items if li.get("product_type")}
line_item_types = ", ".join(sorted(product_types)) if product_types else None

# Discount codes
discount_codes_list = [d.get("code", "") for d in shopify_order.get("discount_codes", []) if d.get("code")]
discount_codes = ", ".join(discount_codes_list) if discount_codes_list else None

# Custom attributes
custom_attrs: dict[str, Any] = {}
for attr in shopify_order.get("note_attributes", []):
    name = attr.get("name", "")
    if name:
        custom_attrs[name] = attr.get("value", "")
```

Then include in the `ExternalOrder(...)` constructor call:

```python
customer_tags=customer_tags,
customer_order_count=customer_order_count,
customer_total_spent=customer_total_spent,
order_note=order_note,
risk_level=risk_level,
shipping_rate_code=shipping_rate_code,
line_item_types=line_item_types,
discount_codes=discount_codes,
custom_attributes=custom_attrs,
```

**Step 4: Run tests**

Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/mcp/external_sources/clients/shopify.py tests/mcp/external_sources/test_shopify_normalize.py
git commit -m "feat(#11): populate new ExternalOrder fields in Shopify normalization

Extracts customer_tags, customer_order_count, customer_total_spent,
order_note, risk_level, shipping_rate_code, line_item_types, discount_codes,
and custom_attributes from Shopify order data."
```

---

## Task 10: Add column mapping entries for new UPS fields

**Files:**
- Modify: `src/services/column_mapping.py`
- Test: `tests/services/test_column_mapping.py`

**Step 1: Write the failing test**

```python
class TestNewFieldMappings:
    """New field mapping entries for P0+P1 UPS fields."""

    def test_shipment_date_in_field_map(self):
        from src.services.column_mapping import _FIELD_TO_ORDER_DATA
        assert "shipmentDate" in _FIELD_TO_ORDER_DATA

    def test_ship_from_fields_in_field_map(self):
        from src.services.column_mapping import _FIELD_TO_ORDER_DATA
        assert "shipFrom.name" in _FIELD_TO_ORDER_DATA
        assert "shipFrom.addressLine1" in _FIELD_TO_ORDER_DATA

    def test_service_options_in_field_map(self):
        from src.services.column_mapping import _FIELD_TO_ORDER_DATA
        for key in ["costCenter", "holdForPickup", "liftGatePickup",
                     "liftGateDelivery", "carbonNeutral", "notification.email"]:
            assert key in _FIELD_TO_ORDER_DATA, f"{key} missing from _FIELD_TO_ORDER_DATA"

    def test_auto_map_detects_ship_date_column(self):
        from src.services.column_mapping import ColumnMappingService
        service = ColumnMappingService()
        # Test that a column named "ship_date" auto-maps
        mapping = service.auto_map(["ship_date", "name", "address"])
        assert any("shipment" in v.lower() or "ship_date" in v.lower()
                    for v in mapping.values() if v)
```

**Step 2: Run test — expected FAIL**

**Step 3: Add mappings**

In `src/services/column_mapping.py`, add to `_FIELD_TO_ORDER_DATA`:

```python
# P0 — Shipment level
"shipmentDate": "shipment_date",
"shipFrom.name": "ship_from_name",
"shipFrom.addressLine1": "ship_from_address1",
"shipFrom.addressLine2": "ship_from_address2",
"shipFrom.city": "ship_from_city",
"shipFrom.state": "ship_from_state",
"shipFrom.postalCode": "ship_from_postal_code",
"shipFrom.country": "ship_from_country",
"shipFrom.phone": "ship_from_phone",

# P1 — Service options
"costCenter": "cost_center",
"holdForPickup": "hold_for_pickup",
"shipperRelease": "shipper_release",
"liftGatePickup": "lift_gate_pickup",
"liftGateDelivery": "lift_gate_delivery",
"insideDelivery": "inside_delivery",
"directDeliveryOnly": "direct_delivery_only",
"deliverToAddresseeOnly": "deliver_to_addressee_only",
"carbonNeutral": "carbon_neutral",
"dropoffAtFacility": "dropoff_at_facility",
"notification.email": "notification_email",

# P1 — Package level
"largePackage": "large_package",
"additionalHandling": "additional_handling",

# P1 — International forms
"termsOfShipment": "terms_of_shipment",
"purchaseOrderNumber": "purchase_order_number",
"invoiceComments": "invoice_comments",
"freightCharges": "freight_charges",
"insuranceCharges": "insurance_charges",
```

Add to `_AUTO_MAP_RULES`:

```python
(["ship", "date"], ["created", "updated", "order"], "shipmentDate"),
(["ship", "from", "name"], [], "shipFrom.name"),
(["ship", "from", "addr"], [], "shipFrom.addressLine1"),
(["ship", "from", "city"], [], "shipFrom.city"),
(["ship", "from", "state"], [], "shipFrom.state"),
(["ship", "from", "zip"], [], "shipFrom.postalCode"),
(["ship", "from", "country"], [], "shipFrom.country"),
(["ship", "from", "phone"], [], "shipFrom.phone"),
(["cost", "center"], [], "costCenter"),
(["hold", "pickup"], [], "holdForPickup"),
(["lift", "gate", "pickup"], [], "liftGatePickup"),
(["lift", "gate", "deliver"], [], "liftGateDelivery"),
(["carbon", "neutral"], [], "carbonNeutral"),
(["notification", "email"], ["customer"], "notification.email"),
(["terms", "shipment"], [], "termsOfShipment"),
(["purchase", "order", "number"], ["phone"], "purchaseOrderNumber"),
(["large", "package"], [], "largePackage"),
(["additional", "handling"], [], "additionalHandling"),
```

**Step 4: Run tests**

Run: `pytest tests/services/test_column_mapping.py -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/services/column_mapping.py tests/services/test_column_mapping.py
git commit -m "feat(#11): add column mapping entries for P0+P1 UPS fields

Adds _FIELD_TO_ORDER_DATA and _AUTO_MAP_RULES entries for: ShipmentDate,
ShipFrom (9 fields), service options (11 fields), package indicators (2),
and international forms (5 fields)."
```

---

## Task 11: Add UPS payload builder support for new fields

**Files:**
- Modify: `src/services/ups_payload_builder.py` (`build_shipment_request()` and `build_ups_api_payload()`)
- Test: `tests/services/test_ups_payload_builder.py`

**Step 1: Write the failing tests**

```python
class TestNewPayloadFields:
    """P0+P1 UPS payload field coverage."""

    def test_shipment_date_in_simplified(self):
        order_data = {"shipment_date": "20260220", "ship_to_name": "Test",
                      "ship_to_address1": "123 Main", "ship_to_city": "NYC",
                      "ship_to_state": "NY", "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert result.get("shipmentDate") == "20260220"

    def test_ship_from_in_simplified(self):
        order_data = {"ship_from_name": "Warehouse A",
                      "ship_from_address1": "456 Elm St",
                      "ship_from_city": "Chicago", "ship_from_state": "IL",
                      "ship_from_postal_code": "60601",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert "shipFrom" in result
        assert result["shipFrom"]["ship_from_name"] == "Warehouse A"

    def test_boolean_indicators_in_simplified(self):
        order_data = {"hold_for_pickup": "true", "carbon_neutral": "yes",
                      "lift_gate_delivery": "1",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert result.get("holdForPickup") is True
        assert result.get("carbonNeutral") is True
        assert result.get("liftGateDelivery") is True

    def test_notification_email_in_simplified(self):
        order_data = {"notification_email": "buyer@example.com",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert result.get("notificationEmail") == "buyer@example.com"

    def test_cost_center_in_simplified(self):
        order_data = {"cost_center": "DEPT-42",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert result.get("costCenter") == "DEPT-42"

    def test_terms_of_shipment_in_simplified(self):
        order_data = {"terms_of_shipment": "DDP",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert result.get("termsOfShipment") == "DDP"

    def test_clean_payload_has_no_empty_objects(self):
        """Payload without new fields produces no empty structures."""
        order_data = {"ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        result = build_shipment_request(order_data)
        assert "shipFrom" not in result
        assert "notificationEmail" not in result
        assert "costCenter" not in result
```

**Step 2: Run test — expected FAIL**

**Step 3: Implement in `build_shipment_request()`**

Add field reading after existing field handling:

```python
    # Shipment date
    if order_data.get("shipment_date"):
        result["shipmentDate"] = order_data["shipment_date"]

    # ShipFrom (dynamic, for multi-warehouse)
    # PRECEDENCE: ShipFrom from row-level data overrides system Shipper for
    # the physical origin address. Shipper block always uses system/env config.
    # If no ship_from_* fields present, ShipFrom is omitted entirely —
    # UPS defaults to using Shipper address as ship-from.
    ship_from_keys = [
        "ship_from_name", "ship_from_address1", "ship_from_address2",
        "ship_from_city", "ship_from_state", "ship_from_postal_code",
        "ship_from_country", "ship_from_phone",
    ]
    ship_from_data = {k: order_data[k] for k in ship_from_keys if order_data.get(k)}
    if ship_from_data:
        result["shipFrom"] = ship_from_data

    # Boolean service option indicators
    _BOOLEAN_FLAGS = [
        ("hold_for_pickup", "holdForPickup"),
        ("lift_gate_pickup", "liftGatePickup"),
        ("lift_gate_delivery", "liftGateDelivery"),
        ("direct_delivery_only", "directDeliveryOnly"),
        ("deliver_to_addressee_only", "deliverToAddresseeOnly"),
        ("carbon_neutral", "carbonNeutral"),
        ("dropoff_at_facility", "dropoffAtFacility"),
        ("shipper_release", "shipperRelease"),
        ("large_package", "largePackage"),
        ("additional_handling", "additionalHandling"),
    ]
    for order_key, simplified_key in _BOOLEAN_FLAGS:
        if _is_truthy(order_data.get(order_key)):
            result[simplified_key] = True

    # Cost center
    if order_data.get("cost_center"):
        result["costCenter"] = order_data["cost_center"]

    # Notification email
    if order_data.get("notification_email"):
        result["notificationEmail"] = order_data["notification_email"]

    # Inside delivery
    if order_data.get("inside_delivery"):
        result["insideDelivery"] = order_data["inside_delivery"]

    # International forms enrichment
    if order_data.get("terms_of_shipment"):
        result["termsOfShipment"] = order_data["terms_of_shipment"]
    if order_data.get("purchase_order_number"):
        result["purchaseOrderNumber"] = order_data["purchase_order_number"]
    if order_data.get("invoice_comments"):
        result["invoiceComments"] = order_data["invoice_comments"]
    if order_data.get("freight_charges"):
        result["freightCharges"] = order_data["freight_charges"]
    if order_data.get("insurance_charges"):
        result["insuranceCharges"] = order_data["insurance_charges"]
```

Then update `build_ups_api_payload()` to emit the UPS JSON structures:

```python
    # ShipmentDate
    if simplified.get("shipmentDate"):
        shipment["ShipmentDate"] = simplified["shipmentDate"]

    # ShipFrom
    if simplified.get("shipFrom"):
        sf = simplified["shipFrom"]
        shipment["ShipFrom"] = {
            "Name": truncate_address(sf.get("ship_from_name", ""), UPS_ADDRESS_MAX_LEN),
            "Address": {
                "AddressLine": [
                    truncate_address(sf.get("ship_from_address1", "")),
                    *([] if not sf.get("ship_from_address2") else [
                        truncate_address(sf["ship_from_address2"])
                    ]),
                ],
                "City": sf.get("ship_from_city", ""),
                "StateProvinceCode": sf.get("ship_from_state", ""),
                "PostalCode": sf.get("ship_from_postal_code", ""),
                "CountryCode": sf.get("ship_from_country", "US"),
            },
            "Phone": {"Number": normalize_phone(sf.get("ship_from_phone"))},
        }

    # CostCenter
    if simplified.get("costCenter"):
        shipment["CostCenter"] = simplified["costCenter"]

    # ShipmentServiceOptions — boolean indicators
    options = shipment.setdefault("ShipmentServiceOptions", {})
    _UPS_INDICATOR_MAP = [
        ("holdForPickup", "HoldForPickupIndicator"),
        ("liftGatePickup", "LiftGateForPickUpIndicator"),
        ("liftGateDelivery", "LiftGateForDeliveryIndicator"),
        ("directDeliveryOnly", "DirectDeliveryOnlyIndicator"),
        ("deliverToAddresseeOnly", "DeliverToAddresseeOnlyIndicator"),
        ("carbonNeutral", "UPScarbonneutralIndicator"),
        ("dropoffAtFacility", "DropoffAtUPSFacilityIndicator"),
    ]
    for simplified_key, ups_key in _UPS_INDICATOR_MAP:
        if simplified.get(simplified_key):
            options[ups_key] = ""

    # Notification email
    if simplified.get("notificationEmail"):
        options["Notification"] = {
            "NotificationCode": "6",
            "EMail": {"EMailAddress": [simplified["notificationEmail"]]},
        }

    # InsideDelivery
    if simplified.get("insideDelivery"):
        options["InsideDelivery"] = {"Code": str(simplified["insideDelivery"])}

    # Remove empty ShipmentServiceOptions
    if not options:
        shipment.pop("ShipmentServiceOptions", None)

    # Package-level indicators
    for pkg in packages:
        pkg_opts = pkg.setdefault("PackageServiceOptions", {})
        if simplified.get("shipperRelease"):
            pkg_opts["ShipperReleaseIndicator"] = ""
        if simplified.get("largePackage"):
            pkg["LargePackageIndicator"] = ""
        if simplified.get("additionalHandling"):
            pkg["AdditionalHandlingIndicator"] = ""
        if not pkg_opts:
            pkg.pop("PackageServiceOptions", None)
```

Also add to `_enrich_international_forms()`:

```python
    if simplified.get("termsOfShipment"):
        intl_forms["TermsOfShipment"] = simplified["termsOfShipment"]
    if simplified.get("purchaseOrderNumber"):
        intl_forms["PurchaseOrderNumber"] = simplified["purchaseOrderNumber"]
    if simplified.get("invoiceComments"):
        intl_forms["Comments"] = simplified["invoiceComments"]
    if simplified.get("freightCharges"):
        intl_forms["FreightCharges"] = {"MonetaryValue": simplified["freightCharges"]}
    if simplified.get("insuranceCharges"):
        intl_forms["InsuranceCharges"] = {"MonetaryValue": simplified["insuranceCharges"]}
```

**Step 4: Add rate payload parity for surcharge-affecting indicators**

Also update `build_rate_payload()` (around line 990+) to include surcharge-affecting indicators. Without these, preview costs will be lower than actual execution costs when these options are enabled:

```python
# In build_rate_payload(), after existing SaturdayDeliveryIndicator handling:
rate_svc_options = rate_shipment.setdefault("ShipmentServiceOptions", {})

_RATE_INDICATOR_MAP = [
    ("holdForPickup", "HoldForPickupIndicator"),
    ("liftGatePickup", "LiftGateForPickUpIndicator"),
    ("liftGateDelivery", "LiftGateForDeliveryIndicator"),
    ("carbonNeutral", "UPScarbonneutralIndicator"),
]
for simplified_key, ups_key in _RATE_INDICATOR_MAP:
    if simplified.get(simplified_key):
        rate_svc_options[ups_key] = ""

if simplified.get("insideDelivery"):
    rate_svc_options["InsideDelivery"] = {"Code": str(simplified["insideDelivery"])}

# Package-level surcharge indicators for rating
for pkg in rate_shipment.get("Package", []):
    if simplified.get("largePackage"):
        pkg["LargePackageIndicator"] = ""
    if simplified.get("additionalHandling"):
        pkg["AdditionalHandlingIndicator"] = ""
```

Add a test for rate payload parity:

```python
class TestRatePayloadParity:
    """Rate payload includes surcharge-affecting indicators."""

    def test_lift_gate_in_rate_payload(self):
        """LiftGateDelivery affects surcharges — must be in rate payload."""
        order_data = {"lift_gate_delivery": "true",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        simplified = build_shipment_request(order_data)
        rate = build_rate_payload(simplified)
        options = rate["RateRequest"]["Shipment"].get("ShipmentServiceOptions", {})
        assert "LiftGateForDeliveryIndicator" in options

    def test_large_package_in_rate_payload(self):
        """LargePackageIndicator affects surcharges — must be in rate payload."""
        order_data = {"large_package": "true",
                      "ship_to_name": "Test", "ship_to_address1": "123 Main",
                      "ship_to_city": "NYC", "ship_to_state": "NY",
                      "ship_to_postal_code": "10001"}
        simplified = build_shipment_request(order_data)
        rate = build_rate_payload(simplified)
        packages = rate["RateRequest"]["Shipment"].get("Package", [])
        assert any("LargePackageIndicator" in pkg for pkg in packages)
```

**Step 5: Run tests**

Run: `pytest tests/services/test_ups_payload_builder.py -v`
Expected: ALL PASS.

**Step 6: Commit**

```bash
git add src/services/ups_payload_builder.py tests/services/test_ups_payload_builder.py
git commit -m "feat(#11): add P0+P1 UPS payload field support + rate payload parity

Implements end-to-end support for: ShipmentDate, ShipFrom (dynamic w/ precedence),
CostCenter, 10 boolean service/package indicators, notification email,
InsideDelivery, and 5 international forms fields.

Rate payload mirrors surcharge-affecting indicators (LiftGate, LargePackage,
AdditionalHandling, CarbonNeutral, InsideDelivery, HoldForPickup) for
accurate preview cost estimation.

Closes #11"
```

---

## Task 12: Add DuckDB JSON path filter support for custom_attributes

**Depends on:** Task 9 (json.dumps serialization ensures the VARCHAR column contains valid JSON)

**Files:**
- Modify: `src/orchestrator/filter_compiler.py` (`_compile_condition()`)
- Test: `tests/orchestrator/test_filter_compiler.py` (existing file, add new test class)

**Step 1: Write the failing test**

```python
class TestCustomAttributesFiltering:
    """JSON path filtering for custom_attributes column."""

    def test_custom_attributes_dot_path_compiles(self):
        """custom_attributes.gift_message generates json_extract SQL."""
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
        col_types = {**COL_TYPES, "custom_attributes": "VARCHAR"}  # VARCHAR containing valid JSON strings
        result = compile_filter_spec(spec, schema, col_types, SCHEMA_SIG)
        assert "json_extract_string" in result.where_sql
        assert "gift_message" in result.where_sql
```

**Step 2: Run — expected FAIL**

**Step 3: Implement JSON path support**

In `_compile_condition()`, before the column validation check (`cond.column not in schema_columns`), add:

```python
    # Handle custom_attributes.* JSON path access
    is_json_path = False
    if cond.column.startswith("custom_attributes."):
        json_key = cond.column.split(".", 1)[1]
        if "custom_attributes" not in schema_columns:
            raise FilterCompilationError(
                FilterErrorCode.UNKNOWN_COLUMN,
                f"Column 'custom_attributes' not found in schema. "
                f"Cannot use JSON path {cond.column!r}.",
            )
        col = f"""json_extract_string("custom_attributes", '$.{json_key}')"""
        is_json_path = True
        columns_used.add("custom_attributes")
    else:
        # Standard column validation (existing code)
        if cond.column not in schema_columns:
            raise FilterCompilationError(...)
        columns_used.add(cond.column)
        col = f'"{cond.column}"'
```

**Step 4: Run tests**

Run: `pytest tests/orchestrator/test_filter_compiler.py -v`
Expected: ALL PASS.

**Step 5: Commit**

```bash
git add src/orchestrator/filter_compiler.py tests/orchestrator/test_filter_compiler.py
git commit -m "feat(#11): add DuckDB JSON path filter support for custom_attributes

Compiles custom_attributes.key queries to json_extract_string SQL.
Enables filtering on arbitrary platform-specific fields stored in the
custom_attributes JSON column."
```

---

## Task 13: Add CLI data source protocol methods

**Files:**
- Modify: `src/cli/protocol.py`
- Test: `tests/cli/test_protocol.py` (existing file, extend)

**Step 1: Add data models and protocol methods**

Add to `src/cli/protocol.py`:

```python
@dataclass
class DataSourceStatus:
    """Current data source connection status."""
    connected: bool
    source_type: str | None = None
    file_path: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    columns: list[str] = field(default_factory=list)

@dataclass
class SavedSourceSummary:
    """Saved data source profile summary."""
    id: str
    name: str
    source_type: str
    file_path: str | None = None
    last_connected: str | None = None
    row_count: int | None = None

    @classmethod
    def from_api(cls, data: dict) -> "SavedSourceSummary":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            source_type=data.get("source_type", ""),
            file_path=data.get("file_path"),
            last_connected=data.get("last_connected"),
            row_count=data.get("row_count"),
        )

@dataclass
class SourceSchemaColumn:
    """Column metadata from current data source."""
    name: str
    type: str
    nullable: bool = True
    sample_values: list[str] = field(default_factory=list)
```

Add methods to `ShipAgentClient` protocol:

```python
    async def get_source_status(self) -> DataSourceStatus:
        """Get current data source connection status."""
        ...

    async def connect_source(self, file_path: str) -> DataSourceStatus:
        """Import a local file as the active data source."""
        ...

    async def connect_db(self, connection_string: str, query: str) -> DataSourceStatus:
        """Import from a database using connection string and query.

        Both parameters are required — the backend (data_sources.py:75)
        rejects DB imports without a query.
        """
        ...

    async def disconnect_source(self) -> None:
        """Disconnect the current data source."""
        ...

    async def list_saved_sources(self) -> list[SavedSourceSummary]:
        """List saved data source profiles."""
        ...

    async def reconnect_saved_source(
        self, identifier: str, by_name: bool = True
    ) -> DataSourceStatus:
        """Reconnect a saved source by name or ID."""
        ...

    async def get_source_schema(self) -> list[SourceSchemaColumn]:
        """Get schema of current data source."""
        ...

    async def connect_platform(self, platform: str) -> DataSourceStatus:
        """Connect an env-configured external platform."""
        ...
```

**Step 2: Type check**

Run: `python -c "from src.cli.protocol import DataSourceStatus, SavedSourceSummary, SourceSchemaColumn; print('OK')"`
Expected: OK.

**Step 3: Commit**

```bash
git add src/cli/protocol.py
git commit -m "feat(#8): add data source protocol methods and data models

Extends ShipAgentClient with get_source_status, connect_source,
disconnect_source, list_saved_sources, reconnect_saved_source,
get_source_schema, and connect_platform methods."
```

---

## Task 14: Implement HttpClient data source methods

**Files:**
- Modify: `src/cli/http_client.py`
- Test: `tests/cli/test_http_client.py` (existing file, extend with data source tests)

**Step 1: Implement methods**

Add to `HttpClient` class in `src/cli/http_client.py`:

```python
    async def get_source_status(self) -> DataSourceStatus:
        """Get current data source connection status."""
        resp = await self._session.get(f"{self._base}/data-sources/status")
        if resp.status_code == 200:
            data = resp.json()
            return DataSourceStatus(
                connected=data.get("connected", False),
                source_type=data.get("source_type"),
                file_path=data.get("file_path"),
                row_count=data.get("row_count"),
                column_count=data.get("column_count"),
                columns=data.get("columns", []),
            )
        if resp.status_code == 404:
            return DataSourceStatus(connected=False)
        raise ShipAgentClientError(f"Failed to get source status: {resp.text}", resp.status_code)

    async def connect_source(self, file_path: str) -> DataSourceStatus:
        """Import a local file as the active data source."""
        from pathlib import Path
        path = Path(file_path)
        if not path.exists():
            raise ShipAgentClientError(f"File not found: {file_path}")
        with open(path, "rb") as f:
            files = {"file": (path.name, f, "application/octet-stream")}
            resp = await self._session.post(f"{self._base}/data-sources/upload", files=files)
        if resp.status_code in (200, 201):
            return await self.get_source_status()
        raise ShipAgentClientError(f"Failed to connect source: {resp.text}", resp.status_code)

    async def disconnect_source(self) -> None:
        """Disconnect the current data source."""
        resp = await self._session.post(f"{self._base}/data-sources/disconnect")
        if resp.status_code not in (200, 204):
            raise ShipAgentClientError(f"Failed to disconnect: {resp.text}", resp.status_code)

    async def list_saved_sources(self) -> list[SavedSourceSummary]:
        """List saved data source profiles."""
        resp = await self._session.get(f"{self._base}/saved-sources")
        if resp.status_code == 200:
            return [SavedSourceSummary.from_api(s) for s in resp.json()]
        raise ShipAgentClientError(f"Failed to list saved sources: {resp.text}", resp.status_code)

    async def reconnect_saved_source(
        self, identifier: str, by_name: bool = True
    ) -> DataSourceStatus:
        """Reconnect a saved source by name or ID."""
        payload = {"name": identifier} if by_name else {"id": identifier}
        resp = await self._session.post(f"{self._base}/saved-sources/reconnect", json=payload)
        if resp.status_code in (200, 201):
            return await self.get_source_status()
        raise ShipAgentClientError(f"Failed to reconnect: {resp.text}", resp.status_code)

    async def get_source_schema(self) -> list[SourceSchemaColumn]:
        """Get schema of current data source."""
        status = await self.get_source_status()
        if not status.connected:
            raise ShipAgentClientError("No data source connected")
        # Schema details are in the status response
        return [SourceSchemaColumn(name=col, type="VARCHAR") for col in status.columns]

    async def connect_db(self, connection_string: str, query: str) -> DataSourceStatus:
        """Import from a database using connection string and query."""
        payload = {"type": "database", "connection_string": connection_string, "query": query}
        resp = await self._session.post(f"{self._base}/data-sources/import", json=payload)
        if resp.status_code in (200, 201):
            return await self.get_source_status()
        raise ShipAgentClientError(f"Failed to connect DB: {resp.text}", resp.status_code)

    async def connect_platform(self, platform: str) -> DataSourceStatus:
        """Connect an env-configured external platform (Shopify only).

        Only Shopify has an env-status endpoint (/shopify/env-status).
        Other platforms require credential-based connection via the agent.
        """
        if platform.lower() != "shopify":
            raise ShipAgentClientError(
                f"Only 'shopify' supports env-based auto-connect. "
                f"Use the agent conversation for {platform}."
            )
        resp = await self._session.get(f"{self._base}/platforms/shopify/env-status")
        if resp.status_code != 200:
            raise ShipAgentClientError(f"Shopify not configured: {resp.text}")
        return await self.get_source_status()
```

**Step 2: Run type check**

Run: `python -c "from src.cli.http_client import HttpClient; print('OK')"`
Expected: OK.

**Step 3: Commit**

```bash
git add src/cli/http_client.py
git commit -m "feat(#8): implement data source methods in HttpClient

Maps protocol methods to existing REST endpoints:
GET/POST data-sources/*, GET/POST saved-sources/*, GET platforms/*/env-status."
```

---

## Task 15: Implement InProcessRunner data source methods

**Files:**
- Modify: `src/cli/runner.py`

**Step 1: Implement methods**

Add to `InProcessRunner` class. These call the gateway directly:

```python
    async def get_source_status(self) -> DataSourceStatus:
        """Get current data source connection status."""
        from src.services.gateway_provider import get_data_gateway
        try:
            gw = await get_data_gateway()
            schema = await gw.get_schema()
            return DataSourceStatus(
                connected=True,
                source_type=getattr(gw, 'source_type', 'unknown'),
                row_count=getattr(gw, 'row_count', None),
                column_count=len(schema) if schema else 0,
                columns=[c.name for c in schema] if schema else [],
            )
        except Exception:
            return DataSourceStatus(connected=False)

    async def connect_source(self, file_path: str) -> DataSourceStatus:
        """Import a local file as the active data source."""
        from src.services.gateway_provider import get_data_gateway
        gw = await get_data_gateway()
        await gw.import_source(file_path)
        return await self.get_source_status()

    async def disconnect_source(self) -> None:
        """Disconnect the current data source."""
        from src.services.gateway_provider import get_data_gateway
        gw = await get_data_gateway()
        await gw.disconnect()

    async def list_saved_sources(self) -> list[SavedSourceSummary]:
        """List saved data source profiles."""
        from src.services.saved_data_source_service import list_saved_sources
        sources = await list_saved_sources()
        return [SavedSourceSummary(
            id=s.id, name=s.name, source_type=s.source_type,
            file_path=s.file_path, last_connected=s.last_connected,
        ) for s in sources]

    async def reconnect_saved_source(
        self, identifier: str, by_name: bool = True
    ) -> DataSourceStatus:
        """Reconnect a saved source by name or ID."""
        from src.services.saved_data_source_service import reconnect_saved_source
        await reconnect_saved_source(identifier, by_name=by_name)
        return await self.get_source_status()

    async def get_source_schema(self) -> list[SourceSchemaColumn]:
        """Get schema of current data source."""
        from src.services.gateway_provider import get_data_gateway
        gw = await get_data_gateway()
        schema = await gw.get_schema()
        return [SourceSchemaColumn(name=c.name, type=c.type) for c in schema]

    async def connect_db(self, connection_string: str, query: str) -> DataSourceStatus:
        """Import from a database using connection string and query."""
        from src.services.gateway_provider import get_data_gateway
        gw = await get_data_gateway()
        await gw.import_database(connection_string, query)
        return await self.get_source_status()

    async def connect_platform(self, platform: str) -> DataSourceStatus:
        """Connect an env-configured external platform (Shopify only)."""
        if platform.lower() != "shopify":
            raise ValueError(
                f"Only 'shopify' supports env-based auto-connect. "
                f"Use the agent conversation for {platform}."
            )
        from src.services.gateway_provider import get_external_sources_client
        client = await get_external_sources_client()
        await client.connect_platform("shopify")
        return await self.get_source_status()
```

**Step 2: Commit**

```bash
git add src/cli/runner.py
git commit -m "feat(#8): implement data source methods in InProcessRunner

Direct gateway calls for standalone mode data source management."
```

---

## Task 16: Add CLI data-source sub-commands

**Files:**
- Modify: `src/cli/main.py`
- Modify: `src/cli/output.py`
- Modify: `src/cli/config.py`
- Test: `tests/cli/test_data_source_commands.py` (new file for CLI sub-app tests)
- Test: `tests/cli/test_config.py` (existing file, extend for DefaultDataSourceConfig)

**Step 1: Add Rich formatters to output.py**

```python
def format_source_status(status: DataSourceStatus) -> Panel:
    """Format data source status as a Rich panel."""
    if not status.connected:
        return Panel("[dim]No data source connected[/dim]", title="Data Source", border_style="dim")
    table = Table(show_header=False, box=None)
    table.add_row("Type:", status.source_type or "unknown")
    if status.file_path:
        table.add_row("Path:", status.file_path)
    if status.row_count is not None:
        table.add_row("Rows:", str(status.row_count))
    if status.column_count is not None:
        table.add_row("Columns:", str(status.column_count))
    return Panel(table, title="[bold]Data Source[/bold]", border_style="green")

def format_saved_sources(sources: list[SavedSourceSummary]) -> Table:
    """Format saved sources as a Rich table."""
    table = Table(title="Saved Data Sources")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Last Connected")
    for s in sources:
        table.add_row(s.id[:8], s.name, s.source_type, s.last_connected or "never")
    return table

def format_schema(columns: list[SourceSchemaColumn]) -> Table:
    """Format schema as a Rich table."""
    table = Table(title="Source Schema")
    table.add_column("Column", style="bold")
    table.add_column("Type")
    for col in columns:
        table.add_row(col.name, col.type)
    return table
```

**Step 2: Add data-source sub-app to main.py**

```python
data_source_app = typer.Typer(name="data-source", help="Manage data sources")
app.add_typer(data_source_app)

@data_source_app.command("status")
def data_source_status():
    """Show current data source connection status."""
    async def _run():
        async with get_client() as client:
            status = await client.get_source_status()
            console.print(format_source_status(status))
    asyncio.run(_run())

@data_source_app.command("connect")
def data_source_connect(
    file: str = typer.Argument(None, help="Path to CSV or Excel file"),
    db: str = typer.Option(None, "--db", help="Database connection string"),
    query: str = typer.Option(None, "--query", help="SQL query (required with --db)"),
    platform: str = typer.Option(None, "--platform", help="Platform name (shopify only)"),
):
    """Connect a data source (file, database, or platform)."""
    async def _run():
        async with get_client() as client:
            if platform:
                if platform.lower() != "shopify":
                    console.print(
                        f"[red]Only 'shopify' supports env-based auto-connect. "
                        f"Use the agent conversation for {platform}.[/red]"
                    )
                    raise typer.Exit(1)
                status = await client.connect_platform(platform)
            elif db:
                if not query:
                    console.print(
                        "[red]--query is required with --db. "
                        "Example: --db 'postgresql://...' --query 'SELECT * FROM orders'[/red]"
                    )
                    raise typer.Exit(1)
                status = await client.connect_db(db, query)
            elif file:
                status = await client.connect_source(file)
            else:
                console.print("[red]Specify a file path, --db + --query, or --platform shopify[/red]")
                raise typer.Exit(1)
            console.print(format_source_status(status))
    asyncio.run(_run())

@data_source_app.command("disconnect")
def data_source_disconnect():
    """Disconnect the current data source."""
    async def _run():
        async with get_client() as client:
            await client.disconnect_source()
            console.print("[green]Data source disconnected.[/green]")
    asyncio.run(_run())

@data_source_app.command("list-saved")
def data_source_list_saved():
    """List saved data source profiles."""
    async def _run():
        async with get_client() as client:
            sources = await client.list_saved_sources()
            if not sources:
                console.print("[dim]No saved sources found.[/dim]")
                return
            console.print(format_saved_sources(sources))
    asyncio.run(_run())

@data_source_app.command("reconnect")
def data_source_reconnect(
    identifier: str = typer.Argument(..., help="Saved source name or ID"),
    by_id: bool = typer.Option(False, "--id", help="Treat identifier as UUID"),
):
    """Reconnect a saved data source."""
    async def _run():
        async with get_client() as client:
            status = await client.reconnect_saved_source(identifier, by_name=not by_id)
            console.print(format_source_status(status))
    asyncio.run(_run())

@data_source_app.command("schema")
def data_source_schema():
    """Show schema of current data source."""
    async def _run():
        async with get_client() as client:
            columns = await client.get_source_schema()
            console.print(format_schema(columns))
    asyncio.run(_run())
```

**Step 3: Add --file/--source/--platform to interact command**

Update the existing `interact` command to accept pre-loading flags:

```python
@app.command("interact")
def interact(
    file: str = typer.Option(None, "--file", help="Load file before REPL"),
    source: str = typer.Option(None, "--source", help="Reconnect saved source before REPL"),
    platform: str = typer.Option(None, "--platform", help="Connect platform before REPL"),
):
    """Start conversational REPL."""
    async def _run():
        async with get_client() as client:
            # Pre-load data source if specified
            if file:
                await client.connect_source(file)
                console.print(f"[green]Loaded: {file}[/green]")
            elif source:
                await client.reconnect_saved_source(source)
                console.print(f"[green]Reconnected: {source}[/green]")
            elif platform:
                await client.connect_platform(platform)
                console.print(f"[green]Connected: {platform}[/green]")
            # Enter REPL
            await repl(client)
    asyncio.run(_run())
```

**Step 4: Add config enhancement**

Add to `src/cli/config.py`:

```python
class DefaultDataSourceConfig(BaseModel):
    """Default data source loaded on startup."""
    path: str | None = None
    saved_source: str | None = None
    platform: str | None = None

class ShipAgentConfig(BaseModel):
    # ... existing fields ...
    default_data_source: DefaultDataSourceConfig | None = None
```

**Step 5: Run tests**

Run: `pytest tests/cli/ -v`
Expected: ALL PASS.

**Step 6: Commit**

```bash
git add src/cli/main.py src/cli/output.py src/cli/config.py tests/cli/test_data_source_commands.py
git commit -m "feat(#8): add data-source CLI sub-commands and interact pre-loading

Adds: shipagent data-source status|connect|disconnect|list-saved|reconnect|schema
Adds: shipagent interact --file|--source|--platform for pre-loading
Adds: DefaultDataSourceConfig in config for persistent default source.

Closes #8"
```

---

## Task 17: Final integration test and cleanup

**Files:**
- All modified files
- Test: Full test suite

**Step 1: Run full test suite**

Run: `pytest -k "not stream and not sse and not progress" -v --tb=short`
Expected: ALL PASS. No regressions.

**Step 2: Run type check**

Run: `python -c "import src.orchestrator.filter_compiler; import src.services.ups_payload_builder; import src.cli.main; print('All imports OK')"`
Expected: OK.

**Step 3: Verify no stale patterns remain**

Run grep to verify old patterns are removed:
- `grep -r "explanation_parts" src/orchestrator/filter_compiler.py` → should return nothing
- `grep -r '"; ".join' src/orchestrator/filter_compiler.py src/orchestrator/filter_resolver.py` → should return nothing

**Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup after issue resolution"
```
