"""Tests for contacts REST API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.schemas import (
    ContactCreate,
    ContactUpdate,
    ContactResponse,
    ContactListResponse,
    CommandCreate,
    CommandUpdate,
    CommandResponse,
    CommandListResponse,
)


def test_contact_schemas_importable():
    """All contact/command Pydantic schemas are importable."""
    assert ContactCreate is not None
    assert ContactUpdate is not None
    assert ContactResponse is not None
    assert ContactListResponse is not None
    assert CommandCreate is not None
    assert CommandUpdate is not None
    assert CommandResponse is not None
    assert CommandListResponse is not None


def test_create_contact_endpoint(client: TestClient):
    resp = client.post("/api/v1/contacts", json={
        "display_name": "Matt Hans",
        "address_line_1": "123 Main St",
        "city": "San Francisco",
        "state_province": "CA",
        "postal_code": "94105",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["handle"] == "matt-hans"
    assert data["display_name"] == "Matt Hans"


def test_list_contacts_endpoint(client: TestClient):
    client.post("/api/v1/contacts", json={
        "handle": "matt",
        "display_name": "Matt",
        "address_line_1": "1",
        "city": "SF",
        "state_province": "CA",
        "postal_code": "94105",
    })
    resp = client.get("/api/v1/contacts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


def test_get_contact_by_handle(client: TestClient):
    client.post("/api/v1/contacts", json={
        "handle": "matt",
        "display_name": "Matt",
        "address_line_1": "1",
        "city": "SF",
        "state_province": "CA",
        "postal_code": "94105",
    })
    resp = client.get("/api/v1/contacts/by-handle/matt")
    assert resp.status_code == 200
    assert resp.json()["handle"] == "matt"


def test_update_contact_endpoint(client: TestClient):
    create_resp = client.post("/api/v1/contacts", json={
        "handle": "matt",
        "display_name": "Matt",
        "address_line_1": "1",
        "city": "SF",
        "state_province": "CA",
        "postal_code": "94105",
    })
    contact_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/contacts/{contact_id}", json={
        "phone": "+14155550100",
    })
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+14155550100"


def test_delete_contact_endpoint(client: TestClient):
    create_resp = client.post("/api/v1/contacts", json={
        "handle": "matt",
        "display_name": "Matt",
        "address_line_1": "1",
        "city": "SF",
        "state_province": "CA",
        "postal_code": "94105",
    })
    contact_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/contacts/{contact_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
