"""Actual PostgreSQL outcomes and retained asynchronous cleanup boundaries."""

import asyncio
import copy
import sqlite3
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.control_plane.persistence.test_agent_run_authority import (
    authority_case as _authority_case,
)
from tests.control_plane.persistence.test_agent_run_authority import (
    submit,
)

authority_case = _authority_case


async def test_aborted_original_transaction_cannot_settle_as_committed(
    authority_case, monkeypatch
):
    c = authority_case
    owner, request = await c.request()
    commit = owner._commit_postgres
    returned = []

    async def abort_then_commit():
        # A real server transaction is aborted between the final validation and
        # COMMIT. PostgreSQL legitimately returns normally from that COMMIT.
        with pytest.raises(DBAPIError):
            await owner._connection.execute(text("SELECT 1/0"))
        await commit()
        returned.append(True)

    monkeypatch.setattr(owner, "_commit_postgres", abort_then_commit)
    with pytest.raises(RuntimeError, match="unavailable"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert returned == [True]
    assert owner.local_commit_known and not owner.postgres_commit_known
    assert owner.retirement_completed
    assert (
        await c.db.scalar(
            text("SELECT pg_xact_status(CAST(:x AS xid8))"), {"x": owner.original_xid}
        )
        == "aborted"
    )
    await c.db.rollback()
    with sqlite3.connect(c.store.path) as db:
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1


@pytest.mark.parametrize("point", ["before", "after"])
async def test_postgres_commit_failure_preserves_original_local_key(
    authority_case, monkeypatch, point
):
    c = authority_case
    owner, request = await c.request()
    commit = owner._commit_postgres

    async def fault():
        if point == "after":
            await commit()
        raise RuntimeError("PRIVATE-COMMIT-CANARY")

    monkeypatch.setattr(owner, "_commit_postgres", fault)
    with pytest.raises(RuntimeError, match="^Agent run authority is unavailable[.]$"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert owner.local_commit_attempted and owner.local_commit_known
    assert not owner.postgres_commit_known and owner.retirement_completed
    state = await c.db.scalar(
        text("SELECT pg_xact_status(CAST(:x AS xid8))"), {"x": owner.original_xid}
    )
    assert state == ("committed" if point == "after" else "aborted")
    await c.db.rollback()
    with sqlite3.connect(c.store.path) as db:
        original = db.execute("SELECT run_reference FROM agent_runs").fetchone()[0]
    _, retried = await submit(c)
    assert retried.run_reference == original


@pytest.mark.parametrize("point", ["before", "after"])
async def test_owned_postgres_backend_death_never_reconnects_to_settle(
    authority_case, monkeypatch, point
):
    c = authority_case
    owner, request = await c.request()
    commit = owner._commit_postgres

    async def kill():
        if point == "after":
            await commit()
        assert await c.db.scalar(
            text("SELECT pg_terminate_backend(:pid)"), {"pid": owner._backend}
        )
        await c.db.commit()
        if point == "before":
            await commit()

    monkeypatch.setattr(owner, "_commit_postgres", kill)
    with pytest.raises(RuntimeError, match="unavailable"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert owner.local_commit_known and not owner.postgres_commit_known
    assert owner.retirement_completed


async def test_cancellation_resistant_identity_task_stays_owned(
    authority_case, monkeypatch
):
    c = authority_case
    owner = c.authority.begin_http_operation(c.service, time.monotonic() + 0.08)
    c.owners.append(owner)
    entered = asyncio.Event()
    release = asyncio.Event()
    resolve = owner._identity_service.resolve

    async def stubborn(**arguments):
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        return await resolve(**arguments)

    monkeypatch.setattr(owner._identity_service, "resolve", stubborn)
    try:
        start = time.monotonic()
        with pytest.raises(PermissionError, match="unavailable"):
            await owner.resolve(c.principal)
        assert time.monotonic() - start < 0.3
        assert (
            entered.is_set()
            and owner._pending is not None
            and not owner._pending.done()
        )
        assert (
            c.service._authority_operation is owner and not owner.retirement_completed
        )
        with pytest.raises(RuntimeError):
            c.service._lease.close()
    finally:
        release.set()
        await asyncio.sleep(0.02)
        await owner.close()
    assert owner.retirement_completed


async def test_cancellation_resistant_session_close_retains_borrow(
    authority_case, monkeypatch
):
    c = authority_case
    owner = c.authority.begin_http_operation(c.service, time.monotonic() + 0.1)
    c.owners.append(owner)
    release = asyncio.Event()
    real = owner._identity_session.close

    async def stubborn():
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        await real()

    monkeypatch.setattr(owner._identity_session, "close", stubborn)
    try:
        with pytest.raises(PermissionError):
            await owner.resolve(c.principal)
        assert not owner.retirement_completed and owner._pending is not None
        with pytest.raises(RuntimeError):
            c.service._lease.close()
    finally:
        release.set()
        await asyncio.sleep(0.02)
        await owner.close()
    assert owner.retirement_completed


@pytest.mark.parametrize("after", [False, True])
async def test_captured_session_close_fault_can_retry_only_cleanup(
    authority_case, monkeypatch, after
):
    c = authority_case
    owner = c.authority.begin_http_operation(c.service, time.monotonic() + 2)
    c.owners.append(owner)
    original = owner._identity_session.close

    async def fault():
        if after:
            await original()
        raise RuntimeError("PRIVATE-CLOSE-CANARY")

    with monkeypatch.context() as patch:
        patch.setattr(owner._identity_session, "close", fault)
        with pytest.raises(
            PermissionError, match="^Agent run authority is unavailable[.]$"
        ):
            await owner.resolve(c.principal)
        assert not owner.retirement_completed and owner._failure is not None
        assert c.service._authority_operation is owner
    await owner.close()
    assert owner.retirement_completed
    with pytest.raises(PermissionError):
        owner.bind_request(owner._context)


async def test_copy_cannot_retire_captured_request(authority_case):
    c = authority_case
    owner, request = await c.request()
    with pytest.raises(RuntimeError):
        await copy.copy(owner).close()
    assert c.service._authority_operation is owner
    result = await c.authority.submit(
        c.service, request, task="Plan safely", mode="source_free", request_key="key"
    )
    assert result.state == "queued"


async def test_final_borrow_after_effect_interruption_preserves_completion(
    authority_case, monkeypatch
):
    c = authority_case
    owner, request = await c.request()
    borrow = owner._borrow
    retire = borrow.retire

    class Stop(BaseException):
        pass

    def fault():
        retire()
        raise Stop

    with monkeypatch.context() as patch:
        patch.setattr(borrow, "retire", fault)
        with pytest.raises(Stop):
            await c.authority.submit(
                c.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
        assert borrow.retirement_completed
        assert owner.retirement_completed, (
            "all SQL scopes and final borrow have positively retired"
        )
        assert c.service._authority_operation is None
    await owner.close()


async def test_service_signals_active_cleanup_before_pending_authority_retirement(
    authority_case, monkeypatch
):
    c = authority_case
    owner, _ = await c.request()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def active_work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = c.service._own_task(asyncio.create_task(active_work()))
    c.service._active_task = task
    await entered.wait()

    async def unavailable(**kwargs):
        raise RuntimeError("retirement pending")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner, "close", unavailable)
            with pytest.raises(RuntimeError):
                await c.service.close()
            await asyncio.sleep(0)
            assert cancelled.is_set(), (
                "pending authority cleanup skipped existing model cleanup"
            )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await owner.close()


@pytest.mark.parametrize("which", ["clock", "monotonic", "reference"])
async def test_final_error_response_uses_original_lifetimes(
    authority_case, monkeypatch, which
):
    c = authority_case
    _, run = await submit(c)
    owner, request = await c.request()
    close = owner.close

    async def late_close(**kwargs):
        await close(**kwargs)
        if which == "clock":
            monkeypatch.setattr(
                c.authority, "_clock", lambda: request.token_expires_at + 1
            )
        elif which == "monotonic":
            monkeypatch.setattr(
                c.authority, "_monotonic", lambda: request.operation_deadline + 1
            )
        else:
            # Keep the current token live beyond the short synthetic reference.
            monkeypatch.setattr(c.authority, "_clock", lambda: time.time() + 2)

    if which == "reference":
        with sqlite3.connect(c.store.path) as db:
            expiry = int(time.time()) + 1
            db.execute("UPDATE agent_runs SET expires_at=?", (expiry,))
            db.execute("UPDATE agent_conversations SET expires_at=?", (expiry,))
    monkeypatch.setattr(owner, "close", late_close)
    with pytest.raises(
        PermissionError, match="^Agent run authority is unavailable[.]$"
    ):
        await c.authority.submit(
            c.service, request, task="changed", mode="source_free", request_key="key"
        )
    assert owner.retirement_completed


async def test_pg_settlement_rejects_original_transaction_replacement(
    authority_case, monkeypatch
):
    c = authority_case
    owner, request = await c.request()
    commit = owner._commit_postgres

    async def replace_transaction():
        await owner._transaction.rollback()
        replacement = await owner._connection.begin()
        await owner._connection.execute(text("SELECT 1"))
        await replacement.commit()
        await commit()

    monkeypatch.setattr(owner, "_commit_postgres", replace_transaction)
    with pytest.raises(RuntimeError, match="unavailable"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert not owner.postgres_commit_known and owner.local_commit_known


async def test_metadata_error_is_closed_while_sql_retirement_is_pending(
    authority_case, monkeypatch
):
    c = authority_case
    await submit(c)
    owner, request = await c.request()

    async def fail_close():
        raise RuntimeError("PRIVATE-PG-CLOSE-CANARY")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_close_pg", fail_close)
        with pytest.raises(
            RuntimeError, match="^Agent run authority is unavailable[.]$"
        ):
            await c.authority.submit(
                c.service,
                request,
                task="different",
                mode="source_free",
                request_key="key",
            )
        assert not owner.retirement_completed
    await owner.close()


async def test_local_commit_evidence_precedes_blocked_pg_retirement(
    authority_case, monkeypatch
):
    c = authority_case
    owner, request = await c.request(seconds=0.2)
    release = asyncio.Event()
    entered = asyncio.Event()
    close = owner._close_pg

    async def blocked():
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        await close()

    monkeypatch.setattr(owner, "_close_pg", blocked)
    try:
        with pytest.raises((PermissionError, RuntimeError)):
            await c.authority.submit(
                c.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
        assert entered.is_set() and not owner.retirement_completed
        with sqlite3.connect(c.store.path) as db:
            assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 1
        assert owner.local_commit_attempted and owner.local_commit_known
    finally:
        release.set()
        await asyncio.sleep(0.01)
        await owner.close()


@pytest.mark.parametrize("point", ["before", "after"])
async def test_final_slot_release_failure_keeps_exact_retry_owner(
    authority_case, monkeypatch, point
):
    c = authority_case
    owner, request = await c.request()
    original = c.service._release_authority_operation

    def fault(value):
        if point == "after":
            original(value)
        raise RuntimeError("PRIVATE-SLOT-CANARY")

    with monkeypatch.context() as patch:
        patch.setattr(c.service, "_release_authority_operation", fault)
        with pytest.raises(
            RuntimeError, match="^Agent run authority is unavailable[.]$"
        ):
            await c.authority.submit(
                c.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
        assert owner.retirement_completed
        assert c.service._authority_operation is (owner if point == "before" else None)
    await owner.close()
    assert c.service._authority_operation is None


async def test_competing_close_does_not_reenter_or_quarantine_active_retirement(
    authority_case, monkeypatch
):
    c = authority_case
    owner, request = await c.request()
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = []
    original = owner._close_pg

    async def blocked():
        closed.append("started")
        entered.set()
        await release.wait()
        await original()
        closed.append("finished")

    monkeypatch.setattr(owner, "_close_pg", blocked)
    action = asyncio.create_task(
        c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    )
    try:
        await entered.wait()
        with pytest.raises(RuntimeError, match="busy"):
            await owner.close(deadline=time.monotonic() + 0.01)
        assert not c.service._unhealthy
        assert closed == ["started"] and not owner.retirement_completed
    finally:
        release.set()
        await action
    assert closed == ["started", "finished"] and owner.retirement_completed


@pytest.mark.parametrize("kind", [ValueError, PermissionError])
async def test_infrastructure_exception_never_becomes_domain_message(
    authority_case, monkeypatch, kind
):
    c = authority_case
    owner, request = await c.request()

    async def fault():
        raise kind("PRIVATE-INFRASTRUCTURE-CANARY")

    monkeypatch.setattr(owner, "_commit_postgres", fault)
    with pytest.raises(
        (RuntimeError, PermissionError), match="^Agent run authority is unavailable[.]$"
    ):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert owner.retirement_completed and owner.local_commit_known


@pytest.mark.parametrize("point", ["before", "after"])
async def test_unknown_connect_is_retained_without_replacement(
    authority_case, monkeypatch, point
):
    c = authority_case
    owner, request = await c.request()
    connect = owner._connect

    async def fault():
        if point == "after":
            await connect()
        else:
            owner._connect_attempted = True
        raise RuntimeError("PRIVATE-CONNECT-CANARY")

    monkeypatch.setattr(owner, "_connect", fault)
    with pytest.raises(RuntimeError, match="unavailable"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    if point == "after":
        assert owner.retirement_completed
    else:
        assert (
            not owner.retirement_completed and c.service._authority_operation is owner
        )
        with pytest.raises(RuntimeError):
            await owner.close()
        # This injected before-effect fixture positively owns no acquired handle.
        # Restore only its synthetic uncertainty so teardown can retire it.
        owner._connect_attempted = False
        owner._connection = None
        await owner.close()


@pytest.mark.parametrize("point", ["validated", "local_commit", "pg_commit"])
async def test_caller_cancellation_retains_exact_known_outcome(
    authority_case, monkeypatch, point
):
    c = authority_case
    owner, request = await c.request()
    entered = asyncio.Event()
    release = asyncio.Event()
    original = owner._commit_postgres

    async def held_commit():
        if point == "pg_commit":
            await original()
        entered.set()
        await release.wait()
        if point != "pg_commit":
            await original()

    if point == "validated":
        connect = owner._connect

        async def held_connect():
            await connect()
            entered.set()
            await release.wait()

        monkeypatch.setattr(owner, "_connect", held_connect)
    else:
        monkeypatch.setattr(owner, "_commit_postgres", held_commit)
    task = asyncio.create_task(
        c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    )
    try:
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await owner.close()
        assert owner.retirement_completed
        with sqlite3.connect(c.store.path) as db:
            count = db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
        assert count == (0 if point == "validated" else 1)
        assert owner.local_commit_known == (point != "validated")
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_original_driver_swap_cannot_settle_an_identical_backend_result(
    authority_case, monkeypatch
):
    c = authority_case
    owner, request = await c.request()
    commit = owner._commit_postgres
    async with c.db.bind.connect() as other:
        raw = await other.get_raw_connection()

        async def replace_driver():
            await commit()
            owner._driver = raw.driver_connection
            owner._backend = owner._driver.get_server_pid()

        monkeypatch.setattr(owner, "_commit_postgres", replace_driver)
        with pytest.raises(RuntimeError, match="unavailable"):
            await c.authority.submit(
                c.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
    assert not owner.postgres_commit_known and owner.local_commit_known


@pytest.mark.parametrize("point", ["missing_commit", "future_xid", "invalid_xid"])
async def test_status_evidence_is_original_committed_xid_only(
    authority_case, monkeypatch, point
):
    c = authority_case
    owner, request = await c.request()
    commit = owner._commit_postgres

    async def fault():
        if point == "missing_commit":
            return
        await commit()
        owner._xid = 0 if point == "invalid_xid" else 2**63

    monkeypatch.setattr(owner, "_commit_postgres", fault)
    with pytest.raises(RuntimeError, match="unavailable"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert not owner.postgres_commit_known and owner.local_commit_known


async def test_explicit_cleanup_uses_closed_ordinary_failure(
    authority_case, monkeypatch
):
    c = authority_case
    owner = c.authority.begin_http_operation(c.service, time.monotonic() + 2)
    c.owners.append(owner)

    async def fault():
        raise ValueError("PRIVATE-EXPLICIT-CLEANUP-CANARY")

    with monkeypatch.context() as patch:
        patch.setattr(owner._identity_session, "close", fault)
        with pytest.raises(
            RuntimeError, match="^Agent run authority is unavailable[.]$"
        ):
            await owner.close()
        assert not owner.retirement_completed
    await owner.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer", "\ud800"),
        ("token_expires_at", True),
        ("token_expires_at", float("inf")),
        ("token_expires_at", 1e100),
        ("scopes", frozenset({"shipagent.execute"})),
    ],
)
async def test_private_authority_values_are_closed_and_bounded(
    authority_case, field, value
):
    from dataclasses import replace

    c = authority_case
    owner, request = await c.request()
    with pytest.raises(PermissionError, match="unavailable"):
        replace(request, **{field: value})
    await owner.close()


@pytest.mark.parametrize("after", [False, True])
async def test_exact_native_pg_close_fault_retains_stage_for_retry(
    authority_case, monkeypatch, after
):
    from sqlalchemy.ext.asyncio import AsyncConnection

    c = authority_case
    owner, request = await c.request()
    close = AsyncConnection.close

    async def fault(connection):
        if connection is owner._connection:
            if after:
                await close(connection)
            raise RuntimeError("PRIVATE-NATIVE-CLOSE-CANARY")
        await close(connection)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "close", fault)
        with pytest.raises(
            RuntimeError, match="^Agent run authority is unavailable[.]$"
        ):
            await c.authority.submit(
                c.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
        assert owner.local_commit_known and owner.postgres_commit_known
        assert not owner.retirement_completed
        assert c.service._authority_operation is owner
    await owner.close()
    assert owner.retirement_completed


async def test_task1_failed_rollback_remains_the_http_owners_exact_session(
    authority_case, monkeypatch
):
    from src.control_plane.models import CloudAccount

    c = authority_case
    account = await c.db.get(CloudAccount, c.binding.account_id)
    account.suspended = True
    await c.db.commit()
    owner = c.authority.begin_http_operation(c.service, time.monotonic() + 0.15)
    c.owners.append(owner)
    exact = owner._identity_session
    rollback = exact.rollback
    entered, release = asyncio.Event(), asyncio.Event()

    async def stubborn():
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        await rollback()

    monkeypatch.setattr(exact, "rollback", stubborn)
    try:
        with pytest.raises(PermissionError, match="unavailable"):
            await owner.resolve(c.principal)
        assert entered.is_set() and owner._identity_service.db is exact
        assert (
            owner._identity_service.cleanup_pending and not owner.retirement_completed
        )
    finally:
        release.set()
        await asyncio.sleep(0.01)
        await owner.close()
    assert owner.retirement_completed


async def test_account_lock_precedes_link_lock_and_local_writer_is_nonwaiting(
    authority_case,
):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.control_plane.models import ProviderConnection

    c = authority_case
    owner, request = await c.request()
    factory = async_sessionmaker(c.db.bind, expire_on_commit=False)
    async with factory() as blocker:
        await blocker.execute(
            select(ProviderConnection)
            .where(ProviderConnection.id == c.binding.provider_connection_id)
            .with_for_update()
        )
        task = asyncio.create_task(
            c.authority.submit(
                c.service,
                request,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
        )
        try:
            # The server reports this exact backend waiting for the held link.
            async with factory() as observer:
                for _ in range(100):
                    if owner._backend is not None:
                        waiting = await observer.scalar(
                            text(
                                "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"
                            ),
                            {"pid": owner._backend},
                        )
                        await observer.rollback()
                        if waiting:
                            break
                    await asyncio.sleep(0.005)
                else:
                    pytest.fail("owned backend did not reach the link lock")
                await observer.execute(text("SET LOCAL lock_timeout='30ms'"))
                with pytest.raises(DBAPIError):
                    await observer.execute(
                        text(
                            "SELECT id FROM cloud_accounts WHERE id=:id FOR UPDATE NOWAIT"
                        ),
                        {"id": c.binding.account_id},
                    )
                await observer.rollback()
            with sqlite3.connect(c.store.path, timeout=0) as local:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    local.execute("BEGIN IMMEDIATE")
            await blocker.rollback()
            assert (await task).state == "queued"
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_safe_conflict_requires_original_rollback_not_replacement(
    authority_case, monkeypatch
):
    c = authority_case
    await submit(c)
    owner, request = await c.request()
    original = owner._close_pg

    async def replaced():
        await owner._transaction.rollback()
        await owner._connection.begin()
        await owner._connection.execute(text("SELECT 1"))
        await original()

    monkeypatch.setattr(owner, "_close_pg", replaced)
    with pytest.raises(RuntimeError, match="^Agent run authority is unavailable[.]$"):
        await c.authority.submit(
            c.service, request, task="changed", mode="source_free", request_key="key"
        )
    assert owner.retirement_completed and not owner.local_commit_attempted


async def test_safe_message_after_local_commit_is_still_unavailable(
    authority_case, monkeypatch
):
    from src.services.agent_runs.transaction import AgentRunTransaction

    c = authority_case
    owner, request = await c.request()
    accept = AgentRunTransaction.accept

    def effect_then_denial(tx, **arguments):
        accept(tx, **arguments)
        tx.commit()
        raise ValueError("Request key was already used for a different task.")

    monkeypatch.setattr(AgentRunTransaction, "accept", effect_then_denial)
    with pytest.raises(RuntimeError, match="^Agent run authority is unavailable[.]$"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert owner.local_commit_known and owner.retirement_completed


async def test_safe_precommit_conflict_is_classified_under_original_guards(
    authority_case,
):
    c = authority_case
    await submit(c)
    owner, request = await c.request()
    with pytest.raises(
        ValueError, match="^Request key was already used for a different task[.]$"
    ):
        await c.authority.submit(
            c.service, request, task="changed", mode="source_free", request_key="key"
        )
    assert not owner.local_commit_attempted and owner.retirement_completed
    assert (
        await c.db.scalar(
            text("SELECT pg_xact_status(CAST(:x AS xid8))"), {"x": owner.original_xid}
        )
        == "aborted"
    )
    await c.db.rollback()


async def test_copied_service_cannot_bypass_the_shared_operation_slot(authority_case):
    c = authority_case
    copied = copy.copy(c.service)
    try:
        with pytest.raises(RuntimeError, match="unavailable"):
            c.authority.begin_http_operation(copied, time.monotonic() + 2)
        assert c.service._authority_operation is None
    finally:
        if copied._authority_operation is not None:
            await copied._authority_operation.close()


@pytest.mark.parametrize("clock_name", ["_clock", "_monotonic"])
async def test_worker_admission_clock_failure_is_closed_before_ownership(
    authority_case, monkeypatch, clock_name
):
    from tests.control_plane.persistence.test_agent_run_authority import claim_candidate

    c = authority_case
    await submit(c)
    run = claim_candidate(c)

    def unavailable_clock():
        raise ValueError("PRIVATE-WORKER-CLOCK-CANARY")

    with monkeypatch.context() as patch:
        patch.setattr(c.authority, clock_name, unavailable_clock)
        with pytest.raises(
            PermissionError, match="^Agent run authority is unavailable[.]$"
        ):
            await c.authority.admit_dispatch(c.service, run)
        assert c.service._authority_operation is None
        assert c.service._authority_dispatch_run is None


@pytest.mark.parametrize("status", [None, "in progress", "unsupported"])
async def test_noncommitted_status_result_is_never_settlement(
    authority_case, monkeypatch, status
):
    c = authority_case
    owner, request = await c.request()
    query = owner._query
    observed = []

    def changed_status(sync, statement, parameters=None):
        row = query(sync, statement, parameters)
        if "pg_xact_status" in str(statement):
            assert row["status"] == "committed"
            observed.append(status)
            return {**row, "status": status}
        return row

    monkeypatch.setattr(owner, "_query", changed_status)
    with pytest.raises(RuntimeError, match="^Agent run authority is unavailable[.]$"):
        await c.authority.submit(
            c.service,
            request,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert observed == [status]
    assert owner.local_commit_known and not owner.postgres_commit_known
    assert owner.retirement_completed
