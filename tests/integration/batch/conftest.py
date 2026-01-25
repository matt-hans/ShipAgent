"""Fixtures for batch integration tests."""

import csv
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Job, JobRow, JobStatus, RowStatus
from src.services.job_service import JobService
from src.services.audit_service import AuditService


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Create temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)

    yield path

    os.unlink(path)


@pytest.fixture
def db_session(temp_db: str):
    """Create database session."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def job_service(db_session) -> JobService:
    """Create JobService with test database."""
    return JobService(db_session)


@pytest.fixture
def audit_service(db_session) -> AuditService:
    """Create AuditService with test database."""
    return AuditService(db_session)


@pytest.fixture
def temp_csv() -> Generator[str, None, None]:
    """Create temporary CSV file with sample data."""
    fd, path = tempfile.mkstemp(suffix=".csv")

    with os.fdopen(fd, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "order_id", "recipient_name", "address", "city", "state", "zip", "weight"
        ])
        writer.writeheader()
        for i in range(10):
            writer.writerow({
                "order_id": 1000 + i,
                "recipient_name": f"Customer {i}",
                "address": f"{i}00 Main St",
                "city": "Los Angeles",
                "state": "CA",
                "zip": "90001",
                "weight": 2.5 + i * 0.5,
            })

    yield path
    os.unlink(path)


@pytest.fixture
def mock_data_mcp() -> AsyncMock:
    """Mock Data MCP call function."""
    mock = AsyncMock()

    async def call_impl(tool_name: str, args: dict):
        if tool_name == "get_rows_by_filter":
            # Return sample rows
            rows = [
                {"row_number": i, "data": {"order_id": 1000 + i, "recipient_name": f"Customer {i}"}}
                for i in range(min(args.get("limit", 10), 10))
            ]
            return {"rows": rows, "total_count": 10}
        elif tool_name == "get_row":
            return {"row_number": args["row_number"], "data": {"order_id": 1000 + args["row_number"]}}
        elif tool_name == "write_back":
            return {"success": True}
        return {}

    mock.side_effect = call_impl
    return mock


@pytest.fixture
def mock_ups_mcp() -> AsyncMock:
    """Mock UPS MCP call function."""
    mock = AsyncMock()

    async def call_impl(tool_name: str, args: dict):
        if tool_name == "rating_quote":
            return {"totalCharges": {"amount": "15.50"}}
        elif tool_name == "shipping_create":
            return {
                "trackingNumbers": ["1Z999AA10123456784"],
                "labelPaths": ["/labels/test.pdf"],
                "totalCharges": {"monetaryValue": "15.50"},
            }
        return {}

    mock.side_effect = call_impl
    return mock


@pytest.fixture
def sample_job(job_service: JobService) -> Job:
    """Create sample job with rows."""
    job = job_service.create_job(
        name="Test Batch",
        original_command="Ship California orders via Ground",
    )
    job_service.create_rows(job.id, [
        {"row_number": i, "row_checksum": f"hash{i}"}
        for i in range(1, 6)
    ])
    return job
