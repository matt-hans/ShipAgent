"""Migration tests for write_back_tasks uniqueness hardening."""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from src.db.connection import _ensure_columns_exist


def test_write_back_migration_dedups_and_enforces_unique_index() -> None:
    """Startup migration should dedup historical duplicates before indexing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            # Minimal schema expected by _ensure_columns_exist.
            conn.execute(text("""
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    original_command TEXT,
                    status TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE job_rows (
                    id TEXT PRIMARY KEY,
                    job_id TEXT,
                    row_number INTEGER,
                    row_checksum TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE write_back_tasks (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    tracking_number TEXT NOT NULL,
                    shipped_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """))

            # Seed duplicates for same (job_id,row_number).
            conn.execute(text("""
                INSERT INTO write_back_tasks
                (id, job_id, row_number, tracking_number, shipped_at, status, retry_count, created_at)
                VALUES
                ('a1', 'job-1', 1, '1ZOLD', '2026-02-17T00:00:00Z', 'pending', 0, '2026-02-17T00:00:00Z'),
                ('a2', 'job-1', 1, '1ZNEW', '2026-02-18T00:00:00Z', 'pending', 0, '2026-02-18T00:00:00Z'),
                ('b1', 'job-1', 2, '1ZROW2', '2026-02-18T00:00:00Z', 'completed', 0, '2026-02-18T00:00:00Z')
            """))

        with engine.begin() as conn:
            _ensure_columns_exist(conn)

        with engine.begin() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM write_back_tasks WHERE job_id='job-1' AND row_number=1")
            ).scalar_one()
            assert count == 1

            # Ensure unique index exists.
            indexes = conn.execute(text("PRAGMA index_list('write_back_tasks')")).fetchall()
            index_names = {str(row[1]) for row in indexes}
            assert "uq_write_back_tasks_job_row_number" in index_names

            # Duplicate insert must now fail.
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("""
                        INSERT INTO write_back_tasks
                        (id, job_id, row_number, tracking_number, shipped_at, status, retry_count, created_at)
                        VALUES
                        ('a3', 'job-1', 1, '1ZFAIL', '2026-02-19T00:00:00Z', 'pending', 0, '2026-02-19T00:00:00Z')
                    """)
                )
    finally:
        os.unlink(db_path)
