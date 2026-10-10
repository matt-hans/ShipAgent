"""Independent exact-backend loss around local COMMIT, with real PostgreSQL."""

import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.services.agent_runs.transaction import AgentRunTransaction
from tests.control_plane.persistence.conftest import (  # noqa: F401
    disposable_control_stores,
    postgres_db,
)
from tests.control_plane.persistence.test_agent_run_authority import (  # noqa: F401
    authority_case,
    submit,
)


@pytest.mark.parametrize("loss_point", ["before_local_commit", "after_local_commit"])
async def test_original_backend_loss_during_local_commit_is_not_authority(
    authority_case, monkeypatch, loss_point
):
    case = authority_case
    owner, request = await case.request()
    original_commit = AgentRunTransaction._commit_sql
    deaths = []

    def commit_at_loss(transaction):
        assert transaction is owner._target
        if loss_point == "after_local_commit":
            original_commit(transaction)
        # This sync callback runs in the existing run_sync bridge. Kill only the
        # original captured backend, never the test postmaster or another owner.
        with pytest.raises(DBAPIError):
            owner._sync.execute(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": owner._backend}
            )
        deaths.append(owner._backend)
        if loss_point == "before_local_commit":
            original_commit(transaction)

    with monkeypatch.context() as patch:
        patch.setattr(AgentRunTransaction, "_commit_sql", commit_at_loss)
        with pytest.raises(
            (RuntimeError, PermissionError),
            match=r"^Agent run authority is unavailable\.$",
        ):
            await case.authority.submit(
                case.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )

    assert len(deaths) == 1
    assert owner.local_commit_attempted and owner.local_commit_known
    assert not owner.postgres_commit_known
    assert owner.retirement_completed
    assert case.service._authority_operation is None
    assert case.service._authority_dispatch_run is None
    with sqlite3.connect(case.store.path) as db:
        rows = db.execute("SELECT run_reference, state FROM agent_runs").fetchall()
    assert len(rows) == 1 and rows[0][1] == "queued"

    # Fresh current authority can reconcile the same original key. Neither the
    # lost request nor reconciliation is a provider-dispatch permit.
    retry_owner, recovered = await submit(case)
    assert recovered.run_reference == rows[0][0]
    assert retry_owner.local_commit_known and retry_owner.postgres_commit_known
    assert retry_owner.retirement_completed
    assert case.service._authority_dispatch_run is None
    with sqlite3.connect(case.store.path) as db:
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1
