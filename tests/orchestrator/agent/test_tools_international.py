"""Tests for international field support in agent tools."""

from src.orchestrator.agent.tools.core import _normalize_rows_for_shipping


class TestNormalizeRowsCountryDefault:
    """Verify US default removal from row normalization."""

    def test_missing_country_not_defaulted_to_us(self):
        """Rows without ship_to_country should NOT be silently defaulted to US."""
        rows = [{"name": "Jane Doe", "city": "Toronto", "state": "ON", "zip": "M5V 2T6"}]
        result = _normalize_rows_for_shipping(rows)
        # Should not have ship_to_country set to "US"
        assert result[0].get("ship_to_country") != "US"

    def test_explicit_country_preserved(self):
        """Rows with explicit ship_to_country should keep it."""
        rows = [{"ship_to_name": "Jane", "ship_to_country": "CA"}]
        result = _normalize_rows_for_shipping(rows)
        assert result[0]["ship_to_country"] == "CA"

    def test_domestic_with_explicit_us_preserved(self):
        """Rows with explicit US country should keep it."""
        rows = [{"ship_to_name": "John", "ship_to_country": "US"}]
        result = _normalize_rows_for_shipping(rows)
        assert result[0]["ship_to_country"] == "US"


class TestInteractiveToolSchema:
    """Verify interactive tool schema includes international fields."""

    def test_interactive_schema_has_ship_to_country(self):
        from src.orchestrator.agent.tools import get_all_tool_definitions

        defs = get_all_tool_definitions(interactive_shipping=True)
        preview_def = next(d for d in defs if d["name"] == "preview_interactive_shipment")
        props = preview_def["input_schema"]["properties"]
        assert "ship_to_country" in props

    def test_interactive_schema_has_description(self):
        from src.orchestrator.agent.tools import get_all_tool_definitions

        defs = get_all_tool_definitions(interactive_shipping=True)
        preview_def = next(d for d in defs if d["name"] == "preview_interactive_shipment")
        props = preview_def["input_schema"]["properties"]
        assert "shipment_description" in props

    def test_interactive_schema_has_attention_name(self):
        from src.orchestrator.agent.tools import get_all_tool_definitions

        defs = get_all_tool_definitions(interactive_shipping=True)
        preview_def = next(d for d in defs if d["name"] == "preview_interactive_shipment")
        props = preview_def["input_schema"]["properties"]
        assert "ship_to_attention_name" in props

    def test_ship_to_state_not_required(self):
        """ship_to_state should not be required for international shipments."""
        from src.orchestrator.agent.tools import get_all_tool_definitions

        defs = get_all_tool_definitions(interactive_shipping=True)
        preview_def = next(d for d in defs if d["name"] == "preview_interactive_shipment")
        required = preview_def["input_schema"]["required"]
        assert "ship_to_state" not in required


class TestCoreServiceCodeNames:
    """Verify SERVICE_CODE_NAMES in core.py includes international codes."""

    def test_international_codes_present(self):
        from src.orchestrator.agent.tools.core import SERVICE_CODE_NAMES

        assert "07" in SERVICE_CODE_NAMES
        assert "08" in SERVICE_CODE_NAMES
        assert "54" in SERVICE_CODE_NAMES
        assert "65" in SERVICE_CODE_NAMES
