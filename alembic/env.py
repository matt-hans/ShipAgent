from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from src.control_plane import models as _control_plane_models  # noqa: F401
from src.control_plane.audit import models as _control_plane_audit_models  # noqa: F401
from src.control_plane.database_url import normalize_control_plane_database_url
from src.control_plane.db import (
    control_plane_schema_for_database_url,
    resolve_control_plane_schema,
)
from src.control_plane.models import ControlPlaneBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Alembic metadata target (public canonical source for control-plane models)
target_metadata = ControlPlaneBase.metadata


def _database_url() -> str:
    """Resolve the control-plane URL: environment first, then alembic.ini."""
    configured_url = (
        os.environ.get("SHIPAGENT_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or ""
    )
    return normalize_control_plane_database_url(configured_url)


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql+asyncpg://") or url.startswith("postgresql://")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _configured_schema() -> str | None:
    runtime_section = config.get_section("alembic:runtime") or {}
    return runtime_section.get("shipagent_control_plane_schema")


def _schema_for_dialect(dialect_name: str) -> str | None:
    return resolve_control_plane_schema(
        dialect_name=dialect_name,
        configured_schema=_configured_schema(),
    )


def _configure_schema_attribute(schema: str | None) -> None:
    # Migrations read the resolved schema from here (None means no schema, e.g. SQLite).
    config.attributes["shipagent_control_plane_schema"] = schema


def _configure_context(connection, schema: str | None) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=schema is not None,
        version_table_schema=schema,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    url = _database_url()
    schema = control_plane_schema_for_database_url(
        url, configured_schema=_configured_schema()
    )
    _configure_schema_attribute(schema)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_schemas=schema is not None,
        version_table_schema=schema,
        compare_type=True,
        compare_server_default=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_postgres_migrations(database_url: str) -> None:
    """Run migrations through the async PostgreSQL driver with a scoped schema."""
    initial_schema = _schema_for_dialect("postgresql")
    connect_args = (
        {"server_settings": {"search_path": initial_schema}}
        if initial_schema is not None
        else {}
    )
    connectable = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args=connect_args,
    )

    def _run(sync_connection) -> None:
        schema = _schema_for_dialect(sync_connection.dialect.name)
        _configure_schema_attribute(schema)
        if schema is not None:
            sync_connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(schema)}")
            )
            sync_connection.execute(
                text(f"SET search_path TO {_quote_identifier(schema)}")
            )
        _configure_context(sync_connection, schema)
        with context.begin_transaction():
            context.run_migrations()

    async def _main() -> None:
        async with connectable.begin() as connection:
            await connection.run_sync(_run)
        await connectable.dispose()

    asyncio.run(_main())


def _run_sync_migrations(database_url: str) -> None:
    """Run migrations through a synchronous engine (SQLite and other dialects)."""
    connectable = create_engine(database_url, poolclass=NullPool)
    with connectable.connect() as connection:
        schema = _schema_for_dialect(connection.dialect.name)
        _configure_schema_attribute(schema)
        if schema is not None:
            connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(schema)}")
            )
        _configure_context(connection, schema)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    database_url = _database_url()
    if _is_postgres(database_url):
        _run_postgres_migrations(database_url)
    else:
        _run_sync_migrations(database_url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
