"""Real PostgreSQL settlement composes with an owned local Agent Run writer."""

import asyncio
import copy
import importlib
import importlib.util
import sqlite3
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.models import CloudAccount, ProviderConnection
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from tests.control_plane.auth.test_service import (
    STRICT_ISSUER,
    strict_request,
    strict_service,
)


def authority_module():
    name = "src.control_plane.agent_run_authority"
    assert importlib.util.find_spec(name) is not None, (
        "missing captured PostgreSQL authority owner"
    )
    return importlib.import_module(name)


def test_captured_postgres_authority_is_available():
    assert callable(getattr(authority_module(), "PostgresAgentRunAuthority", None))


@pytest.fixture
async def authority_case(postgres_db, tmp_path):
    binding = await strict_service(postgres_db).resolve(**strict_request())
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id=binding.account_id,
        execution_target_id="target",
        create=True,
    )

    def no_provider(_):
        pytest.fail("Task 3 must not dispatch a model")

    service = AgentRunService(store=store, provider_factory=no_provider)
    await service.start()
    await asyncio.sleep(0)  # Existing worker is idle; Task 4 will own strict routing.
    owners = []
    case = SimpleNamespace(
        db=postgres_db, store=store, service=service, binding=binding, owners=owners
    )
    try:
        cls = authority_module().PostgresAgentRunAuthority
        case.authority = cls(
            engine=postgres_db.bind,
            account_id=binding.account_id,
            execution_target_id="target",
            issuer=STRICT_ISSUER,
            clients={"chatgpt-client": "chatgpt"},
        )
        case.principal = TokenPrincipal(
            subject="strict-owner",
            client_id="chatgpt-client",
            scopes=frozenset({"shipagent.status", "shipagent.preview"}),
            issuer=STRICT_ISSUER,
            issued_at=time.time() - 5,
            expires_at=time.time() + 90,
            issuer_link_id="link_a",
        )

        async def request(*, principal=None, seconds=2):
            owner = case.authority.begin_http_operation(
                service, time.monotonic() + seconds
            )
            owners.append(owner)
            context = await owner.resolve(principal or case.principal)
            return owner, owner.bind_request(context)

        case.request = request
        yield case
    finally:
        for owner in reversed(owners):
            await owner.close()
        await service.close()


async def submit(case, *, key="key", task="Plan safely"):
    owner, authority = await case.request()
    result = await case.authority.submit(
        case.service, authority, task=task, mode="source_free", request_key=key
    )
    return owner, result


async def test_real_authority_commit_and_same_key_recovery(authority_case):
    c = authority_case
    owner, run = await submit(c)
    assert run.link_epoch == c.binding.link_epoch
    assert run.turn_authority_expires_at == c.principal.expires_at
    assert owner.local_commit_known and owner.postgres_commit_known
    assert owner.retirement_completed
    assert (
        await c.db.scalar(
            text("SELECT pg_xact_status(CAST(:x AS xid8))"), {"x": owner.original_xid}
        )
        == "committed"
    )
    await c.db.rollback()
    _, retried = await submit(c)
    assert retried.run_reference == run.run_reference
    assert retried.turn_authority_expires_at == run.turn_authority_expires_at
    with sqlite3.connect(c.store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 1


async def test_slot_and_coordinator_are_pinned_before_identity_io(authority_case):
    c = authority_case
    owner = c.authority.begin_http_operation(c.service, time.monotonic() + 2)
    c.owners.append(owner)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="busy"):
        c.authority.begin_http_operation(c.service, time.monotonic() + 2)
    assert time.monotonic() - start < 0.1
    with pytest.raises(RuntimeError):
        c.service._lease.close()
    await owner.close()
    assert owner.retirement_completed


@pytest.mark.parametrize(
    "change", ["epoch", "revoked", "scopes", "suspended", "issuer"]
)
async def test_current_postgres_authority_denies_before_local_effect(
    authority_case, change
):
    c = authority_case
    owner, authority = await c.request()
    field, value = {
        "epoch": ("link_epoch", "new-epoch"),
        "revoked": ("status", "revoked"),
        "scopes": ("allowed_scopes_text", "shipagent.status"),
        "suspended": ("suspended", True),
        "issuer": ("issuer", "https://other.invalid/"),
    }[change]
    model = CloudAccount if change in {"suspended", "issuer"} else ProviderConnection
    identity = (
        c.binding.account_id
        if model is CloudAccount
        else c.binding.provider_connection_id
    )
    row = await c.db.get(model, identity)
    setattr(row, field, value)
    await c.db.commit()
    with pytest.raises(PermissionError, match="unavailable"):
        await c.authority.submit(
            c.service,
            authority,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    assert owner.retirement_completed and not owner.local_commit_attempted
    with sqlite3.connect(c.store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0


async def test_request_identity_cannot_be_copied_or_adopted(authority_case):
    c = authority_case
    owner, authority = await c.request()
    with pytest.raises(PermissionError):
        await c.authority.submit(
            c.service,
            copy.copy(authority),
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )
    await owner.close()
    with pytest.raises(PermissionError):
        await c.authority.submit(
            c.service,
            authority,
            task="Plan safely",
            mode="source_free",
            request_key="key",
        )


async def test_pg_lock_wait_preserves_heartbeat_and_prompt_busy(authority_case):
    c = authority_case
    owner, authority = await c.request()
    factory = async_sessionmaker(c.db.bind, expire_on_commit=False)
    async with factory() as blocker:
        await blocker.execute(
            select(CloudAccount)
            .where(CloudAccount.id == c.binding.account_id)
            .with_for_update()
        )
        task = asyncio.create_task(
            c.authority.submit(
                c.service,
                authority,
                task="Plan safely",
                mode="source_free",
                request_key="key",
            )
        )
        try:
            ticks = 0
            for _ in range(5):
                await asyncio.sleep(0.01)
                ticks += 1
            assert ticks == 5 and not task.done()
            with pytest.raises(RuntimeError, match="busy"):
                c.authority.begin_http_operation(c.service, time.monotonic() + 2)
            await blocker.rollback()
            run = await task
            assert run.state == "queued"
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_read_and_cancel_reauthorize_with_current_request(authority_case):
    c = authority_case
    _, run = await submit(c)
    owner, request = await c.request()
    read = await c.authority.read(c.service, request, run_reference=run.run_reference)
    assert read.run_reference == run.run_reference and owner.postgres_commit_known
    owner, request = await c.request()
    cancelled = await c.authority.cancel(
        c.service, request, run_reference=run.run_reference
    )
    assert cancelled.state == "cancelled" and owner.postgres_commit_known


def claim_candidate(case):
    borrow, generation = case.service.borrow_coordinator()
    tx = case.store.transaction(
        borrow=borrow, generation=generation, monotonic=time.monotonic
    )
    try:
        tx.acquire(deadline=time.monotonic() + 2)
        run = tx.claim()
        tx.commit()
        case.service._active_run = run
        return run
    finally:
        tx.retire()
        borrow.retire()


async def test_dispatch_returns_private_one_shot_only_after_settlement(authority_case):
    c = authority_case
    await submit(c)
    run = claim_candidate(c)
    assert callable(getattr(c.authority, "admit_dispatch", None)), (
        "missing owned dispatch authority"
    )
    result = await c.authority.admit_dispatch(c.service, run)
    assert result.private_history_json == b"[]"
    assert "private_history" not in repr(result)
    assert c.service._authority_operation is None
    provider_owner = object()
    result.permit.bind_provider_owner(c.service, run, provider_owner)
    with pytest.raises(PermissionError):
        result.permit.consume(c.service, run, object())
    with pytest.raises(PermissionError):
        copy.copy(result.permit).consume(c.service, run, provider_owner)
    result.permit.consume(c.service, run, provider_owner)
    with pytest.raises(PermissionError):
        result.permit.consume(c.service, run, provider_owner)
    with pytest.raises(PermissionError):
        await c.authority.admit_dispatch(c.service, run)


async def test_publication_and_continuation_use_current_owned_authority(authority_case):
    c = authority_case
    await submit(c)
    run = claim_candidate(c)
    assert callable(getattr(c.authority, "publish", None)), (
        "missing owned publication authority"
    )
    await c.authority.publish(
        c.service,
        run,
        outcome="clarification_required",
        private_history=[{"role": "user", "content": "private canary"}],
        clarification="package_scope",
    )
    owner, request = await c.request()
    next_run = await c.authority.continue_turn(
        c.service,
        request,
        conversation_reference=run.conversation_reference,
        run_reference=run.run_reference,
        expected_revision=1,
        task="One package",
        request_key="next",
    )
    assert next_run.revision == 2 and next_run.expires_at == run.expires_at
    claimed = claim_candidate(c)
    dispatched = await c.authority.admit_dispatch(c.service, claimed)
    assert b"private canary" in dispatched.private_history_json
    assert "private canary" not in repr(dispatched)


@pytest.mark.parametrize("which", ["dispatch", "publish"])
async def test_worker_current_link_revocation_denies(authority_case, which):
    c = authority_case
    await submit(c)
    run = claim_candidate(c)
    await strict_service(c.db).revoke_link(
        c.binding.account_id, c.binding.provider_connection_id
    )
    method = getattr(
        c.authority, "admit_dispatch" if which == "dispatch" else "publish", None
    )
    assert callable(method), "missing worker authority action"
    arguments = (
        {}
        if which == "dispatch"
        else {"outcome": "planning_completed", "private_history": []}
    )
    with pytest.raises(PermissionError, match="unavailable"):
        await method(c.service, run, **arguments)
    with sqlite3.connect(c.store.path) as db:
        assert db.execute("SELECT state FROM agent_runs").fetchone()[0] == "running"


async def test_dispatch_permit_denies_foreign_thread_before_consumption(authority_case):
    import threading

    c = authority_case
    await submit(c)
    run = claim_candidate(c)
    result = await c.authority.admit_dispatch(c.service, run)
    owner = object()
    result.permit.bind_provider_owner(c.service, run, owner)
    outcomes = []

    def consume():
        try:
            result.permit.consume(c.service, run, owner)
        except PermissionError:
            outcomes.append("denied")
        else:
            outcomes.append("consumed")

    thread = threading.Thread(target=consume)
    thread.start()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert outcomes == ["denied"]
    result.permit.consume(c.service, run, owner)
