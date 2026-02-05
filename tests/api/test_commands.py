"""Tests for command submission and history endpoints.

Tests the /api/v1/commands endpoints for submitting natural language
shipping commands and retrieving command history.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import Job, JobStatus


class TestSubmitCommand:
    """Tests for POST /api/v1/commands endpoint."""

    def test_submit_command_creates_job(self, client: TestClient, test_db: Session):
        """Submitting a command creates a new job with pending status."""
        response = client.post(
            "/api/v1/commands",
            json={"command": "Ship all orders from today using UPS Ground"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

        # Verify job was created in database
        job = test_db.query(Job).filter(Job.id == data["job_id"]).first()
        assert job is not None
        assert job.original_command == "Ship all orders from today using UPS Ground"
        assert job.status == JobStatus.pending.value

    def test_submit_command_truncates_long_name(
        self, client: TestClient, test_db: Session
    ):
        """Job name is truncated for long commands."""
        long_command = "Ship all orders from " + "x" * 100

        response = client.post("/api/v1/commands", json={"command": long_command})

        assert response.status_code == 201
        job = test_db.query(Job).filter(Job.id == response.json()["job_id"]).first()
        # Name format: "Command: " (9 chars) + first 50 chars + "..." (3 chars) = 62 max
        assert len(job.name) <= 62
        assert "..." in job.name

    def test_submit_command_validates_empty_input(self, client: TestClient):
        """Empty command returns 422 validation error."""
        response = client.post("/api/v1/commands", json={"command": ""})

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any("command" in str(e).lower() for e in detail)

    def test_submit_command_validates_missing_field(self, client: TestClient):
        """Missing command field returns 422 validation error."""
        response = client.post("/api/v1/commands", json={})

        assert response.status_code == 422

    def test_submit_command_returns_correct_format(self, client: TestClient):
        """Response contains job_id and status fields."""
        response = client.post(
            "/api/v1/commands", json={"command": "Ship order #12345"}
        )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert "status" in data
        # job_id should be a valid UUID format
        assert len(data["job_id"]) == 36


class TestCommandHistory:
    """Tests for GET /api/v1/commands/history endpoint."""

    def test_get_command_history_empty(self, client: TestClient):
        """Empty database returns empty list."""
        response = client.get("/api/v1/commands/history")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_command_history_returns_recent(
        self, client: TestClient, test_db: Session
    ):
        """Returns recently submitted commands."""
        # Create some jobs
        for i in range(3):
            job = Job(
                name=f"Test Job {i}",
                original_command=f"Command {i}",
                status=JobStatus.pending.value,
            )
            test_db.add(job)
        test_db.commit()

        response = client.get("/api/v1/commands/history")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should have required fields
        assert all("id" in item for item in data)
        assert all("command" in item for item in data)
        assert all("status" in item for item in data)
        assert all("created_at" in item for item in data)

    def test_command_history_respects_limit(
        self, client: TestClient, test_db: Session
    ):
        """Limit parameter restricts number of results."""
        # Create 10 jobs
        for i in range(10):
            job = Job(
                name=f"Test Job {i}",
                original_command=f"Command {i}",
                status=JobStatus.pending.value,
            )
            test_db.add(job)
        test_db.commit()

        response = client.get("/api/v1/commands/history?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    def test_command_history_default_limit(
        self, client: TestClient, test_db: Session
    ):
        """Default limit is 10."""
        # Create 15 jobs
        for i in range(15):
            job = Job(
                name=f"Test Job {i}",
                original_command=f"Command {i}",
                status=JobStatus.pending.value,
            )
            test_db.add(job)
        test_db.commit()

        response = client.get("/api/v1/commands/history")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 10

    def test_command_history_max_limit(self, client: TestClient):
        """Limit cannot exceed 50."""
        response = client.get("/api/v1/commands/history?limit=100")

        assert response.status_code == 422

    def test_command_history_ordered_by_date(
        self, client: TestClient, test_db: Session
    ):
        """Results are ordered by created_at descending (most recent first)."""
        # Create jobs - they will have sequential created_at timestamps
        for i in range(3):
            job = Job(
                name=f"Test Job {i}",
                original_command=f"Command {i}",
                status=JobStatus.pending.value,
            )
            test_db.add(job)
            test_db.commit()

        response = client.get("/api/v1/commands/history")
        data = response.json()

        # Most recent should be first (Command 2)
        assert data[0]["command"] == "Command 2"
        assert data[-1]["command"] == "Command 0"
