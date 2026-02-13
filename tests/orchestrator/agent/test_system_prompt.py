"""Tests for system prompt builder.

Verifies that build_system_prompt() produces a unified system prompt
containing all required domain knowledge for the SDK orchestration agent.
"""

from src.orchestrator.agent.system_prompt import build_system_prompt
from src.services.data_source_service import DataSourceInfo, SchemaColumnInfo


def _make_source_info() -> DataSourceInfo:
    """Create a test DataSourceInfo with sample columns."""
    return DataSourceInfo(
        source_type="csv",
        file_path="/tmp/orders.csv",
        columns=[
            SchemaColumnInfo(name="order_id", type="VARCHAR", nullable=False),
            SchemaColumnInfo(name="customer_name", type="VARCHAR", nullable=True),
            SchemaColumnInfo(name="state", type="VARCHAR", nullable=True),
            SchemaColumnInfo(name="total_weight_grams", type="INTEGER", nullable=True),
            SchemaColumnInfo(name="created_at", type="DATE", nullable=True),
        ],
        row_count=150,
    )


def test_prompt_contains_identity():
    """System prompt includes ShipAgent identity."""
    prompt = build_system_prompt()
    assert "ShipAgent" in prompt


def test_prompt_contains_service_codes():
    """System prompt includes UPS service code table."""
    prompt = build_system_prompt()
    assert "03" in prompt  # Ground
    assert "01" in prompt  # Next Day Air
    assert "02" in prompt  # Second Day Air
    assert "12" in prompt  # Three Day Select
    assert "13" in prompt  # Next Day Air Saver
    assert "ground" in prompt.lower()
    assert "overnight" in prompt.lower()


def test_prompt_contains_filter_rules():
    """System prompt includes filter generation rules from filter_generator.py."""
    prompt = build_system_prompt()
    # Person name disambiguation
    assert "customer_name" in prompt
    assert "ship_to_name" in prompt
    # Status handling
    assert "financial_status" in prompt or "fulfillment_status" in prompt
    # Weight handling
    assert "total_weight_grams" in prompt or "453" in prompt
    # Tag handling
    assert "tags" in prompt.lower()


def test_prompt_includes_source_schema():
    """System prompt includes dynamic schema when source_info is provided."""
    source = _make_source_info()
    prompt = build_system_prompt(source_info=source)
    assert "order_id" in prompt
    assert "customer_name" in prompt
    assert "state" in prompt
    assert "total_weight_grams" in prompt
    assert "created_at" in prompt
    assert "150" in prompt  # row count
    assert "csv" in prompt.lower()


def test_prompt_without_source_shows_no_connection():
    """System prompt indicates no data source when source_info is None."""
    prompt = build_system_prompt(source_info=None)
    assert "no data source" in prompt.lower() or "not connected" in prompt.lower()


def test_prompt_without_source_interactive_does_not_demand_connection():
    """When interactive=True and no source, prompt allows ad-hoc shipments without demanding a connection."""
    prompt = build_system_prompt(source_info=None, interactive_shipping=True)
    lower = prompt.lower()
    # Should mention interactive mode is active
    assert "interactive shipping mode is active" in lower
    # Should allow single ad-hoc shipments
    assert "ad-hoc shipments" in lower or "single ad-hoc" in lower
    # Should NOT contain the blanket "ask the user to connect" instruction
    assert "ask the user to connect a csv" not in lower


def test_prompt_without_source_batch_demands_connection():
    """When interactive=False and no source, prompt demands data source connection."""
    prompt = build_system_prompt(source_info=None, interactive_shipping=False)
    lower = prompt.lower()
    assert "ask the user to connect" in lower


def test_prompt_contains_workflow():
    """System prompt includes workflow steps."""
    prompt = build_system_prompt()
    # Should describe the key workflow steps
    assert "preview" in prompt.lower()
    assert "confirm" in prompt.lower()


def test_prompt_contains_safety_rules():
    """System prompt includes safety rules about confirmation before execution."""
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "never" in lower or "must" in lower
    assert "confirm" in lower


def test_prompt_contains_current_date():
    """System prompt includes the current date for temporal context."""
    from datetime import datetime

    prompt = build_system_prompt()
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in prompt


def test_prompt_returns_string():
    """build_system_prompt always returns a string."""
    result = build_system_prompt()
    assert isinstance(result, str)
    assert len(result) > 100  # non-trivial prompt


def test_prompt_contains_direct_single_shipment_section_when_interactive():
    """System prompt includes the exclusive interactive ad-hoc section when interactive=True."""
    prompt = build_system_prompt(interactive_shipping=True)
    assert "Interactive Ad-hoc Mode (Exclusive)" in prompt
    assert "mcp__ups__create_shipment" in prompt
    assert "request_body" in prompt


def test_prompt_contains_validation_error_handling_when_interactive():
    """System prompt includes validation error handling when interactive=True."""
    prompt = build_system_prompt(interactive_shipping=True)
    assert "Handling Create Shipment Validation Errors" in prompt
    assert "missing" in prompt.lower()


def test_prompt_contains_elicitation_declined_rule_when_interactive():
    """System prompt instructs not to retry cancelled/declined errors when interactive=True."""
    prompt = build_system_prompt(interactive_shipping=True)
    assert "ELICITATION_DECLINED" in prompt
    assert "ELICITATION_CANCELLED" in prompt


def test_prompt_contains_malformed_request_rule_when_interactive():
    """System prompt instructs MALFORMED_REQUEST is structural when interactive=True."""
    prompt = build_system_prompt(interactive_shipping=True)
    assert "MALFORMED_REQUEST" in prompt


# --- Interactive shipping prompt conditioning tests ---


class TestInteractiveShippingPromptConditioning:
    """Tests for interactive_shipping prompt conditioning."""

    def test_interactive_sections_included_when_true(self):
        """Direct shipment + validation sections present when interactive=True."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "Interactive Ad-hoc Mode (Exclusive)" in prompt
        assert "Handling Create Shipment Validation Errors" in prompt

    def test_interactive_sections_omitted_when_false(self):
        """Direct shipment + validation sections absent when interactive=False."""
        prompt = build_system_prompt(interactive_shipping=False)
        assert "Direct Single-Shipment Commands" not in prompt
        assert "Handling Create Shipment Validation Errors" not in prompt

    def test_interactive_sections_omitted_by_default(self):
        """Default (no flag) omits interactive sections."""
        prompt = build_system_prompt()
        assert "Direct Single-Shipment Commands" not in prompt
        assert "Handling Create Shipment Validation Errors" not in prompt

    def test_exclusive_mode_policy_when_true(self):
        """Interactive prompt explicitly enforces exclusive ad-hoc mode."""
        prompt = build_system_prompt(interactive_shipping=True)
        lower = prompt.lower()
        assert "do not call batch or data-source tools" in lower
        assert "turn interactive shipping off" in lower

    def test_interactive_section_mentions_ambiguity_guard(self):
        """Interactive section still includes ambiguity handling guidance."""
        prompt = build_system_prompt(interactive_shipping=True)
        lower = prompt.lower()
        assert "ask one clarifying question" in lower

    def test_batch_workflow_present_only_when_interactive_disabled(self):
        """Batch shipping workflow is omitted when interactive mode is enabled."""
        prompt_off = build_system_prompt(interactive_shipping=False)
        prompt_on = build_system_prompt(interactive_shipping=True)
        assert "ship_command_pipeline" in prompt_off
        assert "### Shipping Commands (default path)" in prompt_off
        assert "### Shipping Commands (default path)" not in prompt_on

    def test_safety_rules_always_present(self):
        """Safety rules are present regardless of interactive flag."""
        prompt_off = build_system_prompt(interactive_shipping=False)
        prompt_on = build_system_prompt(interactive_shipping=True)
        for prompt in (prompt_off, prompt_on):
            assert "Safety Rules" in prompt
            assert "confirm" in prompt.lower()

    def test_elicitation_codes_absent_when_false(self):
        """Elicitation error codes absent from prompt when interactive=False."""
        prompt = build_system_prompt(interactive_shipping=False)
        assert "ELICITATION_DECLINED" not in prompt
        assert "ELICITATION_CANCELLED" not in prompt
        assert "MALFORMED_REQUEST" not in prompt

    def test_no_source_safety_rule_scoped_to_batch_when_interactive(self):
        """Interactive mode instructs explicit redirect for batch/data-source requests."""
        prompt = build_system_prompt(source_info=None, interactive_shipping=True)
        assert "turn interactive shipping off" in prompt.lower()

    def test_schema_suppressed_when_interactive_even_with_source(self):
        """Interactive mode suppresses schema details even when source_info exists."""
        source = _make_source_info()
        prompt = build_system_prompt(source_info=source, interactive_shipping=True)
        assert "Columns:" not in prompt
        assert "order_id (VARCHAR, not null)" not in prompt
