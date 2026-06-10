import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.control_plane.models import ControlPlaneBase


@pytest.fixture
async def control_db() -> AsyncGenerator[AsyncSession, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database_url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    sync_database_url = database_url.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_database_url)
    try:
        ControlPlaneBase.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()

    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()

    await engine.dispose()
    os.unlink(path)
