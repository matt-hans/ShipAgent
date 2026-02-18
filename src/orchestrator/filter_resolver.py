"""FilterSpec semantic resolver — expands canonical terms to concrete conditions.

Resolves a FilterIntent (LLM output) into a ResolvedFilterSpec by expanding
SemanticReferences through canonical dictionaries. Tier A terms auto-expand,
Tier B terms require user confirmation via HMAC-signed tokens, Tier C terms
return suggestions for clarification.

See docs/plans/2026-02-16-filter-determinism-design.md Section 4.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Union

from src.orchestrator.models.filter_spec import (
    FilterCompilationError,
    FilterCondition,
    FilterErrorCode,
    FilterGroup,
    FilterIntent,
    FilterOperator,
    PendingConfirmation,
    ResolvedFilterSpec,
    ResolutionStatus,
    SemanticReference,
    TypedLiteral,
    UnresolvedTerm,
)
from src.services.filter_constants import (
    CANONICAL_DICT_VERSION,
    REGION_ALIASES,
    REGIONS,
    STATE_ABBREVIATIONS,
    get_tier,
    match_column_pattern,
    normalize_term,
    resolve_business_predicate,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_TOKEN_TTL_SECONDS = 600  # 10-minute TTL for resolution tokens


class FilterConfigError(Exception):
    """Raised when required filter configuration is missing."""


def _get_token_secret() -> str:
    """Lazy getter for FILTER_TOKEN_SECRET env var.

    Raises FilterConfigError on first use if not set. Not validated at import
    time to avoid breaking unrelated tests and code paths.

    Returns:
        The token secret string.

    Raises:
        FilterConfigError: If FILTER_TOKEN_SECRET is not set.
    """
    secret = os.environ.get("FILTER_TOKEN_SECRET")
    if not secret:
        raise FilterConfigError(
            "FILTER_TOKEN_SECRET environment variable is required for "
            "Tier B confirmation tokens. Set it in your .env file."
        )
    return secret


def validate_filter_config() -> None:
    """Validate filter configuration at startup.

    Called by FastAPI lifespan to fail fast at server boot.

    Raises:
        FilterConfigError: If required configuration is missing.
    """
    _get_token_secret()


# ---------------------------------------------------------------------------
# Arity rules for operators
# ---------------------------------------------------------------------------

_OPERATOR_ARITY: dict[FilterOperator, int | tuple[int, int | None]] = {
    FilterOperator.eq: 1,
    FilterOperator.neq: 1,
    FilterOperator.gt: 1,
    FilterOperator.gte: 1,
    FilterOperator.lt: 1,
    FilterOperator.lte: 1,
    FilterOperator.in_: (1, None),  # 1 or more
    FilterOperator.not_in: (1, None),
    FilterOperator.contains_ci: 1,
    FilterOperator.starts_with_ci: 1,
    FilterOperator.ends_with_ci: 1,
    FilterOperator.is_null: 0,
    FilterOperator.is_not_null: 0,
    FilterOperator.is_blank: 0,
    FilterOperator.is_not_blank: 0,
    FilterOperator.between: 2,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_filter_intent(
    intent: FilterIntent,
    schema_columns: set[str],
    column_types: dict[str, str],
    schema_signature: str,
    session_confirmations: dict[str, ResolvedFilterSpec] | None = None,
) -> ResolvedFilterSpec:
    """Resolve semantic references in a FilterIntent to concrete conditions.

    Args:
        intent: Structured filter intent from the LLM.
        schema_columns: Available column names from the current data source.
        column_types: Column name → DuckDB type mapping.
        schema_signature: Hash of the current schema for staleness detection.
        session_confirmations: Prior Tier B confirmations {token → confirmed spec}.

    Returns:
        ResolvedFilterSpec with status, resolved AST, and optional
        confirmation/clarification data.

    Raises:
        FilterCompilationError: On validation failures (unknown column, etc.).
    """
    if session_confirmations is None:
        session_confirmations = {}

    # Accumulate resolution state
    pending_confirmations: list[PendingConfirmation] = []
    unresolved_terms: list[UnresolvedTerm] = []
    child_statuses: list[ResolutionStatus] = []

    # NOTE: Confirmation matching is done per-term inside _expand_tier_b
    # (via _is_confirmed with semantic_term). There is NO global confirmation
    # override — a confirmed Tier-B term does not auto-resolve other terms.

    resolved_root = _resolve_group(
        intent.root,
        schema_columns,
        column_types,
        schema_signature,
        session_confirmations,
        pending_confirmations,
        unresolved_terms,
        child_statuses,
    )

    # Determine overall status from child statuses
    status = _worst_status(child_statuses)

    # Canonicalize the resolved tree
    canonicalized_root = _canonicalize_group(resolved_root)

    # Build explanation
    explanation = _build_explanation(canonicalized_root)

    # Generate resolution token for ALL resolutions (Tier-A and Tier-B).
    # This ensures every filter_spec has a server-issued, HMAC-signed provenance
    # token. The pipeline hook validates this token unconditionally, preventing
    # a client from submitting a hand-crafted RESOLVED spec without server proof.
    #
    # CRITICAL: The token encodes the resolution status. A NEEDS_CONFIRMATION
    # token cannot be used to execute — only RESOLVED tokens pass the hook.
    # This prevents the agent from flipping status to RESOLVED without a
    # genuine confirmation-then-re-resolve cycle.
    resolution_token = None
    if status in (ResolutionStatus.RESOLVED, ResolutionStatus.NEEDS_CONFIRMATION):
        resolution_token = _generate_resolution_token(
            schema_signature=schema_signature,
            resolved_root=canonicalized_root,
            resolution_status=status.value,
        )

    return ResolvedFilterSpec(
        status=status,
        root=canonicalized_root,
        explanation=explanation,
        resolution_token=resolution_token,
        pending_confirmations=pending_confirmations if pending_confirmations else None,
        unresolved_terms=unresolved_terms if unresolved_terms else None,
        schema_signature=schema_signature,
        canonical_dict_version=CANONICAL_DICT_VERSION,
    )


# ---------------------------------------------------------------------------
# Resolution — recursive group/node processing
# ---------------------------------------------------------------------------


def _resolve_group(
    group: FilterGroup,
    schema_columns: set[str],
    column_types: dict[str, str],
    schema_signature: str,
    session_confirmations: dict[str, ResolvedFilterSpec],
    pending_confirmations: list[PendingConfirmation],
    unresolved_terms: list[UnresolvedTerm],
    child_statuses: list[ResolutionStatus],
) -> FilterGroup:
    """Resolve all children in a FilterGroup.

    Args:
        group: The group to resolve.
        schema_columns: Valid column names.
        column_types: Column type map.
        schema_signature: Current schema hash.
        session_confirmations: Prior confirmed tokens.
        pending_confirmations: Accumulator for Tier B terms.
        unresolved_terms: Accumulator for Tier C terms.
        child_statuses: Accumulator for child resolution statuses.

    Returns:
        A new FilterGroup with resolved children.
    """
    resolved_children: list[Union[FilterCondition, FilterGroup]] = []

    for child in group.conditions:
        if isinstance(child, FilterCondition):
            _validate_condition(child, schema_columns)
            resolved_children.append(child)
            child_statuses.append(ResolutionStatus.RESOLVED)

        elif isinstance(child, SemanticReference):
            resolved = _resolve_semantic(
                child,
                schema_columns,
                column_types,
                schema_signature,
                session_confirmations,
                pending_confirmations,
                unresolved_terms,
                child_statuses,
            )
            if resolved is not None:
                resolved_children.append(resolved)

        elif isinstance(child, FilterGroup):
            resolved_child = _resolve_group(
                child,
                schema_columns,
                column_types,
                schema_signature,
                session_confirmations,
                pending_confirmations,
                unresolved_terms,
                child_statuses,
            )
            resolved_children.append(resolved_child)

    return FilterGroup(logic=group.logic, conditions=resolved_children)


def _validate_condition(
    cond: FilterCondition,
    schema_columns: set[str],
) -> None:
    """Validate a direct FilterCondition.

    Args:
        cond: The condition to validate.
        schema_columns: Valid column names.

    Raises:
        FilterCompilationError: On validation failure.
    """
    if cond.column not in schema_columns:
        raise FilterCompilationError(
            FilterErrorCode.UNKNOWN_COLUMN,
            f"Column {cond.column!r} not found in schema. "
            f"Available: {sorted(schema_columns)}.",
        )

    # Validate arity
    _validate_arity(cond.operator, len(cond.operands))


def _validate_arity(operator: FilterOperator, operand_count: int) -> None:
    """Validate operand count matches operator requirements.

    Args:
        operator: The filter operator.
        operand_count: Number of operands provided.

    Raises:
        FilterCompilationError: If arity is wrong.
    """
    expected = _OPERATOR_ARITY.get(operator)
    if expected is None:
        raise FilterCompilationError(
            FilterErrorCode.INVALID_OPERATOR,
            f"Operator {operator.value!r} is not recognized.",
        )

    if isinstance(expected, tuple):
        min_arity, max_arity = expected
        if operand_count < min_arity:
            raise FilterCompilationError(
                FilterErrorCode.INVALID_ARITY,
                f"Operator {operator.value!r} requires at least {min_arity} "
                f"operand(s), got {operand_count}.",
            )
        if max_arity is not None and operand_count > max_arity:
            raise FilterCompilationError(
                FilterErrorCode.INVALID_ARITY,
                f"Operator {operator.value!r} allows at most {max_arity} "
                f"operand(s), got {operand_count}.",
            )
    else:
        if operand_count != expected:
            raise FilterCompilationError(
                FilterErrorCode.INVALID_ARITY,
                f"Operator {operator.value!r} requires exactly {expected} "
                f"operand(s), got {operand_count}.",
            )


# ---------------------------------------------------------------------------
# Semantic resolution — expand canonical terms
# ---------------------------------------------------------------------------


def _resolve_semantic(
    ref: SemanticReference,
    schema_columns: set[str],
    column_types: dict[str, str],
    schema_signature: str,
    session_confirmations: dict[str, ResolvedFilterSpec],
    pending_confirmations: list[PendingConfirmation],
    unresolved_terms: list[UnresolvedTerm],
    child_statuses: list[ResolutionStatus],
) -> FilterCondition | FilterGroup | None:
    """Resolve a SemanticReference to a concrete condition.

    Args:
        ref: The semantic reference to resolve.
        schema_columns: Valid column names.
        column_types: Column type map.
        schema_signature: Current schema hash.
        session_confirmations: Prior confirmed tokens.
        pending_confirmations: Accumulator for Tier B terms.
        unresolved_terms: Accumulator for Tier C terms.
        child_statuses: Accumulator for child statuses.

    Returns:
        A FilterCondition, FilterGroup, or None (for unresolved terms).
    """
    normalized_key = normalize_term(ref.semantic_key)
    tier = get_tier(ref.semantic_key)

    # --- Tier A: auto-expand ---
    if tier == "A":
        return _expand_tier_a(ref, normalized_key, schema_columns, child_statuses)

    # --- Tier B: region or business predicate ---
    if tier == "B":
        return _expand_tier_b(
            ref,
            normalized_key,
            schema_columns,
            schema_signature,
            session_confirmations,
            pending_confirmations,
            child_statuses,
        )

    # --- Tier C: unknown term ---
    child_statuses.append(ResolutionStatus.UNRESOLVED)
    suggestions = _generate_suggestions(ref.semantic_key)
    unresolved_terms.append(
        UnresolvedTerm(phrase=ref.semantic_key, suggestions=suggestions)
    )
    # Return a placeholder condition that won't execute
    return None


def _expand_tier_a(
    ref: SemanticReference,
    normalized_key: str,
    schema_columns: set[str],
    child_statuses: list[ResolutionStatus],
) -> FilterCondition:
    """Expand a Tier A term (state abbreviation).

    Args:
        ref: The semantic reference.
        normalized_key: Normalized term key.
        schema_columns: Valid column names.
        child_statuses: Status accumulator.

    Returns:
        A FilterCondition with the expanded value.
    """
    # Validate target column
    if ref.target_column not in schema_columns:
        raise FilterCompilationError(
            FilterErrorCode.UNKNOWN_COLUMN,
            f"Target column {ref.target_column!r} not in schema.",
        )

    abbreviation = STATE_ABBREVIATIONS[normalized_key]
    child_statuses.append(ResolutionStatus.RESOLVED)
    return FilterCondition(
        column=ref.target_column,
        operator=FilterOperator.eq,
        operands=[TypedLiteral(type="string", value=abbreviation)],
    )


def _expand_tier_b(
    ref: SemanticReference,
    normalized_key: str,
    schema_columns: set[str],
    schema_signature: str,
    session_confirmations: dict[str, ResolvedFilterSpec],
    pending_confirmations: list[PendingConfirmation],
    child_statuses: list[ResolutionStatus],
) -> FilterCondition | FilterGroup:
    """Expand a Tier B term (region or business predicate).

    Checks session_confirmations for prior approval. If not confirmed,
    returns the expansion but marks as NEEDS_CONFIRMATION.

    Args:
        ref: The semantic reference.
        normalized_key: Normalized term key.
        schema_columns: Valid column names.
        schema_signature: Current schema hash.
        session_confirmations: Prior confirmed tokens.
        pending_confirmations: Accumulator for pending confirmations.
        child_statuses: Status accumulator.

    Returns:
        A FilterCondition or FilterGroup with the expanded value.
    """
    # Check if this is a region alias
    if normalized_key in REGION_ALIASES:
        region_key = REGION_ALIASES[normalized_key]
        states = REGIONS[region_key]

        # Validate target column
        if ref.target_column not in schema_columns:
            raise FilterCompilationError(
                FilterErrorCode.UNKNOWN_COLUMN,
                f"Target column {ref.target_column!r} not in schema.",
            )

        expansion = FilterCondition(
            column=ref.target_column,
            operator=FilterOperator.in_,
            operands=sorted(
                [TypedLiteral(type="string", value=s) for s in states],
                key=lambda t: str(t.value),
            ),
        )
        description = (
            f"{ref.semantic_key} → {region_key} "
            f"({len(states)} states: {', '.join(sorted(states))})"
        )

        # Check if we have a prior confirmation for this specific term
        if _is_confirmed(
            session_confirmations, schema_signature, semantic_term=ref.semantic_key
        ):
            child_statuses.append(ResolutionStatus.RESOLVED)
            return expansion

        child_statuses.append(ResolutionStatus.NEEDS_CONFIRMATION)
        pending_confirmations.append(
            PendingConfirmation(
                term=ref.semantic_key,
                expansion=description,
                tier="B",
            )
        )
        return expansion

    # Check if this is a business predicate
    business_predicate = resolve_business_predicate(ref.semantic_key)
    if business_predicate is not None:
        canonical_key, predicate = business_predicate
        patterns = predicate["target_column_patterns"]
        expansion_type = predicate["expansion"]

        # Match target column patterns against schema
        matched = match_column_pattern(patterns, schema_columns)
        if len(matched) == 0:
            raise FilterCompilationError(
                FilterErrorCode.MISSING_TARGET_COLUMN,
                f"Business predicate {canonical_key!r} requires one of "
                f"{patterns}, but none found in schema {sorted(schema_columns)}.",
            )
        if len(matched) > 1:
            raise FilterCompilationError(
                FilterErrorCode.AMBIGUOUS_TERM,
                f"Business predicate {canonical_key!r} matched multiple columns: "
                f"{matched}. Specify which column to use.",
            )

        target_col = matched[0]

        # Build expansion condition
        if expansion_type == "is_not_blank":
            op = FilterOperator.is_not_blank
        elif expansion_type == "is_blank":
            op = FilterOperator.is_blank
        else:
            raise FilterCompilationError(
                FilterErrorCode.INVALID_OPERATOR,
                f"Unknown expansion type {expansion_type!r} for "
                f"predicate {canonical_key!r}.",
            )

        expansion = FilterCondition(
            column=target_col,
            operator=op,
            operands=[],
        )
        description = (
            f"{canonical_key} → {expansion_type} on '{target_col}'"
        )

        # Check if we have a prior confirmation for this specific term
        if _is_confirmed(
            session_confirmations, schema_signature, semantic_term=canonical_key
        ):
            child_statuses.append(ResolutionStatus.RESOLVED)
            return expansion

        child_statuses.append(ResolutionStatus.NEEDS_CONFIRMATION)
        pending_confirmations.append(
            PendingConfirmation(
                term=canonical_key,
                expansion=description,
                tier="B",
            )
        )
        return expansion

    # Fallback — should not reach here if get_tier() is consistent
    child_statuses.append(ResolutionStatus.UNRESOLVED)
    return FilterCondition(
        column=ref.target_column,
        operator=FilterOperator.eq,
        operands=[TypedLiteral(type="string", value=ref.semantic_key)],
    )


def _is_confirmed(
    session_confirmations: dict[str, ResolvedFilterSpec],
    schema_signature: str,
    semantic_term: str | None = None,
) -> bool:
    """Check if a session confirmation exists for this specific term.

    Args:
        session_confirmations: Prior confirmed tokens {token → confirmed spec}.
        schema_signature: Current schema hash.
        semantic_term: The semantic key to match (e.g. 'northeast',
            'BUSINESS_RECIPIENT'). If provided, only matches confirmations
            whose pending_confirmations list includes this term.

    Returns:
        True if a valid, matching confirmation exists.
    """
    for token, confirmed in session_confirmations.items():
        if not _validate_resolution_token(token, schema_signature):
            continue
        if semantic_term is not None and confirmed.pending_confirmations:
            target_term = normalize_term(semantic_term)
            confirmed_terms = {
                normalize_term(pc.term) for pc in confirmed.pending_confirmations
            }
            if target_term not in confirmed_terms:
                continue
        return True
    return False


# ---------------------------------------------------------------------------
# Suggestion generation for Tier C
# ---------------------------------------------------------------------------


def _generate_suggestions(term: str) -> list[dict[str, str]]:
    """Generate 2-3 candidate suggestions for an unresolved term.

    Uses simple substring matching against known region aliases.

    Args:
        term: The unresolved term.

    Returns:
        List of suggestion dicts with 'key' and 'expansion'.
    """
    normalized = normalize_term(term)
    suggestions: list[dict[str, str]] = []

    # Check partial matches in region aliases
    for alias, region_key in REGION_ALIASES.items():
        # Simple relevance: check if any word in the term appears in the alias
        term_words = set(normalized.split())
        alias_words = set(alias.split())
        if term_words & alias_words:
            states = REGIONS.get(region_key, [])
            suggestions.append({
                "key": region_key,
                "expansion": f"{region_key} ({', '.join(sorted(states)[:5])}...)",
            })

    # Deduplicate by key
    seen = set()
    unique: list[dict[str, str]] = []
    for s in suggestions:
        if s["key"] not in seen:
            seen.add(s["key"])
            unique.append(s)

    # Return at most 3
    if unique:
        return unique[:3]

    # Fallback: suggest the most common regions
    fallback_keys = ["SOUTHEAST", "SOUTHWEST", "MIDWEST"]
    return [
        {"key": k, "expansion": f"{k} ({len(REGIONS.get(k, []))} states)"}
        for k in fallback_keys
    ]


# ---------------------------------------------------------------------------
# HMAC token generation and validation
# ---------------------------------------------------------------------------


def _generate_resolution_token(
    schema_signature: str,
    resolved_root: FilterGroup,
    resolution_status: str = "RESOLVED",
) -> str:
    """Generate an HMAC-signed resolution token.

    Args:
        schema_signature: Schema hash at resolution time.
        resolved_root: The resolved AST to bind to the token.
        resolution_status: The resolution status at token generation time.
            Encoded in the token to prevent status-flipping attacks.

    Returns:
        Base64-encoded token string.
    """
    secret = _get_token_secret()
    expires_at = time.time() + _TOKEN_TTL_SECONDS

    # Hash the resolved spec for tamper detection
    spec_hash = hashlib.sha256(
        resolved_root.model_dump_json().encode()
    ).hexdigest()

    payload = {
        "schema_signature": schema_signature,
        "canonical_dict_version": CANONICAL_DICT_VERSION,
        "resolved_spec_hash": spec_hash,
        "resolution_status": resolution_status,
        "expires_at": expires_at,
    }

    # Sign the payload
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()

    payload["signature"] = signature

    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return token


def _validate_resolution_token(
    token: str,
    schema_signature: str,
) -> dict | None:
    """Validate an HMAC-signed resolution token.

    Args:
        token: Base64-encoded token string.
        schema_signature: Current schema hash to validate against.

    Returns:
        Decoded payload dict if valid, None otherwise. Callers can
        inspect payload fields like 'resolution_status'.
    """
    try:
        secret = _get_token_secret()
        decoded = json.loads(base64.urlsafe_b64decode(token))

        # Check expiry
        if time.time() > decoded.get("expires_at", 0):
            return None

        # Check schema signature
        if decoded.get("schema_signature") != schema_signature:
            return None

        # Verify HMAC signature
        signature = decoded.pop("signature", None)
        if signature is None:
            return None

        payload_json = json.dumps(decoded, sort_keys=True)
        expected = hmac.new(
            secret.encode(), payload_json.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            return None

        return decoded

    except (json.JSONDecodeError, ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def _canonicalize_group(group: FilterGroup) -> FilterGroup:
    """Sort children of commutative groups for deterministic output.

    Args:
        group: The group to canonicalize.

    Returns:
        A new FilterGroup with sorted children.
    """
    canonicalized_children = []
    for child in group.conditions:
        if isinstance(child, FilterGroup):
            canonicalized_children.append(_canonicalize_group(child))
        elif isinstance(child, FilterCondition):
            # Sort IN-list operands
            if child.operator in (FilterOperator.in_, FilterOperator.not_in):
                sorted_operands = sorted(
                    child.operands, key=lambda o: str(o.value)
                )
                child = FilterCondition(
                    column=child.column,
                    operator=child.operator,
                    operands=sorted_operands,
                )
            canonicalized_children.append(child)
        else:
            canonicalized_children.append(child)

    # Sort children by their serialized form
    sorted_children = sorted(canonicalized_children, key=_serialize_node)
    return FilterGroup(logic=group.logic, conditions=sorted_children)


def _serialize_node(
    node: Union[FilterCondition, SemanticReference, FilterGroup],
) -> str:
    """Serialize a node to a stable string for sorting.

    Args:
        node: The AST node to serialize.

    Returns:
        Stable string representation.
    """
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


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------


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
    return "Filter: " + "; ".join(parts) + "."


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
                joiner = f" {group.logic.lower()} "
                parts.append(f"({joiner.join(sub)})")
    return parts


def _explain_condition(cond: FilterCondition) -> str:
    """Explain a single condition.

    Args:
        cond: The condition to explain.

    Returns:
        Human-readable description.
    """
    values = [str(o.value) for o in cond.operands]
    op = cond.operator

    if op == FilterOperator.eq:
        return f"{cond.column} = {values[0]}"
    elif op == FilterOperator.neq:
        return f"{cond.column} != {values[0]}"
    elif op in (FilterOperator.in_, FilterOperator.not_in):
        prefix = "in" if op == FilterOperator.in_ else "not in"
        return f"{cond.column} {prefix} [{', '.join(values)}]"
    elif op == FilterOperator.is_null:
        return f"{cond.column} is null"
    elif op == FilterOperator.is_not_null:
        return f"{cond.column} is not null"
    elif op == FilterOperator.is_blank:
        return f"{cond.column} is blank"
    elif op == FilterOperator.is_not_blank:
        return f"{cond.column} is not blank"
    elif op == FilterOperator.between:
        return f"{cond.column} between {values[0]} and {values[1]}"
    elif op in (FilterOperator.contains_ci, FilterOperator.starts_with_ci,
                FilterOperator.ends_with_ci):
        return f"{cond.column} {op.value} '{values[0]}'"
    else:
        return f"{cond.column} {op.value} {', '.join(values)}"


# ---------------------------------------------------------------------------
# Status precedence
# ---------------------------------------------------------------------------


_STATUS_PRIORITY = {
    ResolutionStatus.RESOLVED: 0,
    ResolutionStatus.NEEDS_CONFIRMATION: 1,
    ResolutionStatus.UNRESOLVED: 2,
}


def _worst_status(statuses: list[ResolutionStatus]) -> ResolutionStatus:
    """Return the worst (highest priority) status.

    Precedence: UNRESOLVED > NEEDS_CONFIRMATION > RESOLVED.

    Args:
        statuses: List of child statuses.

    Returns:
        The worst status, or RESOLVED if empty.
    """
    if not statuses:
        return ResolutionStatus.RESOLVED
    return max(statuses, key=lambda s: _STATUS_PRIORITY[s])
