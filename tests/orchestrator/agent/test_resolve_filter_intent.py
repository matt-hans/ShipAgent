"""Tests for the resolve_filter_intent tool handler."""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.orchestrator.models.filter_spec import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    ResolutionStatus,
    SemanticReference,
    TypedLiteral,
)


@pytest.fixture(autouse=True)
def _set_token_secret(monkeypatch):
    """Ensure FILTER_TOKEN_SECRET is set for all tests."""
    monkeypatch.setenv("FILTER_TOKEN_SECRET", "test-secret-for-tool-handler-tests")


def _mock_gateway(columns=None, source_info=None):
    """Create a mock data gateway with schema info."""
    if columns is None:
        columns = [
            {"name": "state", "type": "VARCHAR", "nullable": True},
            {"name": "company", "type": "VARCHAR", "nullable": True},
            {"name": "weight", "type": "DOUBLE", "nullable": True},
        ]
    if source_info is None:
        source_info = {
            "source_type": "csv",
            "row_count": 100,
            "columns": columns,
            "signature": "test_schema_sig",
        }
    gw = AsyncMock()
    gw.get_source_info.return_value = source_info
    return gw


def _parse_tool_result(result: dict) -> tuple[bool, dict | str]:
    """Parse a tool response dict into (is_error, content)."""
    is_error = result.get("isError", False)
    content_list = result.get("content", [])
    if content_list and content_list[0].get("type") == "text":
        text = content_list[0]["text"]
        try:
            return is_error, json.loads(text)
        except json.JSONDecodeError:
            return is_error, text
    return is_error, {}


class TestResolveFilterIntentTool:
    """Verify resolve_filter_intent_tool() handler."""

    @pytest.mark.asyncio
    async def test_valid_intent_returns_resolved(self):
        """Valid intent with direct conditions returns RESOLVED spec."""
        from src.orchestrator.agent.tools.data import resolve_filter_intent_tool

        gw = _mock_gateway()
        intent_dict = {
            "root": {
                "logic": "AND",
                "conditions": [
                    {"column": "state", "operator": "eq", "operands": [{"type": "string", "value": "CA"}]},
                ],
            },
            "schema_signature": "test_schema_sig",
        }

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", return_value=gw):
            result = await resolve_filter_intent_tool({"intent": intent_dict})

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "RESOLVED"
        assert content["schema_signature"] == "test_schema_sig"

    @pytest.mark.asyncio
    async def test_semantic_reference_returns_appropriate_status(self):
        """Intent with semantic reference returns NEEDS_CONFIRMATION."""
        from src.orchestrator.agent.tools.data import resolve_filter_intent_tool

        gw = _mock_gateway()
        intent_dict = {
            "root": {
                "logic": "AND",
                "conditions": [
                    {"semantic_key": "northeast", "target_column": "state"},
                ],
            },
            "schema_signature": "test_schema_sig",
        }

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", return_value=gw):
            result = await resolve_filter_intent_tool({"intent": intent_dict})

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "NEEDS_CONFIRMATION"
        assert content["pending_confirmations"] is not None

    @pytest.mark.asyncio
    async def test_resolved_spec_is_cached_on_bridge(self):
        """RESOLVED output should populate bridge cache for pipeline recovery."""
        from src.orchestrator.agent.tools.data import resolve_filter_intent_tool

        gw = _mock_gateway()
        bridge = EventEmitterBridge()
        bridge.last_user_message = "ship CA orders"
        intent_dict = {
            "root": {
                "logic": "AND",
                "conditions": [
                    {"column": "state", "operator": "eq", "operands": [{"type": "string", "value": "CA"}]},
                ],
            },
            "schema_signature": "test_schema_sig",
        }

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", return_value=gw):
            result = await resolve_filter_intent_tool({"intent": intent_dict}, bridge=bridge)

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "RESOLVED"
        assert isinstance(bridge.last_resolved_filter_spec, dict)
        assert bridge.last_resolved_filter_spec.get("status") == "RESOLVED"
        assert bridge.last_resolved_filter_command == "ship CA orders"

    @pytest.mark.asyncio
    async def test_missing_schema_returns_error(self):
        """Missing data source returns error."""
        from src.orchestrator.agent.tools.data import resolve_filter_intent_tool

        gw = AsyncMock()
        gw.get_source_info.return_value = None

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", return_value=gw):
            result = await resolve_filter_intent_tool({"intent": {}})

        is_error, _ = _parse_tool_result(result)
        assert is_error is True

    @pytest.mark.asyncio
    async def test_invalid_intent_structure_returns_error(self):
        """Invalid intent JSON structure returns error."""
        from src.orchestrator.agent.tools.data import resolve_filter_intent_tool

        gw = _mock_gateway()
        # Missing required 'root' field
        intent_dict = {"service_code": "03"}

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", return_value=gw):
            result = await resolve_filter_intent_tool({"intent": intent_dict})

        is_error, _ = _parse_tool_result(result)
        assert is_error is True
