"""Tests for system prompt FilterIntent schema rewrite."""

from src.orchestrator.agent.system_prompt import build_system_prompt
from src.services.data_source_mcp_client import DataSourceInfo, SchemaColumnInfo


def _make_source_info() -> DataSourceInfo:
    """Create a minimal DataSourceInfo for testing."""
    return DataSourceInfo(
        source_type="csv",
        file_path="/test/orders.csv",
        row_count=100,
        columns=[
            SchemaColumnInfo(name="state", type="VARCHAR", nullable=True),
            SchemaColumnInfo(name="city", type="VARCHAR", nullable=True),
            SchemaColumnInfo(name="total", type="DOUBLE", nullable=True),
        ],
    )


class TestSystemPromptFilterIntent:
    """Verify system prompt uses FilterIntent schema in batch mode."""

    def test_batch_contains_filter_intent(self):
        """Batch mode prompt contains 'FilterIntent'."""
        prompt = build_system_prompt(source_info=_make_source_info())
        assert "FilterIntent" in prompt

    def test_batch_contains_resolve_filter_intent(self):
        """Batch mode prompt mentions resolve_filter_intent tool."""
        prompt = build_system_prompt(source_info=_make_source_info())
        assert "resolve_filter_intent" in prompt

    def test_batch_contains_never_generate_sql(self):
        """Batch mode prompt contains 'NEVER generate SQL' instruction."""
        prompt = build_system_prompt(source_info=_make_source_info())
        assert "NEVER generate SQL" in prompt or "NEVER generate raw SQL" in prompt

    def test_batch_lists_operators(self):
        """Batch mode prompt lists available operators."""
        prompt = build_system_prompt(source_info=_make_source_info())
        # Check for at least a few key operators
        assert "eq" in prompt
        assert "contains_ci" in prompt
        assert "between" in prompt

    def test_batch_lists_semantic_keys(self):
        """Batch mode prompt lists canonical semantic keys."""
        prompt = build_system_prompt(source_info=_make_source_info())
        # Should mention regions or semantic references
        assert "NORTHEAST" in prompt or "semantic" in prompt.lower()

    def test_interactive_omits_filter_intent(self):
        """Interactive mode prompt does NOT contain FilterIntent instructions."""
        prompt = build_system_prompt(
            source_info=_make_source_info(),
            interactive_shipping=True,
        )
        assert "FilterIntent" not in prompt
        assert "resolve_filter_intent" not in prompt
