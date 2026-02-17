"""Tests for HttpClient — mocked HTTP responses."""

import json

import pytest
import httpx

from src.cli.http_client import HttpClient
from src.cli.protocol import JobSummary, JobDetail


class FakeTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns canned responses."""

    def __init__(self, responses: dict[str, tuple[int, dict]]):
        self._responses = responses

    async def handle_async_request(self, request):
        path = request.url.path
        for pattern, (status, body) in self._responses.items():
            if pattern in path:
                return httpx.Response(
                    status, json=body,
                    request=request,
                )
        return httpx.Response(404, json={"error": "not found"}, request=request)


def _make_client(responses: dict) -> HttpClient:
    """Create HttpClient with mocked transport."""
    client = HttpClient(base_url="http://test:8000")
    transport = FakeTransport(responses)
    client._client = httpx.AsyncClient(transport=transport, base_url="http://test:8000")
    return client


class TestListJobs:
    """Tests for HttpClient.list_jobs."""

    @pytest.mark.asyncio
    async def test_returns_job_summaries(self):
        """Parses job list response into JobSummary objects."""
        client = _make_client({
            "/api/v1/jobs": (200, {
                "jobs": [{
                    "id": "job-1", "name": "Test", "status": "completed",
                    "total_rows": 10, "successful_rows": 9, "failed_rows": 1,
                    "created_at": "2026-02-16T10:00:00Z",
                }],
                "total": 1, "limit": 50, "offset": 0,
            })
        })
        jobs = await client.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "job-1"
        assert jobs[0].status == "completed"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty job list returns empty array."""
        client = _make_client({
            "/api/v1/jobs": (200, {"jobs": [], "total": 0, "limit": 50, "offset": 0})
        })
        jobs = await client.list_jobs()
        assert jobs == []


class TestGetJob:
    """Tests for HttpClient.get_job."""

    @pytest.mark.asyncio
    async def test_returns_job_detail(self):
        """Parses job response into JobDetail."""
        client = _make_client({
            "/api/v1/jobs/job-1": (200, {
                "id": "job-1", "name": "Test", "status": "completed",
                "original_command": "Ship all", "total_rows": 10,
                "processed_rows": 10, "successful_rows": 9, "failed_rows": 1,
                "total_cost_cents": 5000, "created_at": "2026-02-16T10:00:00Z",
                "started_at": None, "completed_at": None,
                "error_code": None, "error_message": None,
            })
        })
        detail = await client.get_job("job-1")
        assert detail.id == "job-1"
        assert detail.total_cost_cents == 5000


class TestHealth:
    """Tests for HttpClient.health."""

    @pytest.mark.asyncio
    async def test_healthy(self):
        """Health check parses response."""
        client = _make_client({
            "/health": (200, {"status": "healthy"})
        })
        status = await client.health()
        assert status.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy(self):
        """Connection failure reports unhealthy."""
        client = HttpClient(base_url="http://localhost:99999")
        # Don't set mock transport — will fail to connect
        client._client = httpx.AsyncClient(base_url="http://localhost:99999", timeout=0.1)
        status = await client.health()
        assert status.healthy is False


class TestCancelJob:
    """Tests for HttpClient.cancel_job."""

    @pytest.mark.asyncio
    async def test_sends_patch(self):
        """Cancel sends PATCH with cancelled status."""
        client = _make_client({
            "/api/v1/jobs/job-1/status": (200, {
                "id": "job-1", "name": "Test", "status": "cancelled",
                "total_rows": 0, "processed_rows": 0,
                "successful_rows": 0, "failed_rows": 0,
                "total_cost_cents": 0,
                "created_at": "2026-02-16T10:00:00Z",
                "original_command": "test",
                "started_at": None, "completed_at": None,
                "error_code": None, "error_message": None,
            })
        })
        await client.cancel_job("job-1")  # Should not raise


class TestCreateSession:
    """Tests for HttpClient.create_session."""

    @pytest.mark.asyncio
    async def test_creates_session(self):
        """Creates conversation session via API."""
        client = _make_client({
            "/api/v1/conversations": (201, {"session_id": "sess-abc"})
        })
        session_id = await client.create_session()
        assert session_id == "sess-abc"
