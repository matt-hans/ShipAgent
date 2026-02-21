"""Tests for the ShipAgentClient protocol and data models."""

from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    ShipAgentClient,
    SubmitResult,
)


class TestDataModels:
    """Tests for CLI data models."""

    def test_submit_result(self):
        """SubmitResult holds job submission outcome."""
        result = SubmitResult(
            job_id="job-123",
            status="pending",
            row_count=10,
            message="File imported, 10 rows queued",
        )
        assert result.job_id == "job-123"
        assert result.row_count == 10

    def test_job_summary(self):
        """JobSummary holds lightweight job listing data."""
        summary = JobSummary(
            id="job-123",
            name="CA Orders",
            status="running",
            original_command="Ship all CA orders",
            total_rows=50,
            processed_rows=32,
            successful_rows=30,
            failed_rows=2,
            total_cost_cents=15000,
            created_at="2026-02-16T10:00:00Z",
            is_interactive=False,
        )
        assert summary.id == "job-123"
        assert summary.status == "running"
        assert summary.processed_rows == 32
        assert summary.total_cost_cents == 15000

    def test_job_detail(self):
        """JobDetail holds full job information."""
        detail = JobDetail(
            id="job-123",
            name="CA Orders",
            status="completed",
            original_command="Ship all CA orders",
            total_rows=50,
            processed_rows=50,
            successful_rows=48,
            failed_rows=2,
            total_cost_cents=62350,
            created_at="2026-02-16T10:00:00Z",
            started_at="2026-02-16T10:01:00Z",
            completed_at="2026-02-16T10:05:00Z",
            error_code=None,
            error_message=None,
            auto_confirm_violations=None,
        )
        assert detail.total_cost_cents == 62350
        assert detail.auto_confirm_violations is None

    def test_row_detail(self):
        """RowDetail holds per-row outcome data."""
        row = RowDetail(
            id="row-1",
            row_number=1,
            status="completed",
            tracking_number="1Z999AA10123456784",
            cost_cents=1250,
            error_code=None,
            error_message=None,
        )
        assert row.tracking_number == "1Z999AA10123456784"

    def test_health_status(self):
        """HealthStatus reports daemon health."""
        health = HealthStatus(
            healthy=True,
            version="3.0.0",
            uptime_seconds=3600,
            active_jobs=2,
            watchdog_active=True,
            watch_folders=["./inbox/priority"],
        )
        assert health.healthy is True
        assert health.watchdog_active is True

    def test_progress_event(self):
        """ProgressEvent holds streaming progress data."""
        event = ProgressEvent(
            job_id="job-123",
            event_type="row_completed",
            row_number=5,
            total_rows=50,
            tracking_number="1Z999AA10123456784",
            message="Row 5 completed",
        )
        assert event.event_type == "row_completed"

    def test_agent_event(self):
        """AgentEvent holds streaming agent output."""
        event = AgentEvent(
            event_type="agent_message_delta",
            content="I found 12 orders",
            tool_name=None,
            tool_input=None,
        )
        assert event.event_type == "agent_message_delta"


class TestProtocolExists:
    """Tests that ShipAgentClient protocol is properly defined."""

    def test_protocol_has_required_methods(self):
        """Protocol defines all required methods."""
        import inspect
        members = dict(inspect.getmembers(ShipAgentClient))
        required = [
            "submit_file", "list_jobs", "get_job", "get_job_rows",
            "cancel_job", "approve_job", "stream_progress",
            "send_message", "health", "cleanup",
            "create_session", "delete_session",
            "__aenter__", "__aexit__",
        ]
        for method in required:
            assert method in members, f"Missing protocol method: {method}"
