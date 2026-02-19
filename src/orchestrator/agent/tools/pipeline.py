"""Batch pipeline tool handlers.

Handles the shipping command pipeline, job creation, row management,
batch preview, and batch execution.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from src.db.connection import get_db_context
from src.orchestrator.filter_schema_inference import (
    resolve_fulfillment_status_column,
    resolve_total_column,
)
from src.orchestrator.binding_hash import build_binding_fingerprint
from src.orchestrator.filter_compiler import COMPILER_VERSION
from src.services.job_service import JobService
from src.services.decision_audit_context import get_decision_run_id, set_decision_job_id
from src.services.decision_audit_service import DecisionAuditService
from src.services.column_mapping import NORMALIZER_VERSION
from src.services.filter_constants import (
    BUSINESS_PREDICATES,
    REGIONS,
    REGION_ALIASES,
    STATE_ABBREVIATIONS,
    normalize_term,
)
from src.services.mapping_cache import MAPPING_VERSION
from src.services.ups_service_codes import translate_service_name

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _build_job_row_data_with_metadata,
    _command_explicitly_requests_service,
    _emit_event,
    _emit_preview_ready,
    _enrich_preview_rows_from_map,
    _err,
    _get_ups_client,
    _ok,
    _persist_job_source_signature,
    get_data_gateway,
)
from src.services.errors import UPSServiceError

logger = logging.getLogger(__name__)


def _audit_event(
    phase: str,
    event_name: str,
    payload: dict[str, Any],
    *,
    actor: str = "tool",
    tool_name: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Emit best-effort decision audit event in current run context."""
    DecisionAuditService.log_event_from_context(
        phase=phase,
        event_name=event_name,
        actor=actor,
        tool_name=tool_name,
        payload=payload,
        latency_ms=latency_ms,
    )

_FILTER_QUALIFIER_TERMS = frozenset(
    set(REGION_ALIASES.keys())
    | {
        "company",
        "companies",
        "business",
        "recipient",
        "where",
        "unfulfilled",
        "fulfilled",
        "pending",
        "cancelled",
        "canceled",
    }
)
_NUMERIC_QUALIFIER_PATTERNS = (
    " over ",
    " under ",
    " between ",
    " greater than ",
    " less than ",
    " more than ",
    " at least ",
    " at most ",
    " above ",
    " below ",
)
_STATE_NAME_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, STATE_ABBREVIATIONS.keys()), key=len, reverse=True)) + r")\b"
)
_STATE_CODE_UPPER_PATTERN = re.compile(r"\b[A-Z]{2}\b")


def _determinism_mode() -> str:
    raw = os.environ.get("DETERMINISM_ENFORCEMENT_MODE", "warn").strip().lower()
    return "enforce" if raw == "enforce" else "warn"


def _validate_allowed_args(
    tool_name: str,
    args: dict[str, Any],
    allowed: set[str],
) -> dict[str, Any] | None:
    unknown = sorted(k for k in args.keys() if k not in allowed)
    if not unknown:
        return None
    mode = _determinism_mode()
    logger.warning(
        "metric=tool_unknown_args_total tool=%s unknown_keys=%s mode=%s",
        tool_name,
        unknown,
        mode,
    )
    if mode == "enforce":
        return _err(
            f"Unexpected argument(s) for {tool_name}: {', '.join(unknown)}. "
            "Remove unknown keys and retry."
        )
    return None


def _command_implies_filter(command: str) -> bool:
    """Return True when the command clearly contains filter qualifiers."""
    normalized = f" {' '.join(normalize_term(command).split())} "
    if any(term in normalized for term in _FILTER_QUALIFIER_TERMS):
        return True
    if any(pattern in normalized for pattern in _NUMERIC_QUALIFIER_PATTERNS):
        return True
    if _STATE_NAME_PATTERN.search(normalized):
        return True
    return False


def _command_specificity_score(command: str) -> tuple[int, int]:
    """Score command richness for deterministic validation source selection."""
    normalized = normalize_term(command)
    score = 0
    if _expected_region_from_command(command):
        score += 6
    states = _expected_state_codes_from_command(command)
    if states:
        score += 4 + min(len(states), 6)
    if _command_requests_business_filter(command):
        score += 3
    lower, upper = _requested_total_bounds_from_command(command)
    if lower:
        score += 2
    if upper:
        score += 2
    if _requested_fulfillment_status_from_command(command):
        score += 2
    if _command_explicitly_requests_service(command):
        score += 1
    if _command_implies_filter(command):
        score += 1
    return score, len(normalized)


def _command_filter_fingerprint(
    command: str,
) -> tuple[
    str | None,
    frozenset[str],
    bool,
    tuple[tuple[float, bool] | None, tuple[float, bool] | None],
    str | None,
]:
    """Return normalized filter semantics used for safe cache reuse."""
    return (
        _expected_region_from_command(command),
        frozenset(_expected_state_codes_from_command(command)),
        _command_requests_business_filter(command),
        _requested_total_bounds_from_command(command),
        _requested_fulfillment_status_from_command(command),
    )


def _commands_filter_equivalent_for_cache(
    cached_command: str,
    current_command: str,
) -> bool:
    """True when two commands express the same filter semantics.

    This allows service-only or wording-only follow-ups to reuse the same
    resolved filter without re-running resolve_filter_intent.
    """
    if not _command_implies_filter(cached_command):
        return False
    if not _command_implies_filter(current_command):
        return False
    return _command_filter_fingerprint(cached_command) == _command_filter_fingerprint(
        current_command
    )


def _select_validation_command(
    arg_command: str,
    bridge: EventEmitterBridge | None,
) -> tuple[str, str]:
    """Choose the most constrained available command text for safety checks."""
    candidates: list[tuple[str, str]] = [("arg_command", arg_command)]
    if bridge is not None:
        bridge_shipping = getattr(bridge, "last_shipping_command", None)
        if isinstance(bridge_shipping, str):
            candidates.append(("bridge_last_shipping_command", bridge_shipping))
        bridge_message = getattr(bridge, "last_user_message", None)
        if isinstance(bridge_message, str):
            candidates.append(("bridge_last_user_message", bridge_message))
        bridge_resolved = getattr(bridge, "last_resolved_filter_command", None)
        if isinstance(bridge_resolved, str):
            candidates.append(("bridge_last_resolved_filter_command", bridge_resolved))

    best_source = "arg_command"
    best_command = arg_command.strip()
    best_score = _command_specificity_score(best_command)
    seen_norm: set[str] = set()

    for source, raw in candidates:
        candidate = raw.strip()
        if not candidate:
            continue
        normalized = normalize_term(candidate)
        if normalized in seen_norm:
            continue
        seen_norm.add(normalized)
        score = _command_specificity_score(candidate)
        if score > best_score:
            best_source = source
            best_command = candidate
            best_score = score

    return best_command, best_source


def _iter_conditions(group: Any) -> list[Any]:
    """Flatten FilterGroup tree into a list of FilterCondition nodes."""
    conditions: list[Any] = []
    stack = [group]
    while stack:
        node = stack.pop()
        for child in getattr(node, "conditions", []):
            if hasattr(child, "column") and hasattr(child, "operator"):
                conditions.append(child)
            elif hasattr(child, "conditions"):
                stack.append(child)
    return conditions


def _expected_region_from_command(command: str) -> str | None:
    """Return canonical region key referenced in command text, if any."""
    normalized = normalize_term(command)
    for alias, region_key in REGION_ALIASES.items():
        if alias in normalized:
            return region_key
    return None


def _expected_state_codes_from_command(command: str) -> set[str]:
    """Extract explicit state constraints from command text."""
    expected: set[str] = set()
    normalized = normalize_term(command)

    for match in _STATE_NAME_PATTERN.findall(normalized):
        code = STATE_ABBREVIATIONS.get(match)
        if code:
            expected.add(code)

    # Support explicit uppercase 2-letter state codes in user command.
    for token in _STATE_CODE_UPPER_PATTERN.findall(command):
        if token in REGIONS["ALL_US"]:
            expected.add(token)

    return expected


def _resolve_state_column(schema_columns: set[str]) -> str | None:
    """Resolve the most likely state column case-insensitively."""
    preferred = (
        "ship_to_state",
        "state",
        "stateprovincecode",
        "state_province_code",
        "province",
    )
    normalized_lookup = {col.casefold(): col for col in schema_columns}
    for key in preferred:
        match = normalized_lookup.get(key.casefold())
        if match:
            return match
    return None


def _literal_to_state_code(value: object) -> str | None:
    """Normalize state literal to two-letter code when possible."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    upper = candidate.upper()
    if upper in REGIONS["ALL_US"]:
        return upper
    return STATE_ABBREVIATIONS.get(normalize_term(candidate))


def _spec_state_codes(spec: Any, state_column: str) -> set[str]:
    """Collect explicit state codes constrained by spec on target column."""
    codes: set[str] = set()
    for cond in _iter_conditions(spec.root):
        column = str(getattr(cond, "column", ""))
        if column.casefold() != state_column.casefold():
            continue
        op = str(getattr(cond, "operator", ""))
        raw_values = [getattr(o, "value", None) for o in getattr(cond, "operands", [])]
        if op.endswith("eq") and raw_values:
            code = _literal_to_state_code(raw_values[0])
            if code:
                codes.add(code)
        elif op.endswith("in_") or op.endswith("in"):
            for raw in raw_values:
                code = _literal_to_state_code(raw)
                if code:
                    codes.add(code)
    return codes


def _append_state_filter(spec: Any, state_column: str, states: set[str]) -> None:
    """Append deterministic state IN condition to spec root."""
    from src.orchestrator.models.filter_spec import (
        FilterCondition,
        FilterOperator,
        TypedLiteral,
    )

    spec.root.conditions.append(
        FilterCondition(
            column=state_column,
            operator=FilterOperator.in_,
            operands=[
                TypedLiteral(type="string", value=s)
                for s in sorted(states)
            ],
        )
    )


def _requested_total_bounds_from_command(
    command: str,
) -> tuple[tuple[float, bool] | None, tuple[float, bool] | None]:
    """Extract lower/upper total bounds from command.

    Returns:
        (lower_bound, upper_bound) where each bound is (value, inclusive).
    """
    normalized = normalize_term(command)
    if "total" not in normalized and "amount" not in normalized:
        return None, None

    def _as_float(raw: str) -> float | None:
        cleaned = raw.replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    lower: tuple[float, bool] | None = None
    upper: tuple[float, bool] | None = None

    lower_patterns = (
        (r"(?:over|greater than|above)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", False),
        (r"(?:at least|>=?)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", True),
    )
    upper_patterns = (
        (r"(?:under|less than|below)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", False),
        (r"(?:at most|<=?)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", True),
    )

    for pattern, inclusive in lower_patterns:
        m = re.search(pattern, normalized)
        if m:
            value = _as_float(m.group(1))
            if value is not None:
                lower = (value, inclusive)
                break
    for pattern, inclusive in upper_patterns:
        m = re.search(pattern, normalized)
        if m:
            value = _as_float(m.group(1))
            if value is not None:
                upper = (value, inclusive)
                break

    between = re.search(
        r"between\s*\$?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:and|to)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)",
        normalized,
    )
    if between:
        lo = _as_float(between.group(1))
        hi = _as_float(between.group(2))
        if lo is not None and hi is not None:
            lower = (lo, True)
            upper = (hi, True)

    return lower, upper


def _resolve_total_column(schema_columns: set[str]) -> str | None:
    """Resolve likely monetary total column from schema."""
    return resolve_total_column(schema_columns)


def _coerce_numeric(value: object) -> float | None:
    """Best-effort numeric conversion for filter literal operands."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _spec_total_bounds(
    spec: Any,
    total_column: str,
) -> tuple[tuple[float, bool] | None, tuple[float, bool] | None]:
    """Extract lower/upper numeric bounds from spec on total column."""
    lower: tuple[float, bool] | None = None
    upper: tuple[float, bool] | None = None

    for cond in _iter_conditions(spec.root):
        column = str(getattr(cond, "column", ""))
        if column.casefold() != total_column.casefold():
            continue
        op = str(getattr(cond, "operator", ""))
        raw_values = [getattr(o, "value", None) for o in getattr(cond, "operands", [])]

        if op.endswith("between") and len(raw_values) >= 2:
            lo = _coerce_numeric(raw_values[0])
            hi = _coerce_numeric(raw_values[1])
            if lo is not None:
                lower = (lo, True)
            if hi is not None:
                upper = (hi, True)
            continue

        if not raw_values:
            continue
        value = _coerce_numeric(raw_values[0])
        if value is None:
            continue
        if op.endswith("gt"):
            lower = (value, False)
        elif op.endswith("gte"):
            lower = (value, True)
        elif op.endswith("lt"):
            upper = (value, False)
        elif op.endswith("lte"):
            upper = (value, True)

    return lower, upper


def _append_total_bounds_filter(
    spec: Any,
    total_column: str,
    lower: tuple[float, bool] | None,
    upper: tuple[float, bool] | None,
) -> None:
    """Append missing lower/upper total bound conditions to spec root."""
    from src.orchestrator.models.filter_spec import (
        FilterCondition,
        FilterOperator,
        TypedLiteral,
    )

    if lower is not None:
        lo, inclusive = lower
        spec.root.conditions.append(
            FilterCondition(
                column=total_column,
                operator=FilterOperator.gte if inclusive else FilterOperator.gt,
                operands=[TypedLiteral(type="number", value=lo)],
            )
        )
    if upper is not None:
        hi, inclusive = upper
        spec.root.conditions.append(
            FilterCondition(
                column=total_column,
                operator=FilterOperator.lte if inclusive else FilterOperator.lt,
                operands=[TypedLiteral(type="number", value=hi)],
            )
        )


def _spec_includes_region(spec: Any, region_key: str) -> bool:
    """Check whether resolved spec contains a condition matching region states."""
    expected = {s.upper() for s in REGIONS.get(region_key, [])}
    for cond in _iter_conditions(spec.root):
        op = str(getattr(cond, "operator", ""))
        raw_values = [getattr(o, "value", None) for o in getattr(cond, "operands", [])]
        values = {str(v).upper() for v in raw_values if isinstance(v, str)}
        if op.endswith("in_") or op.endswith("in"):
            if values and values.issubset(expected) and values:
                return True
        if op.endswith("eq") and len(values) == 1 and next(iter(values)) in expected:
            return True
    return False


def _command_requests_business_filter(command: str) -> bool:
    """Detect business/company qualifier in command text."""
    normalized = normalize_term(command)
    return any(t in normalized for t in ("company", "companies", "business"))


def _spec_includes_business_filter(spec: Any) -> bool:
    """Check whether resolved spec includes BUSINESS_RECIPIENT-like predicate."""
    patterns = BUSINESS_PREDICATES["BUSINESS_RECIPIENT"]["target_column_patterns"]
    for cond in _iter_conditions(spec.root):
        op = str(getattr(cond, "operator", ""))
        column = str(getattr(cond, "column", "")).lower()
        if op.endswith("is_not_blank") and any(p in column for p in patterns):
            return True
    return False


def _requested_fulfillment_status_from_command(command: str) -> str | None:
    """Infer requested fulfillment status from command text."""
    normalized = normalize_term(command)
    has_unfulfilled = (
        "unfulfilled" in normalized
        or "not fulfilled" in normalized
        or "pending fulfillment" in normalized
    )
    # Avoid classifying "unfulfilled" as "fulfilled" because of substring overlap.
    has_fulfilled = "fulfilled" in normalized and not has_unfulfilled
    if has_unfulfilled and not has_fulfilled:
        return "unfulfilled"
    if has_fulfilled and not has_unfulfilled:
        return "fulfilled"
    return None


def _resolve_fulfillment_status_column(schema_columns: set[str]) -> str | None:
    """Resolve fulfillment status column name case-insensitively."""
    return resolve_fulfillment_status_column(schema_columns)


def _spec_includes_expected_fulfillment_status(
    spec: Any,
    fulfillment_column: str,
    expected_status: str,
) -> bool:
    """Return True if spec already enforces expected fulfillment status."""
    expected_norm = expected_status.casefold()
    for cond in _iter_conditions(spec.root):
        column = str(getattr(cond, "column", ""))
        if column.casefold() != fulfillment_column.casefold():
            continue
        op = str(getattr(cond, "operator", ""))
        raw_values = [getattr(o, "value", None) for o in getattr(cond, "operands", [])]
        values = {str(v).casefold() for v in raw_values if isinstance(v, str)}
        if op.endswith("eq") and values == {expected_norm}:
            return True
        if (op.endswith("in_") or op.endswith("in")) and expected_norm in values:
            return True
    return False


def _spec_conflicts_with_expected_fulfillment_status(
    spec: Any,
    fulfillment_column: str,
    expected_status: str,
) -> bool:
    """Return True if spec contains an explicit opposite fulfillment status filter."""
    expected_norm = expected_status.casefold()
    known = {"fulfilled", "unfulfilled", "partial", "restocked", "open"}
    for cond in _iter_conditions(spec.root):
        column = str(getattr(cond, "column", ""))
        if column.casefold() != fulfillment_column.casefold():
            continue
        op = str(getattr(cond, "operator", ""))
        raw_values = [getattr(o, "value", None) for o in getattr(cond, "operands", [])]
        values = {str(v).casefold() for v in raw_values if isinstance(v, str)}
        if op.endswith("eq") and values and values != {expected_norm} and values <= known:
            return True
        if (op.endswith("in_") or op.endswith("in")) and values and expected_norm not in values and values <= known:
            return True
    return False


def _append_fulfillment_status_condition(
    spec: Any,
    fulfillment_column: str,
    expected_status: str,
) -> None:
    """Append deterministic fulfillment status condition to spec root."""
    from src.orchestrator.models.filter_spec import (
        FilterCondition,
        FilterOperator,
        TypedLiteral,
    )

    spec.root.conditions.append(
        FilterCondition(
            column=fulfillment_column,
            operator=FilterOperator.eq,
            operands=[TypedLiteral(type="string", value=expected_status)],
        )
    )


async def get_job_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the summary/status of a job.

    Args:
        args: Dict with 'job_id' (str).

    Returns:
        Tool response with job summary metrics.
    """
    job_id = args.get("job_id", "")
    if not job_id:
        return _err("job_id is required")

    try:
        with get_db_context() as db:
            svc = JobService(db)
            summary = svc.get_job_summary(job_id)
            return _ok(summary)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_job_status_tool failed: %s", e)
        return _err(f"Failed to get job status: {e}")


def _canonical_param(v: Any) -> Any:
    """Normalize a param value for deterministic hashing.

    Ensures dates use UTC ISO8601, decimals are normalized, and no type
    relies on locale-specific str() formatting.

    Args:
        v: Parameter value from CompiledFilter.params.

    Returns:
        JSON-safe canonical representation.
    """
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v.normalize())
    if isinstance(v, float):
        return str(v)
    return v


def _compute_compiled_hash(
    where_sql: str,
    params: list[Any],
    binding_fingerprint: str = "",
) -> str:
    """Compute deterministic SHA-256 hash of compiled query payload.

    Args:
        where_sql: Parameterized WHERE clause.
        params: Positional parameter values.

    Returns:
        Hex digest of the canonical JSON representation.
    """
    canonical = json.dumps(
        {
            "where_sql": where_sql,
            "params": [_canonical_param(p) for p in params],
            "binding_fingerprint": binding_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def ship_command_pipeline_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Fast-path pipeline for straightforward shipping commands.

    Performs compile → fetch → create job → add rows → preview in one call.
    Accepts exactly one of filter_spec or all_rows=true. Rejects where_clause.
    """
    from src.orchestrator.filter_compiler import compile_filter_spec
    from src.orchestrator.models.filter_spec import (
        FilterCompilationError,
        ResolvedFilterSpec,
    )

    unknown = _validate_allowed_args(
        "ship_command_pipeline",
        args,
        {"filter_spec", "all_rows", "command", "job_name", "service_code", "limit"},
    )
    if unknown is not None:
        return unknown

    command = str(args.get("command", "")).strip()
    if not command:
        return _err("command is required")

    validation_command, validation_source = _select_validation_command(command, bridge)
    if validation_command != command:
        logger.info(
            "ship_command_pipeline selected validation command source=%s "
            "arg_command=%r selected_command=%r",
            validation_source,
            command[:120],
            validation_command[:120],
        )
    _audit_event(
        "pipeline",
        "ship_command_pipeline.validation_command.selected",
        {
            "validation_source": validation_source,
            "input_command_len": len(command),
            "selected_command_len": len(validation_command),
        },
        tool_name="ship_command_pipeline",
    )

    # Hard cutover: reject legacy where_clause
    if "where_clause" in args:
        return _err(
            "where_clause is not accepted. Use resolve_filter_intent "
            "to create a filter_spec."
        )

    filter_spec_raw = args.get("filter_spec")
    all_rows = bool(args.get("all_rows", False))
    used_cached_filter_spec = False

    # Exactly one of filter_spec or all_rows must be provided
    if filter_spec_raw and all_rows:
        return _err(
            "Conflicting arguments: provide filter_spec OR all_rows=true, not both."
        )
    if not filter_spec_raw and not all_rows:
        cached_spec: dict[str, Any] | None = None
        if bridge is not None:
            cached_spec_raw = getattr(bridge, "last_resolved_filter_spec", None)
            cached_command_raw = getattr(bridge, "last_resolved_filter_command", None)
            if isinstance(cached_spec_raw, dict) and isinstance(cached_command_raw, str):
                same_command = (
                    normalize_term(cached_command_raw)
                    == normalize_term(validation_command)
                )
                same_filter_semantics = _commands_filter_equivalent_for_cache(
                    cached_command_raw,
                    validation_command,
                )
                if same_command or same_filter_semantics:
                    cached_spec = cached_spec_raw
                    if same_filter_semantics and not same_command:
                        logger.info(
                            "ship_command_pipeline reusing cached filter_spec via "
                            "semantic-equivalence cached_command=%r current_command=%r",
                            cached_command_raw[:120],
                            validation_command[:120],
                        )

        if cached_spec is not None:
            filter_spec_raw = cached_spec
            used_cached_filter_spec = True
            logger.info(
                "ship_command_pipeline recovered missing filter_spec from bridge cache",
            )
        else:
            return _err(
                "Either filter_spec or all_rows=true is required. "
                "Use resolve_filter_intent to create a filter, or set "
                "all_rows=true to ship everything."
            )
    if all_rows and _command_implies_filter(validation_command):
        return _err(
            "all_rows=true is not allowed when the command contains filters "
            "(e.g., regions or business/company qualifiers). Resolve and pass "
            "a filter_spec via resolve_filter_intent."
        )

    try:
        limit = int(args.get("limit", 250))
    except (TypeError, ValueError):
        limit = 250
    if limit < 1:
        limit = 250
    job_name = str(args.get("job_name") or validation_command or "Shipping Job")
    raw_service_code = args.get("service_code")
    service_code: str | None = None
    if raw_service_code:
        resolved = translate_service_name(str(raw_service_code))
        if _command_explicitly_requests_service(validation_command):
            service_code = resolved
            logger.info(
                "ship_command_pipeline applying explicit service override=%s",
                service_code,
            )
        else:
            logger.info(
                "ship_command_pipeline ignoring implicit service_code=%s for "
                "command without explicit service; using row-level service data",
                raw_service_code,
            )

    raw_packaging = args.get("packaging_type")
    packaging_override: str | None = None
    if raw_packaging:
        from src.services.ups_payload_builder import resolve_packaging_code

        packaging_override = resolve_packaging_code(str(raw_packaging))
        logger.info(
            "ship_command_pipeline applying packaging override=%s (raw=%s)",
            packaging_override,
            raw_packaging,
        )

    # Compile filter or use all-rows path
    filter_explanation = ""
    filter_audit: dict[str, Any] = {}
    enforced_state_codes: list[str] | None = None
    enforced_total_bounds: dict[str, Any] | None = None
    enforced_fulfillment_status: str | None = None
    gw = await get_data_gateway()
    source_info = await gw.get_source_info()
    if source_info is None:
        return _err("No data source connected.")
    if not isinstance(source_info, dict):
        logger.warning(
            "ship_command_pipeline expected dict source_info, got %s; "
            "proceeding without schema metadata",
            type(source_info).__name__,
        )
        source_info = {}
    deterministic_ready = bool(source_info.get("deterministic_ready", True))
    if not deterministic_ready:
        strategy = source_info.get("row_key_strategy", "none")
        logger.warning(
            "metric=determinism_guard_blocked_total tool=ship_command_pipeline row_key_strategy=%s",
            strategy,
        )
        return _err(
            "Shipping determinism guard: active source does not have stable row ordering "
            f"(row_key_strategy={strategy}). Re-import with row_key_columns or use a "
            "source with PRIMARY KEY/UNIQUE constraints."
        )

    raw_signature = source_info.get("signature", "")
    schema_signature = raw_signature if isinstance(raw_signature, str) else ""
    source_signature = {
        "source_type": source_info.get("source_type", "unknown"),
        "source_ref": source_info.get("path") or source_info.get("query") or "",
        "schema_fingerprint": schema_signature,
    }
    binding_fingerprint = build_binding_fingerprint(
        source_signature=source_signature,
        compiler_version=COMPILER_VERSION,
        mapping_version=MAPPING_VERSION,
        normalizer_version=NORMALIZER_VERSION,
    )
    if used_cached_filter_spec and bridge is not None:
        cached_signature_raw = getattr(
            bridge,
            "last_resolved_filter_schema_signature",
            None,
        )
        cached_signature = (
            cached_signature_raw.strip()
            if isinstance(cached_signature_raw, str)
            else ""
        )
        if not cached_signature or not schema_signature or cached_signature != schema_signature:
            return _err(
                "Cached filter_spec no longer matches the active source schema. "
                "Re-run resolve_filter_intent before shipping."
            )

    if filter_spec_raw:
        # Compile FilterSpec → parameterized SQL
        columns = source_info.get("columns", [])
        schema_columns = {col["name"] for col in columns}
        column_types = {col["name"]: col["type"] for col in columns}

        try:
            spec = ResolvedFilterSpec(**filter_spec_raw)
        except Exception as e:
            return _err(f"Invalid filter_spec structure: {e}")

        expected_region = _expected_region_from_command(validation_command)
        if expected_region and not _spec_includes_region(spec, expected_region):
            return _err(
                f"Filter mismatch: command references region '{expected_region}' "
                "but filter_spec does not include a matching state filter. "
                "Re-run resolve_filter_intent with the correct region semantic key."
            )
        if _command_requests_business_filter(validation_command) and not _spec_includes_business_filter(spec):
            return _err(
                "Filter mismatch: command requests companies/business recipients, "
                "but filter_spec does not include a business/company predicate. "
                "Re-run resolve_filter_intent and include BUSINESS_RECIPIENT."
            )
        expected_states = _expected_state_codes_from_command(validation_command)
        state_column = _resolve_state_column(schema_columns)
        if expected_states and not state_column:
            return _err(
                "Filter mismatch: command includes explicit state constraints "
                f"{sorted(expected_states)}, but this data source has no recognized "
                "state column. Reconnect source and re-run resolve_filter_intent."
            )
        if expected_states and state_column:
            spec_states = _spec_state_codes(spec, state_column)
            if spec_states and not expected_states.issubset(spec_states):
                return _err(
                    "Filter mismatch: command constrains states to "
                    f"{sorted(expected_states)}, but filter_spec uses "
                    f"{sorted(spec_states)}. Re-run resolve_filter_intent with "
                    "the exact state set."
                )
            if not spec_states:
                _append_state_filter(spec, state_column, expected_states)
                filter_spec_raw = spec.model_dump()
                enforced_state_codes = sorted(expected_states)
                logger.info(
                    "ship_command_pipeline enforced state set=%s on column=%s",
                    enforced_state_codes,
                    state_column,
                )

        expected_lower, expected_upper = _requested_total_bounds_from_command(
            validation_command
        )
        total_column = _resolve_total_column(schema_columns)
        if (expected_lower or expected_upper) and not total_column:
            return _err(
                "Filter mismatch: command includes total/amount bounds, but this "
                "data source has no recognized total column. Re-run "
                "resolve_filter_intent with a source that includes totals."
            )
        if (expected_lower or expected_upper) and total_column:
            actual_lower, actual_upper = _spec_total_bounds(spec, total_column)
            if (
                expected_lower
                and actual_lower
                and (
                    abs(expected_lower[0] - actual_lower[0]) > 1e-9
                    or expected_lower[1] != actual_lower[1]
                )
            ):
                return _err(
                    "Filter mismatch: command lower total bound is "
                    f"{expected_lower[0]}, but filter_spec uses {actual_lower[0]}. "
                    "Re-run resolve_filter_intent with the exact price range."
                )
            if (
                expected_upper
                and actual_upper
                and (
                    abs(expected_upper[0] - actual_upper[0]) > 1e-9
                    or expected_upper[1] != actual_upper[1]
                )
            ):
                return _err(
                    "Filter mismatch: command upper total bound is "
                    f"{expected_upper[0]}, but filter_spec uses {actual_upper[0]}. "
                    "Re-run resolve_filter_intent with the exact price range."
                )
            if (
                (expected_lower and not actual_lower)
                or (expected_upper and not actual_upper)
            ):
                _append_total_bounds_filter(
                    spec,
                    total_column,
                    expected_lower if not actual_lower else None,
                    expected_upper if not actual_upper else None,
                )
                filter_spec_raw = spec.model_dump()
                enforced_total_bounds = {
                    "column": total_column,
                    "lower": expected_lower[0] if expected_lower else None,
                    "upper": expected_upper[0] if expected_upper else None,
                }
                logger.info(
                    "ship_command_pipeline enforced total bounds=%s on column=%s",
                    enforced_total_bounds,
                    total_column,
                )

        expected_fulfillment = _requested_fulfillment_status_from_command(validation_command)
        fulfillment_column = _resolve_fulfillment_status_column(schema_columns)
        if expected_fulfillment and not fulfillment_column:
            return _err(
                "Filter mismatch: command requests fulfillment status filtering, "
                "but this data source has no recognized fulfillment_status column."
            )
        if expected_fulfillment and fulfillment_column:
            if _spec_conflicts_with_expected_fulfillment_status(
                spec,
                fulfillment_column,
                expected_fulfillment,
            ):
                return _err(
                    "Filter mismatch: command requests "
                    f"'{expected_fulfillment}' orders, but filter_spec enforces a "
                    "different fulfillment_status. Re-run resolve_filter_intent "
                    "with the exact fulfillment status."
                )
            if not _spec_includes_expected_fulfillment_status(
                spec,
                fulfillment_column,
                expected_fulfillment,
            ):
                _append_fulfillment_status_condition(
                    spec,
                    fulfillment_column,
                    expected_fulfillment,
                )
                filter_spec_raw = spec.model_dump()
                enforced_fulfillment_status = expected_fulfillment
                logger.info(
                    "ship_command_pipeline enforced fulfillment_status=%s on column=%s",
                    expected_fulfillment,
                    fulfillment_column,
                )

        try:
            compiled = compile_filter_spec(
                spec=spec,
                schema_columns=schema_columns,
                column_types=column_types,
                runtime_schema_signature=schema_signature,
            )
        except FilterCompilationError as e:
            return _err(f"[{e.code.value}] {e.message}")
        except Exception as e:
            logger.error("ship_command_pipeline compile failed: %s", e)
            return _err(f"Filter compilation failed: {e}")

        where_sql = compiled.where_sql
        params = compiled.params
        filter_explanation = compiled.explanation

        # Build audit trail
        spec_hash = hashlib.sha256(
            json.dumps(filter_spec_raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        compiled_hash = _compute_compiled_hash(
            where_sql,
            params,
            binding_fingerprint=binding_fingerprint,
        )

        filter_audit = {
            "spec_hash": spec_hash,
            "compiled_hash": compiled_hash,
            "schema_signature": schema_signature,
            "dict_version": spec.canonical_dict_version,
            "validation_command_source": validation_source,
            "source_fingerprint": binding_fingerprint,
            "compiler_version": COMPILER_VERSION,
            "mapping_version": MAPPING_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
        }
        if used_cached_filter_spec:
            filter_audit["recovered_from_cache"] = True
        if enforced_state_codes:
            filter_audit["enforced_state_codes"] = enforced_state_codes
        if enforced_total_bounds:
            filter_audit["enforced_total_bounds"] = enforced_total_bounds
        if enforced_fulfillment_status:
            filter_audit["enforced_fulfillment_status"] = enforced_fulfillment_status
        _audit_event(
            "pipeline",
            "ship_command_pipeline.filter_compiled",
            {
                "validation_command_source": validation_source,
                "compiled_hash": compiled_hash,
                "spec_hash": spec_hash,
                "schema_signature": schema_signature,
                "source_fingerprint": binding_fingerprint,
                "enforced_state_codes": enforced_state_codes,
                "enforced_total_bounds": enforced_total_bounds,
                "enforced_fulfillment_status": enforced_fulfillment_status,
                "recovered_from_cache": used_cached_filter_spec,
            },
            tool_name="ship_command_pipeline",
        )
    else:
        # all_rows path
        where_sql = "1=1"
        params = []
        filter_explanation = "All rows (no filter applied)"

    try:
        total_count = 0
        used_count_endpoint = False
        get_rows_with_count = getattr(gw, "get_rows_with_count", None)
        if callable(get_rows_with_count):
            count_result = await get_rows_with_count(
                where_sql=where_sql,
                limit=limit,
                params=params,
            )
            if isinstance(count_result, dict):
                result_rows = count_result.get("rows")
                if isinstance(result_rows, list):
                    fetched_rows = result_rows
                    total_count = int(count_result.get("total_count", len(fetched_rows)))
                    used_count_endpoint = True

        if not used_count_endpoint:
            fetched_rows = await gw.get_rows_by_filter(
                where_sql=where_sql,
                limit=limit,
                params=params,
            )
            total_count = len(fetched_rows)

        # Deterministic safety: never ship a silently truncated match set.
        if total_count > len(fetched_rows):
            max_fetch_rows_raw = os.environ.get("SHIP_PIPELINE_MAX_FETCH_ROWS", "1000")
            try:
                max_fetch_rows = max(1, int(max_fetch_rows_raw))
            except ValueError:
                max_fetch_rows = 1000

            if total_count > max_fetch_rows:
                return _err(
                    "Filter matched "
                    f"{total_count} rows, exceeding SHIP_PIPELINE_MAX_FETCH_ROWS="
                    f"{max_fetch_rows}. Refine the filter and retry."
                )

            fetched_rows = await gw.get_rows_by_filter(
                where_sql=where_sql,
                limit=total_count,
                params=params,
            )
            logger.info(
                "ship_command_pipeline expanded truncated fetch "
                "where_sql=%s total_count=%d requested_limit=%d",
                where_sql,
                total_count,
                limit,
            )
    except Exception as e:
        logger.error("ship_command_pipeline fetch failed: %s", e)
        return _err(f"Failed to fetch rows: {e}")

    if not fetched_rows:
        return _err("No rows matched the provided filter.")

    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import build_shipper

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    shipper = build_shipper()
    ups = await _get_ups_client()
    row_map: dict[int, dict[str, Any]] = {}

    try:
        with get_db_context() as db:
            job_service = JobService(db)
            job = job_service.create_job(
                name=job_name,
                original_command=validation_command,
            )
            set_decision_job_id(job.id)
            DecisionAuditService.set_run_job_id(
                get_decision_run_id(),
                job.id,
            )
            _audit_event(
                "pipeline",
                "ship_command_pipeline.job_created",
                {"job_id": job.id, "job_name": job_name},
                tool_name="ship_command_pipeline",
            )
            await _persist_job_source_signature(
                job.id,
                db,
                source_signature=source_signature,
            )
            try:
                mapping_started = time.perf_counter()
                row_payload, mapping_hash = _build_job_row_data_with_metadata(
                    fetched_rows,
                    service_code_override=service_code,
                    packaging_type_override=packaging_override,
                    schema_fingerprint=schema_signature,
                )
                if filter_audit is not None:
                    filter_audit["mapping_hash"] = mapping_hash or ""
                _audit_event(
                    "mapping",
                    "ship_command_pipeline.mapping_resolved",
                    {
                        "job_id": job.id,
                        "row_count": len(fetched_rows),
                        "mapping_hash": mapping_hash or "",
                        "schema_fingerprint": schema_signature,
                    },
                    tool_name="ship_command_pipeline",
                )
                logger.info(
                    "mapping_resolution_timing marker=job_row_data_ready "
                    "job_id=%s rows=%d fingerprint=%s mapping_hash=%s elapsed=%.3f",
                    job.id,
                    len(fetched_rows),
                    schema_signature[:12] if schema_signature else "",
                    (mapping_hash or "")[:12],
                    time.perf_counter() - mapping_started,
                )
                job_service.create_rows(
                    job.id,
                    row_payload,
                )
            except Exception as e:
                # Cleanup orphan job when rows fail to persist.
                try:
                    job_service.delete_job(job.id)
                except Exception as cleanup_err:
                    logger.warning(
                        "ship_command_pipeline cleanup failed for job %s: %s",
                        job.id,
                        cleanup_err,
                    )
                logger.error("ship_command_pipeline create_rows failed: %s", e)
                return _err(f"Failed to add rows to job: {e}")

            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            db_rows = job_service.get_rows(job.id)
            def _emit_preview_partial(payload: dict[str, Any]) -> None:
                _emit_event("preview_partial", payload, bridge=bridge)
            try:
                result = await engine.preview(
                    job_id=job.id,
                    rows=db_rows,
                    shipper=shipper,
                    service_code=service_code,
                    on_preview_partial=_emit_preview_partial,
                )
                for db_row in db_rows:
                    try:
                        parsed = json.loads(db_row.order_data) if db_row.order_data else {}
                    except (TypeError, json.JSONDecodeError):
                        parsed = {}
                    row_map[db_row.row_number] = parsed
            except Exception as e:
                logger.error(
                    "ship_command_pipeline preview failed for %s: %s", job.id, e
                )
                _audit_event(
                    "error",
                    "ship_command_pipeline.preview_failed",
                    {"job_id": job.id, "message": str(e)},
                    tool_name="ship_command_pipeline",
                )
                return _err(f"Preview failed for job {job.id}: {e}")
    except Exception as e:
        logger.error("ship_command_pipeline create_job failed: %s", e)
        return _err(f"Failed to create job: {e}")

    preview_rows = result.get("preview_rows", [])
    _enrich_preview_rows_from_map(preview_rows, row_map)
    rows_with_warnings = sum(1 for row in preview_rows if row.get("warnings"))
    result["rows_with_warnings"] = rows_with_warnings

    # Attach filter metadata for audit trail
    if filter_explanation:
        result["filter_explanation"] = filter_explanation
    if filter_audit:
        result["filter_audit"] = filter_audit
    if filter_spec_raw:
        result["compiled_filter"] = where_sql

    _audit_event(
        "pipeline",
        "ship_command_pipeline.preview_ready",
        {
            "job_id": result.get("job_id"),
            "total_rows": result.get("total_rows", 0),
            "rows_with_warnings": rows_with_warnings,
            "total_estimated_cost_cents": result.get("total_estimated_cost_cents", 0),
            "mapping_hash": filter_audit.get("mapping_hash") if filter_audit else "",
            "compiled_hash": filter_audit.get("compiled_hash") if filter_audit else "",
        },
        tool_name="ship_command_pipeline",
    )

    return _emit_preview_ready(
        result=result,
        rows_with_warnings=rows_with_warnings,
        bridge=bridge,
    )


async def batch_execute_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a confirmed batch job (create shipments).

    Requires explicit approval. Returns error if approved is not True.

    Args:
        args: Dict with 'job_id' (str) and 'approved' (bool).

    Returns:
        Tool response with execution status, or error if not approved.
    """
    unknown = _validate_allowed_args(
        "batch_execute",
        args,
        {"job_id", "approved"},
    )
    if unknown is not None:
        return unknown

    job_id = args.get("job_id", "")
    approved = args.get("approved", False)

    if not approved:
        return _err(
            "Batch execution requires user approval. "
            "Set approved=True only after the user has confirmed the preview."
        )

    if not job_id:
        return _err("job_id is required")

    try:
        from src.services.batch_engine import BatchEngine
        from src.services.ups_payload_builder import build_shipper

        account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
        shipper = build_shipper()
        ups = await _get_ups_client()

        with get_db_context() as db:
            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            svc = JobService(db)
            rows = svc.get_rows(job_id)
            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
            )
        return _ok(result)
    except Exception as e:
        logger.error("batch_execute_tool failed: %s", e)
        return _err(f"Batch execution failed: {e}")


async def get_landed_cost_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Estimate duties, taxes, and fees for an international shipment.

    Emits a landed_cost_result event to the frontend.

    Args:
        args: Dict with currency_code, export_country_code,
              import_country_code, commodities, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with landed cost breakdown, or error envelope.
    """
    try:
        def _first_non_empty(*values: Any) -> str:
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
            return ""

        client = await _get_ups_client()
        result = await client.get_landed_cost(**args)
        commodities_raw = args.get("commodities", [])
        commodities: list[dict[str, Any]] = (
            commodities_raw if isinstance(commodities_raw, list) else []
        )
        commodity_by_id: dict[str, dict[str, Any]] = {}
        commodity_by_index: list[dict[str, Any]] = []
        total_units = 0
        declared_value = 0.0
        for idx, item in enumerate(commodities, start=1):
            if not isinstance(item, dict):
                continue
            commodity_by_index.append(item)
            commodity_id = _first_non_empty(
                item.get("commodity_id"),
                item.get("commodityId"),
                item.get("commodityID"),
                item.get("id"),
                str(idx),
            )
            commodity_by_id[commodity_id] = item
            try:
                qty = int(item.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(item.get("price", 0) or 0)
            except (TypeError, ValueError):
                price = 0.0
            total_units += max(qty, 0)
            declared_value += max(qty, 0) * max(price, 0.0)

        items_raw = result.get("items", [])
        rendered_items: list[dict[str, Any]] = []
        if isinstance(items_raw, list):
            for index, item in enumerate(items_raw):
                if not isinstance(item, dict):
                    continue
                commodity_id = str(item.get("commodityId", "")).strip()
                source = commodity_by_id.get(commodity_id)
                if source is None and index < len(commodity_by_index):
                    source = commodity_by_index[index]
                item_label = ""
                if source is not None:
                    item_label = _first_non_empty(
                        source.get("description"),
                        source.get("name"),
                        source.get("item_name"),
                        source.get("title"),
                        source.get("sku"),
                        source.get("hs_code"),
                    )
                rendered_items.append(
                    {
                        **item,
                        "itemLabel": item_label,
                    }
                )

        payload = {
            "action": "landed_cost",
            "success": True,
            **result,
            "items": rendered_items if rendered_items else result.get("items", []),
            "requestSummary": {
                "exportCountryCode": str(args.get("export_country_code", "")).upper(),
                "importCountryCode": str(args.get("import_country_code", "")).upper(),
                "currencyCode": str(
                    args.get("currency_code")
                    or result.get("currencyCode", "USD")
                ).upper(),
                "shipmentType": str(args.get("shipment_type", "Sale")),
                "commodityCount": len(commodities),
                "totalUnits": total_units,
                "declaredMerchandiseValue": f"{declared_value:.2f}",
            },
        }
        _emit_event("landed_cost_result", payload, bridge=bridge)
        return _ok("Landed cost estimate displayed.")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_landed_cost_tool")
        return _err(f"Unexpected error: {e}")
