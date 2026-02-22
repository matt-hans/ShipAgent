"""Tests for settings API routes."""

from fastapi.testclient import TestClient


def test_get_settings_returns_defaults(client: TestClient):
    """GET /settings returns default settings."""
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch_concurrency"] == 5
    assert data["onboarding_completed"] is False


def test_patch_settings_updates_fields(client: TestClient):
    """PATCH /settings updates specified fields."""
    resp = client.patch(
        "/api/v1/settings",
        json={"shipper_name": "Test Corp", "batch_concurrency": 10}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["shipper_name"] == "Test Corp"
    assert data["batch_concurrency"] == 10


def test_get_credential_status(client: TestClient):
    """GET /settings/credentials/status shows which keys are set."""
    resp = client.get("/api/v1/settings/credentials/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "anthropic_api_key" in data
    # Should be False since no key is set in test (unless env var set)
    assert isinstance(data["anthropic_api_key"], bool)


def test_post_onboarding_complete(client: TestClient):
    """POST /settings/onboarding/complete marks onboarding done."""
    resp = client.post("/api/v1/settings/onboarding/complete")
    assert resp.status_code == 200

    # Verify it persisted
    resp2 = client.get("/api/v1/settings")
    assert resp2.json()["onboarding_completed"] is True
