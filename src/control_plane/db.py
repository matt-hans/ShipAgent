from __future__ import annotations

import os

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.control_plane.database_url import normalize_control_plane_database_url

DEFAULT_CONTROL_PLANE_SCHEMA = "shipagent_private"
CONTROL_PLANE_SCHEMA_ENV = "SHIPAGENT_CONTROL_PLANE_SCHEMA"


def resolve_control_plane_schema(
    *,
    dialect_name: str,
    configured_schema: str | None = None,
) -> str | None:
    """Return the control-plane schema for a dialect (None for SQLite)."""
    if dialect_name == "sqlite":
        return None
    schema = os.environ.get(CONTROL_PLANE_SCHEMA_ENV)
    if schema is None:
        schema = configured_schema or DEFAULT_CONTROL_PLANE_SCHEMA
    return schema.strip() or None


def control_plane_schema_for_database_url(
    database_url: str,
    *,
    configured_schema: str | None = None,
) -> str | None:
    """Return the control-plane schema implied by a database URL."""
    return resolve_control_plane_schema(
        dialect_name=make_url(database_url).get_backend_name(),
        configured_schema=configured_schema,
    )


def build_session_factory(
    database_url: str,
    *,
    control_plane_schema: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Build an async session factory bound to the control-plane schema."""
    database_url = normalize_control_plane_database_url(database_url)
    if control_plane_schema is not None:
        # An explicit schema argument takes precedence over the environment.
        schema = control_plane_schema.strip() or None
    else:
        schema = control_plane_schema_for_database_url(database_url)
    connect_args = (
        {"server_settings": {"search_path": schema}}
        if schema is not None and database_url.startswith("postgresql+asyncpg://")
        else {}
    )
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    return async_sessionmaker(engine, expire_on_commit=False)
