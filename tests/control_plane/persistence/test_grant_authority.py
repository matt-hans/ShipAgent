"""Dormant authority proof uses real disposable Redis and PostgreSQL."""

import asyncio
import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_grants import ExecutionGrantDenial, ExecutionGrantError
from src.control_plane.redis_keys import RedisKey
from src.control_plane.relay.protocol import relay_invocation_input_hash
from tests.control_plane.persistence.test_postgres_ledger import seed


def purchase(data, **changes):
    from src.control_plane.grant_models import ApprovedPurchase

    values = {
        "account_id": data.account_id,
        "provider_connection_id": data.provider_connection_id,
        "execution_target_id": "relay:relay_device_" + "a" * 32,
        "execution_target_fingerprint_hash": "f" * 64,
        "preview_id": "sa_preview_" + "b" * 32,
        "tool_name": "execute_shipments",
        "prepare_tool": "prepare_shipments",
        "policy": "priced_preview",
        "amount": "12.00",
        "currency_code": "USD",
        "preview_hash": "c" * 64,
        "arguments_hash": relay_invocation_input_hash("execute_shipments", {}),
    }
    values.update(changes)
    return ApprovedPurchase(**values)


class LivePreview:
    def __init__(self, value):
        self.value = value

    async def resolve(self, **kwargs):
        return self.value


async def setup_authority(redis, session, **options):
    from src.control_plane.grant_ledger import GrantLedger
    from src.control_plane.redis_grant_authority import RedisExecutionGrantAuthority

    data = await seed(session)
    context = AuthorizationContext(
        account_id=data.account_id,
        provider_connection_id=data.provider_connection_id,
        provider_surface="test",
        subject="test-fixture|" + data.account_id,
        client_id="test-client",
        scopes=frozenset(),
    )
    preview = LivePreview(purchase(data))
    ledger = GrantLedger(async_sessionmaker(session.bind, expire_on_commit=False))
    authority = RedisExecutionGrantAuthority(
        redis_client=redis, ledger=ledger, live_preview=preview, **options
    )
    approval = await authority.issue_approved(
        context=context,
        purchase=preview.value,
        approving_subject_hash=hashlib.sha256(context.subject.encode()).hexdigest(),
    )
    return authority, context, preview, approval


async def reserve(authority, context, preview, approval):
    return await authority.reserve(
        context=context,
        tool_name=preview.value.tool_name,
        prepare_tool=preview.value.prepare_tool,
        approval_request_id=approval,
        preview_id=preview.value.preview_id,
    )


async def test_real_authority_atomic_reservation_and_original_ttl(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    key = RedisKey.execution_grant(approval)
    expiry = await real_redis.pexpiretime(key)
    results = await asyncio.gather(
        *(reserve(authority, context, preview, approval) for _ in range(8)),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1
    assert all(
        r.denial == ExecutionGrantDenial.GRANT_IN_USE
        for r in results
        if isinstance(r, Exception)
    )
    assert winners[0].binding.amount == "12.00"
    assert await real_redis.pexpiretime(key) == expiry
    assert 0 < await real_redis.pttl(key) <= 900000


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "11.00"},
        {"amount": "13.00"},
        {"currency_code": "EUR"},
        {"preview_hash": "d" * 64},
        {"arguments_hash": "sha256:" + "e" * 64},
        {"execution_target_id": "relay:relay_device_" + "f" * 32},
        {"policy": "other_policy"},
    ],
)
async def test_live_binding_drift_including_lower_price_denies(
    real_redis, postgres_db, changes
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    preview.value = preview.value.model_copy(update=changes)
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == ExecutionGrantDenial.PREVIEW_CHANGED


async def test_ledger_is_hashed_and_committed_before_executable_state(
    real_redis, postgres_db
):
    from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    rows = (
        await postgres_db.scalars(select(ControlPlaneAuthorizationLedgerEvent))
    ).all()
    assert {row.grant_transition for row in rows} >= {"approved", "reserved"}
    assert all(row.approval_request_id == approval for row in rows)
    assert all(
        row.idempotency_key_hash
        == hashlib.sha256(reservation.binding.idempotency_key.encode()).hexdigest()
        for row in rows
    )
    assert all(row.authorized_amount_minor == 1200 for row in rows)
    assert context.subject not in repr([row.__dict__ for row in rows])
    assert reservation.binding.idempotency_key not in repr(
        [row.__dict__ for row in rows]
    )


async def test_hold_blocks_ordinary_release_and_missing_state_never_remints(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    await reservation.hold_for_reconciliation()
    await reservation.release()
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == ExecutionGrantDenial.RECONCILIATION_PENDING
    await real_redis.delete(RedisKey.execution_grant(approval))
    await reservation.release()
    await reservation.hold_for_reconciliation()
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == ExecutionGrantDenial.GRANT_UNAVAILABLE
    assert not await real_redis.exists(RedisKey.execution_grant(approval))


async def test_positive_preaccept_release_changes_owner_and_stale_callbacks_deny(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    first = await reserve(authority, context, preview, approval)
    await first.release()
    second = await reserve(authority, context, preview, approval)
    assert second.binding.reservation_token != first.binding.reservation_token
    await first.hold_for_reconciliation()
    await first.release()
    with pytest.raises(ExecutionGrantError):
        await authority.callbacks_for_binding(
            context=context, approval_request_id=approval, binding=first.binding
        )
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == ExecutionGrantDenial.GRANT_IN_USE


async def test_sql_revocation_denies_new_enabling_transitions(real_redis, postgres_db):
    from src.control_plane.models import ProviderConnection

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    connection = await postgres_db.get(
        ProviderConnection, context.provider_connection_id
    )
    connection.status = "revoked"
    await postgres_db.commit()
    with pytest.raises(ExecutionGrantError):
        await reserve(authority, context, preview, approval)


async def test_failed_ledger_commit_does_not_publish_reservation(
    real_redis, postgres_db, monkeypatch
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    key = RedisKey.execution_grant(approval)
    original = await real_redis.get(key)

    async def unavailable(*args, **kwargs):
        raise RuntimeError("PRIVATE_DATABASE_CANARY")

    monkeypatch.setattr(authority.ledger, "enable", unavailable)
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert "PRIVATE_DATABASE_CANARY" not in str(error.value)
    assert await real_redis.get(key) == original


@pytest.mark.parametrize("after_write", [False, True])
async def test_reserve_cancellation_before_or_after_write_never_returns_owner(
    real_redis, postgres_db, monkeypatch, after_write
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db, io_timeout=0.2
    )
    original = authority.state.replace_existing
    entered = asyncio.Event()

    async def interrupted(*args, **kwargs):
        if after_write:
            await original(*args, **kwargs)
        entered.set()
        await asyncio.sleep(10)

    monkeypatch.setattr(authority.state, "replace_existing", interrupted)
    task = asyncio.create_task(reserve(authority, context, preview, approval))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    monkeypatch.setattr(authority.state, "replace_existing", original)
    if after_write:
        with pytest.raises(ExecutionGrantError) as error:
            await reserve(authority, context, preview, approval)
        assert error.value.denial == ExecutionGrantDenial.GRANT_IN_USE
    else:
        assert await reserve(authority, context, preview, approval)


async def test_lost_reserve_reply_and_expired_lease_never_reenable(
    real_redis, postgres_db, monkeypatch
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db, lease_seconds=0.03
    )
    original = authority.state.replace_existing

    async def lost(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("PRIVATE_REDIS_CANARY")

    monkeypatch.setattr(authority.state, "replace_existing", lost)
    with pytest.raises(ExecutionGrantError):
        await reserve(authority, context, preview, approval)
    monkeypatch.setattr(authority.state, "replace_existing", original)
    await asyncio.sleep(0.04)
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial in {
        ExecutionGrantDenial.GRANT_IN_USE,
        ExecutionGrantDenial.RECONCILIATION_PENDING,
    }


async def test_terminal_revoke_fences_delayed_release(real_redis, postgres_db):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    await authority.revoke(context=context, approval_request_id=approval)
    await reservation.release()
    await reservation.hold_for_reconciliation()
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == ExecutionGrantDenial.APPROVAL_REJECTED


async def test_cancelled_reserve_remote_write_after_account_deletion_cannot_revive(
    real_redis, postgres_db, monkeypatch
):
    from src.control_plane.accounts.service import CloudAccountDeletionService

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    real_eval = real_redis.eval
    entered, finish = asyncio.Event(), asyncio.Event()
    remote_writes = []

    async def delayed(script, *args):
        if "KEEPTTL" in script and '"status":"reserved"' in str(args):

            async def remote():
                await finish.wait()
                return await real_eval(script, *args)

            task = asyncio.create_task(remote())
            remote_writes.append(task)
            entered.set()
            return await asyncio.shield(task)
        return await real_eval(script, *args)

    monkeypatch.setattr(real_redis, "eval", delayed)
    request = asyncio.create_task(reserve(authority, context, preview, approval))
    await asyncio.wait_for(entered.wait(), 1)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    # Allow the SQL transaction's cancellation cleanup to release its account lock.
    async with authority.ledger.sessions() as session:
        await CloudAccountDeletionService.delete_account(
            session=session,
            account_id=context.account_id,
            actor_id_hash="e" * 64,
            state_store=authority.state,
        )
        await session.commit()
    finish.set()
    assert await asyncio.wait_for(asyncio.gather(*remote_writes), 1) == [0]
    assert not await real_redis.exists(RedisKey.execution_grant(approval))
    with pytest.raises(ExecutionGrantError):
        await reserve(authority, context, preview, approval)


async def test_consume_requires_persisted_exact_acceptance(real_redis, postgres_db):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    with pytest.raises(ExecutionGrantError):
        await reservation.consume()
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == ExecutionGrantDenial.GRANT_IN_USE


@pytest.mark.parametrize("failure_at", ["flush", "commit"])
async def test_real_sql_transaction_failure_prevents_reserve_cas(
    real_redis, postgres_db, monkeypatch, failure_at
):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    from src.control_plane.audit.authorization_ledger import AuthorizationLedgerService

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    original_value = await real_redis.get(RedisKey.execution_grant(approval))
    engine = postgres_db.bind.sync_engine

    def commit_failure(connection):
        raise SQLAlchemyError("PRIVATE_COMMIT_CANARY")

    if failure_at == "flush":
        original_record = AuthorizationLedgerService.record

        async def failed_flush(**kwargs):
            await original_record(**kwargs)  # Real INSERT/flush, then fail transaction.
            raise SQLAlchemyError("PRIVATE_FLUSH_CANARY")

        monkeypatch.setattr(AuthorizationLedgerService, "record", failed_flush)
    else:
        event.listen(engine, "commit", commit_failure)
    try:
        with pytest.raises(ExecutionGrantError):
            await reserve(authority, context, preview, approval)
    finally:
        if failure_at == "commit":
            event.remove(engine, "commit", commit_failure)
    assert await real_redis.get(RedisKey.execution_grant(approval)) == original_value


async def test_late_pending_create_after_delete_is_inert_and_cannot_activate(
    real_redis, postgres_db, monkeypatch
):
    import json

    from src.control_plane.accounts.service import CloudAccountDeletionService

    authority, context, preview, old_approval = await setup_authority(
        real_redis, postgres_db
    )
    original_create = authority.state.create
    entered, finish = asyncio.Event(), asyncio.Event()
    writes = []
    pending = []

    async def late_create(kind, record):
        if kind == "execution_grant":
            pending.append(record)

            async def remote():
                await finish.wait()
                return await original_create(kind, record)

            task = asyncio.create_task(remote())
            writes.append(task)
            entered.set()
            return await asyncio.shield(task)
        return await original_create(kind, record)

    monkeypatch.setattr(authority.state, "create", late_create)
    request = asyncio.create_task(
        authority.issue_approved(
            context=context,
            purchase=preview.value,
            approving_subject_hash=hashlib.sha256(context.subject.encode()).hexdigest(),
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    async with authority.ledger.sessions() as session:
        await CloudAccountDeletionService.delete_account(
            session=session,
            account_id=context.account_id,
            actor_id_hash="e" * 64,
            state_store=authority.state,
        )
        await session.commit()
    finish.set()
    assert await asyncio.wait_for(asyncio.gather(*writes), 1) == [True]
    key = RedisKey.execution_grant(pending[0].metadata.approval_request_id)
    assert json.loads(await real_redis.get(key))["grant"]["status"] == "pending"
    with pytest.raises(ExecutionGrantError):
        await reserve(
            authority, context, preview, pending[0].metadata.approval_request_id
        )
    assert not await real_redis.exists(RedisKey.execution_grant(old_approval))


async def test_binding_repr_excludes_private_owner_and_purchase_key(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    assert reservation.binding.reservation_token not in repr(reservation.binding)
    assert reservation.binding.idempotency_key not in repr(reservation.binding)


async def test_fresh_id_collision_with_old_request_cannot_remint_missing_grant(
    real_redis, postgres_db, monkeypatch
):
    from src.control_plane import redis_grant_authority

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    grant_key = RedisKey.execution_grant(approval)
    request_key = RedisKey.approval_request(approval)
    original_request = await real_redis.get(request_key)
    original_expiry = await real_redis.pexpiretime(request_key)
    await real_redis.delete(grant_key)
    original_hex = redis_grant_authority.secrets.token_hex
    monkeypatch.setattr(
        redis_grant_authority.secrets,
        "token_hex",
        lambda size: approval.removeprefix("sa_approval_request_")
        if size == 16
        else original_hex(size),
    )
    with pytest.raises(ExecutionGrantError):
        await authority.issue_approved(
            context=context,
            purchase=preview.value,
            approving_subject_hash=hashlib.sha256(context.subject.encode()).hexdigest(),
        )
    assert not await real_redis.exists(grant_key)
    assert await real_redis.get(request_key) == original_request
    assert await real_redis.pexpiretime(request_key) == original_expiry


async def test_corrupt_approved_dispatch_claim_is_denied_not_normalized(
    real_redis, postgres_db
):
    import json

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    key = RedisKey.execution_grant(approval)
    raw = json.loads(await real_redis.get(key))
    raw["grant"]["dispatch_claimed"] = True
    await real_redis.set(
        key,
        json.dumps(raw, sort_keys=True, separators=(",", ":")),
        xx=True,
        keepttl=True,
    )
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == "execution_grant_unavailable"
    assert json.loads(await real_redis.get(key))["grant"]["status"] == "approved"


async def test_live_target_fingerprint_replacement_under_same_target_id_denies(
    real_redis, postgres_db
):
    from src.control_plane.grant_models import ApprovedPurchase

    assert "execution_target_fingerprint_hash" in ApprovedPurchase.model_fields
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    original_target = preview.value.execution_target_id
    preview.value = preview.value.model_copy(
        update={"execution_target_fingerprint_hash": "e" * 64}
    )
    assert preview.value.execution_target_id == original_target
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == "preview_changed"


async def test_authority_ledger_and_lifecycle_bind_actual_target_fingerprint(
    real_redis, postgres_db
):
    from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent
    from src.control_plane.grant_models import ApprovedPurchase

    assert "execution_target_fingerprint_hash" in ApprovedPurchase.model_fields
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    expected = preview.value.execution_target_fingerprint_hash
    assert (
        reservation.identity.execution_target_fingerprint_hash == "sha256:" + expected
    )
    rows = (
        await postgres_db.scalars(select(ControlPlaneAuthorizationLedgerEvent))
    ).all()
    assert all(row.execution_target_fingerprint_hash == expected for row in rows)
    assert (
        expected
        != hashlib.sha256(preview.value.execution_target_id.encode()).hexdigest()
    )
