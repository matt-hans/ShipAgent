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

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base


# Configuration
def get_database_url() -> str:
    """Get database URL from environment or use default SQLite.

    Precedence:
    1. DATABASE_URL (canonical)
    2. SHIPAGENT_DB_PATH (compat fallback, converted to sqlite URL)
    3. sqlite:///./shipagent.db
    """
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    db_path = os.environ.get("SHIPAGENT_DB_PATH", "").strip()
    if db_path:
        if db_path.startswith("sqlite:"):
            return db_path
        return f"sqlite:///{db_path}"

    from src.utils.paths import get_default_db_path
    return f"sqlite:///{get_default_db_path()}"


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
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
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
    """Configure SQLite pragmas for correctness and concurrency.

    Enables:
    - foreign_keys=ON: Referential integrity (disabled by default in SQLite).
    - journal_mode=WAL: Allows concurrent readers + a single writer without
      blocking — critical for multiple MCP subprocesses hitting the same DB.
    - synchronous=NORMAL: Full WAL performance benefit without sacrificing
      durability. Commits are durable after WAL fsync; checkpoints may lose
      a few recent transactions on power loss (acceptable for desktop app).
    """
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
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


def _migrate_provider_connections(conn: Any, log: Any) -> None:
    """Create or migrate the provider_connections table.

    Idempotent — safe to call on every startup. Handles:
    - Table creation (fresh DB)
    - Column additions (partial-upgrade)
    - Unique index hardening
    - NULL backfill for defaults

    Args:
        conn: SQLAlchemy Connection.
        log: Logger instance.
    """
    from datetime import UTC, datetime

    from sqlalchemy.exc import OperationalError

    # Step 1: Create table if not exists
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS provider_connections (
            id TEXT PRIMARY KEY,
            connection_key TEXT NOT NULL,
            provider TEXT NOT NULL,
            display_name TEXT NOT NULL,
            auth_mode TEXT NOT NULL,
            environment TEXT,
            status TEXT NOT NULL DEFAULT 'configured',
            encrypted_credentials TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            last_error_code TEXT,
            error_message TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1,
            key_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    )

    # Step 2: Introspect existing columns and add missing ones
    result = conn.execute(text("PRAGMA table_info(provider_connections)"))
    existing_cols = {row[1] for row in result.fetchall()}

    pc_migrations: list[tuple[str, str]] = [
        ("provider", "ALTER TABLE provider_connections ADD COLUMN provider TEXT"),
        (
            "display_name",
            "ALTER TABLE provider_connections ADD COLUMN display_name TEXT",
        ),
        ("auth_mode", "ALTER TABLE provider_connections ADD COLUMN auth_mode TEXT"),
        ("environment", "ALTER TABLE provider_connections ADD COLUMN environment TEXT"),
        ("status", "ALTER TABLE provider_connections ADD COLUMN status TEXT"),
        (
            "encrypted_credentials",
            "ALTER TABLE provider_connections ADD COLUMN encrypted_credentials TEXT",
        ),
        (
            "metadata_json",
            "ALTER TABLE provider_connections ADD COLUMN metadata_json TEXT",
        ),
        (
            "last_error_code",
            "ALTER TABLE provider_connections ADD COLUMN last_error_code TEXT",
        ),
        (
            "error_message",
            "ALTER TABLE provider_connections ADD COLUMN error_message TEXT",
        ),
        (
            "schema_version",
            "ALTER TABLE provider_connections ADD COLUMN schema_version INTEGER",
        ),
        (
            "key_version",
            "ALTER TABLE provider_connections ADD COLUMN key_version INTEGER",
        ),
        ("created_at", "ALTER TABLE provider_connections ADD COLUMN created_at TEXT"),
        ("updated_at", "ALTER TABLE provider_connections ADD COLUMN updated_at TEXT"),
    ]

    for col_name, ddl in pc_migrations:
        if col_name not in existing_cols:
            try:
                conn.execute(text(ddl))
            except OperationalError as e:
                if "duplicate column" in str(e).lower():
                    log.debug("Column %s already exists (concurrent add).", col_name)
                else:
                    log.error("Failed to add column %s: %s", col_name, e)
                    raise

    # Step 3: Backfill NULL defaults
    now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    backfill_stmts = [
        "UPDATE provider_connections SET metadata_json = '{}' WHERE metadata_json IS NULL",
        "UPDATE provider_connections SET schema_version = 1 WHERE schema_version IS NULL",
        "UPDATE provider_connections SET key_version = 1 WHERE key_version IS NULL",
        "UPDATE provider_connections SET status = 'needs_reconnect' WHERE status IS NULL",
    ]
    for stmt in backfill_stmts:
        conn.execute(text(stmt))

    # Backfill timestamps
    ts_result = conn.execute(
        text(
            "SELECT COUNT(*) FROM provider_connections WHERE created_at IS NULL OR updated_at IS NULL"
        )
    )
    null_ts_count = ts_result.scalar()
    if null_ts_count and null_ts_count > 0:
        conn.execute(
            text(
                f"UPDATE provider_connections SET created_at = '{now_utc}' WHERE created_at IS NULL"
            )
        )
        conn.execute(
            text(
                f"UPDATE provider_connections SET updated_at = '{now_utc}' WHERE updated_at IS NULL"
            )
        )
        log.info(
            "Backfilled timestamps on %d provider_connections rows.", null_ts_count
        )

    # Step 4: Duplicate-key pre-check before unique index creation
    dup_result = conn.execute(
        text(
            "SELECT connection_key, COUNT(*) c "
            "FROM provider_connections "
            "GROUP BY connection_key "
            "HAVING c > 1"
        )
    )
    duplicates = dup_result.fetchall()
    if duplicates:
        dup_count = len(duplicates)
        dup_keys = [row[0] for row in duplicates]
        log.error(
            "Found %d duplicate connection_key values: %s — resolve before migration can proceed",
            dup_count,
            dup_keys,
        )
        raise RuntimeError(
            f"Found {dup_count} duplicate connection_key values — resolve before migration can proceed"
        )

    # Step 5: Create indexes
    for idx_stmt in [
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_connections_connection_key "
        "ON provider_connections (connection_key)",
        "CREATE INDEX IF NOT EXISTS idx_provider_connections_provider "
        "ON provider_connections (provider)",
    ]:
        try:
            conn.execute(text(idx_stmt))
        except OperationalError as e:
            log.warning("provider_connections index creation failed: %s", e)


def _ensure_columns_exist(conn: Any) -> None:
    """Add new columns to existing tables if missing (SQLite only).

    Uses PRAGMA table_info to introspect columns and ALTER TABLE to add
    missing ones. Idempotent — safe to call on every startup.

    Works with both sync (engine.begin()) and async (run_sync) connections.

    Args:
        conn: SQLAlchemy Connection (sync or from run_sync).

    Raises:
        OperationalError: For non-duplicate-column DDL failures (locked DB,
            malformed SQL, etc.).
    """
    import logging

    from sqlalchemy.exc import OperationalError

    log = logging.getLogger(__name__)

    if conn.dialect.name != "sqlite":
        return

    # Check if jobs table exists before migrating it
    jobs_exists = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs' LIMIT 1")
    ).fetchone()

    if jobs_exists:
        result = conn.execute(text("PRAGMA table_info(jobs)"))
        existing = {row[1] for row in result.fetchall()}

        migrations: list[tuple[str, str]] = [
            ("shipper_json", "ALTER TABLE jobs ADD COLUMN shipper_json TEXT"),
            (
                "is_interactive",
                "ALTER TABLE jobs ADD COLUMN is_interactive BOOLEAN NOT NULL DEFAULT 0",
            ),
            # Preview integrity hash for TOCTOU protection
            (
                "preview_hash",
                "ALTER TABLE jobs ADD COLUMN preview_hash VARCHAR(64)",
            ),
            # International shipping columns — jobs table
            (
                "total_duties_taxes_cents",
                "ALTER TABLE jobs ADD COLUMN total_duties_taxes_cents INTEGER",
            ),
            (
                "international_row_count",
                "ALTER TABLE jobs ADD COLUMN international_row_count INTEGER NOT NULL DEFAULT 0",
            ),
        ]

        for col_name, ddl in migrations:
            if col_name not in existing:
                try:
                    conn.execute(text(ddl))
                except OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        log.debug(
                            "Column %s already exists (concurrent add).", col_name
                        )
                    else:
                        log.error("Failed to add column %s: %s", col_name, e)
                        raise

    # job_rows table migrations
    job_rows_exists = conn.execute(
        text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_rows' LIMIT 1"
        )
    ).fetchone()

    if job_rows_exists:
        result_rows = conn.execute(text("PRAGMA table_info(job_rows)"))
        existing_rows = {row[1] for row in result_rows.fetchall()}

        row_migrations: list[tuple[str, str]] = [
            (
                "destination_country",
                "ALTER TABLE job_rows ADD COLUMN destination_country VARCHAR(2)",
            ),
            (
                "duties_taxes_cents",
                "ALTER TABLE job_rows ADD COLUMN duties_taxes_cents INTEGER",
            ),
            (
                "charge_breakdown",
                "ALTER TABLE job_rows ADD COLUMN charge_breakdown TEXT",
            ),
            # Phase 8: Execution determinism columns
            (
                "idempotency_key",
                "ALTER TABLE job_rows ADD COLUMN idempotency_key VARCHAR(200)",
            ),
            (
                "ups_shipment_id",
                "ALTER TABLE job_rows ADD COLUMN ups_shipment_id VARCHAR(50)",
            ),
            (
                "ups_tracking_number",
                "ALTER TABLE job_rows ADD COLUMN ups_tracking_number VARCHAR(50)",
            ),
            (
                "recovery_attempt_count",
                "ALTER TABLE job_rows ADD COLUMN recovery_attempt_count INTEGER NOT NULL DEFAULT 0",
            ),
        ]

        for col_name, ddl in row_migrations:
            if col_name not in existing_rows:
                try:
                    conn.execute(text(ddl))
                except OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        log.debug(
                            "Column %s already exists (concurrent add).", col_name
                        )
                    else:
                        log.error("Failed to add column %s: %s", col_name, e)
                        raise

        # Always attempt index creation — CREATE INDEX IF NOT EXISTS is
        # safe to run repeatedly and handles partial-upgrade states where
        # a column was added but the index creation failed or was skipped.
        for idx_stmt in [
            "CREATE INDEX IF NOT EXISTS idx_job_rows_idempotency ON job_rows (idempotency_key)",
            "CREATE INDEX IF NOT EXISTS idx_job_rows_tracking ON job_rows (ups_tracking_number)",
        ]:
            try:
                conn.execute(text(idx_stmt))
            except OperationalError:
                pass  # Column doesn't exist yet (pre-Phase-8 DB)

    # Agent decision audit ledger tables/indexes.
    # Use idempotent CREATE TABLE/INDEX for resilience in partial upgrades.
    for ddl in [
        """
        CREATE TABLE IF NOT EXISTS agent_decision_runs (
            id VARCHAR(36) PRIMARY KEY,
            session_id VARCHAR(64),
            job_id VARCHAR(36),
            user_message_hash VARCHAR(64) NOT NULL,
            user_message_redacted TEXT NOT NULL,
            source_signature TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            model VARCHAR(120),
            interactive_shipping BOOLEAN NOT NULL DEFAULT 0,
            started_at VARCHAR(50) NOT NULL,
            completed_at VARCHAR(50),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_decision_events (
            id VARCHAR(36) PRIMARY KEY,
            run_id VARCHAR(36) NOT NULL,
            seq INTEGER NOT NULL,
            timestamp VARCHAR(50) NOT NULL,
            phase VARCHAR(32) NOT NULL,
            event_name VARCHAR(120) NOT NULL,
            actor VARCHAR(20) NOT NULL,
            tool_name VARCHAR(120),
            payload_redacted TEXT NOT NULL,
            payload_hash VARCHAR(64) NOT NULL,
            latency_ms INTEGER,
            prev_event_hash VARCHAR(64),
            event_hash VARCHAR(64) NOT NULL,
            UNIQUE(run_id, seq),
            FOREIGN KEY(run_id) REFERENCES agent_decision_runs(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_runs_session ON agent_decision_runs (session_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_runs_job ON agent_decision_runs (job_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_runs_status ON agent_decision_runs (status)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_runs_started_at ON agent_decision_runs (started_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_events_run ON agent_decision_events (run_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_events_phase ON agent_decision_events (phase)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_events_event_name ON agent_decision_events (event_name)",
        "CREATE INDEX IF NOT EXISTS idx_agent_decision_events_timestamp ON agent_decision_events (timestamp)",
    ]:
        try:
            conn.execute(text(ddl))
        except OperationalError as e:
            log.warning("Agent decision ledger migration step failed: %s", e)

    # --- provider_connections table migration ---
    _migrate_provider_connections(conn, log)

    # write_back_tasks migration: deduplicate historical duplicates before
    # enforcing uniqueness on (job_id, row_number).
    try:
        table_exists = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='write_back_tasks' LIMIT 1"
            )
        ).fetchone()
        if table_exists:
            conn.execute(
                text(
                    """
                    DELETE FROM write_back_tasks
                    WHERE rowid IN (
                        SELECT rowid FROM (
                            SELECT
                                rowid,
                                ROW_NUMBER() OVER (
                                    PARTITION BY job_id, row_number
                                    ORDER BY
                                        CASE status
                                            WHEN 'pending' THEN 3
                                            WHEN 'completed' THEN 2
                                            WHEN 'dead_letter' THEN 1
                                            ELSE 0
                                        END DESC,
                                        created_at DESC,
                                        rowid DESC
                                ) AS rn
                            FROM write_back_tasks
                        ) ranked
                        WHERE rn > 1
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_write_back_tasks_job_row_number "
                    "ON write_back_tasks (job_id, row_number)"
                )
            )
    except OperationalError as e:
        log.warning("write_back_tasks uniqueness migration skipped: %s", e)


def init_db() -> None:
    """Create all database tables synchronously.

    Uses the Base.metadata from models.py to create all defined tables.
    Safe to call multiple times - will not recreate existing tables.
    Runs column migration for new columns on existing tables.

    Usage:
        from src.db.connection import init_db
        init_db()
    """
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _ensure_columns_exist(conn)


async def async_init_db() -> None:
    """Create all database tables asynchronously.

    Uses the Base.metadata from models.py to create all defined tables.
    Safe to call multiple times - will not recreate existing tables.
    Runs column migration for new columns on existing tables.

    Usage:
        from src.db.connection import async_init_db
        await async_init_db()
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns_exist)


# Cleanup functions


def close_db() -> None:
    """Close the sync engine and dispose of connection pool."""
    engine.dispose()


async def close_async_db() -> None:
    """Close the async engine and dispose of connection pool."""
    await async_engine.dispose()
