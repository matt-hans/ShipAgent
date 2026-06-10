from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.control_plane.models import ControlPlaneBase
from src.control_plane.audit.models import ControlPlaneAuditEvent
from src.control_plane.models import CloudAccount, ProviderConnection


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Alembic metadata target (public canonical source for control-plane models)
target_metadata = ControlPlaneBase.metadata


def _import_all_models() -> None:
    # Ensure model modules are imported for full metadata visibility.
    ControlPlaneBase.metadata
    CloudAccount
    ProviderConnection
    ControlPlaneAuditEvent


def _target_schema() -> str:
    return config.get_section("alembic:runtime").get(
        "shipagent_control_plane_schema",
        os.environ.get("SHIPAGENT_CONTROL_PLANE_SCHEMA", "shipagent_private"),
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    _import_all_models()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
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
    """Run migrations in 'online' mode."""

    _import_all_models()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schema = _target_schema()
        connection.execute(
            f'CREATE SCHEMA IF NOT EXISTS "{schema}"'
        )
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=schema,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

