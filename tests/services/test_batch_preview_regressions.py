"""Offline acceptance regressions for priced batch confirmation and recovery."""

from unittest.mock import AsyncMock

import pytest

from src.db.models import Job, JobRow
from tests.services.provider_scenarios import PROVIDERS
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


@pytest.mark.parametrize("kind", PROVIDERS)
@pytest.mark.parametrize("quote", ["NaN", "Infinity", "missing", "timeout", "rejected"])
async def test_invalid_quote_never_authorizes_purchase(
    kind, quote, source, ups, api, session_factory, monkeypatch
):
    original = ups.get_rate
    if quote == "missing":
        monkeypatch.setattr(ups, "get_rate", AsyncMock(return_value={"success": True}))
    elif quote == "timeout":
        monkeypatch.setattr(ups, "get_rate", AsyncMock(side_effect=TimeoutError()))
    elif quote == "rejected":
        from tests.services.batch_acceptance_support import hard_rejection

        monkeypatch.setattr(ups, "get_rate", AsyncMock(side_effect=hard_rejection()))
    else:
        ups.rate = quote
    obs, _ = await _preview_in_conversation(kind, source, ups)
    ready = _preview_ready(obs)
    job_id = ready["job_id"]
    ups.rate = "12.34"
    monkeypatch.setattr(ups, "get_rate", original)
    rest = await api.get(f"/api/v1/jobs/{job_id}/preview")
    response = await _confirm(api, job_id)
    await _drain_batches()
    assert ups.create_calls == []
    assert response.status_code == 400
    assert ready["confirmation_ready"] is False
    assert rest.json()["confirmation_ready"] is False
    assert rest.json()["rows_with_warnings"] == ready["rows_with_warnings"] == 4
    assert _jobs(session_factory)[0].status == "pending"


@pytest.mark.parametrize("cap", [0, 2])
async def test_rest_preview_preserves_priced_artifact(
    cap, source, ups, api, monkeypatch
):
    monkeypatch.setenv("BATCH_PREVIEW_MAX_ROWS", str(cap))
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    ready = _preview_ready(obs)
    rest = (await api.get(f"/api/v1/jobs/{ready['job_id']}/preview")).json()
    for field in (
        "total_rows",
        "additional_rows",
        "total_estimated_cost_cents",
        "rows_with_warnings",
    ):
        assert rest[field] == ready[field]
    for expected, actual in zip(
        ready["preview_rows"], rest["preview_rows"], strict=True
    ):
        assert {key: actual[key] for key in expected} == expected
    assert rest["confirmation_ready"] is True
    assert rest["total_estimated_cost_cents"] == 4936


async def test_preview_get_cannot_arm_never_priced_job(
    api, ups, session_factory, source
):
    with session_factory() as db:
        job = Job(name="Unpriced", original_command="ship all", total_rows=1)
        db.add(job)
        db.flush()
        job_id = job.id
        db.add(
            JobRow(
                job_id=job_id, row_number=1, row_checksum="original", order_data="{}"
            )
        )
        db.commit()
    assert (await api.get(f"/api/v1/jobs/{job_id}/preview")).status_code == 200
    assert (await _confirm(api, job_id)).status_code == 400
    await _drain_batches()
    assert ups.create_calls == []
    assert _jobs(session_factory)[0].preview_hash is None


async def test_zero_quote_remains_valid(source, ups, api):
    ups.rate = "0.00"
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    ready = _preview_ready(obs)
    assert ready["confirmation_ready"] is True
    assert (await _confirm(api, ready["job_id"])).status_code == 200
    await _drain_batches()
    assert len(ups.create_calls) == 4


async def test_repreview_can_recover_from_unavailable_quote(
    source, ups, api, session_factory
):
    ups.rate = "NaN"
    failed, _ = await _preview_in_conversation("scripted", source, ups)
    old_job = _preview_ready(failed)["job_id"]
    ups.rate = "12.34"
    recovered, _ = await _preview_in_conversation("scripted", source, ups)
    new_job = _preview_ready(recovered)["job_id"]
    assert new_job != old_job
    assert (await _confirm(api, old_job)).status_code == 400
    assert (await _confirm(api, new_job)).status_code == 200
    await _drain_batches()
    assert len(ups.create_calls) == 4
