"""Pytest fixtures for API tests.

Provides test client, database session, and sample data fixtures
for testing FastAPI endpoints.
"""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.db.connection import get_db
from src.db.models import Base, Job, JobRow, JobStatus, RowStatus


@pytest.fixture
def test_db() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database for testing.

    Creates all tables, yields a session, and cleans up after test.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(test_db: Session) -> Generator[TestClient, None, None]:
    """Create a TestClient with overridden database dependency.

    Args:
        test_db: Test database session fixture.

    Yields:
        TestClient configured for testing.
    """

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_job(test_db: Session) -> Job:
    """Create a sample job in the test database.

    Returns:
        Job instance with pending status.
    """
    job = Job(
        name="Test Job",
        original_command="Ship all orders using UPS Ground",
        status=JobStatus.pending.value,
        total_rows=5,
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)
    return job


@pytest.fixture
def job_with_rows(test_db: Session, sample_job: Job) -> Job:
    """Create a job with multiple rows in the test database.

    Args:
        test_db: Test database session.
        sample_job: Base job fixture.

    Returns:
        Job with rows attached.
    """
    for i in range(1, 6):
        row = JobRow(
            job_id=sample_job.id,
            row_number=i,
            row_checksum=f"checksum_{i}",
            status=RowStatus.pending.value,
            cost_cents=1000 + i * 100,
        )
        test_db.add(row)

    test_db.commit()
    test_db.refresh(sample_job)
    return sample_job


@pytest.fixture
def completed_job(test_db: Session) -> Job:
    """Create a completed job with tracking numbers and label paths.

    Returns:
        Completed job with processed rows.
    """
    job = Job(
        name="Completed Job",
        original_command="Ship all California orders",
        status=JobStatus.completed.value,
        total_rows=3,
        processed_rows=3,
        successful_rows=3,
        total_cost_cents=3500,
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)

    # Add completed rows with tracking numbers
    for i in range(1, 4):
        row = JobRow(
            job_id=job.id,
            row_number=i,
            row_checksum=f"checksum_{i}",
            status=RowStatus.completed.value,
            tracking_number=f"1Z999AA1001234500{i}",
            cost_cents=1000 + i * 100,
        )
        test_db.add(row)

    test_db.commit()
    return job


@pytest.fixture
def temp_label_dir(tmp_path):
    """Create a temporary directory for test label files.

    Args:
        tmp_path: pytest built-in fixture for temp directory.

    Returns:
        Path to temporary directory.
    """
    return tmp_path


@pytest.fixture
def sample_label_file(temp_label_dir):
    """Create a sample PDF label file for testing.

    Args:
        temp_label_dir: Temporary directory fixture.

    Returns:
        Path to the test PDF file.
    """
    label_path = temp_label_dir / "1Z999AA10012345001.pdf"
    # Create a minimal PDF-like content (not a real PDF but enough for testing)
    label_path.write_bytes(b"%PDF-1.4\nTest PDF content\n%%EOF")
    return label_path


def create_valid_pdf(path: Path) -> Path:
    """Create a valid PDF file that pypdf can read.

    Args:
        path: Where to write the PDF file.

    Returns:
        The path to the created file.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=288, height=432)
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def valid_label_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for valid PDF label files.

    Args:
        tmp_path: pytest built-in fixture for temp directory.

    Returns:
        Path to temporary directory.
    """
    return tmp_path
