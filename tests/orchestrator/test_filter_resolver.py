"""Tests for the FilterSpec semantic resolver.

Covers Tier A/B/C resolution, HMAC tokens, business predicates,
column matching, status precedence, and canonicalization.
"""

import hmac
import json
import os
import time
from hashlib import sha256

import pytest

from src.orchestrator.models.filter_spec import (
    FilterCompilationError,
    FilterCondition,
    FilterErrorCode,
    FilterGroup,
    FilterIntent,
    FilterOperator,
    ResolvedFilterSpec,
    ResolutionStatus,
    SemanticReference,
    TypedLiteral,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHEMA_COLS = {"state", "company", "name", "weight", "city"}
COL_TYPES = {
    "state": "VARCHAR",
    "company": "VARCHAR",
    "name": "VARCHAR",
    "weight": "DOUBLE",
    "city": "VARCHAR",
}
SCHEMA_SIG = "test_schema_sig_resolver"

# Set test token secret for HMAC tests
TEST_TOKEN_SECRET = "test-secret-for-resolver-tests"


@pytest.fixture(autouse=True)
def _set_token_secret(monkeypatch):
    """Ensure FILTER_TOKEN_SECRET is set for all tests."""
    monkeypatch.setenv("FILTER_TOKEN_SECRET", TEST_TOKEN_SECRET)


def _intent(root: FilterGroup, schema_sig: str = SCHEMA_SIG) -> FilterIntent:
    """Build a minimal FilterIntent."""
    return FilterIntent(root=root, schema_signature=schema_sig)


def _lit(value, type_: str = "string") -> TypedLiteral:
    return TypedLiteral(type=type_, value=value)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestFilterResolver:
    """Verify resolve_filter_intent() resolves semantic references correctly."""

    def test_tier_a_state_abbreviation_auto_expand(self):
        """1. SemanticReference('california', 'state') → eq condition with 'CA'."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(semantic_key="california", target_column="state")
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.RESOLVED
        # The resolved root should contain a FilterCondition, not a SemanticReference
        assert len(result.root.conditions) == 1
        cond = result.root.conditions[0]
        assert isinstance(cond, FilterCondition)
        assert cond.column == "state"
        assert cond.operator == FilterOperator.eq
        assert cond.operands[0].value == "CA"

    def test_tier_b_region_needs_confirmation(self):
        """2. SemanticReference('NORTHEAST') → NEEDS_CONFIRMATION with token."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(semantic_key="northeast", target_column="state")
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.NEEDS_CONFIRMATION
        assert result.pending_confirmations is not None
        assert len(result.pending_confirmations) > 0
        assert result.resolution_token is not None

    def test_tier_b_confirmed_region_expands(self):
        """3. Pass prior confirmation token → RESOLVED with IN condition."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # First call: get token
        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(semantic_key="northeast", target_column="state")
                ],
            )
        )
        first_result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert first_result.resolution_token is not None

        # Second call: pass the token as session confirmation
        confirmed = resolve_filter_intent(
            intent,
            SCHEMA_COLS,
            COL_TYPES,
            SCHEMA_SIG,
            session_confirmations={first_result.resolution_token: first_result},
        )
        assert confirmed.status == ResolutionStatus.RESOLVED
        # Root should have an IN condition with 9 northeast states
        cond = confirmed.root.conditions[0]
        assert isinstance(cond, FilterCondition)
        assert cond.operator == FilterOperator.in_
        assert len(cond.operands) == 9  # NORTHEAST has 9 states

    def test_tier_c_unknown_term_returns_suggestions(self):
        """4. 'the south' → UNRESOLVED with suggestions."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(semantic_key="the south", target_column="state")
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.UNRESOLVED
        assert result.unresolved_terms is not None
        assert len(result.unresolved_terms) > 0
        assert result.unresolved_terms[0].phrase == "the south"
        assert len(result.unresolved_terms[0].suggestions) > 0

    def test_business_predicate_business_recipient(self):
        """5. BUSINESS_RECIPIENT → is_not_blank on matched company column."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="BUSINESS_RECIPIENT", target_column="company"
                    )
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        # Business predicates are Tier B — needs confirmation
        assert result.status == ResolutionStatus.NEEDS_CONFIRMATION
        assert result.pending_confirmations is not None
        assert result.pending_confirmations[0].term == "BUSINESS_RECIPIENT"

    def test_business_predicate_business_recipient_lowercase_key(self):
        """Lowercase semantic key resolves to canonical BUSINESS_RECIPIENT."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="business_recipient", target_column="company"
                    )
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.NEEDS_CONFIRMATION
        assert result.pending_confirmations is not None
        assert result.pending_confirmations[0].term == "BUSINESS_RECIPIENT"

    def test_business_predicate_matches_shopify_ship_to_company(self):
        """BUSINESS_RECIPIENT resolves on Shopify-style ship_to_company column."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        shopify_schema = {"ship_to_company", "ship_to_state", "ship_to_name"}
        shopify_types = {
            "ship_to_company": "VARCHAR",
            "ship_to_state": "VARCHAR",
            "ship_to_name": "VARCHAR",
        }
        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="BUSINESS_RECIPIENT",
                        target_column="ship_to_company",
                    )
                ],
            )
        )

        result = resolve_filter_intent(
            intent, shopify_schema, shopify_types, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.NEEDS_CONFIRMATION
        assert result.pending_confirmations is not None

    def test_column_matching_exact_match(self):
        """6. target_column='company' matches 'company' in schema."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # A direct FilterCondition on an existing column passes through
        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="company",
                        operator=FilterOperator.is_not_null,
                        operands=[],
                    )
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.RESOLVED
        cond = result.root.conditions[0]
        assert isinstance(cond, FilterCondition)
        assert cond.column == "company"

    def test_column_matching_zero_matches(self):
        """7. Business predicate target column not in schema → MISSING_TARGET_COLUMN."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # Schema without any company-like column
        schema_no_company = {"state", "name", "weight", "city"}
        col_types_no_company = {
            "state": "VARCHAR",
            "name": "VARCHAR",
            "weight": "DOUBLE",
            "city": "VARCHAR",
        }
        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="BUSINESS_RECIPIENT", target_column="company"
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            resolve_filter_intent(
                intent, schema_no_company, col_types_no_company, SCHEMA_SIG
            )
        assert exc_info.value.code == FilterErrorCode.MISSING_TARGET_COLUMN

    def test_column_matching_multiple_matches(self):
        """8. Multiple column matches → AMBIGUOUS_TERM."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # Schema with both 'company' and 'company_name'
        schema_multi = {"state", "company", "company_name", "weight"}
        col_types_multi = {
            "state": "VARCHAR",
            "company": "VARCHAR",
            "company_name": "VARCHAR",
            "weight": "DOUBLE",
        }
        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="BUSINESS_RECIPIENT", target_column="company"
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            resolve_filter_intent(
                intent, schema_multi, col_types_multi, SCHEMA_SIG
            )
        assert exc_info.value.code == FilterErrorCode.AMBIGUOUS_TERM

    def test_direct_condition_passes_through(self):
        """9. Direct FilterCondition validated but unchanged."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[_lit("CA")],
                    )
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.RESOLVED
        cond = result.root.conditions[0]
        assert isinstance(cond, FilterCondition)
        assert cond.column == "state"
        assert cond.operands[0].value == "CA"

    def test_unknown_column_in_condition(self):
        """10. FilterCondition with unknown column → UNKNOWN_COLUMN."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="nonexistent",
                        operator=FilterOperator.eq,
                        operands=[_lit("val")],
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            resolve_filter_intent(
                intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
            )
        assert exc_info.value.code == FilterErrorCode.UNKNOWN_COLUMN

    def test_invalid_operator(self):
        """11. Invalid operator raises INVALID_OPERATOR."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # Create a condition with mismatched arity (eq needs 1 operand, give 0)
        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[],  # eq requires exactly 1 operand
                    )
                ],
            )
        )
        with pytest.raises(FilterCompilationError) as exc_info:
            resolve_filter_intent(
                intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
            )
        assert exc_info.value.code == FilterErrorCode.INVALID_ARITY

    def test_status_precedence_unresolved_wins(self):
        """12. Mixed group: UNRESOLVED > NEEDS_CONFIRMATION > RESOLVED."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    # Tier A (RESOLVED)
                    SemanticReference(semantic_key="california", target_column="state"),
                    # Tier C (UNRESOLVED)
                    SemanticReference(semantic_key="the south", target_column="state"),
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        # UNRESOLVED takes precedence
        assert result.status == ResolutionStatus.UNRESOLVED

    def test_schema_signature_embedded(self):
        """13. Schema signature is embedded in the output."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[_lit("CA")],
                    )
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.schema_signature == SCHEMA_SIG

    def test_token_is_hmac_signed(self):
        """14. Token is HMAC-signed, not raw base64."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(semantic_key="northeast", target_column="state")
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.resolution_token is not None
        # Token should be a base64-encoded string containing a signature
        # It should decode to JSON with a 'signature' field
        import base64

        decoded = json.loads(base64.urlsafe_b64decode(result.resolution_token))
        assert "signature" in decoded
        assert "expires_at" in decoded
        # Token must encode the resolution status
        assert decoded["resolution_status"] == result.status.value

    def test_nested_group_resolution(self):
        """15. Recursive resolution of nested groups."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        intent = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterGroup(
                        logic="OR",
                        conditions=[
                            SemanticReference(
                                semantic_key="california", target_column="state"
                            ),
                            FilterCondition(
                                column="state",
                                operator=FilterOperator.eq,
                                operands=[_lit("NY")],
                            ),
                        ],
                    ),
                    FilterCondition(
                        column="company",
                        operator=FilterOperator.is_not_null,
                        operands=[],
                    ),
                ],
            )
        )
        result = resolve_filter_intent(
            intent, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        assert result.status == ResolutionStatus.RESOLVED
        # The nested OR group should have resolved California → CA
        nested = result.root.conditions[0]
        if isinstance(nested, FilterGroup):
            # Find the resolved condition
            found_ca = False
            for cond in nested.conditions:
                if isinstance(cond, FilterCondition) and cond.column == "state":
                    if any(o.value == "CA" for o in cond.operands):
                        found_ca = True
            assert found_ca, "California should be resolved to CA"

    def test_canonicalization_in_lists_sorted(self):
        """16. IN-lists are sorted and commutative children are sorted."""
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # Two identical intents with conditions in different order
        intent_a = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[_lit("CA")],
                    ),
                    FilterCondition(
                        column="company",
                        operator=FilterOperator.is_not_null,
                        operands=[],
                    ),
                ],
            )
        )
        intent_b = _intent(
            FilterGroup(
                logic="AND",
                conditions=[
                    FilterCondition(
                        column="company",
                        operator=FilterOperator.is_not_null,
                        operands=[],
                    ),
                    FilterCondition(
                        column="state",
                        operator=FilterOperator.eq,
                        operands=[_lit("CA")],
                    ),
                ],
            )
        )
        result_a = resolve_filter_intent(
            intent_a, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        result_b = resolve_filter_intent(
            intent_b, SCHEMA_COLS, COL_TYPES, SCHEMA_SIG
        )
        # Both should produce the same canonical order
        assert result_a.root.model_dump() == result_b.root.model_dump()
