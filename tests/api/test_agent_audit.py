"""Tests for agent decision audit API routes."""

from unittest.mock import MagicMock


def test_list_runs_endpoint(client, monkeypatch):
    """GET /agent-audit/runs returns service payload."""
    expected = {"runs": [{"id": "r1"}], "total": 1, "limit": 10, "offset": 0}
    mock_fn = MagicMock(return_value=expected)
    monkeypatch.setattr(
        "src.api.routes.agent_audit.DecisionAuditService.list_runs",
        mock_fn,
    )

    resp = client.get("/api/v1/agent-audit/runs?limit=10")
    assert resp.status_code == 200
    assert resp.json() == expected
    mock_fn.assert_called_once()


def test_get_run_404(client, monkeypatch):
    """GET /agent-audit/runs/{run_id} returns 404 when run missing."""
    monkeypatch.setattr(
        "src.api.routes.agent_audit.DecisionAuditService.get_run",
        MagicMock(return_value=None),
    )
    resp = client.get("/api/v1/agent-audit/runs/missing")
    assert resp.status_code == 404


def test_get_job_events_endpoint(client, monkeypatch):
    """GET /agent-audit/jobs/{job_id}/events returns event payload."""
    expected = {"events": [{"id": "e1"}], "total": 1, "limit": 20, "offset": 0}
    monkeypatch.setattr(
        "src.api.routes.agent_audit.DecisionAuditService.list_events_for_job",
        MagicMock(return_value=expected),
    )
    resp = client.get("/api/v1/agent-audit/jobs/job-1/events?limit=20")
    assert resp.status_code == 200
    assert resp.json() == expected


def test_export_requires_filter(client):
    """Export endpoint requires at least one filter."""
    resp = client.get("/api/v1/agent-audit/export")
    assert resp.status_code == 400


def test_export_jsonl(client, monkeypatch):
    """Export returns JSONL content."""
    monkeypatch.setattr(
        "src.api.routes.agent_audit.DecisionAuditService.export_events",
        MagicMock(return_value=[{"id": "e1", "run_id": "r1"}]),
    )
    resp = client.get("/api/v1/agent-audit/export?run_id=r1")
    assert resp.status_code == 200
    body = resp.text.strip().splitlines()
    assert len(body) == 1
    assert '"id":"e1"' in body[0]
