"""Offline acceptance regressions for priced batch confirmation and recovery."""

import asyncio

import pytest

from src.api.routes import preview as preview_routes
from src.services.batch_engine import BatchEngine
from tests.services.test_batch_confirmation_acceptance import (
    _confirm,
    _drain_batches,
    _isolated_runtime,
    _jobs,
    _preview_in_conversation,
    _preview_ready,
    _progress,
    _rows,
    api,
    session_factory,
    source,
    ups,
)

# Imported fixtures are intentionally shared with the conversation acceptance seam.
__all__ = ["_isolated_runtime", "api", "session_factory", "source", "ups"]
pytestmark = pytest.mark.usefixtures("session_factory")


async def test_cancel_stops_unlaunched_rows(
    source, ups, api, session_factory, monkeypatch
):
    monkeypatch.setattr(BatchEngine, "_resolve_concurrency", staticmethod(lambda: 1))
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    release = ups.hold_creates()
    events = preview_routes._get_sse_observer().subscribe(job_id)
    await _confirm(api, job_id)
    await asyncio.wait_for(ups.in_create.wait(), 5)
    assert (
        await api.patch(f"/api/v1/jobs/{job_id}/status", json={"status": "cancelled"})
    ).status_code == 200
    release.set()
    await _drain_batches()
    assert len(ups.create_calls) == 1
    assert _jobs(session_factory)[0].status == "cancelled"
    assert [r.status for r in _rows(session_factory, job_id)] == [
        "completed",
        "pending",
        "pending",
        "pending",
    ]
    progress = await _progress(api, job_id)
    assert (progress["status"], progress["successful_rows"]) == ("cancelled", 1)
    emitted = []
    while not events.empty():
        emitted.append(events.get_nowait())
    assert emitted[-1]["event"] == "batch_failed"
    assert emitted[-1]["data"]["status"] == "cancelled"
    preview_routes._get_sse_observer().unsubscribe(job_id)


async def test_shutdown_reconciles_uncertain_accepted_call(
    source, ups, api, session_factory, monkeypatch
):
    monkeypatch.setattr(BatchEngine, "_resolve_concurrency", staticmethod(lambda: 1))
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    ups.hold_creates()
    await _confirm(api, job_id)
    await asyncio.wait_for(ups.in_create.wait(), 5)
    await preview_routes.shutdown_batch_runtime(timeout_seconds=0.01)
    assert [r.status for r in _rows(session_factory, job_id)] == [
        "needs_review",
        "pending",
        "pending",
        "pending",
    ]
    assert _jobs(session_factory)[0].status == "cancelled"
    assert (await _progress(api, job_id))["failed_rows"] == 1
    assert (await _confirm(api, job_id)).status_code == 400
    assert len(ups.create_calls) == 1


async def test_cancel_before_launch_purchases_nothing(
    source, ups, api, session_factory, monkeypatch
):
    from src.services import batch_executor

    entered = asyncio.Event()
    release = asyncio.Event()
    original = batch_executor.get_shipper_for_job

    async def held_shipper(job):
        entered.set()
        await release.wait()
        return await original(job)

    monkeypatch.setattr(batch_executor, "get_shipper_for_job", held_shipper)
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    await _confirm(api, job_id)
    await asyncio.wait_for(entered.wait(), 5)
    await api.patch(f"/api/v1/jobs/{job_id}/status", json={"status": "cancelled"})
    release.set()
    await _drain_batches()
    assert ups.create_calls == []
    assert _jobs(session_factory)[0].status == "cancelled"


async def test_cancel_at_final_progress_preserves_accepted_rows(
    source, ups, api, session_factory, monkeypatch
):
    observer = preview_routes._get_sse_observer()
    original = observer.on_row_completed

    async def cancel_after_last(*args, **kwargs):
        await original(*args, **kwargs)
        if args[1] == 4:
            response = await api.patch(
                f"/api/v1/jobs/{args[0]}/status", json={"status": "cancelled"}
            )
            assert response.status_code == 200

    monkeypatch.setattr(observer, "on_row_completed", cancel_after_last)
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    await _confirm(api, job_id)
    await _drain_batches()
    assert len(ups.create_calls) == 4
    assert _jobs(session_factory)[0].status == "cancelled"
    assert [r.status for r in _rows(session_factory, job_id)] == ["completed"] * 4


async def test_pause_during_last_accepted_call_finishes_truthfully(
    source, ups, api, session_factory
):
    from tests.services.test_batch_confirmation_acceptance import _state_filter

    obs, _ = await _preview_in_conversation(
        "scripted",
        source,
        ups,
        args={
            "command": "Ship TX orders",
            "filter_spec": await _state_filter(source, "TX"),
        },
    )
    job_id = _preview_ready(obs)["job_id"]
    release = ups.hold_creates()
    await _confirm(api, job_id)
    await asyncio.wait_for(ups.in_create.wait(), 5)
    assert (
        await api.patch(f"/api/v1/jobs/{job_id}/status", json={"status": "paused"})
    ).status_code == 200
    release.set()
    await _drain_batches()
    assert len(ups.create_calls) == 1
    assert _jobs(session_factory)[0].status == "completed"
    assert [row.status for row in _rows(session_factory, job_id)] == ["completed"]
