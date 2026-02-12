"""FastAPI routes for command submission and history.

.. deprecated::
    Use ``/api/v1/conversations/`` endpoints instead.
    The conversations route provides agent-driven SSE streaming via
    the Claude SDK orchestration path. This legacy command path
    bypasses the SDK and calls CommandProcessor directly.

Provides REST API endpoints for submitting natural language shipping
commands and retrieving command history.

The command submission endpoint creates a job and triggers background
processing via CommandProcessor to parse intent, filter orders, and
create job rows with cost estimates.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session

from src.api.schemas import (
    CommandHistoryItem,
    CommandSubmit,
    CommandSubmitResponse,
)
from src.db.connection import SessionLocal, get_db
from src.db.models import Job, JobStatus
from src.services.command_processor import CommandProcessor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/commands", tags=["commands"])


def _get_db_session() -> Session:
    """Create a new database session for background tasks.

    Returns:
        A new SQLAlchemy session.
    """
    return SessionLocal()


@router.post("", response_model=CommandSubmitResponse, status_code=201)
async def submit_command(
    payload: CommandSubmit,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
) -> CommandSubmitResponse:
    """Submit a natural language command for processing.

    .. deprecated::
        Use ``POST /api/v1/conversations/{id}/messages`` instead.

    Creates a new job with the provided command and triggers background
    processing via CommandProcessor. The processor will:
    1. Parse the intent from the natural language command
    2. Generate a SQL filter for order selection
    3. Fetch matching orders from connected platforms (Shopify)
    4. Create JobRows with cost estimates

    Args:
        payload: Command submission data containing the natural language command.
        background_tasks: FastAPI background tasks for async processing.
        db: Database session dependency.

    Returns:
        Response with job_id and initial status (pending).
    """
    # Generate clean display name
    if payload.refinements and payload.base_command:
        # Refined job: show base → ref1 → ref2 → ...
        base_summary = payload.base_command[:40].rstrip()
        if len(payload.base_command) > 40:
            base_summary += "..."
        parts = [base_summary]
        for ref in payload.refinements:
            ref_summary = ref[:40].rstrip()
            if len(ref) > 40:
                ref_summary += "..."
            parts.append(ref_summary)
        job_name = " → ".join(parts)
    else:
        job_name = f"Command: {payload.command[:50]}{'...' if len(payload.command) > 50 else ''}"

    # Create job with command
    job = Job(
        name=job_name,
        original_command=payload.command,
        status=JobStatus.pending.value,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Trigger background processing via CommandProcessor
    processor = CommandProcessor(db_session_factory=_get_db_session)
    background_tasks.add_task(processor.process, str(job.id), payload.command)

    # Deprecation headers
    logger.warning("Deprecated /commands/ endpoint called. Use /conversations/ instead.")
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/v1/conversations/>; rel="successor-version"'

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
