"""Tests for /connections API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.db.connection import get_db
from src.db.models import Base


@pytest.fixture
def db_engine():
    """Create in-memory SQLite engine with StaticPool."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_client(db_engine, tmp_path, monkeypatch):
    """Provide a TestClient with DB override and temp key dir."""
    Session = sessionmaker(bind=db_engine)

    # Override key dir to use temp directory
    monkeypatch.setenv("SHIPAGENT_CREDENTIAL_KEY_FILE", "")
    monkeypatch.setenv("SHIPAGENT_CREDENTIAL_KEY", "")
    monkeypatch.delenv("SHIPAGENT_CREDENTIAL_KEY_FILE", raising=False)
    monkeypatch.delenv("SHIPAGENT_CREDENTIAL_KEY", raising=False)

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _ups_payload(**overrides):
    """Build a standard UPS save payload."""
    payload = {
        "auth_mode": "client_credentials",
        "credentials": {"client_id": "test_id", "client_secret": "test_sec"},
        "metadata": {},
        "environment": "test",
        "display_name": "UPS Test",
    }
    payload.update(overrides)
    return payload


def _shopify_payload(**overrides):
    """Build a standard Shopify save payload."""
    payload = {
        "auth_mode": "legacy_token",
        "credentials": {"access_token": "shpat_test123"},
        "metadata": {"store_domain": "mystore.myshopify.com"},
        "display_name": "My Store",
    }
    payload.update(overrides)
    return payload


class TestListConnections:

    def test_list_empty(self, test_client):
        """GET /connections/ returns empty list."""
        resp = test_client.get("/api/v1/connections/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_ordered_with_runtime_usable(self, test_client):
        """GET /connections/ returns ordered results with runtime_usable."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        test_client.post("/api/v1/connections/shopify/save", json=_shopify_payload())

        resp = test_client.get("/api/v1/connections/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Shopify alphabetically before UPS
        assert data[0]["provider"] == "shopify"
        assert data[1]["provider"] == "ups"
        # runtime_usable present
        assert "runtime_usable" in data[0]
        assert "runtime_usable" in data[1]

    def test_no_credentials_in_list(self, test_client):
        """List responses never expose credentials."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        resp = test_client.get("/api/v1/connections/")
        data = resp.json()
        for conn in data:
            assert "encrypted_credentials" not in conn
            assert "client_id" not in conn
            assert "client_secret" not in conn


class TestSaveConnection:

    def test_save_ups_creates_201(self, test_client):
        """POST /connections/ups/save returns 201 on create."""
        resp = test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_new"] is True
        assert data["connection_key"] == "ups:test"

    def test_save_ups_overwrite_200(self, test_client):
        """POST /connections/ups/save returns 200 on overwrite."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        resp = test_client.post("/api/v1/connections/ups/save", json=_ups_payload(
            display_name="UPS v2",
        ))
        assert resp.status_code == 200
        assert resp.json()["is_new"] is False

    def test_save_shopify(self, test_client):
        """POST /connections/shopify/save saves Shopify credentials."""
        resp = test_client.post("/api/v1/connections/shopify/save", json=_shopify_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["connection_key"] == "shopify:mystore.myshopify.com"

    def test_invalid_provider_400(self, test_client):
        """Invalid provider returns 400."""
        resp = test_client.post("/api/v1/connections/fedex/save", json={
            "auth_mode": "oauth", "credentials": {}, "metadata": {},
            "display_name": "FedEx",
        })
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_PROVIDER"

    def test_missing_fields_400(self, test_client):
        """Missing required fields returns 400."""
        resp = test_client.post("/api/v1/connections/ups/save", json={
            "auth_mode": "client_credentials",
            "credentials": {"client_id": "only_id"},
            "metadata": {}, "environment": "test",
            "display_name": "UPS",
        })
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "MISSING_FIELD"


class TestGetConnection:

    def test_get_connection(self, test_client):
        """GET /connections/{key} returns connection with runtime_usable."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        resp = test_client.get("/api/v1/connections/ups:test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "ups"
        assert "runtime_usable" in data

    def test_get_not_found_404(self, test_client):
        """GET /connections/{key} returns 404 for missing."""
        resp = test_client.get("/api/v1/connections/ups:nonexistent")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_no_credentials_in_get(self, test_client):
        """Get response never exposes credentials."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        resp = test_client.get("/api/v1/connections/ups:test")
        data = resp.json()
        assert "encrypted_credentials" not in data
        assert "client_id" not in data


class TestDeleteConnection:

    def test_delete_connection(self, test_client):
        """DELETE /connections/{key} removes connection."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        resp = test_client.delete("/api/v1/connections/ups:test")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_not_found_404(self, test_client):
        """DELETE /connections/{key} returns 404 for missing."""
        resp = test_client.delete("/api/v1/connections/ups:nonexistent")
        assert resp.status_code == 404


class TestDisconnectConnection:

    def test_disconnect_preserves_row(self, test_client):
        """POST /connections/{key}/disconnect sets status, preserves row."""
        test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        resp = test_client.post("/api/v1/connections/ups:test/disconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disconnected"
        # Row still exists
        get_resp = test_client.get("/api/v1/connections/ups:test")
        assert get_resp.status_code == 200

    def test_disconnect_not_found(self, test_client):
        """Disconnect returns 404 for missing key."""
        resp = test_client.post("/api/v1/connections/ups:nonexistent/disconnect")
        assert resp.status_code == 404


class TestServiceConstructionFailure:

    def test_save_returns_json_500_on_service_init_failure(self, test_client, monkeypatch):
        """Service construction failure returns structured JSON 500, not bare text.

        When ConnectionService.__init__ raises (e.g. encryption key issue),
        the route must still return a JSON error envelope so the frontend
        can display a meaningful message.
        """
        from src.services.connection_service import ConnectionService

        original_init = ConnectionService.__init__

        def bad_init(self, db, key_dir=None):
            raise RuntimeError("Key file permission denied")

        monkeypatch.setattr(ConnectionService, "__init__", bad_init)

        resp = test_client.post("/api/v1/connections/ups/save", json=_ups_payload())
        assert resp.status_code == 500
        assert resp.headers["content-type"] == "application/json"
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "permission denied" in body["error"]["message"].lower()

    def test_list_returns_json_500_on_service_init_failure(self, test_client, monkeypatch):
        """List endpoint also returns structured JSON 500 on init failure."""
        from src.services.connection_service import ConnectionService

        def bad_init(self, db, key_dir=None):
            raise RuntimeError("Key not found")

        monkeypatch.setattr(ConnectionService, "__init__", bad_init)

        resp = test_client.get("/api/v1/connections/")
        assert resp.status_code == 500
        assert resp.headers["content-type"] == "application/json"
        assert resp.json()["error"]["code"] == "INTERNAL_ERROR"


class TestValidateConnection:

    def test_validate_not_found(self, test_client):
        """POST /connections/{key}/validate returns 404 for missing connection."""
        resp = test_client.post("/api/v1/connections/ups:test/validate")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_validate_shopify_auth_failure(self, test_client):
        """POST /connections/{key}/validate returns 422 with descriptive error for invalid Shopify token."""
        # Save credentials first
        save_resp = test_client.post(
            "/api/v1/connections/shopify/save",
            json=_shopify_payload(),
        )
        assert save_resp.status_code == 201
        connection_key = save_resp.json()["connection_key"]

        # Validate — will fail because token is fake
        resp = test_client.post(f"/api/v1/connections/{connection_key}/validate")
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False
        assert body["status"] == "error"
        assert len(body["message"]) > 0

    def test_validate_ups_auth_failure(self, test_client):
        """POST /connections/{key}/validate returns 422 with descriptive error for invalid UPS creds."""
        # Save credentials first
        save_resp = test_client.post(
            "/api/v1/connections/ups/save",
            json=_ups_payload(),
        )
        assert save_resp.status_code == 201
        connection_key = save_resp.json()["connection_key"]

        # Validate — will fail because creds are fake
        resp = test_client.post(f"/api/v1/connections/{connection_key}/validate")
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False
        assert body["status"] == "error"
        assert len(body["message"]) > 0

    def test_validate_updates_status_to_error(self, test_client):
        """Validation failure updates connection status to 'error' with error code."""
        save_resp = test_client.post(
            "/api/v1/connections/shopify/save",
            json=_shopify_payload(),
        )
        connection_key = save_resp.json()["connection_key"]

        # Validate (will fail)
        test_client.post(f"/api/v1/connections/{connection_key}/validate")

        # Get connection — status should be 'error'
        get_resp = test_client.get(f"/api/v1/connections/{connection_key}")
        conn = get_resp.json()
        assert conn["status"] == "error"
        assert conn["last_error_code"] is not None


class TestCustom422Handler:

    def test_422_redaction_strips_input_values(self, test_client):
        """Custom 422 handler strips raw input values for connection routes."""
        # Send a non-dict body (string) to trigger 422
        resp = test_client.post(
            "/api/v1/connections/ups/save",
            content=b'"my_secret_password_123"',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
        body = resp.json()
        # Must have error wrapper
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        # Secret should NOT appear in the response
        body_str = str(body)
        assert "my_secret_password_123" not in body_str
