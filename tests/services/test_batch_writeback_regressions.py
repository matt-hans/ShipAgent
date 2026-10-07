"""Offline acceptance regressions for priced batch confirmation and recovery."""

from unittest.mock import AsyncMock

import pytest

from src.db.models import Job, WriteBackTask
from tests.services.test_batch_confirmation_acceptance import (
    _confirm,
    _drain_batches,
    _isolated_runtime,
    _jobs,
    _preview_in_conversation,
    _preview_ready,
    api,
    session_factory,
    source,
    ups,
)

# Imported fixtures are intentionally shared with the conversation acceptance seam.
__all__ = ["_isolated_runtime", "api", "session_factory", "source", "ups"]
pytestmark = pytest.mark.usefixtures("session_factory")


async def test_writeback_opt_out_has_no_actionable_queue(
    source, ups, api, session_factory
):
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    await _confirm(api, job_id, write_back_enabled=False)
    await _drain_batches()
    with session_factory() as db:
        assert db.query(WriteBackTask).filter_by(status="pending").all() == []
    assert "write_back" not in source.tool_calls


@pytest.mark.parametrize("replacement", ["different", "disconnected"])
async def test_writeback_never_targets_replaced_source(
    replacement, source, ups, api, session_factory, monkeypatch
):
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    other = AsyncMock()
    other.get_source_info.return_value = (
        None
        if replacement == "disconnected"
        else {
            "source_type": "csv",
            "path": "different-file.csv",
            "signature": "different",
        }
    )
    other.get_source_signature.return_value = (
        None
        if replacement == "disconnected"
        else {
            "source_type": "csv",
            "source_ref": "different-file.csv",
            "schema_fingerprint": "different",
        }
    )
    other.write_back_batch.return_value = {
        "success_count": 4,
        "failure_count": 0,
        "errors": [],
    }
    monkeypatch.setattr(
        "src.services.gateway_provider.get_data_gateway", AsyncMock(return_value=other)
    )
    monkeypatch.setattr(
        "src.services.batch_engine.get_data_gateway", AsyncMock(return_value=other)
    )
    await _confirm(api, job_id, write_back_enabled=True)
    await _drain_batches()
    assert len(ups.create_calls) == 4
    assert other.write_back_batch.await_count == 0
    assert _jobs(session_factory)[0].status == "completed_with_warnings"


async def test_writeback_rechecks_binding_at_actual_write(
    source, ups, api, session_factory, tmp_path, monkeypatch
):
    """A source swap after the engine's check cannot receive even one write."""
    from tests.services.batch_acceptance_support import IMPORTED_ORDERS_CSV

    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    replacement = tmp_path / "replacement.csv"
    replacement.write_text(IMPORTED_ORDERS_CSV.replace("1001", "2001"))
    original = source._call_tool
    swapped = False

    async def swap_before_write(name, arguments):
        nonlocal swapped
        if name == "write_back" and not swapped:
            swapped = True
            await source.import_csv_file(replacement)
        return await original(name, arguments)

    monkeypatch.setattr(source, "_call_tool", swap_before_write)
    await _confirm(api, job_id, write_back_enabled=True)
    await _drain_batches()
    assert len(ups.create_calls) == 4
    assert "tracking_number" not in replacement.read_text()
    assert _jobs(session_factory)[0].status == "completed_with_warnings"


@pytest.mark.parametrize("opted_out", [True, False])
async def test_durable_retry_checks_source_and_saved_preference(
    opted_out, source, ups, api, session_factory
):
    from src.services.write_back_worker import (
        enqueue_write_back,
        process_write_back_queue,
    )

    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    with session_factory() as db:
        db.get(Job, job_id).write_back_enabled = not opted_out
        task = enqueue_write_back(db, job_id, 1, "1ZSYNTHETIC", "2026-10-07T00:00:00Z")
        gateway = AsyncMock()
        gateway.get_source_info.return_value = None
        gateway.get_source_signature.return_value = None
        await process_write_back_queue(db, gateway, [task])
        assert gateway.write_back_single.await_count == 0
        assert task.status != "completed"


async def test_same_source_durable_retry_preserves_row_mapping(
    source, ups, api, session_factory
):
    import csv

    from src.services.write_back_worker import (
        enqueue_write_back,
        process_write_back_queue,
    )

    obs, _ = await _preview_in_conversation(
        "scripted",
        source,
        ups,
        args={
            "command": "Ship all orders",
            "all_rows": True,
        },
    )
    job_id = _preview_ready(obs)["job_id"]
    with session_factory() as db:
        task = enqueue_write_back(db, job_id, 2, "1ZDURABLE", "2026-10-07T00:00:00Z")
        result = await process_write_back_queue(db, source, [task])
        assert result["processed"] == 1
        assert task.status == "completed"
    info = await source.get_source_info()
    with open(info["path"], newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[1]["tracking_number"] == "1ZDURABLE"
    assert rows[0]["tracking_number"] == ""


async def test_unbound_external_account_never_receives_tracking(
    source, ups, api, session_factory, monkeypatch
):
    """A platform label alone cannot authorize the currently connected account."""
    source._lifespan["current_source"]["type"] = "shopify"
    external_b = AsyncMock()
    external_b.update_tracking.return_value = {"success": True}
    monkeypatch.setattr(
        "src.services.batch_engine.get_external_sources_client",
        AsyncMock(return_value=external_b),
        raising=False,
    )
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    await _confirm(api, job_id, write_back_enabled=True)
    await _drain_batches()
    assert len(ups.create_calls) == 4
    assert external_b.update_tracking.await_count == 0
    with session_factory() as db:
        tasks = db.query(WriteBackTask).filter_by(job_id=job_id).all()
        assert tasks and all(task.status == "blocked" for task in tasks)
    assert _jobs(session_factory)[0].status == "completed_with_warnings"


async def test_safe_source_binding_survives_audit_and_reimport_is_distinct(source, ups, session_factory):
    import json

    from src.db.models import AuditLog
    info = await source.get_source_info()
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    with session_factory() as db:
        record = db.query(AuditLog).filter_by(job_id=job_id, message="job_source_signature").one()
        signature = json.loads(record.details)["source_signature"]
        assert signature["binding_digest"] == info["binding_digest"]
        assert "CANARY" not in record.details
    from pathlib import Path
    await source.import_csv_file(Path(info["path"]))
    replacement = await source.get_source_info()
    assert replacement["binding_digest"] != info["binding_digest"]
    assert replacement["signature"] == info["signature"]
