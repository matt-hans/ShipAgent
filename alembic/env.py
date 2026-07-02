from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from src.control_plane.audit.models import ControlPlaneAuditEvent
from src.control_plane.db import (
    control_plane_schema_for_database_url,
    resolve_control_plane_schema,
)
from src.control_plane.models import (
    CloudAccount,
    ControlPlaneBase,
    ProviderConnection,
    RelayDevice,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Alembic metadata target (public canonical source for control-plane models)
target_metadata = ControlPlaneBase.metadata


def _import_all_models() -> None:
    # Ensure model modules are imported for full metadata visibility.
    for model in (
        CloudAccount,
        ProviderConnection,
        RelayDevice,
        ControlPlaneAuditEvent,
    ):
        assert model is not None


def _configured_schema() -> str | None:
    runtime_section = config.get_section("alembic:runtime") or {}
    return runtime_section.get("shipagent_control_plane_schema")


def _schema_for_dialect(dialect_name: str) -> str | None:
    return resolve_control_plane_schema(
        dialect_name=dialect_name,
        configured_schema=_configured_schema(),
    )


def _schema_for_url(url: str) -> str | None:
    return control_plane_schema_for_database_url(
        url,
        configured_schema=_configured_schema(),
    )


def _configure_schema_attribute(schema: str | None) -> None:
    config.attributes["shipagent_control_plane_schema"] = schema


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    _import_all_models()
    url = config.get_main_option("sqlalchemy.url")
    schema = _schema_for_url(url)
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


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    _import_all_models()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schema = _schema_for_dialect(connection.dialect.name)
        _configure_schema_attribute(schema)
        if schema is not None:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=schema is not None,
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
