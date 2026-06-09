from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from src.control_plane import models as _control_plane_models  # noqa: F401
from src.control_plane.audit import models as _control_plane_audit_models  # noqa: F401
from src.control_plane.models import ControlPlaneBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic metadata target (public canonical source for control-plane models)
target_metadata = ControlPlaneBase.metadata


def _database_url() -> str:
    return (
        os.environ.get("SHIPAGENT_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or ""
    )


def _target_schema() -> str:
    return os.environ.get("SHIPAGENT_CONTROL_PLANE_SCHEMA") or config.get_section(
        "alembic:runtime", {}
    ).get(
        "shipagent_control_plane_schema",
        "shipagent_private",
    )


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql+asyncpg://") or url.startswith("postgresql://")


def _quote_identifier(value: str) -> str:
    return f'"{value.replace('"', '""')}"'


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode using async engine compatibility."""
    schema = _target_schema()
    database_url = _database_url()
    connect_args = (
        {"server_settings": {"search_path": schema}}
        if _is_postgres(database_url)
        else {}
    )

    connectable = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args=connect_args,
    )

    async def _run_migrations(connection) -> None:
        def _run(sync_connection):
            if sync_connection.dialect.name == "postgresql":
                sync_connection.execute(
                    text(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(schema)}")
                )
                sync_connection.execute(
                    text(f"SET search_path TO {_quote_identifier(schema)}")
                )

            context.configure(
                connection=sync_connection,
                target_metadata=target_metadata,
                include_schemas=True,
                version_table_schema=schema,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()

        await connection.run_sync(_run)

    import asyncio

    async def _main() -> None:
        async with connectable.connect() as connection:
            await _run_migrations(connection)
        await connectable.dispose()

    asyncio.run(_main())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
