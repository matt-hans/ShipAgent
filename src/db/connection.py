"""Database connection management for ShipAgent.

Provides both synchronous and asynchronous database access using SQLAlchemy.
Supports SQLite for development with PostgreSQL migration path for production.

Usage:
    # Sync (for FastAPI Depends)
    from src.db.connection import get_db, init_db

    init_db()  # Create tables
    db = next(get_db())
    # ... use db session

    # Async
    from src.db.connection import get_async_db, async_init_db

    await async_init_db()
    async for db in get_async_db():
        # ... use async db session
"""

import os
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base


# Configuration
def get_database_url() -> str:
    """Get database URL from environment or use default SQLite."""
    return os.environ.get("DATABASE_URL", "sqlite:///./shipagent.db")


def get_async_database_url() -> str:
    """Get async database URL from environment or derive from sync URL.

    Converts sqlite:/// to sqlite+aiosqlite:/// for async support.
    """
    url = get_database_url()
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return url


# Engine creation
DATABASE_URL = get_database_url()
ASYNC_DATABASE_URL = get_async_database_url()

# Sync engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=os.environ.get("SQL_ECHO", "").lower() == "true",
)

# Async engine
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.environ.get("SQL_ECHO", "").lower() == "true",
)


# Enable foreign keys for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Enable foreign key constraints for SQLite connections.

    SQLite has foreign keys disabled by default. This pragma enables them
    for every connection to ensure referential integrity.
    """
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Session factories
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Dependency functions for FastAPI


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for synchronous operations.

    Intended for use with FastAPI's Depends() for request-scoped sessions.

    Usage:
        @app.get("/jobs")
        def list_jobs(db: Session = Depends(get_db)):
            return db.query(Job).all()

    Yields:
        Session: SQLAlchemy session that will be closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for asynchronous operations.

    Intended for use with FastAPI's Depends() for async request handlers.

    Usage:
        @app.get("/jobs")
        async def list_jobs(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(Job))
            return result.scalars().all()

    Yields:
        AsyncSession: Async SQLAlchemy session that will be closed after use.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Context managers for manual session management


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for database sessions outside of FastAPI.

    Usage:
        with get_db_context() as db:
            job = db.query(Job).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@asynccontextmanager
async def get_async_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions outside of FastAPI.

    Usage:
        async with get_async_db_context() as db:
            result = await db.execute(select(Job))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Initialization functions


def init_db() -> None:
    """Create all database tables synchronously.

    Uses the Base.metadata from models.py to create all defined tables.
    Safe to call multiple times - will not recreate existing tables.

    Usage:
        from src.db.connection import init_db
        init_db()
    """
    Base.metadata.create_all(bind=engine)


async def async_init_db() -> None:
    """Create all database tables asynchronously.

    Uses the Base.metadata from models.py to create all defined tables.
    Safe to call multiple times - will not recreate existing tables.

    Usage:
        from src.db.connection import async_init_db
        await async_init_db()
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# Cleanup functions


def close_db() -> None:
    """Close the sync engine and dispose of connection pool."""
    engine.dispose()


async def close_async_db() -> None:
    """Close the async engine and dispose of connection pool."""
    await async_engine.dispose()
