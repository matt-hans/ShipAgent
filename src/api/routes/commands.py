"""FastAPI routes for command submission and history.

Provides REST API endpoints for submitting natural language shipping
commands and retrieving command history.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.schemas import (
    CommandHistoryItem,
    CommandSubmit,
    CommandSubmitResponse,
)
from src.db.connection import get_db
from src.db.models import Job, JobStatus

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post("", response_model=CommandSubmitResponse, status_code=201)
def submit_command(
    payload: CommandSubmit,
    db: Session = Depends(get_db),
) -> CommandSubmitResponse:
    """Submit a natural language command for processing.

    Creates a new job with the provided command and returns the job ID
    for tracking. The job will be processed asynchronously by the
    orchestration agent.

    Args:
        payload: Command submission data containing the natural language command.
        db: Database session dependency.

    Returns:
        Response with job_id and initial status.
    """
    # Create job with command
    job = Job(
        name=f"Command: {payload.command[:50]}{'...' if len(payload.command) > 50 else ''}",
        original_command=payload.command,
        status=JobStatus.pending.value,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return CommandSubmitResponse(
        job_id=str(job.id),
        status=job.status,
    )


@router.get("/history", response_model=list[CommandHistoryItem])
def get_command_history(
    limit: int = Query(10, ge=1, le=50, description="Maximum number of commands to return"),
    db: Session = Depends(get_db),
) -> list[CommandHistoryItem]:
    """Get recent commands for reuse.

    Returns the most recent commands ordered by creation date descending.
    Useful for displaying command history in the UI for quick resubmission.

    Args:
        limit: Maximum number of commands to return (default 10, max 50).
        db: Database session dependency.

    Returns:
        List of recent commands with their job status.
    """
    jobs = (
        db.query(Job)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        CommandHistoryItem(
            id=str(job.id),
            command=job.original_command,
            status=job.status,
            created_at=job.created_at,
        )
        for job in jobs
    ]
