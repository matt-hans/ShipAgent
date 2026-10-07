"""CLI confirmation uses the same priced, single-claim batch workflow as REST."""

import pytest

from src.cli.protocol import ShipAgentClientError
from src.cli.runner import InProcessRunner
from tests.services.test_batch_confirmation_acceptance import (
    _isolated_runtime,
    _jobs,
    _preview_in_conversation,
    _preview_ready,
    session_factory,
    source,
    ups,
)

__all__ = ["_isolated_runtime", "session_factory", "source", "ups"]
pytestmark = pytest.mark.usefixtures("session_factory")


async def test_cli_confirmation_claims_valid_preview_once(source, ups, session_factory):
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    runner = InProcessRunner()
    await runner.approve_job(job_id)
    assert _jobs(session_factory)[0].status == "completed"
    with pytest.raises(ShipAgentClientError):
        await runner.approve_job(job_id)
    assert len(ups.create_calls) == 4


async def test_cli_confirmation_rejects_unpriced_preview(source, ups, session_factory):
    ups.rate = "NaN"
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    ups.rate = "12.34"
    with pytest.raises(ShipAgentClientError):
        await InProcessRunner().approve_job(job_id)
    assert ups.create_calls == []
    assert _jobs(session_factory)[0].status == "pending"
