import pytest

from src.orchestrator.batch.sse_observer import SSEProgressObserver


@pytest.mark.asyncio
async def test_completed_with_warnings_status_reaches_live_progress_subscribers():
    observer = SSEProgressObserver()
    queue = observer.subscribe("job-1")

    await observer.on_batch_completed(
        "job-1",
        total_rows=2,
        successful=2,
        total_cost_cents=2400,
        status="completed_with_warnings",
    )

    event = await queue.get()
    assert event["event"] == "batch_completed"
    assert event["data"]["status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_cancelled_status_reaches_live_progress_subscribers():
    observer = SSEProgressObserver()
    queue = observer.subscribe("job-1")

    await observer.on_batch_failed(
        "job-1",
        error_code="E-CANCELLED",
        error_message="Batch cancelled.",
        processed=0,
        status="cancelled",
    )

    event = await queue.get()
    assert event["event"] == "batch_failed"
    assert event["data"]["status"] == "cancelled"
