"""Tests for deterministic SDK tools (tools_v2).

Each tool wraps an existing service with a thin SDK-compatible interface.
No tool calls the LLM internally — all are deterministic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.agent.tools_v2 import (
    batch_execute_tool,
    batch_preview_tool,
    create_job_tool,
    fetch_rows_tool,
    get_all_tool_definitions,
    get_job_status_tool,
    get_platform_status_tool,
    get_schema_tool,
    get_source_info_tool,
    validate_filter_syntax_tool,
)


# ---------------------------------------------------------------------------
# get_source_info_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_source_info_returns_metadata():
    """Returns source type, file path, row count when connected."""
    mock_info = MagicMock()
    mock_info.source_type = "csv"
    mock_info.file_path = "/tmp/orders.csv"
    mock_info.row_count = 42
    mock_info.columns = []

    with patch(
        "src.orchestrator.agent.tools_v2._get_data_source_service"
    ) as mock_svc_fn:
        mock_svc = MagicMock()
        mock_svc.get_source_info.return_value = mock_info
        mock_svc_fn.return_value = mock_svc

        result = await get_source_info_tool({})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["source_type"] == "csv"
    assert data["row_count"] == 42


@pytest.mark.asyncio
async def test_get_source_info_no_connection_returns_error():
    """Returns isError when no data source is connected."""
    with patch(
        "src.orchestrator.agent.tools_v2._get_data_source_service"
    ) as mock_svc_fn:
        mock_svc = MagicMock()
        mock_svc.get_source_info.return_value = None
        mock_svc_fn.return_value = mock_svc

        result = await get_source_info_tool({})

    assert result["isError"] is True


# ---------------------------------------------------------------------------
# get_schema_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schema_returns_columns():
    """Returns column names and types from the schema."""
    mock_col = MagicMock()
    mock_col.name = "order_id"
    mock_col.type = "VARCHAR"
    mock_col.nullable = False

    mock_info = MagicMock()
    mock_info.columns = [mock_col]

    with patch(
        "src.orchestrator.agent.tools_v2._get_data_source_service"
    ) as mock_svc_fn:
        mock_svc = MagicMock()
        mock_svc.get_source_info.return_value = mock_info
        mock_svc_fn.return_value = mock_svc

        result = await get_schema_tool({})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert len(data["columns"]) == 1
    assert data["columns"][0]["name"] == "order_id"


# ---------------------------------------------------------------------------
# fetch_rows_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_rows_with_valid_filter():
    """Fetches rows using the provided WHERE clause."""
    rows = [{"order_id": 1, "state": "CA"}]

    with patch(
        "src.orchestrator.agent.tools_v2._get_data_source_service"
    ) as mock_svc_fn:
        mock_svc = MagicMock()
        mock_svc.get_rows_by_filter = AsyncMock(return_value=rows)
        mock_svc_fn.return_value = mock_svc

        result = await fetch_rows_tool({"where_clause": "state = 'CA'", "limit": 10})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["row_count"] == 1
    assert data["rows"][0]["state"] == "CA"


# ---------------------------------------------------------------------------
# validate_filter_syntax_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_filter_syntax_valid():
    """Valid SQL WHERE clause passes validation."""
    result = await validate_filter_syntax_tool({"where_clause": "state = 'CA'"})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["valid"] is True


@pytest.mark.asyncio
async def test_validate_filter_syntax_invalid():
    """Invalid SQL WHERE clause is caught."""
    result = await validate_filter_syntax_tool({"where_clause": "SELECT DROP TABLE"})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["valid"] is False


# ---------------------------------------------------------------------------
# create_job_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_returns_job_id():
    """Creates a job and returns its ID."""
    mock_job = MagicMock()
    mock_job.id = "test-job-123"
    mock_job.status = "pending"

    with patch("src.orchestrator.agent.tools_v2.get_db_context") as mock_ctx:
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.orchestrator.agent.tools_v2.JobService") as MockJS:
            MockJS.return_value.create_job.return_value = mock_job

            result = await create_job_tool({
                "name": "Ship CA orders",
                "command": "Ship California orders via Ground",
            })

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["job_id"] == "test-job-123"


# ---------------------------------------------------------------------------
# batch_execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_execute_requires_approval():
    """Execute tool returns error if approved=False."""
    result = await batch_execute_tool({
        "job_id": "some-job",
        "approved": False,
    })
    assert result["isError"] is True
    assert "confirm" in result["content"][0]["text"].lower() or "approv" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_batch_execute_requires_approval_missing():
    """Execute tool returns error if approved is not provided."""
    result = await batch_execute_tool({"job_id": "some-job"})
    assert result["isError"] is True


# ---------------------------------------------------------------------------
# get_job_status_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_job_status_returns_summary():
    """Returns job summary with counts."""
    summary = {
        "total_rows": 10,
        "processed_rows": 5,
        "successful_rows": 4,
        "failed_rows": 1,
        "status": "running",
    }

    with patch("src.orchestrator.agent.tools_v2.get_db_context") as mock_ctx:
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.orchestrator.agent.tools_v2.JobService") as MockJS:
            MockJS.return_value.get_job_summary.return_value = summary

            result = await get_job_status_tool({"job_id": "test-job"})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["total_rows"] == 10


# ---------------------------------------------------------------------------
# batch_preview_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_preview_returns_preview_data():
    """Preview tool delegates to BatchEngine.preview()."""
    preview_result = {
        "total_rows": 5,
        "total_estimated_cost_cents": 3500,
        "preview_rows": [],
    }

    with patch("src.orchestrator.agent.tools_v2._run_batch_preview") as mock_preview:
        mock_preview.return_value = preview_result
        result = await batch_preview_tool({"job_id": "test-job"})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["total_rows"] == 5


# ---------------------------------------------------------------------------
# get_platform_status_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_platform_status():
    """Returns connected platform statuses."""
    result = await get_platform_status_tool({})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert "platforms" in data


# ---------------------------------------------------------------------------
# get_all_tool_definitions
# ---------------------------------------------------------------------------


def test_get_all_tool_definitions_count():
    """Returns definitions for all tools."""
    defs = get_all_tool_definitions()
    assert isinstance(defs, list)
    assert len(defs) >= 8  # at least 8 core tools
    # Each definition has name, description, input_schema
    for d in defs:
        assert "name" in d
        assert "description" in d
        assert "input_schema" in d


def test_tool_definitions_have_unique_names():
    """All tool names are unique."""
    defs = get_all_tool_definitions()
    names = [d["name"] for d in defs]
    assert len(names) == len(set(names))
