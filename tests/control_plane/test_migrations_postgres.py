from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.control_plane.database_url import normalize_control_plane_database_url
from src.control_plane.db import build_session_factory
from src.control_plane.models import CloudAccount


def test_postgres_migration_uses_boolean_false_default(monkeypatch, capsys) -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    monkeypatch.setenv(
        "SHIPAGENT_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/shipagent",
    )
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "shipagent_test")

    command.upgrade(config, "head", sql=True)

    sql = capsys.readouterr().out.lower()
    normalized_sql = " ".join(sql.split())
    assert "suspended boolean default false not null" in normalized_sql
    assert "suspended boolean default 0 not null" not in normalized_sql


def test_alembic_migrations_do_not_disable_application_loggers(
    monkeypatch,
) -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    monkeypatch.setenv(
        "SHIPAGENT_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost/shipagent",
    )
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "shipagent_test")
    application_logger = logging.getLogger("src.services.runtime_credentials")
    previous_disabled = application_logger.disabled
    application_logger.disabled = False

    try:
        command.upgrade(config, "head", sql=True)
        disabled_after_migration = application_logger.disabled
    finally:
        application_logger.disabled = previous_disabled

    assert disabled_after_migration is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_downgrade_preserves_preexisting_postgres_schema() -> None:
    configured_database_url = os.environ.get("SHIPAGENT_TEST_DATABASE_URL")
    if not configured_database_url:
        configured_database_url = os.environ.get("SHIPAGENT_DATABASE_URL")
    if not configured_database_url:
        pytest.skip("No control-plane database URL configured")
    database_url = normalize_control_plane_database_url(configured_database_url)
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.skip("Configured control-plane database is not PostgreSQL")

    try:
        from alembic.config import Config

        from alembic import command
    except Exception as exc:  # pragma: no cover - environment without alembic package
        pytest.skip(f"Alembic unavailable for integration test: {exc}")

    schema = f"shipagent_cp_test_{uuid.uuid4().hex[:10]}"
    root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(root / "alembic.ini"))

    previous = {
        "SHIPAGENT_DATABASE_URL": os.environ.get("SHIPAGENT_DATABASE_URL"),
        "SHIPAGENT_CONTROL_PLANE_SCHEMA": os.environ.get(
            "SHIPAGENT_CONTROL_PLANE_SCHEMA"
        ),
    }
    os.environ["SHIPAGENT_DATABASE_URL"] = configured_database_url
    os.environ["SHIPAGENT_CONTROL_PLANE_SCHEMA"] = schema

    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    session_factory = build_session_factory(
        database_url=configured_database_url,
        control_plane_schema=schema,
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(
                text(f'CREATE TABLE "{schema}".sentinel (value text PRIMARY KEY)')
            )
            await connection.execute(
                text(
                    f"INSERT INTO \"{schema}\".sentinel (value) VALUES ('preserve-me')"
                )
            )

        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

        expected = {"cloud_accounts", "provider_connections", "audit_events"}
        async with engine.connect() as connection:
            table_result = await connection.execute(
                text(
                    """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                          AND table_name IN ('cloud_accounts', 'provider_connections', 'audit_events')
                        """
                ),
                {"schema": schema},
            )
            actual = {row[0] for row in table_result}
            assert expected.issubset(actual)
            revision = await connection.scalar(
                text(f'SELECT version_num FROM "{schema}".alembic_version')
            )
            assert revision == "20260609_0001"

        async with session_factory() as session:
            account = CloudAccount(id=str(uuid.uuid4()), auth0_subject="subject-1")
            session.add(account)
            await session.commit()

            loaded = await session.get(CloudAccount, account.id)
            assert loaded is not None
            assert loaded.auth0_subject == "subject-1"

        await asyncio.to_thread(command.downgrade, alembic_cfg, "base")

        async with engine.connect() as connection:
            sentinel_value = await connection.scalar(
                text(f'SELECT value FROM "{schema}".sentinel')
            )
            assert sentinel_value == "preserve-me"

            table_result = await connection.execute(
                text(
                    """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                          AND table_name IN (
                            'cloud_accounts',
                            'provider_connections',
                            'audit_events'
                          )
                        """
                ),
                {"schema": schema},
            )
            assert {row[0] for row in table_result} == set()

            index_count = await connection.scalar(
                text(
                    """
                        SELECT count(*)
                        FROM pg_indexes
                        WHERE schemaname = :schema
                          AND indexname LIKE 'ix_audit_events_%'
                        """
                ),
                {"schema": schema},
            )
            assert index_count == 0

            revision = await connection.scalar(
                text(f'SELECT version_num FROM "{schema}".alembic_version')
            )
            assert revision is None
    finally:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.commit()

        await engine.dispose()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
