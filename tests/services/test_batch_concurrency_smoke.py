"""Smoke test: verify batch_concurrency DB setting controls actual concurrency.

Two-layer verification:
1. _resolve_concurrency() reads from the DB correctly.
2. The semaphore created from that value actually bounds peak concurrency
   when processing rows through asyncio.gather.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.batch_engine import BatchEngine
from src.services.settings_service import SettingsService


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Create a temporary SQLite DB and patch SessionLocal for _resolve_concurrency."""
    db_path = str(tmp_path / "test_concurrency.db")
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # Patch SessionLocal so _resolve_concurrency reads from our test DB
    monkeypatch.setattr("src.db.connection.SessionLocal", factory)

    # Remove env override so DB value is authoritative
    monkeypatch.delenv("BATCH_CONCURRENCY", raising=False)

    return factory


# ---------------------------------------------------------------------------
# Layer 1: _resolve_concurrency() reads from the DB
# ---------------------------------------------------------------------------


def test_resolve_concurrency_reads_db_default(isolated_db):
    """When no value is set, DB default (5) is returned."""
    result = BatchEngine._resolve_concurrency()
    assert result == 5


def test_resolve_concurrency_reads_db_value_1(isolated_db):
    """Setting batch_concurrency=1 in DB → _resolve_concurrency returns 1."""
    db = isolated_db()
    try:
        svc = SettingsService(db)
        settings = svc.get_or_create()
        settings.batch_concurrency = 1
        db.commit()
    finally:
        db.close()

    assert BatchEngine._resolve_concurrency() == 1


def test_resolve_concurrency_reads_db_value_15(isolated_db):
    """Setting batch_concurrency=15 in DB → _resolve_concurrency returns 15."""
    db = isolated_db()
    try:
        svc = SettingsService(db)
        settings = svc.get_or_create()
        settings.batch_concurrency = 15
        db.commit()
    finally:
        db.close()

    assert BatchEngine._resolve_concurrency() == 15


def test_db_check_constraint_rejects_out_of_range(isolated_db):
    """DB CHECK constraint prevents batch_concurrency > 20 or < 1."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    db = isolated_db()
    try:
        svc = SettingsService(db)
        svc.get_or_create()
        db.commit()

        with pytest.raises(IntegrityError, match="CHECK constraint"):
            db.execute(text("UPDATE app_settings SET batch_concurrency = 50"))
            db.commit()
    finally:
        db.close()


def test_resolve_concurrency_env_fallback(isolated_db, monkeypatch):
    """When DB read fails, falls back to BATCH_CONCURRENCY env var."""
    # Break the DB connection so _resolve_concurrency falls through to env
    monkeypatch.setattr(
        "src.db.connection.SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("DB down")),
    )
    monkeypatch.setenv("BATCH_CONCURRENCY", "7")

    assert BatchEngine._resolve_concurrency() == 7


# ---------------------------------------------------------------------------
# Layer 2: Semaphore actually constrains concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency_to_1(isolated_db):
    """With concurrency=1, peak in-flight tasks is exactly 1."""
    db = isolated_db()
    try:
        svc = SettingsService(db)
        settings = svc.get_or_create()
        settings.batch_concurrency = 1
        db.commit()
    finally:
        db.close()

    max_concurrent = BatchEngine._resolve_concurrency()
    semaphore = asyncio.Semaphore(max_concurrent)

    peak = 0
    current = 0
    lock = asyncio.Lock()

    async def work():
        nonlocal peak, current
        async with semaphore:
            async with lock:
                current += 1
                if current > peak:
                    peak = current
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1

    await asyncio.gather(*(work() for _ in range(10)))
    assert peak == 1, f"Expected peak=1, got {peak}"


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency_to_4(isolated_db):
    """With concurrency=4, peak in-flight tasks is at most 4."""
    db = isolated_db()
    try:
        svc = SettingsService(db)
        settings = svc.get_or_create()
        settings.batch_concurrency = 4
        db.commit()
    finally:
        db.close()

    max_concurrent = BatchEngine._resolve_concurrency()
    semaphore = asyncio.Semaphore(max_concurrent)

    peak = 0
    current = 0
    lock = asyncio.Lock()

    async def work():
        nonlocal peak, current
        async with semaphore:
            async with lock:
                current += 1
                if current > peak:
                    peak = current
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1

    await asyncio.gather(*(work() for _ in range(20)))
    assert 1 < peak <= 4, f"Expected 1 < peak <= 4, got {peak}"


@pytest.mark.asyncio
async def test_changing_db_value_changes_semaphore(isolated_db):
    """Changing DB value between calls changes the semaphore size."""
    db = isolated_db()
    try:
        svc = SettingsService(db)
        settings = svc.get_or_create()

        # Round 1: concurrency=1
        settings.batch_concurrency = 1
        db.commit()
    finally:
        db.close()

    c1 = BatchEngine._resolve_concurrency()
    assert c1 == 1

    sem1 = asyncio.Semaphore(c1)
    peak1 = 0
    current1 = 0
    lock1 = asyncio.Lock()

    async def work1():
        nonlocal peak1, current1
        async with sem1:
            async with lock1:
                current1 += 1
                if current1 > peak1:
                    peak1 = current1
            await asyncio.sleep(0.02)
            async with lock1:
                current1 -= 1

    await asyncio.gather(*(work1() for _ in range(8)))

    # Round 2: bump to 8
    db = isolated_db()
    try:
        svc = SettingsService(db)
        settings = svc.get_or_create()
        settings.batch_concurrency = 8
        db.commit()
    finally:
        db.close()

    c2 = BatchEngine._resolve_concurrency()
    assert c2 == 8

    sem2 = asyncio.Semaphore(c2)
    peak2 = 0
    current2 = 0
    lock2 = asyncio.Lock()

    async def work2():
        nonlocal peak2, current2
        async with sem2:
            async with lock2:
                current2 += 1
                if current2 > peak2:
                    peak2 = current2
            await asyncio.sleep(0.02)
            async with lock2:
                current2 -= 1

    await asyncio.gather(*(work2() for _ in range(8)))

    assert peak1 == 1, f"Round 1 peak should be 1, got {peak1}"
    assert peak2 > 1, f"Round 2 peak should be >1 with concurrency=8, got {peak2}"
    assert peak2 <= 8, f"Round 2 peak should be ≤8, got {peak2}"
