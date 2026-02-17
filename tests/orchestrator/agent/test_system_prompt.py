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
    """System prompt includes FilterIntent schema documentation."""
    prompt = build_system_prompt()
    # FilterIntent schema
    assert "FilterIntent" in prompt
    assert "resolve_filter_intent" in prompt
    # NEVER generate SQL instruction
    assert "NEVER generate" in prompt
    # Operator reference
    assert "eq" in prompt
    assert "contains_ci" in prompt


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


def test_prompt_truncates_long_column_samples(monkeypatch):
    """Long sample values should be truncated to control token usage."""
    monkeypatch.setenv("SYSTEM_PROMPT_SAMPLE_MAX_CHARS", "30")
    source = _make_source_info()
    prompt = build_system_prompt(
        source_info=source,
        column_samples={
            "customer_name": [
                "A" * 120,
            ],
        },
    )
    assert "..." in prompt
    assert "A" * 80 not in prompt


def test_prompt_without_source_shows_no_connection():
    """System prompt indicates no data source when source_info is None."""
    prompt = build_system_prompt(source_info=None)
    assert "no data source" in prompt.lower() or "not connected" in prompt.lower()


def test_prompt_without_source_interactive_does_not_demand_connection():
    """When interactive=True and no source, prompt allows single shipments without demanding a connection."""
    prompt = build_system_prompt(source_info=None, interactive_shipping=True)
    lower = prompt.lower()
    # Should mention interactive mode is active
    assert "interactive shipping mode is active" in lower
    # Should allow single shipment creation
    assert "single shipment creation" in lower
    # Should NOT contain the blanket "ask the user to connect" instruction
    assert "ask the user to connect a csv" not in lower


def test_prompt_without_source_batch_demands_connection():
    """When interactive=False and no source, prompt demands data source connection."""
    prompt = build_system_prompt(source_info=None, interactive_shipping=False)
    lower = prompt.lower()
    assert "ask the user to connect" in lower


def test_prompt_auto_imports_shopify_when_env_configured(monkeypatch):
    """When Shopify env vars are set and no source, prompt demands connect_shopify call."""
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test_token")
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
    prompt = build_system_prompt(source_info=None, interactive_shipping=False)
    lower = prompt.lower()
    assert "connect_shopify" in lower
    assert "must" in lower
    # Data source section should direct auto-import, not ask user to connect a CSV/Excel
    assert "shopify credentials are configured" in lower


def test_prompt_no_shopify_env_asks_user_to_connect(monkeypatch):
    """When Shopify env vars are absent and no source, prompt asks user to connect."""
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SHOPIFY_STORE_DOMAIN", raising=False)
    prompt = build_system_prompt(source_info=None, interactive_shipping=False)
    lower = prompt.lower()
    # Data section should tell agent to ask user — no auto-import
    assert "ask the user to connect" in lower
    # Should not reference connect_shopify in the data section
    assert "connect_shopify" not in lower


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
    """System prompt includes the interactive single shipment section when interactive=True."""
    prompt = build_system_prompt(interactive_shipping=True)
    assert "Interactive Single Shipment Mode" in prompt
    assert "preview_interactive_shipment" in prompt


# --- Interactive shipping prompt conditioning tests ---


class TestInteractiveShippingPromptConditioning:
    """Tests for interactive_shipping prompt conditioning."""

    def test_interactive_sections_included_when_true(self):
        """Direct shipment + validation sections present when interactive=True."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "Interactive Single Shipment Mode" in prompt
        assert "preview_interactive_shipment" in prompt

    def test_interactive_sections_omitted_when_false(self):
        """Direct shipment + validation sections absent when interactive=False."""
        prompt = build_system_prompt(interactive_shipping=False)
        assert "Direct Single-Shipment Commands" not in prompt
        assert "Interactive Single Shipment Mode" not in prompt

    def test_interactive_sections_omitted_by_default(self):
        """Default (no flag) omits interactive sections."""
        prompt = build_system_prompt()
        assert "Direct Single-Shipment Commands" not in prompt
        assert "Interactive Single Shipment Mode" not in prompt

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

    def test_interactive_prompt_mentions_auto_populated_shipper(self):
        """Interactive prompt tells agent that shipper is auto-populated."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "auto-populated from configuration" in prompt

    def test_interactive_prompt_references_preview_tool(self):
        """Interactive prompt references the preview_interactive_shipment tool."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "preview_interactive_shipment" in prompt

    def test_interactive_prompt_denies_direct_create_shipment(self):
        """Interactive prompt tells agent not to call create_shipment directly."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "Do NOT call" in prompt
        assert "mcp__ups__create_shipment" in prompt

    def test_interactive_prompt_requires_service_parameter(self):
        """Interactive prompt enforces explicit service parameter passing."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "ALWAYS pass this as the `service` parameter" in prompt
        assert "NEVER omit the `service` parameter" in prompt

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


# --- International shipping prompt tests ---


class TestInternationalShippingPrompt:
    """Tests for international shipping sections in system prompt."""

    def test_service_table_includes_international_labels(self):
        """Service table labels international codes (07, 08, 11, 54, 65)."""
        prompt = build_system_prompt()
        assert "code 07, international" in prompt
        assert "code 08, international" in prompt
        assert "code 11, international" in prompt
        assert "code 54, international" in prompt
        assert "code 65, international" in prompt

    def test_service_table_labels_domestic_services(self):
        """Service table labels domestic codes (01, 02, 03, 12, 13)."""
        prompt = build_system_prompt()
        assert "code 01, domestic" in prompt
        assert "code 02, domestic" in prompt
        assert "code 03, domestic" in prompt

    def test_international_section_present_when_lanes_configured(self, monkeypatch):
        """International guidance section appears when lanes env var is set."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA,US-MX")
        prompt = build_system_prompt(interactive_shipping=False)
        assert "## International Shipping" in prompt
        assert "US-CA" in prompt
        assert "US-MX" in prompt

    def test_international_section_lists_required_fields(self, monkeypatch):
        """International section includes required field guidance."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA")
        prompt = build_system_prompt(interactive_shipping=False)
        assert "Recipient phone" in prompt
        assert "Description of goods" in prompt
        assert "Commodity data" in prompt
        assert "InvoiceLineTotal" in prompt

    def test_international_section_includes_filter_examples(self, monkeypatch):
        """International section includes country-based SQL filter examples."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA,US-MX")
        prompt = build_system_prompt(interactive_shipping=False)
        assert "ship_to_country = 'CA'" in prompt
        assert "ship_to_country = 'MX'" in prompt

    def test_international_section_warns_about_service_ambiguity(self, monkeypatch):
        """International section warns about 'standard' service code ambiguity."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA")
        prompt = build_system_prompt(interactive_shipping=False)
        lower = prompt.lower()
        assert "do not silently default" in lower

    def test_international_section_present_in_interactive_mode(self, monkeypatch):
        """International guidance appears in interactive mode when lanes are configured."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA")
        prompt = build_system_prompt(interactive_shipping=True)
        assert "## International Shipping" in prompt
        assert "Interactive mode collection requirements" in prompt
        assert "`commodities`" in prompt
        assert "`reason_for_export`" in prompt

    def test_international_section_disabled_when_no_lanes(self, monkeypatch):
        """When no lanes configured, prompt says international is not enabled."""
        monkeypatch.delenv("INTERNATIONAL_ENABLED_LANES", raising=False)
        prompt = build_system_prompt(interactive_shipping=False)
        assert "International shipping is not currently enabled" in prompt

    def test_international_uses_service_codes_not_domestic(self, monkeypatch):
        """International section references international service codes."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA")
        prompt = build_system_prompt(interactive_shipping=False)
        assert "07, 08, 11, 54, or 65" in prompt

    def test_wildcard_shows_all_destinations(self, monkeypatch):
        """Wildcard * displays 'All international destinations' in prompt."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "*")
        prompt = build_system_prompt(interactive_shipping=False)
        assert "All international destinations" in prompt

    def test_exemption_documentation_in_prompt(self, monkeypatch):
        """Prompt includes UPS Letter and EU-to-EU exemption documentation."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "*")
        prompt = build_system_prompt(interactive_shipping=False)
        assert "UPS Letter" in prompt
        assert "EU-to-EU" in prompt


# --- UPS MCP v2 domain workflow prompt tests ---


class TestUPSMCPv2DomainGuidance:
    """Tests for UPS MCP v2 domain workflow sections in system prompt."""

    def test_system_prompt_includes_pickup_guidance(self):
        """System prompt must include pickup scheduling workflow."""
        prompt = build_system_prompt()
        assert "Pickup" in prompt
        assert "schedule_pickup" in prompt or "Schedule Pickup" in prompt
        assert "PRN" in prompt

    def test_system_prompt_includes_locator_guidance(self):
        """System prompt must include location finder guidance."""
        prompt = build_system_prompt()
        assert "find_locations" in prompt or "Location" in prompt
        assert "Access Point" in prompt or "access_point" in prompt

    def test_system_prompt_includes_landed_cost_guidance(self):
        """System prompt must include landed cost estimation guidance."""
        prompt = build_system_prompt()
        assert "Landed Cost" in prompt or "landed_cost" in prompt
        assert "duties" in prompt.lower()

    def test_system_prompt_includes_paperless_guidance(self):
        """System prompt must include paperless document workflow."""
        prompt = build_system_prompt()
        assert "Paperless" in prompt or "paperless" in prompt
        assert "DocumentID" in prompt or "document_id" in prompt

    def test_system_prompt_includes_political_divisions(self):
        """System prompt must mention political divisions reference tool."""
        prompt = build_system_prompt()
        assert "political_divisions" in prompt or "Political Divisions" in prompt

    def test_system_prompt_interactive_mode_mentions_v2_domains(self):
        """Interactive mode prompt includes v2 domain guidance."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "Pickup" in prompt
        assert "Landed Cost" in prompt or "landed_cost" in prompt
