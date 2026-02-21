"""Tests for custom commands REST API routes."""

from fastapi.testclient import TestClient


def test_create_command_endpoint(client: TestClient):
    resp = client.post("/api/v1/commands", json={
        "name": "daily-restock",
        "body": "Ship 3 boxes to @nyc-warehouse via UPS Ground",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "daily-restock"


def test_list_commands_endpoint(client: TestClient):
    client.post("/api/v1/commands", json={"name": "alpha", "body": "a"})
    client.post("/api/v1/commands", json={"name": "beta", "body": "b"})
    resp = client.get("/api/v1/commands")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_update_command_endpoint(client: TestClient):
    create_resp = client.post("/api/v1/commands", json={
        "name": "test", "body": "old",
    })
    cmd_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/commands/{cmd_id}", json={"body": "new"})
    assert resp.status_code == 200
    assert resp.json()["body"] == "new"


def test_delete_command_endpoint(client: TestClient):
    create_resp = client.post("/api/v1/commands", json={
        "name": "test", "body": "body",
    })
    cmd_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/commands/{cmd_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
