"""Real disposable PostgreSQL link identity, lock and migration evidence."""

import asyncio
import time
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from src.control_plane.models import CloudAccount, ProviderConnection
from tests.control_plane.auth.test_service import (
    strict_request,
    strict_service,
)


async def test_concurrent_first_use_converges_on_one_account_and_link(postgres_db):
    factory = async_sessionmaker(postgres_db.bind, expire_on_commit=False)

    async def resolve():
        async with factory() as session:
            return await strict_service(session).resolve(**strict_request())

    results = await asyncio.gather(*(resolve() for _ in range(8)))
    assert len({r.account_id for r in results}) == 1
    assert len({(r.provider_connection_id, r.link_epoch) for r in results}) == 1
    assert await postgres_db.scalar(select(func.count()).select_from(CloudAccount)) == 1
    assert (
        await postgres_db.scalar(select(func.count()).select_from(ProviderConnection))
        == 1
    )


@pytest.mark.parametrize("expire_token", [True, False])
async def test_original_expiry_and_deadline_survive_account_lock_wait(
    postgres_db, expire_token
):
    first = await strict_service(postgres_db).resolve(**strict_request())
    factory = async_sessionmaker(postgres_db.bind, expire_on_commit=False)
    async with factory() as blocker:
        await blocker.execute(
            select(CloudAccount)
            .where(CloudAccount.id == first.account_id)
            .with_for_update()
        )
        async with factory() as waiting:
            args = strict_request()
            if expire_token:
                args["token_expires_at"] = time.time() + 0.15
            else:
                args["operation_deadline"] = time.monotonic() + 0.15
            task = asyncio.create_task(strict_service(waiting).resolve(**args))
            try:
                await asyncio.sleep(0.25)
                assert task.done(), (
                    "bounded identity resolution waited beyond its original budget"
                )
                with pytest.raises(PermissionError):
                    await task
            finally:
                await blocker.rollback()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    assert (
        await postgres_db.scalar(select(func.count()).select_from(ProviderConnection))
        == 1
    )


async def test_scope_reduction_and_revocation_serialize_with_requests(postgres_db):
    first = await strict_service(postgres_db).resolve(**strict_request())
    factory = async_sessionmaker(postgres_db.bind, expire_on_commit=False)
    async with factory() as blocker:
        await blocker.execute(
            select(CloudAccount)
            .where(CloudAccount.id == first.account_id)
            .with_for_update()
        )
        await blocker.execute(
            text(
                "UPDATE provider_connections SET allowed_scopes_text='shipagent.status' WHERE id=:id"
            ),
            {"id": first.provider_connection_id},
        )
        async with factory() as waiting:
            task = asyncio.create_task(
                strict_service(waiting).resolve(**strict_request())
            )
            await asyncio.sleep(0.03)
            assert not task.done()
            await blocker.commit()
            result = await task
            assert result.scopes == frozenset({"shipagent.status"})
    await strict_service(postgres_db).revoke_link(
        first.account_id, first.provider_connection_id
    )
    async with factory() as waiting:
        with pytest.raises(PermissionError):
            await strict_service(waiting).resolve(**strict_request())


def migration_config(url):
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.mark.parametrize("fail", [False, True])
async def test_real_migration_preserves_legacy_and_rolls_back_failure(
    disposable_control_stores, monkeypatch, fail
):
    schema = "links_" + uuid.uuid4().hex[:12]
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", schema)
    url = disposable_control_stores["postgres_url"]
    config = migration_config(url)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        await asyncio.to_thread(command.upgrade, config, "20261007_0004")
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO cloud_accounts (id,auth0_subject) VALUES ('legacy','old-subject')"
                )
            )
            await db.execute(
                text(
                    "INSERT INTO provider_connections (id,account_id,client_id,surface,scopes_text,status) VALUES ('old-link','legacy','chatgpt-client','chatgpt','old-scope','revoked')"
                )
            )
            if fail:
                # An index collision occurs late in migration, after the new columns.
                await db.execute(
                    text(
                        "CREATE INDEX uq_provider_connections_strict_link ON provider_connections (id)"
                    )
                )
        if fail:
            with pytest.raises(ProgrammingError, match="already exists"):
                await asyncio.to_thread(command.upgrade, config, "head")
        else:
            await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT scopes_text,status FROM provider_connections WHERE id='old-link'"
                    )
                )
            ).one()
            assert tuple(row) == ("old-scope", "revoked")
            version = await db.scalar(text("SELECT version_num FROM alembic_version"))
            if fail:
                assert version == "20261007_0004"
                count = await db.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='cloud_accounts' AND column_name='issuer'"
                    ),
                    {"schema": schema},
                )
                assert count == 0
            else:
                assert version == "20261009_0005"
                assert (
                    await db.scalar(
                        text("SELECT issuer FROM cloud_accounts WHERE id='legacy'")
                    )
                    is None
                )
                fields = (
                    await db.execute(
                        text(
                            "SELECT issuer_link_id,link_epoch,allowed_scopes_text FROM provider_connections WHERE id='old-link'"
                        )
                    )
                ).one()
                assert tuple(fields) == (None, None, None)
        if not fail:
            await asyncio.to_thread(command.downgrade, config, "20261007_0004")
            async with engine.connect() as db:
                assert (
                    await db.scalar(
                        text(
                            "SELECT status FROM provider_connections WHERE id='old-link'"
                        )
                    )
                    == "revoked"
                )
    finally:
        async with engine.begin() as db:
            await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def test_downgrade_precondition_excludes_concurrent_strict_creation(
    disposable_control_stores, monkeypatch
):
    import threading

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    schema = "links_" + uuid.uuid4().hex[:12]
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", schema)
    url = disposable_control_stores["postgres_url"]
    config = migration_config(url)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    checked, release = threading.Event(), threading.Event()

    def pause_after_precondition(
        connection, cursor, statement, parameters, context, executemany
    ):
        if statement.startswith("SELECT EXISTS") and "issuer IS NOT NULL" in statement:
            checked.set()
            assert release.wait(3), "test-owned downgrade barrier expired"

    downgrade = resolution = None
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        event.listen(Engine, "after_cursor_execute", pause_after_precondition)
        downgrade = asyncio.create_task(
            asyncio.to_thread(command.downgrade, config, "20261007_0004")
        )
        assert await asyncio.to_thread(checked.wait, 2)
        async with factory() as session:
            resolution = asyncio.create_task(
                strict_service(session).resolve(**strict_request())
            )
            try:
                await asyncio.sleep(0.1)
                assert not resolution.done(), (
                    "strict creation crossed a checked downgrade precondition"
                )
            finally:
                release.set()
                await downgrade
                await asyncio.gather(resolution, return_exceptions=True)
            with pytest.raises(PermissionError):
                resolution.result()
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT count(*) FROM cloud_accounts")) == 0
            assert (
                await db.scalar(text("SELECT version_num FROM alembic_version"))
                == "20261007_0004"
            )
    finally:
        release.set()
        if downgrade is not None:
            await asyncio.gather(downgrade, return_exceptions=True)
        event.remove(Engine, "after_cursor_execute", pause_after_precondition)
        async with engine.begin() as db:
            await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def test_downgrade_preserves_strict_creation_that_wins_first(
    disposable_control_stores, monkeypatch
):
    schema = "links_" + uuid.uuid4().hex[:12]
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", schema)
    url = disposable_control_stores["postgres_url"]
    config = migration_config(url)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        async with factory() as session:
            context = await strict_service(session).resolve(**strict_request())
        with pytest.raises(
            RuntimeError, match="strict provider links prevent downgrade"
        ):
            await asyncio.to_thread(command.downgrade, config, "20261007_0004")
        async with factory() as session:
            restored = await strict_service(session).resolve(**strict_request())
            assert restored.provider_connection_id == context.provider_connection_id
            assert restored.link_epoch == context.link_epoch
    finally:
        async with engine.begin() as db:
            await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
