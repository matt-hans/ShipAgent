"""Unit tests for BatchExecutor.

Tests cover:
- Successful batch execution
- Fail-fast behavior on first error
- Crash recovery via pending rows
- Per-row state commits
- Write-back to source after each row
- Event emission at lifecycle points
- Audit logging for all operations
- Empty batch handling
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.models import Job, JobRow, JobStatus, RowStatus
from src.orchestrator.batch.executor import BatchExecutor
from src.orchestrator.batch.events import BatchEventObserver
from src.orchestrator.batch.models import BatchResult


class MockJobRow:
    """Mock JobRow for testing."""

    def __init__(
        self,
        row_id: str,
        job_id: str,
        row_number: int,
        status: str = "pending",
        checksum: str = "abc123",
    ) -> None:
        """Initialize mock row."""
        self.id = row_id
        self.job_id = job_id
        self.row_number = row_number
        self.row_checksum = checksum
        self.status = status
        self.tracking_number: str | None = None
        self.label_path: str | None = None
        self.cost_cents: int = 0
        self.error_code: str | None = None
        self.error_message: str | None = None


class MockJob:
    """Mock Job for testing."""

    def __init__(
        self,
        job_id: str,
        total_rows: int = 3,
        status: str = "pending",
    ) -> None:
        """Initialize mock job."""
        self.id = job_id
        self.name = "Test Job"
        self.total_rows = total_rows
        self.processed_rows = 0
        self.successful_rows = 0
        self.failed_rows = 0
        self.status = status
        self.error_code: str | None = None
        self.error_message: str | None = None


class MockJobService:
    """In-memory mock of JobService for testing."""

    def __init__(self) -> None:
        """Initialize mock job service with tracking."""
        self.jobs: dict[str, MockJob] = {}
        self.rows: dict[str, MockJobRow] = {}
        self.start_row_calls: list[str] = []
        self.complete_row_calls: list[tuple[str, str, str, int]] = []
        self.fail_row_calls: list[tuple[str, str, str]] = []
        self.update_status_calls: list[tuple[str, JobStatus]] = []
        self.set_error_calls: list[tuple[str, str, str]] = []

    def add_job(self, job: MockJob) -> None:
        """Add a job to the mock."""
        self.jobs[job.id] = job

    def add_row(self, row: MockJobRow) -> None:
        """Add a row to the mock."""
        self.rows[row.id] = row

    def get_job(self, job_id: str) -> MockJob | None:
        """Get a job by ID."""
        return self.jobs.get(job_id)

    def update_status(self, job_id: str, new_status: JobStatus) -> MockJob:
        """Update job status."""
        self.update_status_calls.append((job_id, new_status))
        job = self.jobs[job_id]
        job.status = new_status.value
        return job

    def set_error(self, job_id: str, error_code: str, error_message: str) -> MockJob:
        """Set error on job."""
        self.set_error_calls.append((job_id, error_code, error_message))
        job = self.jobs[job_id]
        job.error_code = error_code
        job.error_message = error_message
        return job

    def get_pending_rows(self, job_id: str) -> list[MockJobRow]:
        """Get pending rows for a job."""
        return [
            row for row in self.rows.values()
            if row.job_id == job_id and row.status == "pending"
        ]

    def start_row(self, row_id: str) -> MockJobRow:
        """Mark row as processing."""
        self.start_row_calls.append(row_id)
        row = self.rows[row_id]
        row.status = "processing"
        return row

    def complete_row(
        self,
        row_id: str,
        tracking_number: str,
        label_path: str,
        cost_cents: int,
    ) -> MockJobRow:
        """Mark row as completed."""
        self.complete_row_calls.append((row_id, tracking_number, label_path, cost_cents))
        row = self.rows[row_id]
        row.status = "completed"
        row.tracking_number = tracking_number
        row.label_path = label_path
        row.cost_cents = cost_cents

        # Update job counts
        job = self.jobs[row.job_id]
        job.processed_rows += 1
        job.successful_rows += 1

        return row

    def fail_row(
        self,
        row_id: str,
        error_code: str,
        error_message: str,
    ) -> MockJobRow:
        """Mark row as failed."""
        self.fail_row_calls.append((row_id, error_code, error_message))
        row = self.rows[row_id]
        row.status = "failed"
        row.error_code = error_code
        row.error_message = error_message

        # Update job counts
        job = self.jobs[row.job_id]
        job.processed_rows += 1
        job.failed_rows += 1

        return row

    def get_job_summary(self, job_id: str) -> dict[str, Any]:
        """Get job summary."""
        job = self.jobs[job_id]
        total_cost = sum(
            row.cost_cents for row in self.rows.values()
            if row.job_id == job_id and row.status == "completed"
        )
        return {
            "total_rows": job.total_rows,
            "processed_rows": job.processed_rows,
            "successful_rows": job.successful_rows,
            "failed_rows": job.failed_rows,
            "total_cost_cents": total_cost,
        }


class MockAuditService:
    """Mock AuditService for testing."""

    def __init__(self) -> None:
        """Initialize mock audit service with tracking."""
        self.state_change_calls: list[tuple[str, str, str]] = []
        self.row_event_calls: list[tuple[str, int, str, dict | None]] = []
        self.job_error_calls: list[tuple[str, str, str]] = []

    def log_state_change(self, job_id: str, old_state: str, new_state: str) -> None:
        """Log state change."""
        self.state_change_calls.append((job_id, old_state, new_state))

    def log_row_event(
        self,
        job_id: str,
        row_number: int,
        event: str,
        details: dict | None = None,
    ) -> None:
        """Log row event."""
        self.row_event_calls.append((job_id, row_number, event, details))

    def log_job_error(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """Log job error."""
        self.job_error_calls.append((job_id, error_code, error_message))


class MockObserver:
    """Mock observer for testing event emission."""

    def __init__(self) -> None:
        """Initialize mock observer with tracking."""
        self.batch_started_calls: list[tuple[str, int]] = []
        self.row_started_calls: list[tuple[str, int]] = []
        self.row_completed_calls: list[tuple[str, int, str, int]] = []
        self.row_failed_calls: list[tuple[str, int, str, str]] = []
        self.batch_completed_calls: list[tuple[str, int, int, int]] = []
        self.batch_failed_calls: list[tuple[str, str, str, int]] = []

    async def on_batch_started(self, job_id: str, total_rows: int) -> None:
        """Record batch started."""
        self.batch_started_calls.append((job_id, total_rows))

    async def on_row_started(self, job_id: str, row_number: int) -> None:
        """Record row started."""
        self.row_started_calls.append((job_id, row_number))

    async def on_row_completed(
        self,
        job_id: str,
        row_number: int,
        tracking_number: str,
        cost_cents: int,
    ) -> None:
        """Record row completed."""
        self.row_completed_calls.append((job_id, row_number, tracking_number, cost_cents))

    async def on_row_failed(
        self,
        job_id: str,
        row_number: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Record row failed."""
        self.row_failed_calls.append((job_id, row_number, error_code, error_message))

    async def on_batch_completed(
        self,
        job_id: str,
        total_rows: int,
        successful: int,
        total_cost_cents: int,
    ) -> None:
        """Record batch completed."""
        self.batch_completed_calls.append((job_id, total_rows, successful, total_cost_cents))

    async def on_batch_failed(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        processed: int,
    ) -> None:
        """Record batch failed."""
        self.batch_failed_calls.append((job_id, error_code, error_message, processed))


@pytest.fixture
def job_service() -> MockJobService:
    """Create mock job service."""
    return MockJobService()


@pytest.fixture
def audit_service() -> MockAuditService:
    """Create mock audit service."""
    return MockAuditService()


@pytest.fixture
def sample_mapping_template() -> str:
    """Simple mapping template for testing."""
    return """{
        "shipTo": {
            "name": "{{ row.customer_name }}",
            "address": "{{ row.address }}"
        },
        "shipper": {
            "name": "{{ shipper.name }}",
            "account": "{{ shipper.account }}"
        },
        "serviceCode": "03"
    }"""


@pytest.fixture
def sample_shipper_info() -> dict[str, Any]:
    """Sample shipper info for testing."""
    return {
        "name": "Test Shipper",
        "account": "ABC123",
    }


class TestBatchExecutorInit:
    """Tests for BatchExecutor initialization."""

    def test_init_with_defaults(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test BatchExecutor initializes with default Jinja environment."""
        data_mcp = AsyncMock()
        ups_mcp = AsyncMock()

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        assert executor._job_service is job_service
        assert executor._audit_service is audit_service
        assert executor._jinja_env is not None
        assert executor.events is not None

    def test_events_property_returns_emitter(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test events property returns event emitter."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        assert hasattr(executor.events, "add_observer")
        assert hasattr(executor.events, "emit_batch_started")


class TestBatchExecutorExecute:
    """Tests for BatchExecutor.execute() method."""

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test successful execution of 3 rows."""
        # Setup
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=3)
        job_service.add_job(job)

        for i in range(1, 4):
            row = MockJobRow(f"row-{i}", job_id, row_number=i)
            job_service.add_row(row)

        data_mcp = AsyncMock()
        data_mcp.side_effect = [
            # get_row calls
            {"data": {"customer_name": "Alice", "address": "123 Main St"}},
            {"data": {"customer_name": "Bob", "address": "456 Oak Ave"}},
            {"data": {"customer_name": "Carol", "address": "789 Pine Rd"}},
            # write_back calls
            {"success": True},
            {"success": True},
            {"success": True},
        ]

        ups_mcp = AsyncMock()
        ups_mcp.return_value = {
            "trackingNumber": "1Z999AA10123456784",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "12.50"},
        }

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        # Execute
        result = await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify result
        assert result.success is True
        assert result.job_id == job_id
        assert result.total_rows == 3
        assert result.successful_rows == 3
        assert result.failed_rows == 0
        assert result.error_code is None

        # Verify all rows completed
        assert len(job_service.complete_row_calls) == 3

        # Verify job status transitions
        assert (job_id, JobStatus.running) in job_service.update_status_calls
        assert (job_id, JobStatus.completed) in job_service.update_status_calls

    @pytest.mark.asyncio
    async def test_execute_fail_fast(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test fail-fast behavior stops on first error."""
        # Setup
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=3)
        job_service.add_job(job)

        for i in range(1, 4):
            row = MockJobRow(f"row-{i}", job_id, row_number=i)
            job_service.add_row(row)

        data_mcp = AsyncMock()
        data_mcp.side_effect = [
            # First row - success
            {"data": {"customer_name": "Alice", "address": "123 Main St"}},
            {"success": True},  # write_back
            # Second row - error on get_row
            {"data": {"customer_name": "Bob", "address": "456 Oak Ave"}},
            # Never reaches write_back for row 2
        ]

        ups_mcp = AsyncMock()
        ups_mcp.side_effect = [
            # First row - success
            {"trackingNumber": "1Z999", "labelPath": "/labels/1.pdf", "totalCharges": {"monetaryValue": "12.50"}},
            # Second row - UPS error
            Exception("UPS API error: Address not found"),
        ]

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        # Execute
        result = await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify result indicates failure
        assert result.success is False
        assert result.successful_rows == 1
        assert result.failed_rows == 1
        assert result.error_code is not None
        assert "UPS" in (result.error_message or "")

        # Verify only first row completed, second failed, third never processed
        assert len(job_service.complete_row_calls) == 1
        assert len(job_service.fail_row_calls) == 1
        assert len(job_service.start_row_calls) == 2  # Only started 2 rows

        # Verify job transitioned to failed
        assert (job_id, JobStatus.failed) in job_service.update_status_calls

    @pytest.mark.asyncio
    async def test_execute_crash_recovery(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test crash recovery only processes pending rows."""
        # Setup - simulate crash: 2 completed, 3 pending
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=5)
        job.processed_rows = 2
        job.successful_rows = 2
        job_service.add_job(job)

        # Rows 1-2 already completed
        for i in range(1, 3):
            row = MockJobRow(f"row-{i}", job_id, row_number=i, status="completed")
            job_service.add_row(row)

        # Rows 3-5 pending
        for i in range(3, 6):
            row = MockJobRow(f"row-{i}", job_id, row_number=i, status="pending")
            job_service.add_row(row)

        data_mcp = AsyncMock()
        # Only called for pending rows 3, 4, 5
        data_mcp.side_effect = [
            {"data": {"customer_name": f"Customer{i}", "address": f"{i} St"}}
            for i in range(3, 6)
        ] + [{"success": True}] * 3

        ups_mcp = AsyncMock()
        ups_mcp.return_value = {
            "trackingNumber": "1Z999",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "10.00"},
        }

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        # Execute
        result = await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify only pending rows were processed
        assert result.success is True
        assert len(job_service.start_row_calls) == 3  # Only rows 3, 4, 5
        assert "row-1" not in job_service.start_row_calls
        assert "row-2" not in job_service.start_row_calls

    @pytest.mark.asyncio
    async def test_execute_state_commits(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test state commits happen per-row."""
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=2)
        job_service.add_job(job)

        for i in range(1, 3):
            row = MockJobRow(f"row-{i}", job_id, row_number=i)
            job_service.add_row(row)

        data_mcp = AsyncMock()
        data_mcp.side_effect = [
            {"data": {"customer_name": "Alice", "address": "123 St"}},
            {"success": True},
            {"data": {"customer_name": "Bob", "address": "456 Ave"}},
            {"success": True},
        ]

        ups_mcp = AsyncMock()
        ups_mcp.return_value = {
            "trackingNumber": "1Z999",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "10.00"},
        }

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify start_row called before complete_row for each row
        assert job_service.start_row_calls == ["row-1", "row-2"]
        assert len(job_service.complete_row_calls) == 2

        # Verify complete_row has correct data
        for call in job_service.complete_row_calls:
            row_id, tracking, label_path, cost = call
            assert tracking == "1Z999"
            assert cost == 1000  # $10.00 in cents

    @pytest.mark.asyncio
    async def test_execute_write_back(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test write_back called for each successful row."""
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=2)
        job_service.add_job(job)

        for i in range(1, 3):
            row = MockJobRow(f"row-{i}", job_id, row_number=i)
            job_service.add_row(row)

        data_mcp = AsyncMock()
        write_back_calls: list[dict] = []

        async def track_data_mcp(tool: str, params: dict) -> dict:
            if tool == "write_back":
                write_back_calls.append(params)
                return {"success": True}
            return {"data": {"customer_name": "Test", "address": "123 St"}}

        data_mcp.side_effect = track_data_mcp

        ups_mcp = AsyncMock()
        ups_mcp.return_value = {
            "trackingNumber": "1Z999AA10123456784",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "12.50"},
        }

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify write_back called for each row
        assert len(write_back_calls) == 2
        assert write_back_calls[0]["row_number"] == 1
        assert write_back_calls[0]["tracking_number"] == "1Z999AA10123456784"
        assert write_back_calls[1]["row_number"] == 2

    @pytest.mark.asyncio
    async def test_execute_events_emitted(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test lifecycle events are emitted correctly."""
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=2)
        job_service.add_job(job)

        for i in range(1, 3):
            row = MockJobRow(f"row-{i}", job_id, row_number=i)
            job_service.add_row(row)

        data_mcp = AsyncMock()
        data_mcp.side_effect = [
            {"data": {"customer_name": "Alice", "address": "123 St"}},
            {"success": True},
            {"data": {"customer_name": "Bob", "address": "456 Ave"}},
            {"success": True},
        ]

        ups_mcp = AsyncMock()
        ups_mcp.return_value = {
            "trackingNumber": "1Z999",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "10.00"},
        }

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        # Add observer
        observer = MockObserver()
        executor.events.add_observer(observer)

        await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify events
        assert len(observer.batch_started_calls) == 1
        assert observer.batch_started_calls[0] == (job_id, 2)

        assert len(observer.row_started_calls) == 2
        assert observer.row_started_calls[0] == (job_id, 1)
        assert observer.row_started_calls[1] == (job_id, 2)

        assert len(observer.row_completed_calls) == 2

        assert len(observer.batch_completed_calls) == 1

    @pytest.mark.asyncio
    async def test_execute_events_emitted_on_failure(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test failure events are emitted correctly."""
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=2)
        job_service.add_job(job)

        for i in range(1, 3):
            row = MockJobRow(f"row-{i}", job_id, row_number=i)
            job_service.add_row(row)

        data_mcp = AsyncMock()
        data_mcp.return_value = {"data": {"customer_name": "Test", "address": "123 St"}}

        ups_mcp = AsyncMock()
        ups_mcp.side_effect = Exception("UPS API timeout")

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        observer = MockObserver()
        executor.events.add_observer(observer)

        await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify failure events
        assert len(observer.row_failed_calls) == 1
        assert len(observer.batch_failed_calls) == 1
        assert observer.batch_completed_calls == []  # No batch_completed on failure

    @pytest.mark.asyncio
    async def test_execute_audit_logging(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test audit logging for all operations."""
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=1)
        job_service.add_job(job)

        row = MockJobRow("row-1", job_id, row_number=1)
        job_service.add_row(row)

        data_mcp = AsyncMock()
        data_mcp.side_effect = [
            {"data": {"customer_name": "Alice", "address": "123 St"}},
            {"success": True},
        ]

        ups_mcp = AsyncMock()
        ups_mcp.return_value = {
            "trackingNumber": "1Z999",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "10.00"},
        }

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Verify state change logging
        assert (job_id, "pending", "running") in audit_service.state_change_calls
        assert (job_id, "running", "completed") in audit_service.state_change_calls

        # Verify row event logging
        row_events = [call[2] for call in audit_service.row_event_calls]
        assert "started" in row_events
        assert "completed" in row_events

    @pytest.mark.asyncio
    async def test_execute_empty_batch(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test execution with 0 pending rows."""
        job_id = str(uuid4())
        job = MockJob(job_id, total_rows=0)
        job_service.add_job(job)

        data_mcp = AsyncMock()
        ups_mcp = AsyncMock()

        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=data_mcp,
            ups_mcp_call=ups_mcp,
        )

        result = await executor.execute(
            job_id=job_id,
            mapping_template=sample_mapping_template,
            shipper_info=sample_shipper_info,
        )

        # Should complete successfully with 0 processed
        assert result.success is True
        assert result.processed_rows == 0
        assert result.successful_rows == 0

        # MCPs should not be called
        data_mcp.assert_not_called()
        ups_mcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_job_not_found(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
        sample_mapping_template: str,
        sample_shipper_info: dict[str, Any],
    ) -> None:
        """Test execution with non-existent job raises ValueError."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        with pytest.raises(ValueError, match="Job not found"):
            await executor.execute(
                job_id="nonexistent-job",
                mapping_template=sample_mapping_template,
                shipper_info=sample_shipper_info,
            )


class TestBatchExecutorErrorTranslation:
    """Tests for error translation in BatchExecutor."""

    def test_translate_ups_auth_error(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test UPS auth errors translate to E-5001."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        code, msg = executor._translate_error(Exception("UPS authentication failed 401"))
        assert code == "E-5001"

    def test_translate_ups_rate_limit_error(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test UPS rate limit errors translate to E-3002."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        code, msg = executor._translate_error(Exception("UPS rate limit exceeded 429"))
        assert code == "E-3002"

    def test_translate_template_error(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test template errors translate to E-4003."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        code, msg = executor._translate_error(Exception("Jinja template syntax error"))
        assert code == "E-4003"

    def test_translate_generic_error(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test generic errors translate to E-4001."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        code, msg = executor._translate_error(Exception("Unknown error occurred"))
        assert code == "E-4001"


class TestBatchExecutorExtractResult:
    """Tests for UPS response extraction."""

    def test_extract_with_tracking_number(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test extraction with trackingNumber field."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        tracking, label, cost = executor._extract_shipment_result({
            "trackingNumber": "1Z999",
            "labelPath": "/labels/test.pdf",
            "totalCharges": {"monetaryValue": "12.50"},
        })

        assert tracking == "1Z999"
        assert label == "/labels/test.pdf"
        assert cost == 1250

    def test_extract_with_tracking_numbers_array(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test extraction with trackingNumbers array."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        tracking, label, cost = executor._extract_shipment_result({
            "trackingNumbers": ["1Z999", "1Z998"],
            "labelPaths": ["/labels/1.pdf", "/labels/2.pdf"],
            "totalCharges": {"monetaryValue": "25.00"},
        })

        assert tracking == "1Z999"  # First tracking number
        assert label == "/labels/1.pdf"  # First label path
        assert cost == 2500

    def test_extract_missing_tracking_raises(
        self,
        job_service: MockJobService,
        audit_service: MockAuditService,
    ) -> None:
        """Test extraction raises ValueError when tracking missing."""
        executor = BatchExecutor(
            job_service=job_service,
            audit_service=audit_service,
            data_mcp_call=AsyncMock(),
            ups_mcp_call=AsyncMock(),
        )

        with pytest.raises(ValueError, match="missing tracking number"):
            executor._extract_shipment_result({
                "labelPath": "/labels/test.pdf",
                "totalCharges": {"monetaryValue": "12.50"},
            })
