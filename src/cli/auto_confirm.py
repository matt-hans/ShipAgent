"""Auto-confirm rule evaluation engine.

Evaluates preview results against configured rules and returns
an approval decision with detailed violation information.
Rules are evaluated in order; all violations are collected.
"""

from dataclasses import dataclass, field

from src.cli.config import AutoConfirmRules
from src.cli.output import format_cost


@dataclass
class RuleViolation:
    """A single auto-confirm rule that was violated."""

    rule: str
    threshold: object
    actual: object
    message: str


@dataclass
class AutoConfirmResult:
    """Result of auto-confirm rule evaluation."""

    approved: bool
    reason: str
    violations: list[RuleViolation] = field(default_factory=list)


def evaluate_auto_confirm(
    rules: AutoConfirmRules, preview: dict
) -> AutoConfirmResult:
    """Evaluate a preview result against auto-confirm rules.

    Rules are checked in order (cheapest checks first). All violations
    are collected so operators see every issue at once.

    Args:
        rules: The auto-confirm rules to evaluate against.
        preview: Preview data dict with keys: total_rows, total_cost_cents,
                 max_row_cost_cents, service_codes, all_addresses_valid,
                 has_address_warnings.

    Returns:
        AutoConfirmResult with approval decision and any violations.
    """
    violations: list[RuleViolation] = []

    # Rule 0: Global kill switch
    if not rules.enabled:
        violations.append(RuleViolation(
            rule="enabled",
            threshold=True,
            actual=False,
            message="Auto-confirm is globally disabled",
        ))
        return AutoConfirmResult(
            approved=False,
            reason="Auto-confirm is disabled",
            violations=violations,
        )

    # Rule 1: Max rows (reject early before cost calculation)
    total_rows = preview.get("total_rows", 0)
    if total_rows > rules.max_rows:
        violations.append(RuleViolation(
            rule="max_rows",
            threshold=rules.max_rows,
            actual=total_rows,
            message=f"Row count {total_rows} exceeds limit {rules.max_rows}",
        ))

    # Rule 2: Max total cost
    total_cost = preview.get("total_cost_cents", 0)
    if total_cost > rules.max_cost_cents:
        violations.append(RuleViolation(
            rule="max_cost_cents",
            threshold=rules.max_cost_cents,
            actual=total_cost,
            message=(
                f"Total cost {format_cost(total_cost)} exceeds "
                f"limit {format_cost(rules.max_cost_cents)}"
            ),
        ))

    # Rule 3: Max cost per row (outlier detection)
    max_row_cost = preview.get("max_row_cost_cents", 0)
    if max_row_cost > rules.max_cost_per_row_cents:
        violations.append(RuleViolation(
            rule="max_cost_per_row_cents",
            threshold=rules.max_cost_per_row_cents,
            actual=max_row_cost,
            message=(
                f"Row cost {format_cost(max_row_cost)} exceeds "
                f"per-row limit {format_cost(rules.max_cost_per_row_cents)}"
            ),
        ))

    # Rule 4: Allowed services whitelist
    if rules.allowed_services:
        service_codes = set(preview.get("service_codes", []))
        allowed = set(rules.allowed_services)
        disallowed = service_codes - allowed
        if disallowed:
            violations.append(RuleViolation(
                rule="allowed_services",
                threshold=sorted(rules.allowed_services),
                actual=sorted(disallowed),
                message=f"Disallowed service codes: {', '.join(sorted(disallowed))}",
            ))

    # Rule 5: Address validation
    if rules.require_valid_addresses:
        if not preview.get("all_addresses_valid", True):
            violations.append(RuleViolation(
                rule="require_valid_addresses",
                threshold=True,
                actual=False,
                message="One or more addresses failed validation",
            ))

    # Rule 6: Address warnings
    if rules.require_valid_addresses and not rules.allow_warnings:
        if preview.get("has_address_warnings", False):
            violations.append(RuleViolation(
                rule="allow_warnings",
                threshold=False,
                actual=True,
                message="Address corrections detected (warnings not allowed)",
            ))

    if violations:
        return AutoConfirmResult(
            approved=False,
            reason=f"{len(violations)} rule(s) violated",
            violations=violations,
        )

    return AutoConfirmResult(
        approved=True,
        reason="All rules satisfied",
        violations=[],
    )
