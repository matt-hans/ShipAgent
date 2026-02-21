"""Tests for fetch_rows_tool hard cutover to filter_spec."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.models.filter_spec import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    ResolutionStatus,
    ResolvedFilterSpec,
    TypedLiteral,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Set env vars needed by filter internals."""
    monkeypatch.setenv("FILTER_TOKEN_SECRET", "test-secret-fetch")


def _mock_gateway(rows=None, source_info=None):
    """Create a mock data gateway."""
    if rows is None:
        rows = [
            {"_row_number": 1, "state": "CA", "company": "Acme"},
            {"_row_number": 2, "state": "CA", "company": "Beta"},
        ]
    if source_info is None:
        source_info = {
            "source_type": "csv",
            "row_count": 100,
            "columns": [
                {"name": "state", "type": "VARCHAR", "nullable": True},
                {"name": "company", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
    gw = AsyncMock()
    gw.get_rows_by_filter.return_value = rows
    gw.get_source_info.return_value = source_info
    return gw


def _make_resolved_spec():
    """Create a RESOLVED FilterSpec dict."""
    return ResolvedFilterSpec(
        status=ResolutionStatus.RESOLVED,
        root=FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="state",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value="CA")],
                )
            ],
        ),
        explanation="state equals CA",
        schema_signature="test_sig",
        canonical_dict_version="1.0",
    ).model_dump()


def _parse_tool_result(result: dict) -> tuple[bool, dict | str]:
    """Parse MCP tool response."""
    is_error = result.get("isError", False)
    content_list = result.get("content", [])
    if content_list and content_list[0].get("type") == "text":
        text = content_list[0]["text"]
        try:
            return is_error, json.loads(text)
        except json.JSONDecodeError:
            return is_error, text
    return is_error, {}


class TestFetchRowsFilterSpec:
    """Verify fetch_rows_tool hard cutover to filter_spec."""

    @pytest.mark.asyncio
    async def test_accepts_filter_spec(self):
        """fetch_rows with filter_spec compiles and passes parameterized SQL."""
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        gw = _mock_gateway()
        bridge = MagicMock()
        bridge.store_rows.return_value = "test-fetch-id"

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", new_callable=AsyncMock, return_value=gw):
            result = await fetch_rows_tool(
                {"filter_spec": _make_resolved_spec()},
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["row_count"] == 2
        assert content["fetch_id"] == "test-fetch-id"

        # Verify parameterized query
        gw.get_rows_by_filter.assert_called_once()
        call_kwargs = gw.get_rows_by_filter.call_args.kwargs
        assert "where_sql" in call_kwargs
        assert "params" in call_kwargs
        assert call_kwargs["params"] == ["CA"]

    @pytest.mark.asyncio
    async def test_rejects_where_clause(self):
        """fetch_rows rejects raw where_clause."""
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        result = await fetch_rows_tool({"where_clause": "state = 'CA'"})

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "where_clause" in content.lower()

    @pytest.mark.asyncio
    async def test_rejects_neither(self):
        """fetch_rows rejects calls with neither filter_spec nor all_rows."""
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        result = await fetch_rows_tool({})

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "filter_spec" in content.lower() or "all_rows" in content.lower()

    @pytest.mark.asyncio
    async def test_rejects_both(self):
        """fetch_rows rejects calls with both filter_spec and all_rows."""
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        result = await fetch_rows_tool({
            "filter_spec": _make_resolved_spec(),
            "all_rows": True,
        })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "conflicting" in content.lower()

    @pytest.mark.asyncio
    async def test_all_rows_fetches_everything(self):
        """fetch_rows with all_rows=true fetches all rows."""
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        gw = _mock_gateway()
        bridge = MagicMock()
        bridge.store_rows.return_value = "test-fetch-id"

        with patch("src.orchestrator.agent.tools.data.get_data_gateway", new_callable=AsyncMock, return_value=gw):
            result = await fetch_rows_tool(
                {"all_rows": True},
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["row_count"] == 2

        # Gateway should be called with all-rows filter
        gw.get_rows_by_filter.assert_called_once()
        call_kwargs = gw.get_rows_by_filter.call_args.kwargs
        assert call_kwargs["where_sql"] == "1=1"
        assert call_kwargs["params"] == []

    @pytest.mark.asyncio
    async def test_uses_total_count_when_gateway_exposes_it(self):
        """fetch_rows should report authoritative total_count, not page size."""
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        gw = AsyncMock()
        gw.get_source_info.return_value = {
            "source_type": "csv",
            "row_count": 100,
            "columns": [
                {"name": "state", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
        gw.get_rows_with_count.return_value = {
            "rows": [
                {"_row_number": 1, "state": "CA"},
                {"_row_number": 2, "state": "CA"},
            ],
            "total_count": 28,
        }
        bridge = MagicMock()
        bridge.store_rows.return_value = "test-fetch-id"

        with patch(
            "src.orchestrator.agent.tools.data.get_data_gateway",
            new_callable=AsyncMock,
            return_value=gw,
        ):
            result = await fetch_rows_tool(
                {"all_rows": True, "limit": 2},
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["row_count"] == 28
        assert content["total_count"] == 28
        assert content["returned_count"] == 2

    @pytest.mark.asyncio
    async def test_rejects_fetch_rows_for_shipping_intent(self):
        """fetch_rows should reject direct shipping requests to force fast path."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.data import fetch_rows_tool

        bridge = EventEmitterBridge()
        bridge.last_user_message = "Ship all orders going to companies in the Northeast."

        result = await fetch_rows_tool({"all_rows": True}, bridge=bridge)

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "ship_command_pipeline" in content
