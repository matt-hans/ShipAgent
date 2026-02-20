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
)
from src.orchestrator.agent.tools.pipeline import (
    batch_execute_tool,
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
async def test_fetch_rows_with_all_rows():
    """Fetches all rows using the all_rows=true path."""
    rows = [{"order_id": 1, "state": "CA"}]
    bridge = EventEmitterBridge()

    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway"
    ) as mock_gw_fn:
        mock_gw = AsyncMock()
        mock_gw.get_rows_by_filter.return_value = rows
        mock_gw_fn.return_value = mock_gw

        result = await fetch_rows_tool(
            {"all_rows": True, "limit": 10},
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
                "all_rows": True,
                "limit": 10,
                "include_rows": True,
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["rows"][0]["state"] == "CA"


# ---------------------------------------------------------------------------
# ship_command_pipeline_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ship_command_pipeline_success_with_all_rows():
    """Pipeline fetches all rows when all_rows=true is provided."""
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
                "all_rows": True,
            }
        )

    assert result["isError"] is False
    mock_gw.get_rows_by_filter.assert_awaited_once_with(
        where_sql="1=1", limit=250, params=[],
    )
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "preview_ready"
    assert payload["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_ship_command_pipeline_threads_schema_fingerprint_to_build_job_row_data():
    """Pipeline passes source signature to row normalization/build path."""
    fetched_rows = [{"order_id": "1", "service_code": "03"}]
    preview_result = {
        "job_id": "job-fp",
        "total_rows": 1,
        "preview_rows": [{"row_number": 1, "estimated_cost_cents": 1000}],
        "total_estimated_cost_cents": 1000,
    }

    with (
        patch("src.orchestrator.agent.tools.pipeline.get_data_gateway") as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch("src.services.ups_payload_builder.build_shipper", return_value={"name": "Store"}),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
        patch(
            "src.orchestrator.agent.tools.pipeline._build_job_row_data_with_metadata",
            return_value=(
                [
                    {
                        "row_number": 1,
                        "row_checksum": "abc",
                        "order_data": json.dumps({"service_code": "03"}),
                    }
                ],
                "map-hash-123",
            ),
        ) as mock_build,
    ):
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "csv",
            "row_count": 1,
            "columns": [{"name": "order_id", "type": "VARCHAR", "nullable": True}],
            "signature": "sig-thread-test",
        }
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-fp"
        MockJS.return_value.create_job.return_value = mock_job
        MockJS.return_value.get_rows.return_value = [
            MagicMock(row_number=1, order_data=json.dumps({"service_code": "03"})),
        ]

        MockEngine.return_value.preview = AsyncMock(return_value=preview_result)

        result = await ship_command_pipeline_tool(
            {"command": "Ship all orders", "all_rows": True}
        )

    assert result["isError"] is False
    mock_build.assert_called_once()
    kwargs = mock_build.call_args.kwargs
    assert kwargs["schema_fingerprint"] == "sig-thread-test"


@pytest.mark.asyncio
async def test_ship_command_pipeline_enriches_preview_from_persisted_job_rows():
    """Preview row enrichment should use persisted order_data, not fetched_rows re-normalization."""
    fetched_rows = [{"order_id": "1", "service_code": "01"}]
    preview_result = {
        "job_id": "job-row-map",
        "total_rows": 1,
        "preview_rows": [{"row_number": 1, "estimated_cost_cents": 1000}],
        "total_estimated_cost_cents": 1000,
    }

    with (
        patch("src.orchestrator.agent.tools.pipeline.get_data_gateway") as mock_gw_fn,
        patch(
            "src.orchestrator.agent.tools.pipeline._get_ups_client",
            new=AsyncMock(return_value=AsyncMock()),
        ),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context") as mock_ctx,
        patch("src.orchestrator.agent.tools.pipeline.JobService") as MockJS,
        patch("src.services.batch_engine.BatchEngine") as MockEngine,
        patch("src.services.ups_payload_builder.build_shipper", return_value={"name": "Store"}),
        patch("src.orchestrator.agent.tools.pipeline._persist_job_source_signature", new=AsyncMock()),
    ):
        mock_gw = AsyncMock()
        mock_gw.get_source_info.return_value = {
            "source_type": "csv",
            "row_count": 1,
            "columns": [{"name": "order_id", "type": "VARCHAR", "nullable": True}],
            "signature": "sig-row-map",
        }
        mock_gw.get_rows_by_filter.return_value = fetched_rows
        mock_gw_fn.return_value = mock_gw

        mock_db = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_job = MagicMock()
        mock_job.id = "job-row-map"
        mock_job_service = MockJS.return_value
        mock_job_service.create_job.return_value = mock_job
        mock_job_service.get_rows.return_value = [
            MagicMock(row_number=1, order_data=json.dumps({"service_code": "03"})),
        ]
        mock_job_service.create_rows.return_value = [MagicMock()]

        MockEngine.return_value.preview = AsyncMock(return_value=preview_result)

        result = await ship_command_pipeline_tool(
            {"command": "Ship all orders", "all_rows": True}
        )

    assert result["isError"] is False
    assert preview_result["preview_rows"][0]["service"] == "UPS Ground"


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
                "command": "ship all orders via UPS Ground",
                "service_code": "03",
                "all_rows": True,
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
                "command": "ship all orders",
                # Simulates agent filling an implicit default even though user did not.
                "service_code": "03",
                "all_rows": True,
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
                "all_rows": True,
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
                "all_rows": True,
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
            {"command": "Ship all orders", "all_rows": True},
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
    """Interactive mode exposes status tools + interactive preview + v2 tools + contacts."""
    defs = get_all_tool_definitions(interactive_shipping=True)
    names = {d["name"] for d in defs}
    expected = {
        "get_job_status", "get_platform_status", "preview_interactive_shipment",
        "schedule_pickup", "cancel_pickup", "rate_pickup", "get_pickup_status",
        "find_locations", "get_service_center_facilities",
        "request_document_upload", "upload_paperless_document",
        "push_document_to_shipment", "delete_paperless_document",
        "get_landed_cost", "track_package",
        "resolve_contact", "save_contact", "list_contacts", "delete_contact",
    }
    assert names == expected


def test_tool_definitions_unfiltered_when_interactive_disabled():
    """Batch/data tools remain available when interactive mode is disabled."""
    defs = get_all_tool_definitions(interactive_shipping=False)
    names = {d["name"] for d in defs}
    assert "ship_command_pipeline" in names
    assert "fetch_rows" in names
    assert "create_job" not in names
    assert "add_rows_to_job" not in names
    assert "batch_preview" not in names


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
                "confirmed": True,
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    text = json.loads(result["content"][0]["text"])
    assert "ABC123" in text  # Minimal summary contains PRN

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "scheduled"
    assert captured[0][1]["prn"] == "ABC123"


@pytest.mark.asyncio
async def test_schedule_pickup_tool_safety_gate():
    """schedule_pickup_tool rejects when confirmed is missing or False."""
    from src.orchestrator.agent.tools.pickup import schedule_pickup_tool

    result = await schedule_pickup_tool({"pickup_date": "20260220"})
    assert result["isError"] is True
    assert "Safety gate" in result["content"][0]["text"]

    result2 = await schedule_pickup_tool({"pickup_date": "20260220", "confirmed": False})
    assert result2["isError"] is True
    assert "Safety gate" in result2["content"][0]["text"]


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
                "confirmed": True,
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

        result = await schedule_pickup_tool({"confirmed": True})

    assert result["isError"] is True
    assert "Unexpected error" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_schedule_pickup_tool_emits_enriched_result():
    """schedule_pickup_tool includes address/contact in pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "2929602E9CP"}

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
                "pickup_date": "20260217",
                "ready_time": "0900",
                "close_time": "1700",
                "address_line": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country_code": "US",
                "contact_name": "John Smith",
                "phone_number": "214-555-1234",
                "confirmed": True,
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    payload = captured[0][1]
    assert payload["prn"] == "2929602E9CP"
    assert payload["address_line"] == "123 Main St"
    assert payload["city"] == "Dallas"
    assert payload["contact_name"] == "John Smith"
    assert payload["pickup_date"] == "20260217"


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
            {"cancel_by": "prn", "prn": "ABC123", "confirmed": True},
            bridge=bridge,
        )

    assert result["isError"] is False
    text = json.loads(result["content"][0]["text"])
    assert "cancelled" in text.lower()

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_pickup_tool_safety_gate():
    """cancel_pickup_tool rejects when confirmed is missing or False."""
    from src.orchestrator.agent.tools.pickup import cancel_pickup_tool

    result = await cancel_pickup_tool({"cancel_by": "prn", "prn": "ABC123"})
    assert result["isError"] is True
    assert "Safety gate" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_rate_pickup_tool_success():
    """rate_pickup_tool returns _ok envelope and emits pickup_preview event."""
    mock_ups = AsyncMock()
    mock_ups.rate_pickup.return_value = {
        "success": True,
        "grandTotal": "5.50",
        "charges": [{"chargeAmount": "5.50", "chargeCode": "B", "chargeLabel": "Base Charge"}],
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
    text = json.loads(result["content"][0]["text"])
    assert "rate" in text.lower()

    assert len(captured) == 1
    assert captured[0][0] == "pickup_preview"
    assert mock_ups.rate_pickup.await_args.kwargs["pickup_type"] == "oncall"


@pytest.mark.asyncio
async def test_rate_pickup_tool_emits_pickup_preview_event():
    """rate_pickup_tool emits pickup_preview (not pickup_result) with all input details."""
    mock_ups = AsyncMock()
    mock_ups.rate_pickup.return_value = {
        "success": True,
        "charges": [
            {"chargeAmount": "9.65", "chargeCode": "B", "chargeLabel": "Base Charge"},
        ],
        "grandTotal": "9.65",
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
                "pickup_type": "smart",
                "address_line": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country_code": "US",
                "pickup_date": "20260217",
                "ready_time": "0900",
                "close_time": "1700",
                "contact_name": "John Smith",
                "phone_number": "214-555-1234",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "pickup_preview"
    payload = captured[0][1]
    assert payload["address_line"] == "123 Main St"
    assert payload["city"] == "Dallas"
    assert payload["contact_name"] == "John Smith"
    assert payload["grand_total"] == "9.65"
    assert payload["charges"][0]["chargeLabel"] == "Base Charge"
    assert payload["pickup_type"] == "oncall"
    assert mock_ups.rate_pickup.await_args.kwargs["pickup_type"] == "oncall"


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
            {},
            bridge=bridge,
        )

    assert result["isError"] is False
    text = json.loads(result["content"][0]["text"])
    assert "status" in text.lower()

    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "status"
    assert mock_ups.get_pickup_status.await_args.kwargs["pickup_type"] == "oncall"


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
async def test_find_locations_tool_maps_services_to_general():
    """location_type=services is coerced to general for drop-off list results."""
    mock_ups = AsyncMock()
    mock_ups.find_locations.return_value = {"success": True, "locations": [{"id": "L1"}]}

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
                "location_type": "services",
                "address_line": "",
                "city": "Atlanta",
                "state": "GA",
                "postal_code": "",
                "country_code": "us",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "location_result"
    mock_ups.find_locations.assert_awaited_once()
    call_kwargs = mock_ups.find_locations.await_args.kwargs
    assert call_kwargs["location_type"] == "general"
    assert call_kwargs["country_code"] == "US"


@pytest.mark.asyncio
async def test_find_locations_tool_retries_general_when_empty():
    """If a narrow mode is empty, tool retries once with general mode."""
    mock_ups = AsyncMock()
    mock_ups.find_locations = AsyncMock(
        side_effect=[
            {"success": True, "locations": []},
            {"success": True, "locations": [{"id": "L2"}]},
        ]
    )

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
                "address_line": "",
                "city": "Atlanta",
                "state": "GA",
                "postal_code": "",
                "country_code": "US",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][1]["locations"] == [{"id": "L2"}]
    assert mock_ups.find_locations.await_count == 2
    first_kwargs = mock_ups.find_locations.await_args_list[0].kwargs
    second_kwargs = mock_ups.find_locations.await_args_list[1].kwargs
    assert first_kwargs["location_type"] == "retail"
    assert second_kwargs["location_type"] == "general"


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
    text = json.loads(result["content"][0]["text"])
    assert "DOC-123" in text

    assert len(captured) == 1
    assert captured[0][0] == "paperless_result"
    assert captured[0][1]["action"] == "uploaded"
    assert captured[0][1]["documentId"] == "DOC-123"


@pytest.mark.asyncio
async def test_upload_paperless_document_tool_handles_missing_file():
    """upload_paperless_document_tool returns _err when no file is available."""
    from src.orchestrator.agent.tools.documents import (
        upload_paperless_document_tool,
    )

    result = await upload_paperless_document_tool({"document_type": "002"})

    assert result["isError"] is True
    assert "No document attached" in result["content"][0]["text"]


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
    text = json.loads(result["content"][0]["text"])
    assert "attached" in text.lower() or "shipment" in text.lower()

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
    text = json.loads(result["content"][0]["text"])
    assert "deleted" in text.lower()

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
                "commodities": [
                    {"price": 25.00, "quantity": 2, "description": "Widget"},
                ],
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    text = json.loads(result["content"][0]["text"])
    assert "Landed cost estimate displayed" in text

    assert len(captured) == 1
    assert captured[0][0] == "landed_cost_result"
    assert captured[0][1]["totalLandedCost"] == "45.23"
    assert captured[0][1]["requestSummary"]["exportCountryCode"] == "US"
    assert captured[0][1]["requestSummary"]["importCountryCode"] == "GB"
    assert captured[0][1]["requestSummary"]["commodityCount"] == 1
    assert captured[0][1]["items"][0]["itemLabel"] == "Widget"


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


# ---------------------------------------------------------------------------
# UPS MCP v2 — Tool registration (Task 13)
# ---------------------------------------------------------------------------


def test_v2_tools_registered_batch_mode():
    """All UPS MCP v2 orchestrator tools appear in batch mode."""
    defs = get_all_tool_definitions()
    names = {d["name"] for d in defs}
    expected_v2 = {
        "schedule_pickup",
        "cancel_pickup",
        "rate_pickup",
        "get_pickup_status",
        "find_locations",
        "get_service_center_facilities",
        "upload_paperless_document",
        "push_document_to_shipment",
        "delete_paperless_document",
        "get_landed_cost",
    }
    assert expected_v2.issubset(names), f"Missing: {expected_v2 - names}"


def test_v2_tools_available_in_interactive_mode():
    """Interactive mode includes v2 orchestrator tools (AD-1 updated).

    V2 tools work independently of data sources and should be
    accessible in both batch and interactive modes.
    """
    defs = get_all_tool_definitions(interactive_shipping=True)
    names = {d["name"] for d in defs}
    # Original 3 tools
    assert "get_job_status" in names
    assert "get_platform_status" in names
    assert "preview_interactive_shipment" in names
    # v2 tools now included
    v2_tools = {
        "schedule_pickup",
        "cancel_pickup",
        "rate_pickup",
        "get_pickup_status",
        "find_locations",
        "get_service_center_facilities",
        "upload_paperless_document",
        "push_document_to_shipment",
        "delete_paperless_document",
        "get_landed_cost",
        "track_package",
    }
    assert v2_tools.issubset(names), f"Missing v2 tools: {v2_tools - names}"
    # Batch-only tools NOT included
    assert "ship_command_pipeline" not in names
    assert "batch_preview" not in names
    assert "fetch_rows" not in names


# ---------------------------------------------------------------------------
# UPS MCP v2 — Integration: tool call → event emission → payload verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_pickup_flow_tool_to_event():
    """End-to-end: schedule_pickup_tool → pickup_result event with correct payload."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "E2E-PRN-123"}

    bridge = EventEmitterBridge()
    captured_events: list[tuple[str, dict]] = []
    bridge.callback = lambda et, d: captured_events.append((et, d))

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool
        tool_result = await schedule_pickup_tool(
            {
                "pickup_date": "20260301", "ready_time": "0800", "close_time": "1800",
                "address_line": "456 Oak Ave", "city": "Dallas", "state": "TX",
                "postal_code": "75201", "country_code": "US",
                "contact_name": "Jane Doe", "phone_number": "2145551234",
                "confirmed": True,
            },
            bridge=bridge,
        )

    # Verify tool returned minimal _ok envelope to LLM
    assert tool_result["isError"] is False
    llm_text = json.loads(tool_result["content"][0]["text"])
    assert "E2E-PRN-123" in llm_text

    # Verify SSE event emitted with full payload
    assert len(captured_events) == 1
    event_type, event_data = captured_events[0]
    assert event_type == "pickup_result"
    assert event_data["action"] == "scheduled"
    assert event_data["prn"] == "E2E-PRN-123"
    assert event_data["success"] is True


@pytest.mark.asyncio
async def test_e2e_landed_cost_flow_tool_to_event():
    """End-to-end: get_landed_cost_tool → landed_cost_result event with breakdown."""
    mock_ups = AsyncMock()
    mock_ups.get_landed_cost.return_value = {
        "success": True,
        "totalLandedCost": "87.50",
        "currencyCode": "USD",
        "items": [
            {"commodityId": "1", "duties": "25.00", "taxes": "12.50", "fees": "0.00"},
            {"commodityId": "2", "duties": "30.00", "taxes": "20.00", "fees": "0.00"},
        ],
    }

    bridge = EventEmitterBridge()
    captured_events: list[tuple[str, dict]] = []
    bridge.callback = lambda et, d: captured_events.append((et, d))

    with patch("src.orchestrator.agent.tools.pipeline._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pipeline import get_landed_cost_tool
        tool_result = await get_landed_cost_tool(
            {
                "currency_code": "USD",
                "export_country_code": "US",
                "import_country_code": "GB",
                "commodities": [
                    {"price": 50.00, "quantity": 1, "hs_code": "6109.10", "description": "Cotton Shirt"},
                    {"price": 75.00, "quantity": 1, "hs_code": "6110.20", "description": "Wool Sweater"},
                ],
            },
            bridge=bridge,
        )

    # Verify tool returned minimal _ok envelope to LLM
    assert tool_result["isError"] is False
    llm_text = json.loads(tool_result["content"][0]["text"])
    assert "Landed cost estimate displayed" in llm_text

    # Verify SSE event emitted with full breakdown
    assert len(captured_events) == 1
    event_type, event_data = captured_events[0]
    assert event_type == "landed_cost_result"
    assert event_data["totalLandedCost"] == "87.50"
    assert len(event_data["items"]) == 2
    assert event_data["items"][0]["itemLabel"] == "Cotton Shirt"
    assert event_data["items"][1]["itemLabel"] == "Wool Sweater"
    assert event_data["requestSummary"]["commodityCount"] == 2
    assert event_data["requestSummary"]["totalUnits"] == 2


# ---------------------------------------------------------------------------
# UPS MCP v2 — Tracking tool handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_package_tool_matching_response():
    """track_package_tool emits tracking_result event with matching tracking number."""
    mock_ups = AsyncMock()
    mock_ups.track_package.return_value = {
        "trackResponse": {
            "shipment": [{
                "package": [{
                    "trackingNumber": "1Z999AA10123456784",
                    "currentStatus": {"code": "D", "description": "Delivered"},
                    "deliveryDate": [{"date": "20260215"}],
                    "activity": [
                        {
                            "date": "20260215",
                            "time": "143000",
                            "location": {"address": {"city": "Austin", "stateProvince": "TX", "countryCode": "US"}},
                            "status": {"description": "Delivered"},
                        },
                        {
                            "date": "20260214",
                            "time": "081500",
                            "location": {"address": {"city": "Dallas", "stateProvince": "TX", "countryCode": "US"}},
                            "status": {"description": "In Transit"},
                        },
                    ],
                }],
            }],
        },
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda et, d: captured.append((et, d))

    with patch(
        "src.orchestrator.agent.tools.tracking._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.tracking import track_package_tool

        result = await track_package_tool(
            {"tracking_number": "1Z999AA10123456784"},
            bridge=bridge,
        )

    assert result["isError"] is False
    text = json.loads(result["content"][0]["text"])
    assert "1Z999AA10123456784" in text  # Minimal summary contains tracking number

    # Verify event emitted with full details
    assert len(captured) == 1
    assert captured[0][0] == "tracking_result"
    assert captured[0][1]["action"] == "tracked"
    assert captured[0][1]["trackingNumber"] == "1Z999AA10123456784"
    assert captured[0][1]["statusDescription"] == "Delivered"
    assert len(captured[0][1]["activities"]) == 2
    assert captured[0][1]["deliveryDate"] == "20260215"
    assert "mismatch" not in captured[0][1]  # No mismatch key when matching


@pytest.mark.asyncio
async def test_track_package_tool_mismatch_detection():
    """track_package_tool flags mismatch when UPS returns different tracking number."""
    mock_ups = AsyncMock()
    mock_ups.track_package.return_value = {
        "trackResponse": {
            "shipment": [{
                "package": [{
                    "trackingNumber": "1ZSANDBOX000000001",
                    "currentStatus": {"code": "IT", "description": "In Transit"},
                    "activity": [],
                }],
            }],
        },
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda et, d: captured.append((et, d))

    with patch(
        "src.orchestrator.agent.tools.tracking._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.tracking import track_package_tool

        result = await track_package_tool(
            {"tracking_number": "1Z999AA10123456784"},
            bridge=bridge,
        )

    assert result["isError"] is False
    text = json.loads(result["content"][0]["text"])
    assert "1ZSANDBOX000000001" in text  # Minimal summary contains returned number
    assert "sandbox" in text.lower()  # Mismatch note present

    # Event should include mismatch flag
    assert len(captured) == 1
    assert captured[0][1]["mismatch"] is True
    assert captured[0][1]["requestedNumber"] == "1Z999AA10123456784"
    assert captured[0][1]["trackingNumber"] == "1ZSANDBOX000000001"


@pytest.mark.asyncio
async def test_track_package_tool_error_handling():
    """track_package_tool returns _err envelope on UPSServiceError."""
    from src.services.errors import UPSServiceError

    mock_ups = AsyncMock()
    mock_ups.track_package.side_effect = UPSServiceError(
        code="E-3001", message="tracking unavailable"
    )

    with patch(
        "src.orchestrator.agent.tools.tracking._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.tracking import track_package_tool

        result = await track_package_tool(
            {"tracking_number": "1Z999AA10123456784"},
        )

    assert result["isError"] is True
    assert "E-3001" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_track_package_tool_missing_tracking_number():
    """track_package_tool returns _err when tracking_number is empty."""
    from src.orchestrator.agent.tools.tracking import track_package_tool

    result = await track_package_tool({})
    assert result["isError"] is True
    assert "Missing required parameter" in result["content"][0]["text"]

    result2 = await track_package_tool({"tracking_number": "  "})
    assert result2["isError"] is True


def test_track_package_registered_in_definitions():
    """track_package appears in the tool definitions."""
    defs = get_all_tool_definitions()
    names = {d["name"] for d in defs}
    assert "track_package" in names


# ---------------------------------------------------------------------------
# Python interpreter fallback
# ---------------------------------------------------------------------------


def test_python_command_fallback():
    """_get_python_command returns sys.executable when .venv doesn't exist."""
    import sys

    with patch("os.path.exists", return_value=False):
        from src.services.ups_mcp_client import _get_python_command

        result = _get_python_command()
        assert result == sys.executable


def test_python_command_prefers_venv():
    """_get_python_command returns venv python when it exists."""
    with patch("os.path.exists", return_value=True):
        from src.services.ups_mcp_client import _get_python_command, _VENV_PYTHON

        result = _get_python_command()
        assert result == _VENV_PYTHON
