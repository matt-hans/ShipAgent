"""Tests for deterministic SDK tools (tools/ package).

Each tool wraps an existing service with a thin SDK-compatible interface.
No tool calls the LLM internally — all are deterministic.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.agent.tools import get_all_tool_definitions
from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _emit_event,
    _emit_preview_ready,
    _enrich_preview_rows,
    _get_ups_client,
    shutdown_cached_ups_client,
)
from src.orchestrator.agent.tools.data import (
    fetch_rows_tool,
    get_platform_status_tool,
    get_schema_tool,
    get_source_info_tool,
    validate_filter_syntax_tool,
)
from src.orchestrator.agent.tools.pipeline import (
    add_rows_to_job_tool,
    batch_execute_tool,
    batch_preview_tool,
    create_job_tool,
    get_job_status_tool,
    ship_command_pipeline_tool,
)


# ---------------------------------------------------------------------------
# get_source_info_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_source_info_returns_metadata():
    """Returns source type, file path, row count when connected."""
    info_dict = {
        "active": True,
        "source_type": "csv",
        "path": "/tmp/orders.csv",
        "row_count": 42,
        "columns": [],
    }

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = info_dict
        mock_gw_fn.return_value = mock_gw

        result = await get_source_info_tool({})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["source_type"] == "csv"
    assert data["row_count"] == 42


@pytest.mark.asyncio
async def test_get_source_info_no_connection_returns_error():
    """Returns isError when no data source is connected."""
    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = None
        mock_gw_fn.return_value = mock_gw

        result = await get_source_info_tool({})

    assert result["isError"] is True


# ---------------------------------------------------------------------------
# get_schema_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schema_returns_columns():
    """Returns column names and types from the schema."""
    info_dict = {
        "active": True,
        "columns": [{"name": "order_id", "type": "VARCHAR", "nullable": False}],
    }

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = info_dict
        mock_gw_fn.return_value = mock_gw

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
    bridge = EventEmitterBridge()

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = rows
        mock_gw_fn.return_value = mock_gw

        result = await fetch_rows_tool(
            {"where_clause": "state = 'CA'", "limit": 10},
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["row_count"] == 1
    assert data["fetch_id"]
    assert data["sample_rows"][0]["state"] == "CA"
    assert "rows" not in data


@pytest.mark.asyncio
async def test_fetch_rows_include_rows_returns_full_payload():
    """include_rows=True returns full rows for compatibility/debug usage."""
    rows = [{"order_id": 1, "state": "CA"}]
    bridge = EventEmitterBridge()

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = rows
        mock_gw_fn.return_value = mock_gw

        result = await fetch_rows_tool(
            {
                "where_clause": "state = 'CA'",
                "limit": 10,
                "include_rows": True,
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["rows"][0]["state"] == "CA"


@pytest.mark.asyncio
async def test_add_rows_to_job_uses_fetch_id_cache():
    """add_rows_to_job accepts fetch_id and resolves rows from cache."""
    rows = [{"order_id": 1, "state": "CA"}]
    bridge = EventEmitterBridge()

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = rows
        mock_gw_fn.return_value = mock_gw
        fetch_res = await fetch_rows_tool(
            {"where_clause": "state = 'CA'"},
            bridge=bridge,
        )

    fetch_data = json.loads(fetch_res["content"][0]["text"])
    fetch_id = fetch_data["fetch_id"]

    with patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx:
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS:
            MockJS.return_value.create_rows.return_value = [MagicMock()]
            result = await add_rows_to_job_tool(
                {
                    "job_id": "job-123",
                    "fetch_id": fetch_id,
                },
                bridge=bridge,
            )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["rows_added"] == 1


@pytest.mark.asyncio
async def test_add_rows_to_job_auto_maps_csv_columns_to_canonical_order_data():
    """CSV-style headers are normalized to ship_to_* fields before persistence."""
    rows = [
        {
            "Recipient Name": "Alice",
            "Address": "123 Main St",
            "City": "Los Angeles",
            "State": "CA",
            "ZIP": "90001",
            "Country": "US",
            "Weight": 2.5,
            "Service": "Ground",
        }
    ]

    captured_row_data: list[dict[str, Any]] = []

    with patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx:
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS:

            def _capture(job_id, row_data):
                captured_row_data.extend(row_data)
                return [MagicMock()]

            MockJS.return_value.create_rows.side_effect = _capture
            result = await add_rows_to_job_tool(
                {
                    "job_id": "job-123",
                    "rows": rows,
                }
            )

    assert result["isError"] is False
    assert captured_row_data
    order_data = json.loads(captured_row_data[0]["order_data"])
    assert order_data["ship_to_name"] == "Alice"
    assert order_data["ship_to_address1"] == "123 Main St"
    assert order_data["ship_to_city"] == "Los Angeles"
    assert order_data["ship_to_state"] == "CA"
    assert order_data["ship_to_postal_code"] == "90001"
    assert order_data["ship_to_country"] == "US"
    assert order_data["service_code"] == "03"


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

    with (
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
    ):
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        MockJS.return_value.create_job.return_value = mock_job

        result = await create_job_tool(
            {
                "name": "Ship CA orders",
                "command": "Ship California orders via Ground",
            }
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["job_id"] == "test-job-123"


# ---------------------------------------------------------------------------
# ship_command_pipeline_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ship_command_pipeline_success_with_where_clause_none():
    """Pipeline fetches all rows when where_clause is omitted/None."""
    fetched_rows = [{"order_id": "1", "service_code": "03"}]
    preview_result = {
        "job_id": "job-1",
        "total_rows": 1,
        "preview_rows": [{"row_number": 1, "estimated_cost_cents": 1000}],
        "total_estimated_cost_cents": 1000,
    }

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline.get_data_gateway"
        ) as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch(
            "src.services.ups_payload_builder.build_shipper",
            return_value={"name": "Store"},
        ),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-1"
        MockJS.return_value.create_job.return_value = mock_job
        MockJS.return_value.get_rows.return_value = [MagicMock()]

        MockEngine.return_value.preview = AsyncMock(return_value=preview_result)

        result = await ship_command_pipeline_tool(
            {
                "command": "Ship all orders",
                "where_clause": None,
            }
        )

    assert result["isError"] is False
    mock_gw.get_rows_by_filter.assert_awaited_once_with(where_clause=None, limit=250)
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "preview_ready"
    assert payload["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_ship_command_pipeline_applies_explicit_service_override_to_rows():
    """Explicit service request is persisted so execute matches preview."""
    fetched_rows = [
        {"order_id": "1", "service_code": "02"},
        {"order_id": "2", "service_code": "12"},
    ]
    preview_result = {
        "job_id": "job-override",
        "total_rows": 2,
        "preview_rows": [{"row_number": 1, "estimated_cost_cents": 1000}],
        "total_estimated_cost_cents": 2000,
    }
    captured_row_data: list[dict[str, Any]] = []

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline.get_data_gateway"
        ) as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch(
            "src.services.ups_payload_builder.build_shipper",
            return_value={"name": "Store"},
        ),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-override"
        mock_job_service = MockJS.return_value
        mock_job_service.create_job.return_value = mock_job
        mock_job_service.get_rows.return_value = [MagicMock(), MagicMock()]

        def _capture(job_id: str, row_data: list[dict[str, Any]]) -> list[MagicMock]:
            captured_row_data.extend(row_data)
            return [MagicMock(), MagicMock()]

        mock_job_service.create_rows.side_effect = _capture
        MockEngine.return_value.preview = AsyncMock(return_value=preview_result)

        result = await ship_command_pipeline_tool(
            {
                "command": "ship all california orders via UPS Ground",
                "service_code": "03",
            }
        )

    assert result["isError"] is False
    assert captured_row_data
    for row in captured_row_data:
        order_data = json.loads(row["order_data"])
        assert order_data["service_code"] == "03"
    assert preview_result["preview_rows"][0]["service"] == "UPS Ground"

    preview_kwargs = MockEngine.return_value.preview.await_args.kwargs
    assert preview_kwargs["service_code"] == "03"


@pytest.mark.asyncio
async def test_ship_command_pipeline_ignores_implicit_service_code_default():
    """Commands without explicit service should use row-level service data."""
    fetched_rows = [
        {"order_id": "1", "service_code": "02"},
        {"order_id": "2", "service_code": "12"},
    ]
    preview_result = {
        "job_id": "job-live-service",
        "total_rows": 2,
        "preview_rows": [{"row_number": 1, "estimated_cost_cents": 1000}],
        "total_estimated_cost_cents": 2000,
    }
    captured_row_data: list[dict[str, Any]] = []

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline.get_data_gateway"
        ) as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch(
            "src.services.ups_payload_builder.build_shipper",
            return_value={"name": "Store"},
        ),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-live-service"
        mock_job_service = MockJS.return_value
        mock_job_service.create_job.return_value = mock_job
        mock_job_service.get_rows.return_value = [MagicMock(), MagicMock()]

        def _capture(job_id: str, row_data: list[dict[str, Any]]) -> list[MagicMock]:
            captured_row_data.extend(row_data)
            return [MagicMock(), MagicMock()]

        mock_job_service.create_rows.side_effect = _capture
        MockEngine.return_value.preview = AsyncMock(return_value=preview_result)

        result = await ship_command_pipeline_tool(
            {
                "command": "ship all california orders",
                # Simulates agent filling an implicit default even though user did not.
                "service_code": "03",
            }
        )

    assert result["isError"] is False
    assert captured_row_data
    assert json.loads(captured_row_data[0]["order_data"])["service_code"] == "02"
    assert json.loads(captured_row_data[1]["order_data"])["service_code"] == "12"

    preview_kwargs = MockEngine.return_value.preview.await_args.kwargs
    assert preview_kwargs["service_code"] is None


@pytest.mark.asyncio
async def test_ship_command_pipeline_create_rows_failure_deletes_job():
    """create_rows failure cleans up the just-created job."""
    fetched_rows = [{"order_id": "1", "service_code": "03"}]

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline.get_data_gateway"
        ) as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch(
            "src.services.ups_payload_builder.build_shipper",
            return_value={"name": "Store"},
        ),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-2"
        mock_job_service = MockJS.return_value
        mock_job_service.create_job.return_value = mock_job
        mock_job_service.create_rows.side_effect = RuntimeError("db row insert failed")

        result = await ship_command_pipeline_tool(
            {
                "command": "Ship all orders",
                "where_clause": None,
            }
        )

    assert result["isError"] is True
    mock_job_service.delete_job.assert_called_once_with("job-2")


@pytest.mark.asyncio
async def test_ship_command_pipeline_preview_failure_preserves_job_and_returns_job_id():
    """Preview hard failure returns error including job id (no delete cleanup)."""
    fetched_rows = [{"order_id": "1", "service_code": "03"}]

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline.get_data_gateway"
        ) as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch(
            "src.services.ups_payload_builder.build_shipper",
            return_value={"name": "Store"},
        ),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-3"
        mock_job_service = MockJS.return_value
        mock_job_service.create_job.return_value = mock_job
        mock_job_service.get_rows.return_value = [MagicMock()]

        MockEngine.return_value.preview = AsyncMock(
            side_effect=RuntimeError("UPS unavailable")
        )

        result = await ship_command_pipeline_tool(
            {
                "command": "Ship all orders",
            }
        )

    assert result["isError"] is True
    assert "job-3" in result["content"][0]["text"]
    mock_job_service.delete_job.assert_not_called()


# ---------------------------------------------------------------------------
# batch_execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_execute_requires_approval():
    """Execute tool returns error if approved=False."""
    result = await batch_execute_tool(
        {
            "job_id": "some-job",
            "approved": False,
        }
    )
    assert result["isError"] is True
    assert (
        "confirm" in result["content"][0]["text"].lower()
        or "approv" in result["content"][0]["text"].lower()
    )


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

    with patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx:
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS:
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
    """Preview tool returns a slim LLM payload while keeping SSE payload full."""
    preview_result = {
        "job_id": "test-job",
        "total_rows": 5,
        "total_estimated_cost_cents": 3500,
        "preview_rows": [],
    }

    with patch("src.orchestrator.agent.tools.pipeline._run_batch_preview") as mock_preview:
        mock_preview.return_value = preview_result
        result = await batch_preview_tool({"job_id": "test-job"})

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["status"] == "preview_ready"
    assert data["total_rows"] == 5
    assert data["total_estimated_cost_cents"] == 3500
    assert "preview_rows" not in data
    assert "STOP HERE" in data["message"]


@pytest.mark.asyncio
async def test_batch_preview_uses_emit_preview_ready_helper():
    """batch_preview_tool delegates response construction to _emit_preview_ready."""
    preview_result = {
        "job_id": "test-job",
        "total_rows": 5,
        "total_estimated_cost_cents": 3500,
        "preview_rows": [],
    }
    bridge = EventEmitterBridge()

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline._run_batch_preview",
            new=AsyncMock(return_value=preview_result),
        ),
        patch(
            "src.orchestrator.agent.tools.pipeline._emit_preview_ready",
            return_value={
                "isError": False,
                "content": [{"type": "text", "text": "{}"}],
            },
        ) as mock_emit,
    ):
        await batch_preview_tool({"job_id": "test-job"}, bridge=bridge)

    mock_emit.assert_called_once()


@pytest.mark.asyncio
async def test_ship_command_pipeline_uses_emit_preview_ready_helper():
    """ship_command_pipeline_tool delegates final payload to _emit_preview_ready."""
    fetched_rows = [{"order_id": "1", "service_code": "03"}]
    preview_result = {
        "job_id": "job-1",
        "total_rows": 1,
        "preview_rows": [{"row_number": 1, "estimated_cost_cents": 1000}],
        "total_estimated_cost_cents": 1000,
    }
    bridge = EventEmitterBridge()

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline.get_data_gateway"
        ) as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch(
            "src.services.ups_payload_builder.build_shipper",
            return_value={"name": "Store"},
        ),
        patch(
            "src.orchestrator.agent.tools.pipeline._emit_preview_ready",
            return_value={
                "isError": False,
                "content": [{"type": "text", "text": "{}"}],
            },
        ) as mock_emit,
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-1"
        MockJS.return_value.create_job.return_value = mock_job
        MockJS.return_value.get_rows.return_value = [MagicMock()]
        MockEngine.return_value.preview = AsyncMock(return_value=preview_result)

        await ship_command_pipeline_tool(
            {"command": "Ship all orders"},
            bridge=bridge,
        )

    mock_emit.assert_called_once()


# ---------------------------------------------------------------------------
# get_platform_status_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_platform_status():
    """Returns connected platform statuses."""
    with patch("src.orchestrator.agent.tools.data.get_data_gateway") as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = None
        mock_gw_fn.return_value = mock_gw

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
    assert any(d["name"] == "ship_command_pipeline" for d in defs)


def test_tool_definitions_have_unique_names():
    """All tool names are unique."""
    defs = get_all_tool_definitions()
    names = [d["name"] for d in defs]
    assert len(names) == len(set(names))


def test_tool_definitions_filtered_for_interactive_mode():
    """Interactive mode exposes only non-batch orchestrator status tools."""
    defs = get_all_tool_definitions(interactive_shipping=True)
    names = {d["name"] for d in defs}
    assert names == {"get_job_status", "get_platform_status", "preview_interactive_shipment"}


def test_tool_definitions_unfiltered_when_interactive_disabled():
    """Batch/data tools remain available when interactive mode is disabled."""
    defs = get_all_tool_definitions(interactive_shipping=False)
    names = {d["name"] for d in defs}
    assert "ship_command_pipeline" in names
    assert "batch_preview" in names
    assert "fetch_rows" in names


# ---------------------------------------------------------------------------
# Event emission (module-level bridge)
# ---------------------------------------------------------------------------


def test_emit_event_calls_callback():
    """_emit_event invokes the registered callback with correct args."""
    captured = []
    bridge = EventEmitterBridge()

    def callback(event_type: str, data: dict) -> None:
        captured.append((event_type, data))

    bridge.callback = callback
    _emit_event("preview_ready", {"job_id": "j1", "total_rows": 3}, bridge=bridge)

    assert len(captured) == 1
    assert captured[0][0] == "preview_ready"
    assert captured[0][1]["job_id"] == "j1"


def test_emit_event_noop_without_emitter():
    """_emit_event does not raise when no emitter is set."""
    bridge = EventEmitterBridge()
    # Should not raise
    _emit_event("preview_ready", {"job_id": "j1"}, bridge=bridge)


def test_emit_event_isolated_between_bridges():
    """Bridge callback mutation is scoped per bridge instance."""
    captured_a: list[tuple[str, dict]] = []
    captured_b: list[tuple[str, dict]] = []
    bridge_a = EventEmitterBridge()
    bridge_b = EventEmitterBridge()

    bridge_a.callback = lambda event_type, data: captured_a.append((event_type, data))
    bridge_b.callback = lambda event_type, data: captured_b.append((event_type, data))

    _emit_event("preview_ready", {"job_id": "a"}, bridge=bridge_a)

    assert len(captured_a) == 1
    assert captured_a[0][1]["job_id"] == "a"
    assert captured_b == []


@pytest.mark.asyncio
async def test_batch_preview_emits_preview_ready():
    """batch_preview_tool emits preview_ready event to the registered callback."""
    preview_result = {
        "job_id": "test-job",
        "total_rows": 2,
        "total_estimated_cost_cents": 2400,
        "preview_rows": [
            {"row_number": 1, "recipient_name": "Alice", "estimated_cost_cents": 1200},
            {
                "row_number": 2,
                "recipient_name": "Bob",
                "estimated_cost_cents": 1200,
                "rate_error": "Bad address",
            },
        ],
    }

    captured = []
    bridge = EventEmitterBridge()

    def callback(event_type: str, data: dict) -> None:
        captured.append((event_type, data))

    bridge.callback = callback
    with (
        patch("src.orchestrator.agent.tools.pipeline._run_batch_preview") as mock_preview,
        patch("src.orchestrator.agent.tools.pipeline._enrich_preview_rows") as mock_enrich,
    ):
        mock_preview.return_value = preview_result
        # _enrich_preview_rows modifies rows in place; simulate no-op
        mock_enrich.return_value = preview_result["preview_rows"]

        result = await batch_preview_tool({"job_id": "test-job"}, bridge=bridge)

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "preview_ready"
    assert captured[0][1]["job_id"] == "test-job"
    assert "preview_rows" in captured[0][1]


@pytest.mark.asyncio
async def test_batch_preview_emits_before_ok_return():
    """_emit_event is called before _ok return construction."""
    preview_result = {
        "job_id": "test-job",
        "total_rows": 1,
        "total_estimated_cost_cents": 123,
        "preview_rows": [],
    }
    call_order: list[str] = []

    def _capture_emit(*_args, **_kwargs) -> None:
        call_order.append("emit")

    def _capture_ok(payload: dict) -> dict:
        call_order.append("ok")
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }

    with (
        patch(
            "src.orchestrator.agent.tools.pipeline._run_batch_preview",
            new=AsyncMock(return_value=preview_result),
        ),
        patch(
            "src.orchestrator.agent.tools.pipeline._enrich_preview_rows",
            return_value=preview_result["preview_rows"],
        ),
        patch("src.orchestrator.agent.tools.core._emit_event", side_effect=_capture_emit),
        patch("src.orchestrator.agent.tools.core._ok", side_effect=_capture_ok),
    ):
        await batch_preview_tool({"job_id": "test-job"})

    assert call_order == ["emit", "ok"]


def test_emit_preview_ready_payload_shape():
    """_emit_preview_ready returns the expected slim payload schema."""
    bridge = EventEmitterBridge()
    result = _emit_preview_ready(
        result={
            "job_id": "job-1",
            "total_rows": 5,
            "total_estimated_cost_cents": 2500,
        },
        rows_with_warnings=1,
        bridge=bridge,
    )
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "preview_ready"
    assert payload["job_id"] == "job-1"
    assert payload["rows_with_warnings"] == 1


@pytest.mark.asyncio
async def test_fetch_cache_isolated_between_bridges():
    """fetch_id created on one bridge is not visible to another bridge."""
    rows = [{"order_id": 1, "state": "CA"}]
    bridge_a = EventEmitterBridge()
    bridge_b = EventEmitterBridge()

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = rows
        mock_gw_fn.return_value = mock_gw
        fetch_res = await fetch_rows_tool(
            {"where_clause": "state = 'CA'"},
            bridge=bridge_a,
        )

    fetch_id = json.loads(fetch_res["content"][0]["text"])["fetch_id"]
    result = await add_rows_to_job_tool(
        {"job_id": "job-123", "fetch_id": fetch_id},
        bridge=bridge_b,
    )
    assert result["isError"] is True
    assert "fetch_id not found" in result["content"][0]["text"]


def test_preview_data_normalization():
    """_enrich_preview_rows converts rate_error→warnings and adds service/order_data."""
    preview_rows = [
        {"row_number": 1, "recipient_name": "Alice", "estimated_cost_cents": 1200},
        {
            "row_number": 2,
            "recipient_name": "Bob",
            "estimated_cost_cents": 0,
            "rate_error": "Address validation failed",
        },
    ]

    # Mock DB rows
    mock_row_1 = MagicMock()
    mock_row_1.row_number = 1
    mock_row_1.order_data = json.dumps({"service_code": "02", "order_id": "A1"})

    mock_row_2 = MagicMock()
    mock_row_2.row_number = 2
    mock_row_2.order_data = json.dumps({"service_code": "03", "order_id": "A2"})

    with patch("src.orchestrator.agent.tools.core.get_db_context") as mock_ctx:
        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.orchestrator.agent.tools.core.JobService") as MockJS:
            MockJS.return_value.get_rows.return_value = [mock_row_1, mock_row_2]

            result = _enrich_preview_rows("test-job", preview_rows)

    # Row 1: no rate_error → empty warnings, service from code 02
    assert result[0]["warnings"] == []
    assert result[0]["service"] == "UPS 2nd Day Air"
    assert result[0]["order_data"]["order_id"] == "A1"
    assert "rate_error" not in result[0]

    # Row 2: rate_error → warnings array, service from code 03
    assert result[1]["warnings"] == ["Address validation failed"]
    assert result[1]["service"] == "UPS Ground"
    assert result[1]["order_data"]["order_id"] == "A2"
    assert "rate_error" not in result[1]


@pytest.mark.asyncio
async def test_cached_ups_client_reused():
    """_get_ups_client delegates to gateway_provider and returns the same instance."""
    mock_client = AsyncMock()
    mock_client.is_connected = True

    with patch(
        "src.services.gateway_provider.get_ups_gateway",
        new=AsyncMock(return_value=mock_client),
    ):
        c1 = await _get_ups_client()
        c2 = await _get_ups_client()

    assert c1 is c2
    assert c1 is mock_client


@pytest.mark.asyncio
async def test_shutdown_cached_ups_client_is_noop():
    """shutdown_cached_ups_client is a no-op (lifecycle managed by gateway_provider)."""
    # Should not raise or do anything
    await shutdown_cached_ups_client()


# ---------------------------------------------------------------------------
# UPS MCP v2 — Pickup tool handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_pickup_tool_success():
    """schedule_pickup_tool returns _ok envelope and emits pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "ABC123"}

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool

        result = await schedule_pickup_tool(
            {
                "pickup_date": "20260220",
                "ready_time": "0900",
                "close_time": "1700",
                "address_line": "123 Main",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country_code": "US",
                "contact_name": "John",
                "phone_number": "5125551234",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["prn"] == "ABC123"
    assert data["success"] is True

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "scheduled"
    assert captured[0][1]["prn"] == "ABC123"


@pytest.mark.asyncio
async def test_schedule_pickup_tool_error():
    """schedule_pickup_tool returns _err envelope on UPSServiceError."""
    from src.services.errors import UPSServiceError

    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.side_effect = UPSServiceError(
        code="E-3007", message="timing error"
    )

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool

        result = await schedule_pickup_tool(
            {
                "pickup_date": "20260220",
                "ready_time": "0900",
                "close_time": "1700",
                "address_line": "123 Main",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country_code": "US",
                "contact_name": "John",
                "phone_number": "5125551234",
            },
        )

    assert result["isError"] is True
    assert "E-3007" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_schedule_pickup_tool_handles_malformed_args():
    """schedule_pickup_tool returns _err for TypeError from bad model args."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.side_effect = TypeError("missing required arg")

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool

        result = await schedule_pickup_tool({})

    assert result["isError"] is True
    assert "Unexpected error" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_cancel_pickup_tool_success():
    """cancel_pickup_tool returns _ok envelope and emits pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.cancel_pickup.return_value = {"success": True, "status": "cancelled"}

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import cancel_pickup_tool

        result = await cancel_pickup_tool(
            {"cancel_by": "prn", "prn": "ABC123"},
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["success"] is True

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "cancelled"


@pytest.mark.asyncio
async def test_rate_pickup_tool_success():
    """rate_pickup_tool returns _ok envelope and emits pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.rate_pickup.return_value = {
        "success": True,
        "grandTotalOfAllCharge": "5.50",
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import rate_pickup_tool

        result = await rate_pickup_tool(
            {
                "pickup_type": "oncall",
                "address_line": "123 Main",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country_code": "US",
                "pickup_date": "20260220",
                "ready_time": "0900",
                "close_time": "1700",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["success"] is True

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "rated"


@pytest.mark.asyncio
async def test_get_pickup_status_tool_success():
    """get_pickup_status_tool returns _ok envelope and emits pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.get_pickup_status.return_value = {
        "success": True,
        "pickups": [{"prn": "ABC123", "status": "Pending"}],
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import get_pickup_status_tool

        result = await get_pickup_status_tool(
            {"pickup_type": "oncall"},
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["success"] is True

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "status"


@pytest.mark.asyncio
async def test_find_locations_tool_emits_location_result():
    """find_locations_tool emits location_result event with results."""
    mock_ups = AsyncMock()
    mock_ups.find_locations.return_value = {
        "success": True,
        "locations": [{"id": "L1", "address": {"line": "123 Main"}}],
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import find_locations_tool

        result = await find_locations_tool(
            {
                "location_type": "retail",
                "address_line": "123 Main",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country_code": "US",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "location_result"
    assert len(captured[0][1]["locations"]) == 1


@pytest.mark.asyncio
async def test_find_locations_tool_handles_malformed_args():
    """find_locations_tool returns _err for TypeError from bad model args."""
    mock_ups = AsyncMock()
    mock_ups.find_locations.side_effect = TypeError("missing required arg")

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import find_locations_tool

        result = await find_locations_tool({})

    assert result["isError"] is True
    assert "Unexpected error" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_get_service_center_facilities_tool_success():
    """get_service_center_facilities_tool returns _ok and emits location_result."""
    mock_ups = AsyncMock()
    mock_ups.get_service_center_facilities.return_value = {
        "success": True,
        "facilities": [{"name": "UPS Store", "address": "456 Oak Ave"}],
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import (
            get_service_center_facilities_tool,
        )

        result = await get_service_center_facilities_tool(
            {
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country_code": "US",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "location_result"
    assert captured[0][1]["action"] == "service_centers"


# ---------------------------------------------------------------------------
# UPS MCP v2 — Paperless document tool handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_paperless_document_tool_emits_event():
    """upload_paperless_document_tool emits paperless_result on success."""
    mock_ups = AsyncMock()
    mock_ups.upload_document.return_value = {
        "success": True,
        "documentId": "DOC-123",
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.documents._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.documents import (
            upload_paperless_document_tool,
        )

        result = await upload_paperless_document_tool(
            {
                "file_content_base64": "dGVzdA==",
                "file_name": "invoice.pdf",
                "file_format": "pdf",
                "document_type": "002",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["documentId"] == "DOC-123"

    assert len(captured) == 1
    assert captured[0][0] == "paperless_result"
    assert captured[0][1]["action"] == "uploaded"
    assert captured[0][1]["documentId"] == "DOC-123"


@pytest.mark.asyncio
async def test_upload_paperless_document_tool_handles_malformed_args():
    """upload_paperless_document_tool returns _err for TypeError from bad args."""
    mock_ups = AsyncMock()
    mock_ups.upload_document.side_effect = TypeError("missing required arg")

    with patch(
        "src.orchestrator.agent.tools.documents._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.documents import (
            upload_paperless_document_tool,
        )

        result = await upload_paperless_document_tool({})

    assert result["isError"] is True
    assert "Unexpected error" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_push_document_to_shipment_tool_success():
    """push_document_to_shipment_tool emits paperless_result on success."""
    mock_ups = AsyncMock()
    mock_ups.push_document.return_value = {"success": True}

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.documents._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.documents import (
            push_document_to_shipment_tool,
        )

        result = await push_document_to_shipment_tool(
            {
                "document_id": "DOC-123",
                "shipment_identifier": "1Z999AA10123456784",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["success"] is True

    assert len(captured) == 1
    assert captured[0][0] == "paperless_result"
    assert captured[0][1]["action"] == "pushed"


@pytest.mark.asyncio
async def test_delete_paperless_document_tool_success():
    """delete_paperless_document_tool emits paperless_result on success."""
    mock_ups = AsyncMock()
    mock_ups.delete_document.return_value = {"success": True}

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.documents._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.documents import (
            delete_paperless_document_tool,
        )

        result = await delete_paperless_document_tool(
            {"document_id": "DOC-123"},
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["success"] is True

    assert len(captured) == 1
    assert captured[0][0] == "paperless_result"
    assert captured[0][1]["action"] == "deleted"


@pytest.mark.asyncio
async def test_delete_paperless_document_tool_error():
    """delete_paperless_document_tool returns _err on UPSServiceError."""
    from src.services.errors import UPSServiceError

    mock_ups = AsyncMock()
    mock_ups.delete_document.side_effect = UPSServiceError(
        code="E-3006", message="document not found"
    )

    with patch(
        "src.orchestrator.agent.tools.documents._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.documents import (
            delete_paperless_document_tool,
        )

        result = await delete_paperless_document_tool(
            {"document_id": "DOC-GONE"},
        )

    assert result["isError"] is True
    assert "E-3006" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# UPS MCP v2 — Landed cost tool handler (pipeline.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_landed_cost_tool_emits_event():
    """get_landed_cost_tool emits landed_cost_result on success."""
    mock_ups = AsyncMock()
    mock_ups.get_landed_cost.return_value = {
        "success": True,
        "totalLandedCost": "45.23",
        "currencyCode": "USD",
        "items": [
            {"commodityId": "1", "duties": "12.50", "taxes": "7.73", "fees": "0.00"}
        ],
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pipeline._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pipeline import get_landed_cost_tool

        result = await get_landed_cost_tool(
            {
                "currency_code": "USD",
                "export_country_code": "US",
                "import_country_code": "GB",
                "commodities": [{"price": 25.00, "quantity": 2}],
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["totalLandedCost"] == "45.23"

    assert len(captured) == 1
    assert captured[0][0] == "landed_cost_result"
    assert captured[0][1]["totalLandedCost"] == "45.23"


@pytest.mark.asyncio
async def test_get_landed_cost_tool_error():
    """get_landed_cost_tool returns _err on UPSServiceError."""
    from src.services.errors import UPSServiceError

    mock_ups = AsyncMock()
    mock_ups.get_landed_cost.side_effect = UPSServiceError(
        code="E-3001", message="service unavailable"
    )

    with patch(
        "src.orchestrator.agent.tools.pipeline._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pipeline import get_landed_cost_tool

        result = await get_landed_cost_tool(
            {
                "currency_code": "USD",
                "export_country_code": "US",
                "import_country_code": "GB",
                "commodities": [],
            },
        )

    assert result["isError"] is True
    assert "E-3001" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_get_landed_cost_tool_handles_malformed_args():
    """get_landed_cost_tool returns _err for TypeError from bad model args."""
    mock_ups = AsyncMock()
    mock_ups.get_landed_cost.side_effect = TypeError("missing required arg")

    with patch(
        "src.orchestrator.agent.tools.pipeline._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pipeline import get_landed_cost_tool

        result = await get_landed_cost_tool({})

    assert result["isError"] is True
    assert "Unexpected error" in result["content"][0]["text"]
