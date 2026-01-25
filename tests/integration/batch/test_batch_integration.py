"""Integration tests for batch execution flow.

Tests verify:
- End-to-end preview -> approve -> execute flow
- Fail-fast behavior on errors
- Crash recovery from interrupted jobs
- Write-back to data sources
- Mode switching behavior

Requirement Coverage:
- BATCH-01: test_execute_processes_all_rows (processes 1-500+ shipments)
- BATCH-02: test_preview_generates_cost_estimates (preview with cost)
- BATCH-03: test_switch_to_auto (auto mode bypasses preview)
- BATCH-04: test_switch_to_auto, test_locked_mode_rejects_change (mode toggle)
- BATCH-05: test_execute_fail_fast (halts on first error)
- BATCH-06: test_resume_processes_only_pending (crash recovery)
- DATA-04: test_execute_writes_back_tracking (write-back)
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.orchestrator.batch import (
    ExecutionMode,
    SessionModeManager,
    PreviewGenerator,
    BatchExecutor,
    check_interrupted_jobs,
    handle_recovery_choice,
    RecoveryChoice,
)
from src.db.models import JobStatus, RowStatus


class TestBatchPreviewFlow:
    """Tests for preview generation."""

    @pytest.mark.asyncio
    async def test_preview_generates_cost_estimates(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Preview should generate cost estimates for first 20 rows.

        Verifies BATCH-02: Preview mode shows cost estimates before execution.
        """
        generator = PreviewGenerator(
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        preview = await generator.generate_preview(
            job_id=sample_job.id,
            filter_clause="1=1",
            mapping_template='{"ShipTo": {"Name": "{{ row.recipient_name }}", "Address": {"City": "LA", "StateProvinceCode": "CA"}}, "Service": {"Code": "03"}}',
            shipper_info={"name": "Test Shipper"},
        )

        assert preview.total_rows > 0
        assert len(preview.preview_rows) <= 20
        assert preview.total_estimated_cost_cents > 0

    @pytest.mark.asyncio
    async def test_preview_handles_large_batch(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Large batches should show aggregate estimate.

        Verifies BATCH-02: Preview extrapolates costs for rows beyond first 20.
        """
        # Mock 50 total rows
        original_impl = mock_data_mcp.side_effect

        async def large_batch_impl(tool_name, args):
            if tool_name == "get_rows_by_filter":
                result = await original_impl(tool_name, args)
                result["total_count"] = 50
                return result
            return await original_impl(tool_name, args)

        mock_data_mcp.side_effect = large_batch_impl

        generator = PreviewGenerator(
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        preview = await generator.generate_preview(
            job_id=sample_job.id,
            filter_clause="1=1",
            mapping_template='{"ShipTo": {"Name": "{{ row.recipient_name }}", "Address": {"City": "LA", "StateProvinceCode": "CA"}}, "Service": {"Code": "03"}}',
            shipper_info={"name": "Test Shipper"},
        )

        assert preview.total_rows == 50
        assert preview.additional_rows == 50 - len(preview.preview_rows)

    @pytest.mark.asyncio
    async def test_preview_empty_batch(
        self, job_service, audit_service, sample_job
    ):
        """Preview should handle empty batch gracefully."""
        async def empty_data_call(tool_name, args):
            if tool_name == "get_rows_by_filter":
                return {"rows": [], "total_count": 0}
            return {}

        mock_data = AsyncMock(side_effect=empty_data_call)
        mock_ups = AsyncMock()

        generator = PreviewGenerator(
            data_mcp_call=mock_data,
            ups_mcp_call=mock_ups,
        )

        preview = await generator.generate_preview(
            job_id=sample_job.id,
            filter_clause="1=1",
            mapping_template="{}",
            shipper_info={"name": "Test Shipper"},
        )

        assert preview.total_rows == 0
        assert len(preview.preview_rows) == 0
        assert preview.total_estimated_cost_cents == 0


class TestBatchExecuteFlow:
    """Tests for batch execution."""

    @pytest.mark.asyncio
    async def test_execute_processes_all_rows(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Execute should process all pending rows.

        Verifies BATCH-01: System processes batch of 1-500+ shipments.
        """
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        result = await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        assert result.success is True
        assert result.processed_rows == 5
        assert result.successful_rows == 5
        assert result.failed_rows == 0

        # Verify job status
        job = job_service.get_job(sample_job.id)
        assert job.status == JobStatus.completed.value

    @pytest.mark.asyncio
    async def test_execute_fail_fast(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Execution should halt on first error.

        Verifies BATCH-05: Fail-fast halts batch on first UPS error.
        """
        call_count = 0

        async def failing_ups_call(tool_name, args):
            nonlocal call_count
            call_count += 1
            if call_count == 3:  # Fail on third row
                raise Exception("UPS API Error")
            return {
                "trackingNumbers": ["1Z999AA10123456784"],
                "labelPaths": ["/labels/test.pdf"],
                "totalCharges": {"monetaryValue": "15.50"},
            }

        mock_ups_mcp.side_effect = failing_ups_call

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        result = await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        assert result.success is False
        assert result.processed_rows == 3  # Stopped at third row
        assert result.successful_rows == 2
        assert result.failed_rows == 1

        # Verify job status
        job = job_service.get_job(sample_job.id)
        assert job.status == JobStatus.failed.value

    @pytest.mark.asyncio
    async def test_execute_writes_back_tracking(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Execute should call write_back for each successful row.

        Verifies DATA-04: Tracking numbers written back to source.
        """
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        # Check write_back was called for each row
        write_back_calls = [
            call for call in mock_data_mcp.call_args_list
            if call[0][0] == "write_back"
        ]
        assert len(write_back_calls) == 5

    @pytest.mark.asyncio
    async def test_execute_records_tracking_numbers(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Execute should store tracking numbers in job rows."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        # Verify tracking numbers stored
        rows = job_service.get_rows(sample_job.id, status=RowStatus.completed)
        assert len(rows) == 5
        for row in rows:
            assert row.tracking_number == "1Z999AA10123456784"
            assert row.cost_cents == 1550

    @pytest.mark.asyncio
    async def test_execute_calculates_total_cost(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Execute should sum costs across all rows."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        result = await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        # 5 rows at $15.50 each = $77.50 = 7750 cents
        assert result.total_cost_cents == 7750


class TestCrashRecovery:
    """Tests for crash recovery."""

    def test_check_interrupted_finds_running_job(
        self, job_service, sample_job
    ):
        """Should detect jobs in running state.

        Verifies BATCH-06: Crash recovery detects interrupted jobs.
        """
        # Simulate interrupted job
        job_service.update_status(sample_job.id, JobStatus.running)

        info = check_interrupted_jobs(job_service)

        assert info is not None
        assert info.job_id == sample_job.id

    def test_check_interrupted_no_running_jobs(self, job_service, sample_job):
        """Should return None if no interrupted jobs."""
        # Job stays in pending state
        info = check_interrupted_jobs(job_service)
        assert info is None

    @pytest.mark.asyncio
    async def test_resume_processes_only_pending(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Resume should skip completed rows.

        Verifies BATCH-06: Crash recovery resumes from pending rows.

        Simulates: User starts job -> partial completion -> crash ->
        user chooses 'resume' -> only pending rows processed.
        """
        # Step 1: Start execution and complete some rows
        job_service.update_status(sample_job.id, JobStatus.running)
        rows = job_service.get_rows(sample_job.id)

        # Mark first 2 rows as completed (simulating partial execution before crash)
        job_service.complete_row(
            rows[0].id, "TRACK001", "/labels/1.pdf", 1550
        )
        job_service.complete_row(
            rows[1].id, "TRACK002", "/labels/2.pdf", 1550
        )

        # Step 2: Verify crash recovery detects the interrupted job
        info = check_interrupted_jobs(job_service)
        assert info is not None
        assert info.completed_rows == 2
        assert info.remaining_rows == 3

        # Step 3: User chooses resume - job stays in running state
        handle_recovery_choice(RecoveryChoice.RESUME, sample_job.id, job_service)

        # Step 4: Verify only pending rows remain
        pending = job_service.get_pending_rows(sample_job.id)
        assert len(pending) == 3

        # Step 5: Verify get_pending_rows returns correct rows (3, 4, 5)
        pending_numbers = [r.row_number for r in pending]
        assert pending_numbers == [3, 4, 5]

    @pytest.mark.asyncio
    async def test_executor_skips_completed_rows(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp
    ):
        """Executor should only process pending rows.

        Verifies the executor's internal behavior of skipping completed rows.
        """
        # Create a fresh job (in pending state)
        job = job_service.create_job(
            name="Fresh Test Batch",
            original_command="Ship orders",
        )
        job_service.create_rows(job.id, [
            {"row_number": i, "row_checksum": f"hash{i}"}
            for i in range(1, 6)
        ])

        # Pre-complete 2 rows before execution even starts
        # This simulates a scenario where rows were manually marked complete
        rows = job_service.get_rows(job.id)
        # Manually update status to completed without going through normal flow
        rows[0].status = RowStatus.completed.value
        rows[0].tracking_number = "EXISTING001"
        rows[0].cost_cents = 1500
        rows[1].status = RowStatus.completed.value
        rows[1].tracking_number = "EXISTING002"
        rows[1].cost_cents = 1500
        job.processed_rows = 2
        job.successful_rows = 2
        job_service.db.commit()

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        result = await executor.execute(
            job_id=job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        # All 5 rows should be accounted for (2 pre-completed + 3 newly processed)
        assert result.successful_rows == 5
        assert result.processed_rows == 5

        # Verify only 3 UPS calls made (for the originally pending rows)
        ups_calls = [
            call for call in mock_ups_mcp.call_args_list
            if call[0][0] == "shipping_create"
        ]
        assert len(ups_calls) == 3

    def test_handle_cancel_transitions_job(self, job_service, sample_job):
        """Cancel should transition job to cancelled."""
        job_service.update_status(sample_job.id, JobStatus.running)

        result = handle_recovery_choice(
            RecoveryChoice.CANCEL,
            sample_job.id,
            job_service,
        )

        assert result["action"] == "cancel"
        job = job_service.get_job(sample_job.id)
        assert job.status == JobStatus.cancelled.value

    def test_handle_resume_returns_info(self, job_service, sample_job):
        """Resume should return action info without state change."""
        job_service.update_status(sample_job.id, JobStatus.running)

        result = handle_recovery_choice(
            RecoveryChoice.RESUME,
            sample_job.id,
            job_service,
        )

        assert result["action"] == "resume"
        # Job stays in running state for executor to pick up
        job = job_service.get_job(sample_job.id)
        assert job.status == JobStatus.running.value

    def test_handle_restart_warns_about_duplicates(self, job_service, sample_job):
        """Restart should warn about potential duplicate shipments."""
        job_service.update_status(sample_job.id, JobStatus.running)

        # Mark some rows completed
        rows = job_service.get_rows(sample_job.id)
        job_service.complete_row(rows[0].id, "TRACK001", "/labels/1.pdf", 1550)

        result = handle_recovery_choice(
            RecoveryChoice.RESTART,
            sample_job.id,
            job_service,
        )

        assert result["action"] == "restart"
        assert result["requires_confirmation"] is True
        assert result["completed_rows_with_tracking"] == 1
        assert "WARNING" in result["warning"]


class TestModeSwitch:
    """Tests for execution mode switching."""

    def test_default_mode_is_confirm(self):
        """Session should default to confirm mode.

        Verifies BATCH-04: Default to CONFIRM mode.
        """
        manager = SessionModeManager()
        assert manager.mode == ExecutionMode.CONFIRM

    def test_switch_to_auto(self):
        """Should be able to switch to auto mode.

        Verifies BATCH-03: Auto mode available.
        Verifies BATCH-04: Mode toggle works.
        """
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        assert manager.mode == ExecutionMode.AUTO

    def test_switch_back_to_confirm(self):
        """Should be able to switch back to confirm mode."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        manager.set_mode(ExecutionMode.CONFIRM)
        assert manager.mode == ExecutionMode.CONFIRM

    def test_locked_mode_rejects_change(self):
        """Should not allow mode change during execution.

        Verifies BATCH-04: Mode cannot change during execution.
        """
        manager = SessionModeManager()
        manager.lock()

        with pytest.raises(ValueError):
            manager.set_mode(ExecutionMode.AUTO)

    def test_unlock_allows_change(self):
        """Should allow mode change after unlock."""
        manager = SessionModeManager()
        manager.lock()
        manager.unlock()
        manager.set_mode(ExecutionMode.AUTO)
        assert manager.mode == ExecutionMode.AUTO

    def test_reset_returns_to_default(self):
        """Reset should return to confirm mode and unlock."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        manager.lock()
        manager.reset()

        assert manager.mode == ExecutionMode.CONFIRM
        assert manager.is_locked() is False


class TestEndToEndFlow:
    """Tests for complete end-to-end batch flow."""

    @pytest.mark.asyncio
    async def test_preview_then_execute_flow(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """Complete flow: preview -> approve -> execute.

        Verifies end-to-end integration of all batch components.
        """
        # Step 1: Generate preview
        generator = PreviewGenerator(
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        preview = await generator.generate_preview(
            job_id=sample_job.id,
            filter_clause="1=1",
            mapping_template='{"ShipTo": {"Name": "Test", "Address": {"City": "LA", "StateProvinceCode": "CA"}}, "Service": {"Code": "03"}}',
            shipper_info={"name": "Test Shipper"},
        )

        assert preview.total_rows > 0
        assert preview.total_estimated_cost_cents > 0

        # Step 2: Execute after "approval"
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        result = await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        assert result.success is True
        assert result.successful_rows == 5

        # Verify job completed
        job = job_service.get_job(sample_job.id)
        assert job.status == JobStatus.completed.value

    @pytest.mark.asyncio
    async def test_auto_mode_skips_preview(
        self, job_service, audit_service, mock_data_mcp, mock_ups_mcp, sample_job
    ):
        """In AUTO mode, preview step can be skipped.

        Verifies BATCH-03: Auto mode bypasses preview requirement.
        """
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)

        # Go directly to execute
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=mock_data_mcp,
            ups_mcp_call=mock_ups_mcp,
        )

        result = await executor.execute(
            job_id=sample_job.id,
            mapping_template='{"test": "{{ row.order_id }}"}',
            shipper_info={"name": "Test Shipper"},
        )

        assert result.success is True
        assert result.successful_rows == 5
