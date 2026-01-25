"""Crash recovery for interrupted batch jobs.

Per CONTEXT.md Decision 3:
- Resume: Prompt user with progress info
- Options: Resume, Restart, Cancel
- Restart warns about duplicate shipments
- Show last error if crash was due to error
"""

from enum import Enum
from typing import Optional

from src.db.models import JobStatus, RowStatus
from src.services.job_service import JobService
from src.orchestrator.batch.models import InterruptedJobInfo


class RecoveryChoice(str, Enum):
    """User choices for interrupted job recovery."""

    RESUME = "resume"
    RESTART = "restart"
    CANCEL = "cancel"


def check_interrupted_jobs(job_service: JobService) -> Optional[InterruptedJobInfo]:
    """Check for jobs interrupted mid-execution.

    Finds jobs in 'running' state, which indicates they were interrupted
    (normal completion transitions to 'completed' or 'failed').

    Args:
        job_service: JobService instance for database queries.

    Returns:
        InterruptedJobInfo if found, None otherwise.
    """
    # Find jobs in 'running' state (indicates crash)
    interrupted = job_service.list_jobs(status=JobStatus.running, limit=1)

    if not interrupted:
        return None

    job = interrupted[0]

    # Get progress info
    completed_count = job.successful_rows
    total = job.total_rows
    remaining = total - job.processed_rows

    # Get last completed row info
    completed_rows = job_service.get_rows(job.id, status=RowStatus.completed)
    last_row_info = None
    last_tracking = None
    if completed_rows:
        last = completed_rows[-1]
        last_row_info = last.row_number
        last_tracking = last.tracking_number

    return InterruptedJobInfo(
        job_id=job.id,
        job_name=job.name,
        completed_rows=completed_count,
        total_rows=total,
        remaining_rows=remaining,
        last_row_number=last_row_info,
        last_tracking_number=last_tracking,
        error_code=job.error_code,
        error_message=job.error_message,
    )


def get_recovery_prompt(info: InterruptedJobInfo) -> str:
    """Generate user-friendly recovery prompt.

    Per CONTEXT.md Decision 3:
    - Summary: "47/200 complete. Last: Row 47 (John Doe, tracking ABC123). 153 remaining."
    - Error context if exists: "Crashed at row 48 due to: UPS API timeout"

    Args:
        info: InterruptedJobInfo from check_interrupted_jobs.

    Returns:
        Formatted prompt string.
    """
    lines = [
        f"Job '{info.job_name}' was interrupted at row {info.completed_rows}/{info.total_rows}.",
        "",
    ]

    if info.last_row_number and info.last_tracking_number:
        lines.append(
            f"Last completed: Row {info.last_row_number} (tracking: {info.last_tracking_number})"
        )

    lines.append(f"Remaining: {info.remaining_rows} rows")

    if info.error_code and info.error_message:
        lines.extend([
            "",
            f"Last error: {info.error_code}: {info.error_message}",
            "Resume will retry from the failed row.",
        ])

    lines.extend([
        "",
        "Options:",
        "  [resume]  - Continue from where it stopped",
        "  [restart] - Start over from the beginning (may create duplicates!)",
        "  [cancel]  - Abandon this job",
    ])

    return "\n".join(lines)


def handle_recovery_choice(
    choice: RecoveryChoice,
    job_id: str,
    job_service: JobService,
) -> dict:
    """Handle user's recovery choice.

    Args:
        choice: User's selected action.
        job_id: UUID of the interrupted job.
        job_service: JobService for state updates.

    Returns:
        Dict with action result and any warnings.

    Raises:
        ValueError: If job not found or unknown choice.
    """
    if choice == RecoveryChoice.RESUME:
        # No state changes needed - executor will process pending rows
        return {
            "action": "resume",
            "job_id": job_id,
            "message": "Resuming from last checkpoint. Pending rows will be processed.",
        }

    elif choice == RecoveryChoice.RESTART:
        # Reset all rows to pending
        job = job_service.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Get all rows and count completed ones with tracking
        all_rows = job_service.get_rows(job_id)
        completed_count = sum(
            1 for r in all_rows
            if r.status == RowStatus.completed.value
        )

        # Return warning about duplicates
        return {
            "action": "restart",
            "job_id": job_id,
            "warning": (
                f"WARNING: {completed_count} rows already have tracking numbers. "
                "Restarting will create duplicate shipments for these rows. "
                "Consider using 'resume' instead."
            ),
            "requires_confirmation": True,
            "completed_rows_with_tracking": completed_count,
        }

    elif choice == RecoveryChoice.CANCEL:
        # Transition job to cancelled
        job_service.update_status(job_id, JobStatus.cancelled)
        return {
            "action": "cancel",
            "job_id": job_id,
            "message": "Job cancelled. No further rows will be processed.",
        }

    else:
        raise ValueError(f"Unknown recovery choice: {choice}")
