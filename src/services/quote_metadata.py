"""Closed non-PII priced-preview metadata shared by persistence and audit."""

from typing import Any

RATE_UNAVAILABLE_WARNING = "Rate unavailable. Re-preview before confirming this batch."
RATE_TIMEOUT_WARNING = "Rate timeout. Re-preview before confirming this batch."
LANE_UNAVAILABLE_WARNING = (
    "This international shipping lane is not enabled. Review shipping settings."
)
SAFE_QUOTE_WARNINGS = frozenset(
    {RATE_UNAVAILABLE_WARNING, RATE_TIMEOUT_WARNING, LANE_UNAVAILABLE_WARNING}
)


def project_quote_estimates(value: Any) -> list[dict[str, Any]] | None:
    """Retain typed quote ordinals/costs, never arbitrary imported row fields.

    None marks malformed authority-bearing metadata. A caller must not use a
    partially projected list to grant confirmation authority.
    """
    if not isinstance(value, list):
        return None
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        ordinal, cost = item.get("row_number"), item.get("estimated_cost_cents")
        warnings = item.get("warnings", [])
        if (
            type(ordinal) is not int
            or ordinal < 1
            or ordinal in seen
            or type(cost) is not int
            or cost < 0
            or not isinstance(warnings, list)
            or any(
                not isinstance(warning, str) or warning not in SAFE_QUOTE_WARNINGS
                for warning in warnings
            )
        ):
            return None
        seen.add(ordinal)
        result.append(
            {
                "row_number": ordinal,
                "estimated_cost_cents": cost,
                "warnings": list(warnings),
            }
        )
    return result
