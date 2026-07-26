import pytest

from src.errors.terminal_diagnostics import MAX_TERMINAL_ROW_DIAGNOSTICS
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


@pytest.mark.asyncio
async def test_row_failure_projects_raw_carrier_text_to_safe_diagnostic():
    observer = SSEProgressObserver()
    queue = observer.subscribe("job-1")
    raw_carrier_text = (
        "UPS request recipient=Jane Doe address=1 Main St "
        "Authorization=Bearer secret-token"
    )

    await observer.on_row_failed(
        "job-1",
        row_number=7,
        error_code="E-3003",
        error_message=raw_carrier_text,
    )

    event = await queue.get()
    assert event == {
        "event": "row_failed",
        "data": {
            "job_id": "job-1",
            "diagnostic": {
                "row_number": 7,
                "error_code": "E-3003",
                "error_category": "ups_api",
                "message": "The carrier could not process this shipment.",
            },
        },
    }
    assert raw_carrier_text not in repr(event)


@pytest.mark.asyncio
async def test_row_failure_stream_caps_safe_diagnostics_and_reports_omission():
    observer = SSEProgressObserver()
    queue = observer.subscribe("job-1")

    for row_number in range(1, MAX_TERMINAL_ROW_DIAGNOSTICS + 2):
        await observer.on_row_failed(
            "job-1",
            row_number=row_number,
            error_code="E-3003",
            error_message="carrier request recipient=Jane Doe token=secret",
        )

    events = [await queue.get() for _ in range(MAX_TERMINAL_ROW_DIAGNOSTICS + 1)]
    assert all("diagnostic" in event["data"] for event in events[:-1])
    assert events[-1]["data"] == {
        "job_id": "job-1",
        "omitted_failure_count": 1,
    }
