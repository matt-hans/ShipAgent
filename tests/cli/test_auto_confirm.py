"""Tests for the auto-confirm rule evaluation engine."""

from src.cli.auto_confirm import AutoConfirmResult, RuleViolation, evaluate_auto_confirm
from src.cli.config import AutoConfirmRules


def _make_preview(
    total_rows: int = 10,
    total_cost_cents: int = 5000,
    max_row_cost_cents: int = 1000,
    service_codes: list[str] | None = None,
    address_valid: bool = True,
    has_warnings: bool = False,
) -> dict:
    """Build a mock preview result for testing."""
    return {
        "total_rows": total_rows,
        "total_cost_cents": total_cost_cents,
        "max_row_cost_cents": max_row_cost_cents,
        "service_codes": service_codes or ["03"],
        "all_addresses_valid": address_valid,
        "has_address_warnings": has_warnings,
    }


class TestEvaluateAutoConfirm:
    """Tests for the rule evaluation engine."""

    def test_all_rules_pass(self):
        """Approves when all rules are satisfied."""
        rules = AutoConfirmRules(
            enabled=True, max_cost_cents=10000, max_rows=50,
            allowed_services=["03"], max_cost_per_row_cents=2000,
        )
        preview = _make_preview()
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True
        assert len(result.violations) == 0

    def test_disabled_rejects(self):
        """Rejects when auto-confirm is globally disabled."""
        rules = AutoConfirmRules(enabled=False)
        result = evaluate_auto_confirm(rules, _make_preview())
        assert result.approved is False
        assert any(v.rule == "enabled" for v in result.violations)

    def test_max_rows_violation(self):
        """Rejects when row count exceeds threshold."""
        rules = AutoConfirmRules(enabled=True, max_rows=5)
        preview = _make_preview(total_rows=10)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "max_rows" for v in result.violations)
        violation = next(v for v in result.violations if v.rule == "max_rows")
        assert violation.threshold == 5
        assert violation.actual == 10

    def test_max_cost_violation(self):
        """Rejects when total cost exceeds threshold."""
        rules = AutoConfirmRules(enabled=True, max_cost_cents=1000)
        preview = _make_preview(total_cost_cents=5000)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "max_cost_cents" for v in result.violations)

    def test_max_cost_per_row_violation(self):
        """Rejects when any single row exceeds per-row threshold."""
        rules = AutoConfirmRules(enabled=True, max_cost_per_row_cents=500)
        preview = _make_preview(max_row_cost_cents=1000)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "max_cost_per_row_cents" for v in result.violations)

    def test_disallowed_service_violation(self):
        """Rejects when rows use services not in the whitelist."""
        rules = AutoConfirmRules(
            enabled=True, allowed_services=["03"],
        )
        preview = _make_preview(service_codes=["03", "01"])
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "allowed_services" for v in result.violations)

    def test_empty_allowed_services_allows_all(self):
        """Empty allowed_services list means no service restriction."""
        rules = AutoConfirmRules(enabled=True, allowed_services=[])
        preview = _make_preview(service_codes=["01", "02", "03"])
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True

    def test_invalid_address_violation(self):
        """Rejects when address validation fails."""
        rules = AutoConfirmRules(enabled=True, require_valid_addresses=True)
        preview = _make_preview(address_valid=False)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "require_valid_addresses" for v in result.violations)

    def test_address_warnings_violation(self):
        """Rejects on address warnings when allow_warnings is False."""
        rules = AutoConfirmRules(
            enabled=True, require_valid_addresses=True, allow_warnings=False,
        )
        preview = _make_preview(has_warnings=True)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "allow_warnings" for v in result.violations)

    def test_address_warnings_allowed(self):
        """Approves address warnings when allow_warnings is True."""
        rules = AutoConfirmRules(
            enabled=True, require_valid_addresses=True, allow_warnings=True,
        )
        preview = _make_preview(has_warnings=True)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True

    def test_multiple_violations(self):
        """Collects all violations, not just the first."""
        rules = AutoConfirmRules(
            enabled=True, max_rows=5, max_cost_cents=1000,
        )
        preview = _make_preview(total_rows=10, total_cost_cents=5000)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert len(result.violations) >= 2
        rule_names = {v.rule for v in result.violations}
        assert "max_rows" in rule_names
        assert "max_cost_cents" in rule_names


class TestServiceParseFailures:
    """Tests for auto-confirm blocking when service code parsing fails."""

    def test_parse_failures_block_when_allowed_services_set(self):
        """Blocks auto-confirm when service_parse_failures > 0 and allowed_services is set.

        Unparseable order data means we cannot verify that the row's service
        code complies with the whitelist, so auto-confirm must be denied.
        """
        rules = AutoConfirmRules(
            enabled=True,
            allowed_services=["03"],
            max_cost_cents=100000,
            max_rows=500,
        )
        preview = _make_preview(service_codes=["03"])
        preview["service_parse_failures"] = 3
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        parse_violations = [
            v for v in result.violations
            if v.rule == "allowed_services" and "unparseable" in str(v.actual)
        ]
        assert len(parse_violations) == 1
        assert "3 row(s)" in parse_violations[0].message

    def test_parse_failures_ignored_when_no_whitelist(self):
        """Parse failures do not block when no allowed_services whitelist is configured.

        Without a service whitelist, there is nothing to enforce — the parse
        failure check is only relevant when allowed_services is non-empty.
        """
        rules = AutoConfirmRules(
            enabled=True,
            allowed_services=[],
            max_cost_cents=100000,
            max_rows=500,
        )
        preview = _make_preview(service_codes=["03"])
        preview["service_parse_failures"] = 3
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True
        assert len(result.violations) == 0

    def test_zero_parse_failures_with_valid_services_approved(self):
        """Normal case: zero parse failures and valid service codes pass cleanly."""
        rules = AutoConfirmRules(
            enabled=True,
            allowed_services=["03", "02"],
            max_cost_cents=100000,
            max_rows=500,
        )
        preview = _make_preview(service_codes=["03"])
        preview["service_parse_failures"] = 0
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True
        assert len(result.violations) == 0
