"""Job service implementing job lifecycle management with state machine validation.

This module provides the core business logic layer for job operations,
enforcing valid state transitions and supporting crash recovery through
per-row status tracking.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, JobStatus, RowStatus


class InvalidStateTransition(Exception):
    """Raised when attempting an invalid job state transition.

    Attributes:
        current_state: The current state of the job.
        attempted_state: The state that was attempted.
        allowed_transitions: List of valid transition targets from current state.
    """

    def __init__(
        self,
        current_state: JobStatus,
        attempted_state: JobStatus,
        allowed_transitions: list[JobStatus],
    ) -> None:
        self.current_state = current_state
        self.attempted_state = attempted_state
        self.allowed_transitions = allowed_transitions
        allowed_str = ", ".join(s.value for s in allowed_transitions) or "none (terminal)"
        super().__init__(
            f"Cannot transition from '{current_state.value}' to '{attempted_state.value}'. "
            f"Allowed transitions: {allowed_str}"
        )


# Valid state transitions for job lifecycle
VALID_TRANSITIONS: dict[JobStatus, list[JobStatus]] = {
    JobStatus.pending: [JobStatus.running, JobStatus.cancelled, JobStatus.failed],
    JobStatus.running: [
        JobStatus.paused,
        JobStatus.completed,
        JobStatus.failed,
        JobStatus.cancelled,
    ],
    JobStatus.paused: [JobStatus.running, JobStatus.cancelled],
    JobStatus.completed: [],  # terminal
    JobStatus.failed: [],  # terminal (retry creates new job with same rows)
    JobStatus.cancelled: [],  # terminal
}


def _utc_now_iso() -> str:
    """Generate current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


class JobService:
    """Service for job lifecycle management with state machine validation.

    Provides CRUD operations for jobs and rows, enforces valid state
    transitions, and tracks per-row processing status for crash recovery.

    Attributes:
        db: SQLAlchemy session for database operations.
    """

    def __init__(self, db: Session) -> None:
        """Initialize the job service with a database session.

        Args:
            db: SQLAlchemy session for database operations.
        """
        self.db = db

    # =========================================================================
    # Job CRUD Operations
    # =========================================================================

    def create_job(
        self,
        name: str,
        original_command: str,
        description: str | None = None,
        mode: str = "confirm",
    ) -> Job:
        """Create a new job with the given parameters.

        Args:
            name: User-provided job name.
            original_command: The natural language command that created this job.
            description: Optional job description.
            mode: Execution mode ('confirm' = wait for approval, 'auto' = immediate).

        Returns:
            The created Job object with generated ID and timestamps.
        """
        now = _utc_now_iso()
        job = Job(
            id=str(uuid4()),
            name=name,
            description=description,
            original_command=original_command,
            status=JobStatus.pending.value,
            mode=mode,
            created_at=now,
            updated_at=now,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        """Get a job by its ID.

        Args:
            job_id: The UUID of the job to retrieve.

        Returns:
            The Job object if found, None otherwise.
        """
        return self.db.query(Job).filter(Job.id == job_id).first()

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        """List jobs with optional filtering and pagination.

        Args:
            status: Filter by job status (optional).
            limit: Maximum number of jobs to return (default 50).
            offset: Number of jobs to skip for pagination (default 0).

        Returns:
            List of Job objects matching the criteria, ordered by created_at DESC.
        """
        query = self.db.query(Job)
        if status is not None:
            query = query.filter(Job.status == status.value)
        query = query.order_by(Job.created_at.desc())
        query = query.limit(limit).offset(offset)
        return query.all()

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and all associated rows and logs (cascade).

        Args:
            job_id: The UUID of the job to delete.

        Returns:
            True if the job was deleted, False if not found.
        """
        job = self.get_job(job_id)
        if job is None:
            return False
        self.db.delete(job)
        self.db.commit()
        return True

    # =========================================================================
    # State Machine Operations
    # =========================================================================

    def can_transition(self, current: JobStatus, target: JobStatus) -> bool:
        """Check if a state transition is valid.

        Args:
            current: The current job status.
            target: The target job status.

        Returns:
            True if the transition is valid, False otherwise.
        """
        return target in VALID_TRANSITIONS.get(current, [])

    def update_status(self, job_id: str, new_status: JobStatus) -> Job:
        """Update a job's status with state machine validation.

        Args:
            job_id: The UUID of the job to update.
            new_status: The new status to transition to.

        Returns:
            The updated Job object.

        Raises:
            ValueError: If job not found.
            InvalidStateTransition: If the transition is not allowed.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        current_status = JobStatus(job.status)
        if not self.can_transition(current_status, new_status):
            raise InvalidStateTransition(
                current_state=current_status,
                attempted_state=new_status,
                allowed_transitions=VALID_TRANSITIONS.get(current_status, []),
            )

        now = _utc_now_iso()
        job.status = new_status.value
        job.updated_at = now

        # Set started_at when first transitioning to running
        if new_status == JobStatus.running and job.started_at is None:
            job.started_at = now

        # Set completed_at for terminal states
        if new_status in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled):
            job.completed_at = now

        self.db.commit()
        self.db.refresh(job)
        return job

    # =========================================================================
    # Job Metrics Operations
    # =========================================================================

    def update_counts(
        self,
        job_id: str,
        total: int | None = None,
        processed: int | None = None,
        successful: int | None = None,
        failed: int | None = None,
    ) -> Job:
        """Update job row counts.

        Args:
            job_id: The UUID of the job to update.
            total: New total row count (optional).
            processed: New processed row count (optional).
            successful: New successful row count (optional).
            failed: New failed row count (optional).

        Returns:
            The updated Job object.

        Raises:
            ValueError: If job not found.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        if total is not None:
            job.total_rows = total
        if processed is not None:
            job.processed_rows = processed
        if successful is not None:
            job.successful_rows = successful
        if failed is not None:
            job.failed_rows = failed

        job.updated_at = _utc_now_iso()
        self.db.commit()
        self.db.refresh(job)
        return job

    def set_error(self, job_id: str, error_code: str, error_message: str) -> Job:
        """Set error information on a job.

        Args:
            job_id: The UUID of the job to update.
            error_code: The error code (E-XXXX format).
            error_message: Human-readable error description.

        Returns:
            The updated Job object.

        Raises:
            ValueError: If job not found.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        job.error_code = error_code
        job.error_message = error_message
        job.updated_at = _utc_now_iso()
        self.db.commit()
        self.db.refresh(job)
        return job

    # =========================================================================
    # Row CRUD Operations
    # =========================================================================

    def create_rows(self, job_id: str, row_data: list[dict[str, Any]]) -> list[JobRow]:
        """Create multiple rows for a job in bulk.

        Args:
            job_id: The UUID of the parent job.
            row_data: List of dicts with 'row_number' (int) and 'row_checksum' (str).

        Returns:
            List of created JobRow objects.

        Raises:
            ValueError: If job not found.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        rows = []
        for data in row_data:
            row = JobRow(
                id=str(uuid4()),
                job_id=job_id,
                row_number=data["row_number"],
                row_checksum=data["row_checksum"],
                order_data=data.get("order_data"),
                status=RowStatus.pending.value,
            )
            rows.append(row)
            self.db.add(row)

        # Update job total row count
        job.total_rows = len(row_data)
        job.updated_at = _utc_now_iso()

        self.db.commit()
        for row in rows:
            self.db.refresh(row)
        self.db.refresh(job)
        return rows

    def get_row(self, row_id: str) -> JobRow | None:
        """Get a row by its ID.

        Args:
            row_id: The UUID of the row to retrieve.

        Returns:
            The JobRow object if found, None otherwise.
        """
        return self.db.query(JobRow).filter(JobRow.id == row_id).first()

    def get_rows(
        self,
        job_id: str,
        status: RowStatus | None = None,
    ) -> list[JobRow]:
        """Get all rows for a job, optionally filtered by status.

        Args:
            job_id: The UUID of the parent job.
            status: Filter by row status (optional).

        Returns:
            List of JobRow objects ordered by row_number ASC.
        """
        query = self.db.query(JobRow).filter(JobRow.job_id == job_id)
        if status is not None:
            query = query.filter(JobRow.status == status.value)
        query = query.order_by(JobRow.row_number.asc())
        return query.all()

    def get_pending_rows(self, job_id: str) -> list[JobRow]:
        """Get all pending rows for a job.

        Args:
            job_id: The UUID of the parent job.

        Returns:
            List of pending JobRow objects ordered by row_number ASC.
        """
        return self.get_rows(job_id, status=RowStatus.pending)

    def get_failed_rows(self, job_id: str) -> list[JobRow]:
        """Get all failed rows for a job.

        Args:
            job_id: The UUID of the parent job.

        Returns:
            List of failed JobRow objects ordered by row_number ASC.
        """
        return self.get_rows(job_id, status=RowStatus.failed)

    # =========================================================================
    # Row State Operations
    # =========================================================================

    def start_row(self, row_id: str) -> JobRow:
        """Mark a row as processing.

        Args:
            row_id: The UUID of the row to update.

        Returns:
            The updated JobRow object.

        Raises:
            ValueError: If row not found.
        """
        row = self.get_row(row_id)
        if row is None:
            raise ValueError(f"Row not found: {row_id}")

        row.status = RowStatus.processing.value
        self.db.commit()
        self.db.refresh(row)
        return row

    def complete_row(
        self,
        row_id: str,
        tracking_number: str,
        label_path: str,
        cost_cents: int,
    ) -> JobRow:
        """Mark a row as completed with shipment details.

        Updates the row status, tracking info, and increments the job's
        processed_rows and successful_rows counts.

        Args:
            row_id: The UUID of the row to update.
            tracking_number: UPS tracking number for the shipment.
            label_path: File path to the saved shipping label.
            cost_cents: Shipping cost in cents.

        Returns:
            The updated JobRow object.

        Raises:
            ValueError: If row not found.
        """
        row = self.get_row(row_id)
        if row is None:
            raise ValueError(f"Row not found: {row_id}")

        now = _utc_now_iso()
        row.status = RowStatus.completed.value
        row.tracking_number = tracking_number
        row.label_path = label_path
        row.cost_cents = cost_cents
        row.processed_at = now

        # Update job counts
        job = row.job
        job.processed_rows += 1
        job.successful_rows += 1
        job.updated_at = now

        self.db.commit()
        self.db.refresh(row)
        self.db.refresh(job)
        return row

    def fail_row(self, row_id: str, error_code: str, error_message: str) -> JobRow:
        """Mark a row as failed with error details.

        Updates the row status, error info, and increments the job's
        processed_rows and failed_rows counts.

        Args:
            row_id: The UUID of the row to update.
            error_code: Error code (E-XXXX format).
            error_message: Human-readable error description.

        Returns:
            The updated JobRow object.

        Raises:
            ValueError: If row not found.
        """
        row = self.get_row(row_id)
        if row is None:
            raise ValueError(f"Row not found: {row_id}")

        now = _utc_now_iso()
        row.status = RowStatus.failed.value
        row.error_code = error_code
        row.error_message = error_message
        row.processed_at = now

        # Update job counts
        job = row.job
        job.processed_rows += 1
        job.failed_rows += 1
        job.updated_at = now

        self.db.commit()
        self.db.refresh(row)
        self.db.refresh(job)
        return row

    def skip_row(self, row_id: str) -> JobRow:
        """Mark a row as skipped (for retry scenarios).

        Args:
            row_id: The UUID of the row to update.

        Returns:
            The updated JobRow object.

        Raises:
            ValueError: If row not found.
        """
        row = self.get_row(row_id)
        if row is None:
            raise ValueError(f"Row not found: {row_id}")

        row.status = RowStatus.skipped.value
        self.db.commit()
        self.db.refresh(row)
        return row

    # =========================================================================
    # Recovery Operations
    # =========================================================================

    def reset_job_for_restart(self, job_id: str) -> Job:
        """Reset a job and all its rows for restart from scratch.

        Resets job counters and marks all rows as pending. Used for crash
        recovery when user chooses to restart instead of resume.

        Args:
            job_id: The UUID of the job to reset.

        Returns:
            The updated Job object.

        Raises:
            ValueError: If job not found.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        now = _utc_now_iso()

        # Reset job counters
        job.processed_rows = 0
        job.successful_rows = 0
        job.failed_rows = 0
        job.error_code = None
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.updated_at = now

        # Reset all rows to pending
        rows = self.get_rows(job_id)
        for row in rows:
            row.status = RowStatus.pending.value
            row.tracking_number = None
            row.label_path = None
            row.cost_cents = None
            row.error_code = None
            row.error_message = None
            row.processed_at = None

        self.db.commit()
        self.db.refresh(job)
        return job

    # =========================================================================
    # Aggregation Operations
    # =========================================================================

    def get_job_summary(self, job_id: str) -> dict[str, Any]:
        """Get a summary of job progress and metrics.

        Args:
            job_id: The UUID of the job.

        Returns:
            Dictionary with job metrics including:
            - total_rows, processed_rows, successful_rows, failed_rows
            - pending_count (calculated)
            - total_cost_cents (sum of successful rows)
            - status, created_at, started_at, completed_at

        Raises:
            ValueError: If job not found.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        # Calculate pending count
        pending_count = job.total_rows - job.processed_rows

        # Calculate total cost from successful rows
        total_cost_result = (
            self.db.query(func.sum(JobRow.cost_cents))
            .filter(JobRow.job_id == job_id)
            .filter(JobRow.status == RowStatus.completed.value)
            .scalar()
        )
        total_cost_cents = total_cost_result or 0

        return {
            "total_rows": job.total_rows,
            "processed_rows": job.processed_rows,
            "successful_rows": job.successful_rows,
            "failed_rows": job.failed_rows,
            "pending_count": pending_count,
            "total_cost_cents": total_cost_cents,
            "status": job.status,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
