"""Real PostgreSQL migration, strict ledger, retention and account cleanup."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from src.control_plane.models import CloudAccount, ProviderConnection
from tests.control_plane.persistence.test_contract import metadata


async def seed(session, **changes):
    data = metadata(**changes)
    session.add(
        CloudAccount(
            id=data.account_id, auth0_subject="test-fixture|" + data.account_id
        )
    )
    await session.flush()
    session.add(
        ProviderConnection(
            id=data.provider_connection_id,
            account_id=data.account_id,
            client_id="test-client",
            surface="test",
        )
    )
    await session.commit()
    return data


async def record(session, data, **changes):
    from src.control_plane.audit.authorization_ledger import AuthorizationLedgerService

    event = await AuthorizationLedgerService.record(
        session=session,
        metadata=data,
        event_type="execution_grant_transition",
        grant_transition="approved",
        **changes,
    )
    await session.commit()
    return event


async def test_postgresql_forward_and_backward_migrations_match_namespace(
    disposable_control_stores,
):
    from src.control_plane.audit.models import (
        ControlPlaneAuthorizationLedgerEvent,
        ControlPlaneLegalHold,
    )

    repo = Path(__file__).resolve().parents[3]
    config = Config(str(repo / "alembic.ini"))
    config.set_main_option("script_location", str(repo / "alembic"))
    config.set_main_option("sqlalchemy.url", disposable_control_stores["postgres_url"])
    config.set_section_option(
        "alembic:runtime", "shipagent_control_plane_schema", "issue64_migration"
    )
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(disposable_control_stores["postgres_url"])
    async with engine.connect() as connection:
        names = await connection.run_sync(
            lambda sync: inspect(sync).get_table_names(schema="issue64_migration")
        )
        assert {"authorization_ledger_events", "legal_holds"} <= set(names)
        for model in (ControlPlaneAuthorizationLedgerEvent, ControlPlaneLegalHold):
            columns = await connection.run_sync(
                lambda sync, model=model: inspect(sync).get_columns(
                    model.__tablename__, schema="issue64_migration"
                )
            )
            assert {c["name"] for c in columns} == set(model.__table__.columns.keys())
    await engine.dispose()
    await asyncio.to_thread(command.downgrade, config, "20260723_0003")
    await asyncio.to_thread(command.upgrade, config, "head")


async def test_ledger_only_stores_allowlisted_hashes_and_references(
    postgres_db, caplog
):
    from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent

    data = await seed(postgres_db)
    event = await record(postgres_db, data, result_category="success")
    row = await postgres_db.get(ControlPlaneAuthorizationLedgerEvent, event.id)
    assert row.preview_hash == data.preview_hash
    assert row.authorized_amount_minor == 1200
    assert row.currency == "USD"
    assert row.approval_request_id == data.approval_request_id
    assert set(row.__table__.columns.keys()) == {
        "id",
        "event_type",
        "account_id",
        "provider_connection_id",
        "approval_request_id",
        "preview_hash",
        "purchase_scope_hash",
        "authorized_amount_minor",
        "currency",
        "approving_subject_hash",
        "execution_target_fingerprint_hash",
        "grant_transition",
        "idempotency_key_hash",
        "result_category",
        "correlation_id",
        "created_at",
    }
    assert not caplog.records


async def test_cross_account_connection_and_unrecognized_codes_are_rejected(
    postgres_db,
):
    from dataclasses import replace

    from src.control_plane.audit.authorization_ledger import AuthorizationLedgerService

    first, other = await seed(postgres_db), await seed(postgres_db)
    with pytest.raises(ValueError):
        await record(
            postgres_db,
            replace(first, provider_connection_id=other.provider_connection_id),
        )
    for changes in (
        {"event_type": "SECRET_CANARY"},
        {"grant_transition": "SECRET_CANARY"},
        {"result_category": "SECRET_CANARY"},
    ):
        args = {
            "event_type": "execution_grant_transition",
            "grant_transition": "approved",
            **changes,
        }
        with pytest.raises(ValueError) as error:
            await AuthorizationLedgerService.record(
                session=postgres_db, metadata=first, **args
            )
        assert "SECRET_CANARY" not in str(error.value)


async def test_sql_failure_is_sanitized_and_not_silently_successful(
    postgres_db, caplog
):
    from src.control_plane.audit.authorization_ledger import (
        AuthorizationLedgerError,
        AuthorizationLedgerService,
    )

    data = await seed(postgres_db)
    await postgres_db.execute(text("DROP TABLE authorization_ledger_events"))
    await postgres_db.commit()
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AuthorizationLedgerError) as error:
            await AuthorizationLedgerService.record(
                session=postgres_db,
                metadata=data,
                event_type="approval_request_created",
            )
    await postgres_db.rollback()
    assert str(error.value) == "authorization_ledger_unavailable"
    assert data.approval_request_id not in caplog.text


async def test_retention_and_explicit_audited_hold_release(postgres_db):
    from src.control_plane.audit.models import (
        ControlPlaneAuditEvent,
        ControlPlaneAuthorizationLedgerEvent,
        ControlPlaneLegalHold,
    )
    from src.control_plane.retention.legal_hold import LegalHoldService
    from src.control_plane.retention.sql_purge import purge_expired_authorization_audit

    old, held, fresh = [await seed(postgres_db) for _ in range(3)]
    for data in (old, held, fresh):
        await record(postgres_db, data)
    now = datetime.now(UTC)
    await postgres_db.execute(
        update(ControlPlaneAuthorizationLedgerEvent)
        .where(
            ControlPlaneAuthorizationLedgerEvent.account_id.in_(
                [old.account_id, held.account_id]
            )
        )
        .values(created_at=now - timedelta(days=91))
    )
    hold = await LegalHoldService.place(
        session=postgres_db,
        account_id=held.account_id,
        reason_hash="a" * 64,
        actor_id_hash="b" * 64,
    )
    await postgres_db.commit()
    result = await purge_expired_authorization_audit(
        session=postgres_db, retention_days=90, now=now
    )
    await postgres_db.commit()
    assert result.authorization_ledger_events_deleted == 1
    assert (
        await postgres_db.scalar(
            select(func.count()).select_from(ControlPlaneAuthorizationLedgerEvent)
        )
        == 2
    )
    assert (
        await postgres_db.scalar(
            select(func.count())
            .select_from(ControlPlaneAuditEvent)
            .where(ControlPlaneAuditEvent.event_type == "legal_hold_placed")
        )
        == 1
    )
    await LegalHoldService.release(
        session=postgres_db, hold_id=hold.id, actor_id_hash="b" * 64
    )
    await postgres_db.commit()
    result = await purge_expired_authorization_audit(
        session=postgres_db, retention_days=90, now=now + timedelta(days=92)
    )
    await postgres_db.commit()
    assert result.authorization_ledger_events_deleted == 2
    assert (
        await postgres_db.scalar(
            select(func.count()).select_from(ControlPlaneLegalHold)
        )
        == 0
    )
    assert (
        await postgres_db.scalar(
            select(func.count()).select_from(ControlPlaneAuditEvent)
        )
        == 0
    )


async def test_cleanup_cannot_bypass_legal_hold_and_deletion_cleans_released_holds(
    postgres_db, real_redis
):
    from src.control_plane.accounts.service import CloudAccountDeletionService
    from src.control_plane.audit.authorization_ledger import AuthorizationLedgerService
    from src.control_plane.audit.models import ControlPlaneLegalHold
    from src.control_plane.authorization_state import (
        AuthorizationState,
        AuthorizationStateStore,
    )
    from src.control_plane.retention.legal_hold import LegalHoldService

    data, other = await seed(postgres_db), await seed(postgres_db)
    await record(postgres_db, data)
    await record(postgres_db, other)
    store = AuthorizationStateStore(real_redis)
    await store.create(
        "approval_request", AuthorizationState.new(metadata=data, now=datetime.now(UTC))
    )
    hold = await LegalHoldService.place(
        session=postgres_db,
        account_id=data.account_id,
        reason_hash="a" * 64,
        actor_id_hash="b" * 64,
    )
    await postgres_db.commit()
    with pytest.raises(PermissionError):
        await AuthorizationLedgerService.cleanup_for_account(
            session=postgres_db, account_id=data.account_id
        )
    with pytest.raises(PermissionError):
        await CloudAccountDeletionService.delete_account(
            session=postgres_db,
            account_id=data.account_id,
            actor_id_hash="c" * 64,
            state_store=store,
        )
    hold_id = hold.id
    await postgres_db.rollback()
    await LegalHoldService.release(
        session=postgres_db, hold_id=hold_id, actor_id_hash="b" * 64
    )
    await postgres_db.commit()
    result = await CloudAccountDeletionService.delete_account(
        session=postgres_db,
        account_id=data.account_id,
        actor_id_hash="c" * 64,
        state_store=store,
    )
    await postgres_db.commit()
    assert result.account_deleted
    assert result.authorization_ledger_events_deleted == 1
    assert not await real_redis.keys("sa:approval:*")
    assert await postgres_db.get(CloudAccount, data.account_id) is None
    assert await postgres_db.get(CloudAccount, other.account_id) is not None
    assert (
        await postgres_db.scalar(
            select(func.count()).select_from(ControlPlaneLegalHold)
        )
        == 0
    )


async def test_audit_cleanup_cannot_delete_held_evidence(postgres_db):
    from src.control_plane.audit.models import ControlPlaneAuditEvent
    from src.control_plane.audit.service import ControlPlaneAuditService
    from src.control_plane.retention.legal_hold import LegalHoldService

    data = await seed(postgres_db)
    await LegalHoldService.place(
        session=postgres_db,
        account_id=data.account_id,
        reason_hash="a" * 64,
        actor_id_hash="b" * 64,
    )
    await postgres_db.commit()
    with pytest.raises(PermissionError, match="active legal hold"):
        await ControlPlaneAuditService.cleanup_for_account(
            session=postgres_db, account_id=data.account_id
        )
    assert (
        await postgres_db.scalar(
            select(func.count()).select_from(ControlPlaneAuditEvent)
        )
        == 1
    )
