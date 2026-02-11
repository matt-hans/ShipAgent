"""Unit tests for batch orchestrator tools.

Tests verify:
- batch_preview_tool generates preview with cost estimates via BatchEngine
- batch_execute_tool runs batch with mode support via BatchEngine
- batch_set_mode_tool changes execution mode
- batch_resume_tool handles crash recovery
- All tools return MCP-compatible responses
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import directly to avoid client.py dependency on claude_agent_sdk
from src.orchestrator.agent.tools import (
    batch_preview_tool,
    batch_execute_tool,
    batch_set_mode_tool,
    batch_resume_tool,
    reset_mode_manager,
    _get_mode_manager,
    BATCH_PREVIEW_SCHEMA,
    BATCH_EXECUTE_SCHEMA,
    BATCH_SET_MODE_SCHEMA,
    BATCH_RESUME_SCHEMA,
)
from src.orchestrator.batch import ExecutionMode


@pytest.fixture(autouse=True)
def reset_mode():
    """Reset mode manager between tests."""
    reset_mode_manager()
    yield
    reset_mode_manager()


@pytest.fixture
def mock_db_session():
    """Mock database session with sample rows."""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.all.return_value = [
        MagicMock(row_number=1, order_data='{"name": "John Doe"}'),
        MagicMock(row_number=2, order_data='{"name": "Jane Doe"}'),
    ]
    mock_session.query.return_value = mock_query
    return mock_session


# =============================================================================
# Test batch_preview_tool
# =============================================================================


class TestBatchPreviewTool:
    """Tests for batch_preview orchestrator tool."""

    @pytest.mark.asyncio
    async def test_requires_job_id(self):
        """Should error if job_id not provided."""
        result = await batch_preview_tool({})

        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "job_id is required" in text

    @pytest.mark.asyncio
    async def test_returns_mcp_format(self, mock_db_session):
        """Should return MCP-compliant response format."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.UPSService"):
                with patch("src.orchestrator.agent.tools.BatchEngine") as mock_engine_cls:
                    mock_engine = AsyncMock()
                    mock_engine.preview.return_value = {
                        "job_id": "test-123",
                        "total_rows": 2,
                        "preview_rows": [],
                        "additional_rows": 0,
                        "estimated_total_cost_cents": 2500,
                    }
                    mock_engine_cls.return_value = mock_engine

                    result = await batch_preview_tool({
                        "job_id": "test-123",
                        "shipper_info": {"Name": "Test Shipper"},
                    })

                    assert "content" in result
                    assert isinstance(result["content"], list)
                    assert result["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_returns_preview_json(self, mock_db_session):
        """Should return preview data as JSON."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.UPSService"):
                with patch("src.orchestrator.agent.tools.BatchEngine") as mock_engine_cls:
                    mock_engine = AsyncMock()
                    mock_engine.preview.return_value = {
                        "job_id": "test-123",
                        "total_rows": 2,
                        "preview_rows": [
                            {"row_number": 1, "estimated_cost_cents": 1250},
                            {"row_number": 2, "estimated_cost_cents": 1250},
                        ],
                        "additional_rows": 0,
                        "estimated_total_cost_cents": 2500,
                    }
                    mock_engine_cls.return_value = mock_engine

                    result = await batch_preview_tool({
                        "job_id": "test-123",
                    })

                    text = result["content"][0]["text"]
                    preview = json.loads(text)

                    assert preview["job_id"] == "test-123"
                    assert preview["total_rows"] == 2
                    assert len(preview["preview_rows"]) == 2
                    assert preview["additional_rows"] == 0

    def test_schema_has_required_fields(self):
        """Schema should define required fields."""
        assert "job_id" in BATCH_PREVIEW_SCHEMA
        assert "shipper_info" in BATCH_PREVIEW_SCHEMA
        assert "service_code" in BATCH_PREVIEW_SCHEMA


# =============================================================================
# Test batch_execute_tool
# =============================================================================


class TestBatchExecuteTool:
    """Tests for batch_execute orchestrator tool."""

    @pytest.mark.asyncio
    async def test_requires_job_id(self):
        """Should error if job_id not provided."""
        result = await batch_execute_tool({})

        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "job_id is required" in text

    @pytest.mark.asyncio
    async def test_confirm_mode_requires_approval(self):
        """Should error if CONFIRM mode and approved=False."""
        # Default mode is CONFIRM
        result = await batch_execute_tool({
            "job_id": "test-job-123",
            "approved": False,
        })

        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Preview approval required" in text

    @pytest.mark.asyncio
    async def test_confirm_mode_with_approval(self, mock_db_session):
        """Should execute if CONFIRM mode and approved=True."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.UPSService"):
                with patch("src.orchestrator.agent.tools.BatchEngine") as mock_engine_cls:
                    mock_engine = AsyncMock()
                    mock_engine.execute.return_value = {
                        "success": True,
                        "job_id": "test-job-123",
                        "total_rows": 2,
                        "successful_rows": 2,
                        "failed_rows": 0,
                        "total_cost_cents": 2500,
                    }
                    mock_engine_cls.return_value = mock_engine

                    result = await batch_execute_tool({
                        "job_id": "test-job-123",
                        "approved": True,
                    })

                    # Should not be an error
                    assert result.get("isError") is None or result.get("isError") is False
                    text = result["content"][0]["text"]
                    parsed = json.loads(text)
                    assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_auto_mode_no_approval_needed(self, mock_db_session):
        """Should execute in AUTO mode without approval."""
        # Set mode to AUTO
        mode_manager = _get_mode_manager()
        mode_manager.set_mode(ExecutionMode.AUTO)

        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.UPSService"):
                with patch("src.orchestrator.agent.tools.BatchEngine") as mock_engine_cls:
                    mock_engine = AsyncMock()
                    mock_engine.execute.return_value = {
                        "success": True,
                        "job_id": "test-job-123",
                        "total_rows": 2,
                        "successful_rows": 2,
                        "failed_rows": 0,
                        "total_cost_cents": 2500,
                    }
                    mock_engine_cls.return_value = mock_engine

                    result = await batch_execute_tool({
                        "job_id": "test-job-123",
                        "approved": False,
                    })

                    # Should succeed without approval in AUTO mode
                    assert result.get("isError") is None or result.get("isError") is False

    @pytest.mark.asyncio
    async def test_locks_mode_during_execution(self, mock_db_session):
        """Mode should be locked during execution."""
        mode_manager = _get_mode_manager()
        mode_manager.set_mode(ExecutionMode.AUTO)

        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.UPSService"):
                with patch("src.orchestrator.agent.tools.BatchEngine") as mock_engine_cls:
                    async def execute_with_check(*args, **kwargs):
                        # Mode should be locked here
                        assert mode_manager.is_locked() is True
                        # Try to change mode - should fail
                        with pytest.raises(ValueError):
                            mode_manager.set_mode(ExecutionMode.CONFIRM)
                        return {
                            "success": True,
                            "job_id": "test-job-123",
                            "total_rows": 1,
                            "successful_rows": 1,
                            "failed_rows": 0,
                            "total_cost_cents": 1000,
                        }

                    mock_engine = AsyncMock()
                    mock_engine.execute.side_effect = execute_with_check
                    mock_engine_cls.return_value = mock_engine

                    await batch_execute_tool({
                        "job_id": "test-job-123",
                    })

                    # After execution, mode should be unlocked
                    assert mode_manager.is_locked() is False

    def test_schema_has_required_fields(self):
        """Schema should define required fields."""
        assert "job_id" in BATCH_EXECUTE_SCHEMA
        assert "shipper_info" in BATCH_EXECUTE_SCHEMA
        assert "approved" in BATCH_EXECUTE_SCHEMA
        assert "service_code" in BATCH_EXECUTE_SCHEMA


# =============================================================================
# Test batch_set_mode_tool
# =============================================================================


class TestBatchSetModeTool:
    """Tests for batch_set_mode orchestrator tool."""

    @pytest.mark.asyncio
    async def test_set_mode_confirm(self):
        """Should set mode to CONFIRM."""
        result = await batch_set_mode_tool({"mode": "confirm"})

        text = result["content"][0]["text"]
        parsed = json.loads(text)

        assert parsed["mode"] == "confirm"
        assert _get_mode_manager().mode == ExecutionMode.CONFIRM

    @pytest.mark.asyncio
    async def test_set_mode_auto(self):
        """Should set mode to AUTO."""
        result = await batch_set_mode_tool({"mode": "auto"})

        text = result["content"][0]["text"]
        parsed = json.loads(text)

        assert parsed["mode"] == "auto"
        assert _get_mode_manager().mode == ExecutionMode.AUTO

    @pytest.mark.asyncio
    async def test_invalid_mode(self):
        """Should error on invalid mode."""
        result = await batch_set_mode_tool({"mode": "invalid"})

        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Invalid mode" in text

    @pytest.mark.asyncio
    async def test_mode_case_insensitive(self):
        """Mode should be case-insensitive."""
        result = await batch_set_mode_tool({"mode": "AUTO"})

        assert result.get("isError") is None or result.get("isError") is False
        assert _get_mode_manager().mode == ExecutionMode.AUTO

        result = await batch_set_mode_tool({"mode": "CONFIRM"})
        assert _get_mode_manager().mode == ExecutionMode.CONFIRM

    @pytest.mark.asyncio
    async def test_locked_mode_error(self):
        """Should error if mode is locked."""
        mode_manager = _get_mode_manager()
        mode_manager.lock()

        result = await batch_set_mode_tool({"mode": "auto"})

        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Cannot change execution mode" in text

    def test_schema_has_mode(self):
        """Schema should have mode field."""
        assert "mode" in BATCH_SET_MODE_SCHEMA


# =============================================================================
# Test batch_resume_tool
# =============================================================================


class TestBatchResumeTool:
    """Tests for batch_resume orchestrator tool."""

    @pytest.mark.asyncio
    async def test_no_interrupted_jobs(self):
        """Should report no interrupted jobs when none exist."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock query to return no interrupted jobs
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result

            with patch("src.orchestrator.agent.tools.JobService"):
                result = await batch_resume_tool({})

                text = result["content"][0]["text"]
                parsed = json.loads(text)

                assert parsed["interrupted_jobs"] == []
                assert "No interrupted jobs" in parsed["message"]

    @pytest.mark.asyncio
    async def test_shows_interrupted_jobs(self):
        """Should show recovery prompt for interrupted jobs."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Mock an interrupted job
            mock_job = MagicMock()
            mock_job.id = "job-123"
            mock_job.name = "Test Job"
            mock_job.status = "running"

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_job]
            mock_session.execute.return_value = mock_result

            with patch("src.orchestrator.agent.tools.JobService") as mock_job_service:
                mock_job_service_instance = MagicMock()
                mock_job_service_instance.get_job_summary.return_value = {
                    "successful_rows": 47,
                    "total_rows": 200,
                }
                mock_job_service.return_value = mock_job_service_instance

                result = await batch_resume_tool({})

                text = result["content"][0]["text"]
                parsed = json.loads(text)

                assert len(parsed["interrupted_jobs"]) == 1
                assert parsed["interrupted_jobs"][0]["job_id"] == "job-123"
                assert "resume" in parsed["options"]
                assert "restart" in parsed["options"]
                assert "cancel" in parsed["options"]

    @pytest.mark.asyncio
    async def test_resume_choice(self):
        """Should handle resume choice."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.JobService") as mock_job_service:
                mock_job = MagicMock()
                mock_job.name = "Test Job"

                mock_job_service_instance = MagicMock()
                mock_job_service_instance.get_job.return_value = mock_job
                mock_job_service_instance.get_pending_rows.return_value = [1, 2, 3]  # 3 pending
                mock_job_service.return_value = mock_job_service_instance

                result = await batch_resume_tool({
                    "choice": "resume",
                    "job_id": "job-123",
                })

                text = result["content"][0]["text"]
                parsed = json.loads(text)

                assert parsed["action"] == "resume"
                assert parsed["pending_rows"] == 3

    @pytest.mark.asyncio
    async def test_restart_choice(self):
        """Should handle restart choice."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.JobService") as mock_job_service:
                mock_job = MagicMock()
                mock_job.name = "Test Job"

                mock_job_service_instance = MagicMock()
                mock_job_service_instance.get_job.return_value = mock_job
                mock_job_service.return_value = mock_job_service_instance

                result = await batch_resume_tool({
                    "choice": "restart",
                    "job_id": "job-123",
                })

                text = result["content"][0]["text"]
                parsed = json.loads(text)

                assert parsed["action"] == "restart"
                mock_job_service_instance.reset_job_for_restart.assert_called_once_with("job-123")

    @pytest.mark.asyncio
    async def test_cancel_choice(self):
        """Should handle cancel choice."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.JobService") as mock_job_service:
                mock_job = MagicMock()
                mock_job.name = "Test Job"

                mock_job_service_instance = MagicMock()
                mock_job_service_instance.get_job.return_value = mock_job
                mock_job_service.return_value = mock_job_service_instance

                result = await batch_resume_tool({
                    "choice": "cancel",
                    "job_id": "job-123",
                })

                text = result["content"][0]["text"]
                parsed = json.loads(text)

                assert parsed["action"] == "cancel"
                mock_job_service_instance.update_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_choice_requires_job_id(self):
        """Should error if choice provided without job_id."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.JobService"):
                result = await batch_resume_tool({
                    "choice": "resume",
                    # No job_id
                })

                assert result.get("isError") is True
                text = result["content"][0]["text"]
                assert "job_id required" in text

    @pytest.mark.asyncio
    async def test_invalid_choice(self):
        """Should error on invalid choice."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.orchestrator.agent.tools.JobService") as mock_job_service:
                mock_job = MagicMock()
                mock_job_service_instance = MagicMock()
                mock_job_service_instance.get_job.return_value = mock_job
                mock_job_service.return_value = mock_job_service_instance

                result = await batch_resume_tool({
                    "choice": "invalid",
                    "job_id": "job-123",
                })

                assert result.get("isError") is True
                text = result["content"][0]["text"]
                assert "Invalid choice" in text

    def test_schema_has_fields(self):
        """Schema should have choice and job_id fields."""
        assert "choice" in BATCH_RESUME_SCHEMA
        assert "job_id" in BATCH_RESUME_SCHEMA


# =============================================================================
# Test MCP Response Format
# =============================================================================


class TestMCPResponseFormat:
    """Tests verifying all batch tools follow MCP response format."""

    @pytest.mark.asyncio
    async def test_preview_has_content_array(self):
        """batch_preview should return content array."""
        with patch("src.orchestrator.agent.tools.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            mock_query.all.return_value = []
            mock_session.query.return_value = mock_query

            with patch("src.orchestrator.agent.tools.UPSService"):
                with patch("src.orchestrator.agent.tools.BatchEngine") as mock_engine_cls:
                    mock_engine = AsyncMock()
                    mock_engine.preview.return_value = {"job_id": "test-123"}
                    mock_engine_cls.return_value = mock_engine

                    result = await batch_preview_tool({
                        "job_id": "test-123",
                    })

                    assert "content" in result
                    assert isinstance(result["content"], list)
                    assert result["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_set_mode_has_content_array(self):
        """batch_set_mode should return content array."""
        result = await batch_set_mode_tool({"mode": "auto"})

        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_error_response_has_is_error(self):
        """Error responses should have isError=True."""
        result = await batch_set_mode_tool({"mode": "invalid"})

        assert result.get("isError") is True
        assert "content" in result
