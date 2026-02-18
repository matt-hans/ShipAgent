"""Tests for tool definitions registry updates for filter_spec."""

import pytest

from src.orchestrator.agent.tools import get_all_tool_definitions


class TestToolDefinitionsFilter:
    """Verify tool registry reflects filter_spec hard cutover."""

    def _get_tool(self, name: str, interactive: bool = False):
        """Find a tool definition by name."""
        defs = get_all_tool_definitions(interactive_shipping=interactive)
        for d in defs:
            if d["name"] == name:
                return d
        return None

    def _tool_names(self, interactive: bool = False) -> set[str]:
        """Get set of all tool names."""
        return {d["name"] for d in get_all_tool_definitions(interactive_shipping=interactive)}

    def test_resolve_filter_intent_exists_in_batch(self):
        """resolve_filter_intent tool exists in batch mode."""
        tool = self._get_tool("resolve_filter_intent", interactive=False)
        assert tool is not None
        assert "FilterIntent" in tool["description"] or "filter" in tool["description"].lower()

    def test_resolve_filter_intent_not_in_interactive(self):
        """resolve_filter_intent tool is NOT in interactive mode."""
        assert "resolve_filter_intent" not in self._tool_names(interactive=True)

    def test_validate_filter_syntax_deleted(self):
        """validate_filter_syntax tool does NOT exist in any mode."""
        assert "validate_filter_syntax" not in self._tool_names(interactive=False)
        assert "validate_filter_syntax" not in self._tool_names(interactive=True)

    def test_pipeline_has_filter_spec_not_where_clause(self):
        """ship_command_pipeline has filter_spec and all_rows, not where_clause."""
        tool = self._get_tool("ship_command_pipeline")
        assert tool is not None
        props = tool["input_schema"]["properties"]
        assert "filter_spec" in props
        assert "all_rows" in props
        assert "where_clause" not in props
        # Keep schema permissive so command-only retries can reach tool-level
        # bridge cache recovery (resolve -> pipeline within the same turn).
        assert "oneOf" not in tool["input_schema"]

    def test_fetch_rows_has_filter_spec_not_where_clause(self):
        """fetch_rows has filter_spec and all_rows, not where_clause."""
        tool = self._get_tool("fetch_rows")
        assert tool is not None
        props = tool["input_schema"]["properties"]
        assert "filter_spec" in props
        assert "all_rows" in props
        assert "where_clause" not in props
        assert "oneOf" in tool["input_schema"]

    def test_resolve_filter_intent_input_schema(self):
        """resolve_filter_intent has intent property in schema."""
        tool = self._get_tool("resolve_filter_intent")
        assert tool is not None
        props = tool["input_schema"]["properties"]
        assert "intent" in props
        assert "intent" in tool["input_schema"].get("required", [])
