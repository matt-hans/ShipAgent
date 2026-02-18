"""Tests for ship_command_pipeline hard cutover to filter_spec."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.models.filter_spec import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    ResolvedFilterSpec,
    ResolutionStatus,
    TypedLiteral,
)


@pytest.fixture(autouse=True)
def _pipeline_env(monkeypatch):
    """Set env vars needed by pipeline internals."""
    monkeypatch.setenv("UPS_ACCOUNT_NUMBER", "TEST123")
    monkeypatch.setenv("FILTER_TOKEN_SECRET", "test-secret-pipeline")


def _mock_gateway(rows=None, source_info=None):
    """Create a mock data gateway."""
    if rows is None:
        rows = [
            {"_row_number": 1, "state": "CA", "company": "Acme", "weight": 5.0},
            {"_row_number": 2, "state": "CA", "company": "Beta", "weight": 3.0},
        ]
    if source_info is None:
        source_info = {
            "source_type": "csv",
            "row_count": 100,
            "columns": [
                {"name": "state", "type": "VARCHAR", "nullable": True},
                {"name": "company", "type": "VARCHAR", "nullable": True},
                {"name": "weight", "type": "DOUBLE", "nullable": True},
            ],
            "signature": "test_sig",
        }
    gw = AsyncMock()
    gw.get_rows_by_filter.return_value = rows
    gw.get_source_info.return_value = source_info
    gw.get_source_signature.return_value = {
        "source_type": "csv",
        "source_ref": "test.csv",
        "schema_fingerprint": "test_sig",
    }
    return gw


def _make_resolved_spec():
    """Create a RESOLVED FilterSpec dict for passing to pipeline."""
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


def _make_northeast_resolved_spec():
    """Create a RESOLVED FilterSpec that matches Northeast states."""
    return ResolvedFilterSpec(
        status=ResolutionStatus.RESOLVED,
        root=FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="state",
                    operator=FilterOperator.in_,
                    operands=[
                        TypedLiteral(type="string", value="NY"),
                        TypedLiteral(type="string", value="NJ"),
                    ],
                )
            ],
        ),
        explanation="state in [NY, NJ]",
        schema_signature="test_sig",
        canonical_dict_version="1.0",
    ).model_dump()


def _make_shopify_range_spec_without_fulfillment():
    """Spec with state + price constraints but no fulfillment_status condition."""
    return ResolvedFilterSpec(
        status=ResolutionStatus.RESOLVED,
        root=FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="ship_to_state",
                    operator=FilterOperator.in_,
                    operands=[
                        TypedLiteral(type="string", value="CA"),
                        TypedLiteral(type="string", value="NY"),
                        TypedLiteral(type="string", value="TX"),
                    ],
                ),
                FilterCondition(
                    column="total_price",
                    operator=FilterOperator.gt,
                    operands=[TypedLiteral(type="number", value=50)],
                ),
                FilterCondition(
                    column="total_price",
                    operator=FilterOperator.lt,
                    operands=[TypedLiteral(type="number", value=500)],
                ),
            ],
        ),
        explanation="state in [CA, NY, TX]; total_price > 50; total_price < 500",
        schema_signature="test_sig",
        canonical_dict_version="1.0",
    ).model_dump()


def _make_shopify_conflicting_fulfillment_spec():
    """Spec that explicitly requests fulfilled orders (conflicts with unfulfilled command)."""
    return ResolvedFilterSpec(
        status=ResolutionStatus.RESOLVED,
        root=FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="fulfillment_status",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value="fulfilled")],
                ),
            ],
        ),
        explanation="fulfillment_status equals fulfilled",
        schema_signature="test_sig",
        canonical_dict_version="1.0",
    ).model_dump()


def _make_shopify_fulfillment_only_spec(status: str = "unfulfilled"):
    """Spec that only constrains fulfillment status."""
    return ResolvedFilterSpec(
        status=ResolutionStatus.RESOLVED,
        root=FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="fulfillment_status",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value=status)],
                ),
            ],
        ),
        explanation=f"fulfillment_status equals {status}",
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


def _mock_job_service():
    """Create a mock JobService with create_job, create_rows, get_rows."""
    svc = MagicMock()
    mock_job = MagicMock()
    mock_job.id = "test-job-id"
    mock_job.status = "pending"
    svc.create_job.return_value = mock_job
    svc.create_rows.return_value = [MagicMock(), MagicMock()]
    svc.get_rows.return_value = [MagicMock(row_number=1), MagicMock(row_number=2)]
    return svc


def _mock_batch_engine():
    """Create a mock BatchEngine that returns preview results."""
    engine = MagicMock()
    engine.preview = AsyncMock(return_value={
        "job_id": "test-job-id",
        "total_rows": 2,
        "total_estimated_cost_cents": 2400,
        "preview_rows": [
            {"row_number": 1, "estimated_cost_cents": 1200},
            {"row_number": 2, "estimated_cost_cents": 1200},
        ],
    })
    return engine


def _pipeline_patches(gw, engine=None, job_svc=None):
    """Return a tuple of context managers for pipeline tests."""
    if engine is None:
        engine = _mock_batch_engine()
    if job_svc is None:
        job_svc = _mock_job_service()

    mock_db_ctx = MagicMock()
    mock_db_ctx.__enter__ = MagicMock(return_value=MagicMock())
    mock_db_ctx.__exit__ = MagicMock(return_value=False)

    return (
        patch("src.orchestrator.agent.tools.pipeline.get_data_gateway", new_callable=AsyncMock, return_value=gw),
        patch("src.orchestrator.agent.tools.core.get_data_gateway", new_callable=AsyncMock, return_value=gw),
        patch("src.orchestrator.agent.tools.pipeline._get_ups_client", new_callable=AsyncMock, return_value=AsyncMock()),
        patch("src.orchestrator.agent.tools.pipeline.get_db_context", return_value=mock_db_ctx),
        patch("src.orchestrator.agent.tools.pipeline.JobService", return_value=job_svc),
        patch("src.services.batch_engine.BatchEngine", return_value=engine),
        patch("src.services.ups_payload_builder.build_shipper", return_value={}),
    )


class TestPipelineFilterSpec:
    """Verify ship_command_pipeline hard cutover to filter_spec."""

    @pytest.mark.asyncio
    async def test_pipeline_accepts_filter_spec(self):
        """Pipeline with filter_spec compiles and passes parameterized SQL to gateway."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "ship CA orders ground",
                "filter_spec": _make_resolved_spec(),
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "preview_ready"

        # Verify gateway was called with parameterized SQL
        gw.get_rows_by_filter.assert_called_once()
        call_kwargs = gw.get_rows_by_filter.call_args.kwargs
        assert "where_sql" in call_kwargs
        assert "params" in call_kwargs
        assert call_kwargs["params"] == ["CA"]

    @pytest.mark.asyncio
    async def test_pipeline_rejects_where_clause(self):
        """Pipeline rejects raw where_clause with error."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        result = await ship_command_pipeline_tool({
            "command": "ship CA orders",
            "where_clause": "state = 'CA'",
        })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "where_clause" in content.lower()
        assert "resolve_filter_intent" in content.lower()

    @pytest.mark.asyncio
    async def test_pipeline_rejects_neither_filter_spec_nor_all_rows(self):
        """Pipeline rejects calls with neither filter_spec nor all_rows."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        result = await ship_command_pipeline_tool({
            "command": "ship some orders",
        })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "filter_spec" in content.lower() or "all_rows" in content.lower()

    @pytest.mark.asyncio
    async def test_pipeline_rejects_both_filter_spec_and_all_rows(self):
        """Pipeline rejects calls with both filter_spec and all_rows."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        result = await ship_command_pipeline_tool({
            "command": "ship all CA orders",
            "filter_spec": _make_resolved_spec(),
            "all_rows": True,
        })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "conflicting" in content.lower()

    @pytest.mark.asyncio
    async def test_pipeline_all_rows_fetches_everything(self):
        """Pipeline with all_rows=true fetches all rows via WHERE 1=1."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "ship everything",
                "all_rows": True,
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "preview_ready"

        # Gateway should have been called with all-rows filter
        gw.get_rows_by_filter.assert_called_once()
        call_kwargs = gw.get_rows_by_filter.call_args.kwargs
        assert call_kwargs["where_sql"] == "1=1"
        assert call_kwargs["params"] == []

    @pytest.mark.asyncio
    async def test_pipeline_rejects_all_rows_for_filtered_command(self):
        """all_rows should be rejected when command includes clear filter terms."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        result = await ship_command_pipeline_tool({
            "command": "Ship all orders going to companies in the Northeast.",
            "all_rows": True,
        })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "all_rows=true is not allowed" in content

    @pytest.mark.asyncio
    async def test_pipeline_rejects_all_rows_for_states_range_and_status(self):
        """all_rows should be rejected for explicit states + numeric/status filters."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        result = await ship_command_pipeline_tool({
            "command": (
                "Ship all orders from customers in California, Texas, or New York "
                "where the total is over $50 and under $500, but only the "
                "unfulfilled ones using UPS Ground."
            ),
            "all_rows": True,
        })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "all_rows=true is not allowed" in content

    @pytest.mark.asyncio
    async def test_pipeline_enforces_unfulfilled_status_when_command_requests_it(self):
        """If command says unfulfilled, pipeline injects deterministic status filter."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        source_info = {
            "source_type": "shopify",
            "row_count": 100,
            "columns": [
                {"name": "ship_to_state", "type": "VARCHAR", "nullable": True},
                {"name": "total_price", "type": "VARCHAR", "nullable": True},
                {"name": "fulfillment_status", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
        gw = _mock_gateway(source_info=source_info)
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": (
                    "Ship all orders from customers in California, Texas, or New York "
                    "where the total is over $50 and under $500, but only the "
                    "unfulfilled ones using UPS Ground."
                ),
                "filter_spec": _make_shopify_range_spec_without_fulfillment(),
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "preview_ready"
        assert content["filter_audit"]["enforced_fulfillment_status"] == "unfulfilled"
        # get_rows_by_filter call should include injected status param.
        params = gw.get_rows_by_filter.call_args.kwargs["params"]
        assert "unfulfilled" in params

    @pytest.mark.asyncio
    async def test_pipeline_rejects_conflicting_fulfillment_status(self):
        """Command/spec status conflict should fail deterministically."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        source_info = {
            "source_type": "shopify",
            "row_count": 100,
            "columns": [
                {"name": "fulfillment_status", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
        gw = _mock_gateway(source_info=source_info)
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "Ship only unfulfilled orders.",
                "filter_spec": _make_shopify_conflicting_fulfillment_spec(),
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "different fulfillment_status" in content

    @pytest.mark.asyncio
    async def test_pipeline_uses_richest_command_and_enforces_states_and_totals(self):
        """When args command is underspecified, bridge shipping command drives safety enforcement."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        source_info = {
            "source_type": "shopify",
            "row_count": 100,
            "columns": [
                {"name": "ship_to_state", "type": "VARCHAR", "nullable": True},
                {"name": "total_price", "type": "VARCHAR", "nullable": True},
                {"name": "fulfillment_status", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
        gw = _mock_gateway(source_info=source_info)
        bridge = EventEmitterBridge()
        bridge.last_user_message = "yes"
        bridge.last_shipping_command = (
            "Ship all orders from customers in California, Texas, or New York "
            "where the total is over $50 and under $500, but only the "
            "unfulfilled ones using UPS Ground."
        )
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool(
                {
                    "command": "Ship only unfulfilled orders.",
                    "filter_spec": _make_shopify_fulfillment_only_spec(),
                },
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "preview_ready"
        assert content["filter_audit"]["enforced_state_codes"] == ["CA", "NY", "TX"]
        assert content["filter_audit"]["enforced_total_bounds"] == {
            "column": "total_price",
            "lower": 50.0,
            "upper": 500.0,
        }
        params = gw.get_rows_by_filter.call_args.kwargs["params"]
        assert "CA" in params and "NY" in params and "TX" in params
        assert 50.0 in params and 500.0 in params

    @pytest.mark.asyncio
    async def test_pipeline_rejects_state_filtered_command_without_state_column(self):
        """Fail closed when command has explicit states but schema lacks state column."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        source_info = {
            "source_type": "shopify",
            "row_count": 100,
            "columns": [
                {"name": "total_price", "type": "VARCHAR", "nullable": True},
                {"name": "fulfillment_status", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
        gw = _mock_gateway(source_info=source_info)
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": (
                    "Ship all orders from customers in California, Texas, or New York "
                    "where the total is over $50 and under $500, but only the "
                    "unfulfilled ones using UPS Ground."
                ),
                "filter_spec": _make_shopify_fulfillment_only_spec(),
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "no recognized state column" in content

    @pytest.mark.asyncio
    async def test_pipeline_rejects_total_filtered_command_without_total_column(self):
        """Fail closed when command has total bounds but schema lacks total column."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        source_info = {
            "source_type": "shopify",
            "row_count": 100,
            "columns": [
                {"name": "ship_to_state", "type": "VARCHAR", "nullable": True},
                {"name": "fulfillment_status", "type": "VARCHAR", "nullable": True},
            ],
            "signature": "test_sig",
        }
        gw = _mock_gateway(source_info=source_info)
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": (
                    "Ship all orders from customers in California, Texas, or New York "
                    "where the total is over $50 and under $500, but only the "
                    "unfulfilled ones using UPS Ground."
                ),
                "filter_spec": _make_shopify_fulfillment_only_spec(),
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "no recognized total column" in content

    @pytest.mark.asyncio
    async def test_pipeline_rejects_region_command_when_spec_missing_region(self):
        """Command mentions Northeast but spec has non-region filter."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "Ship all orders in the Northeast.",
                "filter_spec": _make_resolved_spec(),  # state = CA
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "Filter mismatch" in content
        assert "region" in content.lower()

    @pytest.mark.asyncio
    async def test_pipeline_rejects_business_command_when_spec_missing_business(self):
        """Command mentions companies but spec lacks BUSINESS_RECIPIENT predicate."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        p = _pipeline_patches(gw)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "Ship all company orders in CA.",
                "filter_spec": _make_resolved_spec(),  # only state = CA
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "business/company predicate" in content

    @pytest.mark.asyncio
    async def test_pipeline_uses_bridge_command_for_business_guard(self):
        """Business guard should use the original user message from bridge."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        bridge = EventEmitterBridge()
        bridge.last_user_message = "Ship all orders going to companies in the Northeast."
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool(
                {
                    # Simulate LLM truncating command text in tool args.
                    "command": "Ship all orders in the Northeast.",
                    "filter_spec": _make_northeast_resolved_spec(),
                },
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "business/company predicate" in content

    @pytest.mark.asyncio
    async def test_pipeline_expands_truncated_page_to_authoritative_total(self):
        """Pipeline should auto-expand when count endpoint shows truncation."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        rows_page = [
            {"_row_number": 1, "state": "CA", "company": "Acme", "weight": 5.0},
            {"_row_number": 2, "state": "CA", "company": "Beta", "weight": 3.0},
        ]
        rows_full = rows_page + [
            {"_row_number": 3, "state": "CA", "company": "Gamma", "weight": 2.0},
            {"_row_number": 4, "state": "CA", "company": "Delta", "weight": 1.0},
        ]
        gw = _mock_gateway(rows=rows_full)
        gw.get_rows_with_count.return_value = {
            "rows": rows_page,
            "total_count": 4,
        }
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool(
                {
                    "command": "ship CA orders ground",
                    "filter_spec": _make_resolved_spec(),
                    "limit": 2,
                }
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "preview_ready"
        gw.get_rows_by_filter.assert_called_once()
        assert gw.get_rows_by_filter.call_args.kwargs["limit"] == 4

    @pytest.mark.asyncio
    async def test_pipeline_recovers_missing_filter_spec_from_bridge_cache(self):
        """Pipeline should reuse same-command resolved spec from bridge cache."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        bridge = EventEmitterBridge()
        bridge.last_user_message = "ship CA orders ground"
        bridge.last_resolved_filter_command = "ship CA orders ground"
        bridge.last_resolved_filter_spec = _make_resolved_spec()
        bridge.last_resolved_filter_schema_signature = "test_sig"
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool(
                {
                    "command": "ship CA orders ground",
                },
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert content["status"] == "preview_ready"

    @pytest.mark.asyncio
    async def test_pipeline_rejects_cached_filter_spec_when_schema_signature_mismatches(self):
        """Cache reuse must be blocked when resolved schema signature is stale."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        bridge = EventEmitterBridge()
        bridge.last_user_message = "ship CA orders ground"
        bridge.last_resolved_filter_command = "ship CA orders ground"
        bridge.last_resolved_filter_spec = _make_resolved_spec()
        bridge.last_resolved_filter_schema_signature = "old_sig"
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool(
                {
                    "command": "ship CA orders ground",
                },
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is True
        assert "Cached filter_spec no longer matches" in content

    @pytest.mark.asyncio
    async def test_pipeline_attaches_filter_audit(self):
        """Pipeline attaches filter_audit metadata to preview event."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        engine = _mock_batch_engine()

        captured_preview_event = {}

        def capture_emit(event_type, data):
            if event_type == "preview_ready":
                captured_preview_event.update(data)

        bridge = MagicMock()
        bridge.emit = capture_emit

        p = _pipeline_patches(gw, engine)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool(
                {
                    "command": "ship CA orders ground",
                    "filter_spec": _make_resolved_spec(),
                },
                bridge=bridge,
            )

        is_error, content = _parse_tool_result(result)
        assert is_error is False

        # The preview event should contain filter_audit
        assert "filter_audit" in captured_preview_event
        audit = captured_preview_event["filter_audit"]
        assert "spec_hash" in audit
        assert "compiled_hash" in audit
        assert "schema_signature" in audit
        assert audit["schema_signature"] == "test_sig"

    @pytest.mark.asyncio
    async def test_pipeline_attaches_compiled_filter(self):
        """Pipeline attaches compiled_filter (parameterized SQL) to response."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "ship CA orders ground",
                "filter_spec": _make_resolved_spec(),
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        # compiled_filter should be the parameterized WHERE SQL
        assert "compiled_filter" in content
        assert "$1" in content["compiled_filter"]

    @pytest.mark.asyncio
    async def test_pipeline_all_rows_omits_compiled_filter(self):
        """Pipeline with all_rows=true does NOT attach compiled_filter."""
        from src.orchestrator.agent.tools.pipeline import ship_command_pipeline_tool

        gw = _mock_gateway()
        p = _pipeline_patches(gw)

        with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
            result = await ship_command_pipeline_tool({
                "command": "ship everything",
                "all_rows": True,
            })

        is_error, content = _parse_tool_result(result)
        assert is_error is False
        assert "compiled_filter" not in content
