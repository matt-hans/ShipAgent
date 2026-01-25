"""Unit tests for crash recovery functionality.

Tests cover:
- Detection of interrupted jobs (running state)
- Recovery prompt generation
- Handling of recovery choices (resume, restart, cancel)
- Duplicate shipment warnings
"""

from unittest.mock import MagicMock

import pytest

from src.db.models import JobStatus, RowStatus
from src.orchestrator.batch.models import InterruptedJobInfo
from src.orchestrator.batch.recovery import (
    RecoveryChoice,
    check_interrupted_jobs,
    get_recovery_prompt,
    handle_recovery_choice,
)


class MockJobRow:
    """Mock JobRow for testing."""

    def __init__(
        self,
        row_id: str,
        job_id: str,
        row_number: int,
        status: str = "pending",
        tracking_number: str | None = None,
    ) -> None:
        """Initialize mock row."""
        self.id = row_id
        self.job_id = job_id
        self.row_number = row_number
        self.status = status
        self.tracking_number = tracking_number


class MockJob:
    """Mock Job for testing."""

    def __init__(
        self,
        job_id: str,
        name: str = "Test Batch",
        status: str = "running",
        total_rows: int = 100,
        processed_rows: int = 47,
        successful_rows: int = 47,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Initialize mock job."""
        self.id = job_id
        self.name = name
        self.status = status
        self.total_rows = total_rows
        self.processed_rows = processed_rows
        self.successful_rows = successful_rows
        self.error_code = error_code
        self.error_message = error_message


class MockJobService:
    """Mock JobService for testing recovery functions."""

    def __init__(self) -> None:
        """Initialize mock job service."""
        self.jobs: list[MockJob] = []
        self.rows: dict[str, list[MockJobRow]] = {}
        self.update_status_calls: list[tuple[str, JobStatus]] = []

    def add_job(self, job: MockJob, rows: list[MockJobRow] | None = None) -> None:
        """Add a job with optional rows."""
        self.jobs.append(job)
        if rows:
            self.rows[job.id] = rows

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50
    ) -> list[MockJob]:
        """List jobs optionally filtered by status."""
        result = self.jobs
        if status is not None:
            result = [j for j in result if j.status == status.value]
        return result[:limit]

    def get_job(self, job_id: str) -> MockJob | None:
        """Get a job by ID."""
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def get_rows(
        self, job_id: str, status: RowStatus | None = None
    ) -> list[MockJobRow]:
        """Get rows for a job, optionally filtered by status."""
        rows = self.rows.get(job_id, [])
        if status is not None:
            rows = [r for r in rows if r.status == status.value]
        return sorted(rows, key=lambda r: r.row_number)

    def update_status(self, job_id: str, new_status: JobStatus) -> MockJob:
        """Update job status and track call."""
        self.update_status_calls.append((job_id, new_status))
        job = self.get_job(job_id)
        if job:
            job.status = new_status.value
            return job
        raise ValueError(f"Job {job_id} not found")


class TestCheckInterruptedJobs:
    """Tests for check_interrupted_jobs function."""

    def test_no_interrupted_jobs(self) -> None:
        """Test returns None when no jobs in running state."""
        job_service = MockJobService()
        # Add jobs in other states
        job_service.add_job(MockJob("job-1", status="completed"))
        job_service.add_job(MockJob("job-2", status="pending"))

        result = check_interrupted_jobs(job_service)

        assert result is None

    def test_finds_interrupted_job(self) -> None:
        """Test finds job in running state with correct progress."""
        job_service = MockJobService()
        job = MockJob(
            "job-123",
            name="California Orders",
            status="running",
            total_rows=200,
            processed_rows=47,
            successful_rows=47,
        )
        completed_rows = [
            MockJobRow("row-46", "job-123", 46, "completed", "1Z111"),
            MockJobRow("row-47", "job-123", 47, "completed", "1Z222"),
        ]
        job_service.add_job(job, completed_rows)

        result = check_interrupted_jobs(job_service)

        assert result is not None
        assert result.job_id == "job-123"
        assert result.job_name == "California Orders"
        assert result.completed_rows == 47
        assert result.total_rows == 200
        assert result.remaining_rows == 153  # 200 - 47
        assert result.last_row_number == 47
        assert result.last_tracking_number == "1Z222"

    def test_finds_interrupted_job_with_error(self) -> None:
        """Test includes error info when job crashed with error."""
        job_service = MockJobService()
        job = MockJob(
            "job-err",
            name="Failed Batch",
            status="running",
            total_rows=100,
            processed_rows=48,
            successful_rows=47,
            error_code="E-3001",
            error_message="UPS API timeout",
        )
        job_service.add_job(job)

        result = check_interrupted_jobs(job_service)

        assert result is not None
        assert result.error_code == "E-3001"
        assert result.error_message == "UPS API timeout"

    def test_no_completed_rows(self) -> None:
        """Test handles job with no completed rows."""
        job_service = MockJobService()
        job = MockJob(
            "job-new",
            name="New Batch",
            status="running",
            total_rows=50,
            processed_rows=0,
            successful_rows=0,
        )
        job_service.add_job(job, [])

        result = check_interrupted_jobs(job_service)

        assert result is not None
        assert result.completed_rows == 0
        assert result.last_row_number is None
        assert result.last_tracking_number is None


class TestGetRecoveryPrompt:
    """Tests for get_recovery_prompt function."""

    def test_basic_prompt(self) -> None:
        """Test generates readable prompt with progress."""
        info = InterruptedJobInfo(
            job_id="job-123",
            job_name="California Orders",
            completed_rows=47,
            total_rows=200,
            remaining_rows=153,
            last_row_number=47,
            last_tracking_number="1Z999AA10123456784",
        )

        prompt = get_recovery_prompt(info)

        assert "California Orders" in prompt
        assert "47/200" in prompt
        assert "153 rows" in prompt
        assert "Row 47" in prompt
        assert "1Z999AA10123456784" in prompt
        assert "[resume]" in prompt
        assert "[restart]" in prompt
        assert "[cancel]" in prompt

    def test_prompt_with_error(self) -> None:
        """Test includes error info when present."""
        info = InterruptedJobInfo(
            job_id="job-123",
            job_name="Failed Batch",
            completed_rows=47,
            total_rows=200,
            remaining_rows=153,
            error_code="E-3001",
            error_message="UPS API timeout",
        )

        prompt = get_recovery_prompt(info)

        assert "E-3001" in prompt
        assert "UPS API timeout" in prompt
        assert "retry from the failed row" in prompt

    def test_prompt_no_completed_rows(self) -> None:
        """Test prompt without last completed row info."""
        info = InterruptedJobInfo(
            job_id="job-123",
            job_name="New Batch",
            completed_rows=0,
            total_rows=50,
            remaining_rows=50,
        )

        prompt = get_recovery_prompt(info)

        assert "0/50" in prompt
        assert "50 rows" in prompt
        # Should not include "Last completed" when none
        assert "Last completed:" not in prompt


class TestHandleRecoveryChoice:
    """Tests for handle_recovery_choice function."""

    def test_handle_resume(self) -> None:
        """Test resume returns action without state changes."""
        job_service = MockJobService()
        job = MockJob("job-123", status="running")
        job_service.add_job(job)

        result = handle_recovery_choice(
            RecoveryChoice.RESUME, "job-123", job_service
        )

        assert result["action"] == "resume"
        assert result["job_id"] == "job-123"
        assert "Resuming" in result["message"]
        # No status update should occur
        assert len(job_service.update_status_calls) == 0

    def test_handle_restart_warning(self) -> None:
        """Test restart returns warning about duplicates."""
        job_service = MockJobService()
        job = MockJob("job-123", status="running", total_rows=100)
        completed_rows = [
            MockJobRow(f"row-{i}", "job-123", i, "completed", f"1Z{i:03d}")
            for i in range(1, 48)  # 47 completed
        ]
        job_service.add_job(job, completed_rows)

        result = handle_recovery_choice(
            RecoveryChoice.RESTART, "job-123", job_service
        )

        assert result["action"] == "restart"
        assert result["job_id"] == "job-123"
        assert "WARNING" in result["warning"]
        assert "47" in result["warning"]
        assert "duplicate" in result["warning"].lower()
        assert result["requires_confirmation"] is True
        assert result["completed_rows_with_tracking"] == 47

    def test_handle_restart_no_completed(self) -> None:
        """Test restart with no completed rows."""
        job_service = MockJobService()
        job = MockJob("job-123", status="running")
        job_service.add_job(job, [])

        result = handle_recovery_choice(
            RecoveryChoice.RESTART, "job-123", job_service
        )

        assert result["completed_rows_with_tracking"] == 0

    def test_handle_cancel(self) -> None:
        """Test cancel transitions job to cancelled state."""
        job_service = MockJobService()
        job = MockJob("job-123", status="running")
        job_service.add_job(job)

        result = handle_recovery_choice(
            RecoveryChoice.CANCEL, "job-123", job_service
        )

        assert result["action"] == "cancel"
        assert result["job_id"] == "job-123"
        assert "cancelled" in result["message"].lower()
        # Verify status was updated
        assert (("job-123", JobStatus.cancelled) in job_service.update_status_calls)

    def test_handle_restart_job_not_found(self) -> None:
        """Test restart raises ValueError when job not found."""
        job_service = MockJobService()

        with pytest.raises(ValueError, match="not found"):
            handle_recovery_choice(
                RecoveryChoice.RESTART, "nonexistent", job_service
            )


class TestRecoveryChoiceEnum:
    """Tests for RecoveryChoice enum."""

    def test_enum_values(self) -> None:
        """Test enum has expected values."""
        assert RecoveryChoice.RESUME.value == "resume"
        assert RecoveryChoice.RESTART.value == "restart"
        assert RecoveryChoice.CANCEL.value == "cancel"

    def test_enum_string_inheritance(self) -> None:
        """Test enum inherits from str for JSON serialization."""
        assert isinstance(RecoveryChoice.RESUME, str)
        assert RecoveryChoice.RESUME == "resume"
