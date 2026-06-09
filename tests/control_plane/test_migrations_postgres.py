from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.control_plane.db import build_session_factory
from src.control_plane.models import CloudAccount


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_runs_against_postgres_schema_control_plane() -> None:
    database_url = os.environ.get("SHIPAGENT_TEST_DATABASE_URL")
    if not database_url:
        database_url = os.environ.get("SHIPAGENT_DATABASE_URL")
    if not database_url:
        pytest.skip("No control-plane database URL configured")
    if "postgresql+asyncpg://" not in database_url:
        pytest.skip(
            "Control-plane migration integration test requires asyncpg PostgreSQL URL"
        )

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
    os.environ["SHIPAGENT_DATABASE_URL"] = database_url
    os.environ["SHIPAGENT_CONTROL_PLANE_SCHEMA"] = schema

    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    session_factory = build_session_factory(
        database_url=database_url,
        control_plane_schema=schema,
    )
    try:
        command.upgrade(alembic_cfg, "head")

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

        async with session_factory() as session:
            account = CloudAccount(id=str(uuid.uuid4()), auth0_subject="subject-1")
            session.add(account)
            await session.commit()

            loaded = await session.get(CloudAccount, account.id)
            assert loaded is not None
            assert loaded.auth0_subject == "subject-1"
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
