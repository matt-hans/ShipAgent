"""Tests for HttpClient — mocked HTTP responses."""

import json

import pytest
import httpx
from unittest.mock import AsyncMock, patch

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


class TestSubmitFile:
    """Tests for HttpClient.submit_file — event-sourced job ID and session cleanup."""

    def _make_submit_client(self) -> HttpClient:
        """Client with all upload+session endpoints mocked."""
        return _make_client({
            "/api/v1/data-sources/upload": (200, {"row_count": 5}),
            "/api/v1/jobs": (200, {"jobs": [], "total": 0, "limit": 50, "offset": 0}),
            "/api/v1/conversations": (201, {"session_id": "sess-xyz"}),
            "/api/v1/conversations/sess-xyz/messages": (200, {"status": "queued"}),
        })

    @pytest.mark.asyncio
    async def test_event_sourced_job_id_returned(self, tmp_path):
        """submit_file returns job_id captured from the preview_ready SSE event."""
        csv_file = tmp_path / "orders.csv"
        csv_file.write_text("name\nAlice\n")
        client = self._make_submit_client()

        with patch.object(client, "_drain_session_stream",
                          new=AsyncMock(return_value="job-from-event")):
            result = await client.submit_file(str(csv_file), None, False)

        assert result.job_id == "job-from-event"
        assert result.row_count == 5

    @pytest.mark.asyncio
    async def test_list_diff_fallback_when_no_event(self, tmp_path):
        """submit_file falls back to list diff when no preview_ready event is captured."""
        csv_file = tmp_path / "orders.csv"
        csv_file.write_text("name\nBob\n")

        new_job = JobSummary.from_api({
            "id": "job-new", "name": "New", "status": "pending",
            "total_rows": 3, "successful_rows": 0, "failed_rows": 0,
            "created_at": "2026-02-17T10:00:00Z",
        })

        client = _make_client({
            "/api/v1/data-sources/upload": (200, {"row_count": 3}),
            "/api/v1/conversations": (201, {"session_id": "sess-fallback"}),
            "/api/v1/conversations/sess-fallback/messages": (200, {}),
        })

        # First call (snapshot) returns empty; second call (diff) returns new job.
        with patch.object(client, "_drain_session_stream", new=AsyncMock(return_value=None)), \
             patch.object(client, "list_jobs",
                          new=AsyncMock(side_effect=[[], [new_job]])):
            result = await client.submit_file(str(csv_file), None, False)

        assert result.job_id == "job-new"

    @pytest.mark.asyncio
    async def test_session_deleted_after_extraction(self, tmp_path):
        """submit_file deletes the conversation session after capturing the job ID."""
        csv_file = tmp_path / "orders.csv"
        csv_file.write_text("name\nCarol\n")
        client = self._make_submit_client()

        with patch.object(client, "_drain_session_stream",
                          new=AsyncMock(return_value="job-abc")), \
             patch.object(client, "delete_session", new=AsyncMock()) as mock_delete:
            await client.submit_file(str(csv_file), None, False)

        mock_delete.assert_called_once_with("sess-xyz")
