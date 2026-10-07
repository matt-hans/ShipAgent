"""Offline acceptance regressions for priced batch confirmation and recovery."""

from unittest.mock import AsyncMock

import pytest

from src.db.models import Job
from tests.services.test_batch_confirmation_acceptance import (
    _confirm,
    _drain_batches,
    _isolated_runtime,
    _jobs,
    _preview_in_conversation,
    _preview_ready,
    _progress,
    api,
    session_factory,
    source,
    ups,
)

# Imported fixtures are intentionally shared with the conversation acceptance seam.
__all__ = ["_isolated_runtime", "api", "session_factory", "source", "ups"]
pytestmark = pytest.mark.usefixtures("session_factory")


@pytest.mark.parametrize("interactive, service", [(False, "03"), (True, "invalid")])
async def test_rejected_confirm_preserves_pending_state(
    interactive, service, source, ups, api, session_factory
):
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    with session_factory() as db:
        job = db.get(Job, job_id)
        job.is_interactive = interactive
        db.commit()
    assert (
        await _confirm(api, job_id, selected_service_code=service)
    ).status_code == 400
    assert _jobs(session_factory)[0].status == "pending"
    assert _jobs(session_factory)[0].started_at is None
    assert (await _confirm(api, job_id)).status_code == 200
    await _drain_batches()
    assert len(ups.create_calls) == 4


@pytest.mark.parametrize("failure", ["credentials", "shipper"])
async def test_execution_setup_failure_reaches_terminal_state(
    failure, source, ups, api, session_factory, monkeypatch
):
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    if failure == "credentials":
        monkeypatch.setattr(
            "src.services.runtime_credentials.resolve_ups_credentials", lambda: None
        )
    else:
        monkeypatch.setattr(
            "src.services.batch_executor.get_shipper_for_job",
            AsyncMock(side_effect=RuntimeError("source unavailable")),
        )
    await _confirm(api, job_id)
    await _drain_batches()
    assert ups.create_calls == []
    assert _jobs(session_factory)[0].status == "failed"
    assert (await _progress(api, job_id))["status"] == "failed"
