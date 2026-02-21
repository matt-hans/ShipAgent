"""Tests for HttpClient — mocked HTTP responses."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.cli.http_client import HttpClient
from src.cli.protocol import JobSummary, ShipAgentClientError


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
    client = HttpClient(base_url="http://127.0.0.1:8000")
    transport = FakeTransport(responses)
    client._client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
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


class TestJobAudit:
    """Tests for HttpClient.get_job_audit_events."""

    @pytest.mark.asyncio
    async def test_get_job_audit_events(self):
        """Returns event list from agent audit endpoint."""
        client = _make_client({
            "/api/v1/agent-audit/jobs/job-1/events": (200, {
                "events": [{"id": "evt-1", "run_id": "run-1"}],
                "total": 1,
                "limit": 200,
                "offset": 0,
            }),
        })
        events = await client.get_job_audit_events("job-1")
        assert len(events) == 1
        assert events[0]["id"] == "evt-1"


class CapturingFakeTransport(httpx.AsyncBaseTransport):
    """Mock transport that captures requests and returns canned responses."""

    def __init__(self, responses: dict[str, tuple[int, dict]]):
        """Initialize with response map.

        Args:
            responses: Maps URL path substrings to (status_code, body) tuples.
        """
        self._responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request):
        """Record the request and return a matching canned response."""
        self.requests = getattr(self, "requests", [])
        self.requests.append(request)
        path = request.url.path
        for pattern, (status, body) in self._responses.items():
            if pattern in path:
                return httpx.Response(
                    status, json=body,
                    request=request,
                )
        return httpx.Response(404, json={"error": "not found"}, request=request)


def _make_capturing_client(
    responses: dict,
) -> tuple[HttpClient, CapturingFakeTransport]:
    """Create HttpClient with capturing mock transport.

    Returns:
        Tuple of (HttpClient, CapturingFakeTransport) so tests can inspect requests.
    """
    client = HttpClient(base_url="http://127.0.0.1:8000")
    transport = CapturingFakeTransport(responses)
    client._client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    return client, transport


class TestConnectPlatform:
    """Tests for HttpClient.connect_platform."""

    @pytest.mark.asyncio
    async def test_connect_platform_shopify_posts_to_connect_endpoint(self, monkeypatch):
        """Shopify connect sends POST to /platforms/shopify/connect with credentials payload."""
        monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test_token_123")
        monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "my-store.myshopify.com")

        client, transport = _make_capturing_client({
            "/api/v1/platforms/shopify/connect": (200, {"success": True}),
            "/api/v1/data-sources/status": (200, {
                "connected": True, "source_type": "shopify",
                "file_path": None, "row_count": 42, "columns": [],
            }),
        })

        await client.connect_platform("shopify")

        # Find the POST request to the connect endpoint
        connect_requests = [
            r for r in transport.requests
            if "/platforms/shopify/connect" in r.url.path and r.method == "POST"
        ]
        assert len(connect_requests) == 1, (
            f"Expected exactly one POST to connect endpoint, got {len(connect_requests)}"
        )
        body = json.loads(connect_requests[0].content)
        assert body == {
            "credentials": {"access_token": "shpat_test_token_123"},
            "store_url": "my-store.myshopify.com",
        }

    @pytest.mark.asyncio
    async def test_connect_platform_missing_env_vars_raises(self, monkeypatch):
        """Raises ShipAgentClientError when Shopify env vars are missing."""
        monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("SHOPIFY_STORE_DOMAIN", raising=False)

        client = _make_client({})
        with pytest.raises(ShipAgentClientError, match="SHOPIFY_ACCESS_TOKEN"):
            await client.connect_platform("shopify")

    @pytest.mark.asyncio
    async def test_connect_platform_non_shopify_raises(self):
        """Raises ShipAgentClientError for unsupported platform names."""
        client = _make_client({})
        with pytest.raises(ShipAgentClientError, match="Only 'shopify'"):
            await client.connect_platform("fedex")

        with pytest.raises(ShipAgentClientError, match="Only 'shopify'"):
            await client.connect_platform("woocommerce")


class TestInsecureCredentialTransport:
    """Tests for _reject_insecure_credential_transport."""

    def test_https_allowed(self):
        """HTTPS base URL passes without error."""
        from src.cli.http_client import _reject_insecure_credential_transport
        _reject_insecure_credential_transport("https://daemon.example.com:8443")

    def test_localhost_http_allowed(self):
        """Plain HTTP to localhost variants is safe."""
        from src.cli.http_client import _reject_insecure_credential_transport
        _reject_insecure_credential_transport("http://127.0.0.1:8000")
        _reject_insecure_credential_transport("http://localhost:8000")
        # IPv6 loopback — urlparse strips brackets, so hostname is "::1"
        _reject_insecure_credential_transport("http://[::1]:8000")

    def test_remote_http_blocked(self):
        """Plain HTTP to non-local host raises ShipAgentClientError."""
        from src.cli.http_client import _reject_insecure_credential_transport
        with pytest.raises(ShipAgentClientError, match="Refusing to send"):
            _reject_insecure_credential_transport("http://daemon.example.com:8000")

    @pytest.mark.asyncio
    async def test_connect_platform_blocks_remote_http(self, monkeypatch):
        """connect_platform rejects credentials over remote plain HTTP."""
        monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
        monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
        client = HttpClient(base_url="http://remote-daemon.example.com:8000")
        async with client:
            with pytest.raises(ShipAgentClientError, match="Refusing to send"):
                await client.connect_platform("shopify")
