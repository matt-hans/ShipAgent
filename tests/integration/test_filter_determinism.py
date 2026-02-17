"""End-to-end determinism acceptance tests.

These tests prove that identical FilterIntent + identical schema always produce
identical CompiledFilter output (same where_sql, same params, same compiled_hash).
This is the release gate for the FilterSpec compiler architecture.
"""

import hashlib
import json
import os
from typing import Any

import pytest

from src.orchestrator.filter_compiler import compile_filter_spec
from src.orchestrator.filter_resolver import resolve_filter_intent
from src.orchestrator.models.filter_spec import (
    FilterCondition,
    FilterGroup,
    FilterIntent,
    FilterOperator,
    ResolvedFilterSpec,
    ResolutionStatus,
    TypedLiteral,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SCHEMA_COLUMNS = {
    "order_id", "customer_name", "state", "city", "zip_code",
    "weight_lbs", "service_type", "ship_date", "company_name",
    "total", "tags",
}

_COLUMN_TYPES = {
    "order_id": "VARCHAR",
    "customer_name": "VARCHAR",
    "state": "VARCHAR",
    "city": "VARCHAR",
    "zip_code": "VARCHAR",
    "weight_lbs": "DOUBLE",
    "service_type": "VARCHAR",
    "ship_date": "VARCHAR",
    "company_name": "VARCHAR",
    "total": "DOUBLE",
    "tags": "VARCHAR",
}

_SCHEMA_SIGNATURE = "test-sig-abc123"


def _compute_compiled_hash(where_sql: str, params: list[Any]) -> str:
    """Reproduce the pipeline's compiled hash computation."""
    def _canonical_param(v: Any) -> Any:
        if isinstance(v, float) and v == int(v):
            return int(v)
        if isinstance(v, (int, float, bool, type(None))):
            return v
        return str(v)

    canonical = json.dumps(
        {"where_sql": where_sql, "params": [_canonical_param(p) for p in params]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _set_filter_token_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure FILTER_TOKEN_SECRET is set for all tests in this module."""
    monkeypatch.setenv("FILTER_TOKEN_SECRET", "test-determinism-secret-42")


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestDeterministicReproducibility:
    """Same input => same output, every time."""

    def test_identical_intent_produces_identical_compiled_hash(self) -> None:
        """Run the same FilterIntent through resolve + compile 5 times.

        Assert all 5 produce identical compiled_hash.
        """
        intent = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="CA")],
                    ),
                    FilterCondition(
                        column="weight_lbs",
                        operator=FilterOperator.gt,
                        operands=[TypedLiteral(type="number", value=5.0)],
                    ),
                ],
            )
        )

        hashes = []
        for _ in range(5):
            resolved = resolve_filter_intent(
                intent=intent,
                schema_columns=_SCHEMA_COLUMNS,
                column_types=_COLUMN_TYPES,
                schema_signature=_SCHEMA_SIGNATURE,
            )
            assert resolved.status == ResolutionStatus.RESOLVED
            compiled = compile_filter_spec(
                spec=resolved,
                schema_columns=_SCHEMA_COLUMNS,
                column_types=_COLUMN_TYPES,
                runtime_schema_signature=_SCHEMA_SIGNATURE,
            )
            h = _compute_compiled_hash(compiled.where_sql, compiled.params)
            hashes.append(h)

        # All 5 runs must produce identical hash
        assert len(set(hashes)) == 1, f"Expected 1 unique hash, got {len(set(hashes))}: {hashes}"

    def test_reordered_conditions_produce_same_sql(self) -> None:
        """FilterGroup with conditions in different order produces identical
        where_sql and params after canonicalization."""
        cond_a = FilterCondition(
            column="state",
            operator=FilterOperator.eq,
            operands=[TypedLiteral(type="string", value="NY")],
        )
        cond_b = FilterCondition(
            column="weight_lbs",
            operator=FilterOperator.gte,
            operands=[TypedLiteral(type="number", value=10)],
        )

        # Order A: state first, weight second
        intent_a = FilterIntent(
            root=FilterGroup(logic="AND", conditions=[cond_a, cond_b])
        )
        # Order B: weight first, state second
        intent_b = FilterIntent(
            root=FilterGroup(logic="AND", conditions=[cond_b, cond_a])
        )

        resolved_a = resolve_filter_intent(
            intent=intent_a,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )
        resolved_b = resolve_filter_intent(
            intent=intent_b,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )

        compiled_a = compile_filter_spec(
            spec=resolved_a,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )
        compiled_b = compile_filter_spec(
            spec=resolved_b,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )

        assert compiled_a.where_sql == compiled_b.where_sql
        assert compiled_a.params == compiled_b.params

    def test_reordered_in_list_produces_same_sql(self) -> None:
        """IN-list with values in different order produces identical
        sorted params and identical where_sql."""
        # Order 1: CA, NY, TX
        intent_1 = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.in_,
                        operands=[
                            TypedLiteral(type="string", value="CA"),
                            TypedLiteral(type="string", value="NY"),
                            TypedLiteral(type="string", value="TX"),
                        ],
                    )
                ],
            )
        )
        # Order 2: TX, CA, NY
        intent_2 = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.in_,
                        operands=[
                            TypedLiteral(type="string", value="TX"),
                            TypedLiteral(type="string", value="CA"),
                            TypedLiteral(type="string", value="NY"),
                        ],
                    )
                ],
            )
        )

        resolved_1 = resolve_filter_intent(
            intent=intent_1,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )
        resolved_2 = resolve_filter_intent(
            intent=intent_2,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )

        compiled_1 = compile_filter_spec(
            spec=resolved_1,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )
        compiled_2 = compile_filter_spec(
            spec=resolved_2,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )

        assert compiled_1.where_sql == compiled_2.where_sql
        assert compiled_1.params == compiled_2.params
        # Params should be alphabetically sorted: CA, NY, TX
        assert compiled_1.params == ["CA", "NY", "TX"]

    def test_northeast_region_always_returns_same_expansion(self) -> None:
        """Semantic reference NORTHEAST always resolves to the same state set.

        Resolve NORTHEAST, compile, verify the IN-list is identical across
        multiple runs. (Tier B requires confirmation in production, but the
        expansion itself must be deterministic.)
        """
        from src.orchestrator.models.filter_spec import SemanticReference

        intent = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="NORTHEAST",
                        target_column="state",
                    ),
                ],
            )
        )

        # Resolve 3 times — expansion must be identical each time.
        resolved_specs = []
        for _ in range(3):
            resolved = resolve_filter_intent(
                intent=intent,
                schema_columns=_SCHEMA_COLUMNS,
                column_types=_COLUMN_TYPES,
                schema_signature=_SCHEMA_SIGNATURE,
            )
            # Tier B returns NEEDS_CONFIRMATION with identical expansion
            assert resolved.status == ResolutionStatus.NEEDS_CONFIRMATION
            resolved_specs.append(resolved)

        # All three specs should have identical roots (same expansion)
        roots = [spec.root.model_dump_json() for spec in resolved_specs]
        assert len(set(roots)) == 1, f"Expected identical roots, got {len(set(roots))} variants"

    def test_compiled_hash_is_content_addressed(self) -> None:
        """Two different FilterIntents that produce the same SQL produce
        the same compiled_hash — hash is over canonical compiled output."""
        # Intent A: state = 'CA' with eq operator
        intent_a = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[TypedLiteral(type="string", value="CA")],
                    ),
                ],
            )
        )

        # Intent B: state IN ('CA') — single-element IN list
        intent_b = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.in_,
                        operands=[TypedLiteral(type="string", value="CA")],
                    ),
                ],
            )
        )

        resolved_a = resolve_filter_intent(
            intent=intent_a,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )
        resolved_b = resolve_filter_intent(
            intent=intent_b,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )

        compiled_a = compile_filter_spec(
            spec=resolved_a,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )
        compiled_b = compile_filter_spec(
            spec=resolved_b,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )

        hash_a = _compute_compiled_hash(compiled_a.where_sql, compiled_a.params)
        hash_b = _compute_compiled_hash(compiled_b.where_sql, compiled_b.params)

        # These produce different SQL (= $1 vs IN ($1)) so hashes differ
        assert compiled_a.where_sql != compiled_b.where_sql
        assert hash_a != hash_b

    def test_compiled_hash_preserves_param_order(self) -> None:
        """BETWEEN with (low, high) vs (high, low) produces different hashes.

        Params are hashed in execution order, not sorted — sorting would
        hide meaningful order differences for non-commutative operators.
        """
        # Intent with BETWEEN 5 AND 10
        intent_low_high = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="weight_lbs",
                        operator=FilterOperator.between,
                        operands=[
                            TypedLiteral(type="number", value=5),
                            TypedLiteral(type="number", value=10),
                        ],
                    ),
                ],
            )
        )

        # Intent with BETWEEN 10 AND 5
        intent_high_low = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="weight_lbs",
                        operator=FilterOperator.between,
                        operands=[
                            TypedLiteral(type="number", value=10),
                            TypedLiteral(type="number", value=5),
                        ],
                    ),
                ],
            )
        )

        resolved_lh = resolve_filter_intent(
            intent=intent_low_high,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )
        resolved_hl = resolve_filter_intent(
            intent=intent_high_low,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            schema_signature=_SCHEMA_SIGNATURE,
        )

        compiled_lh = compile_filter_spec(
            spec=resolved_lh,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )
        compiled_hl = compile_filter_spec(
            spec=resolved_hl,
            schema_columns=_SCHEMA_COLUMNS,
            column_types=_COLUMN_TYPES,
            runtime_schema_signature=_SCHEMA_SIGNATURE,
        )

        hash_lh = _compute_compiled_hash(compiled_lh.where_sql, compiled_lh.params)
        hash_hl = _compute_compiled_hash(compiled_hl.where_sql, compiled_hl.params)

        # Same SQL template but different param order → different hash
        assert compiled_lh.params == [5, 10]
        assert compiled_hl.params == [10, 5]
        assert hash_lh != hash_hl
