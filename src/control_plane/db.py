import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

CONTROL_PLANE_SCHEMA = os.getenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "shipagent_private")


def build_session_factory(
    database_url: str,
    *,
    control_plane_schema: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    schema = control_plane_schema or CONTROL_PLANE_SCHEMA
    connect_args = (
        {"server_settings": {"search_path": schema}}
        if "postgresql+asyncpg://" in database_url
        else {}
    )

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    return async_sessionmaker(engine, expire_on_commit=False)
