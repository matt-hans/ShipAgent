"""Tests for optional API-key auth middleware behavior."""

from fastapi.testclient import TestClient


def test_api_auth_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)

    response = client.get("/api/v1/jobs")
    assert response.status_code == 200


def test_api_auth_enforced_when_key_is_set(client: TestClient, monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", "test-secret")

    response = client.get("/api/v1/jobs")
    assert response.status_code == 401

    response = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401

    response = client.get("/api/v1/jobs", headers={"X-API-Key": "test-secret"})
    assert response.status_code == 200


def test_health_and_readyz_are_public(client: TestClient, monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", "test-secret")

    assert client.get("/health").status_code == 200
    assert client.get("/readyz").status_code in {200, 503}

