"""Tests for preview background runtime shutdown behavior."""

import asyncio

import pytest

from src.api.routes import preview


@pytest.mark.asyncio
async def test_shutdown_batch_runtime_noop_when_no_tasks():
    await preview.shutdown_batch_runtime(timeout_seconds=0.01)


@pytest.mark.asyncio
async def test_shutdown_batch_runtime_cancels_stuck_tasks():
    started = asyncio.Event()

    async def _long_running() -> None:
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(_long_running())
    preview._track_batch_task(task)
    await started.wait()

    await preview.shutdown_batch_runtime(timeout_seconds=0.01)

    assert task.done()

