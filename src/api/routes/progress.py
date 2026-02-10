"""FastAPI routes for SSE progress streaming.

Provides Server-Sent Events (SSE) endpoint for real-time batch
progress updates to web clients.
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from src.db.connection import get_db
from src.db.models import Job
from src.orchestrator.batch import SSEProgressObserver

router = APIRouter(tags=["progress"])

# Module-level SSE observer instance
# This is shared across all SSE connections and can be registered
# with BatchEventEmitter to receive batch events
sse_observer = SSEProgressObserver()


async def _event_generator(
    request: Request,
    job_id: str,
    queue: asyncio.Queue,
) -> AsyncGenerator[dict, None]:
    """Generate SSE events from the job's event queue.

    Yields events from the queue with a 15-second timeout to send
    ping events and prevent connection timeouts from load balancers.

    Args:
        request: FastAPI request object for disconnect detection.
        job_id: The job UUID for this subscription.
        queue: Async queue receiving batch events.

    Yields:
        Event dictionaries with 'event' and 'data' keys.
    """
    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                # Wait for event with timeout
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                # Send as unnamed SSE event (type "message") with event type
                # embedded in the data payload. The frontend useSSE hook parses
                # the data as JSON and extracts the "event" field from it.
                # Using named SSE events (event: batch_started) would require
                # addEventListener() on the frontend, but the hook uses the
                # generic onmessage handler instead.
                yield {
                    "data": json.dumps({
                        "event": event["event"],
                        "data": event["data"],
                    }),
                }
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                yield {
                    "data": json.dumps({"event": "ping"}),
                }
    finally:
        # Always unsubscribe when generator exits
        sse_observer.unsubscribe(job_id)


@router.get("/jobs/{job_id}/progress/stream")
async def stream_progress(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Stream batch progress events via Server-Sent Events.

    Subscribes to the SSE observer for the specified job and streams
    real-time progress updates. Sends ping events every 15 seconds
    to prevent connection timeouts.

    The connection will automatically clean up when the client disconnects.

    Args:
        request: FastAPI request object.
        job_id: The job UUID to monitor.
        db: Database session dependency.

    Returns:
        EventSourceResponse streaming batch events.

    Raises:
        HTTPException: If job not found (404).
    """
    # Verify job exists
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Subscribe to events for this job
    queue = sse_observer.subscribe(job_id)

    return EventSourceResponse(
        _event_generator(request, job_id, queue),
        media_type="text/event-stream",
    )


@router.get("/jobs/{job_id}/progress")
def get_progress(
    job_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Get current job progress (fallback for non-SSE clients).

    Returns the current progress state of a job. Use this endpoint
    for initial state load before connecting to the SSE stream, or
    for clients that don't support SSE.

    Args:
        job_id: The job UUID.
        db: Database session dependency.

    Returns:
        Dictionary with current job progress.

    Raises:
        HTTPException: If job not found (404).
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": str(job.id),
        "status": job.status,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "successful_rows": job.successful_rows,
        "failed_rows": job.failed_rows,
        "total_cost_cents": job.total_cost_cents,
    }
