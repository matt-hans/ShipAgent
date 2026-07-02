from __future__ import annotations

import os

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_CONTROL_PLANE_SCHEMA = "shipagent_private"
CONTROL_PLANE_SCHEMA_ENV = "SHIPAGENT_CONTROL_PLANE_SCHEMA"


def control_plane_schema_for_database_url(database_url: str) -> str | None:
    if make_url(database_url).get_backend_name() == "sqlite":
        return None
    schema = os.environ.get(CONTROL_PLANE_SCHEMA_ENV, DEFAULT_CONTROL_PLANE_SCHEMA)
    return schema.strip() or None


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _configure_control_plane_schema(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    schema = control_plane_schema_for_database_url(database_url)
    if schema is None:
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {_quote_identifier(schema)}")
        finally:
            cursor.close()


def build_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    _configure_control_plane_schema(engine, database_url)
    return async_sessionmaker(engine, expire_on_commit=False)
