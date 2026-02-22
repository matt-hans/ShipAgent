"""Integration tests for production readiness features.

Validates end-to-end flows for settings, credentials, onboarding,
runtime detection, and environment variable overrides.
"""

import os
import sys
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SHIPAGENT_SKIP_SDK_CHECK", "true")
os.environ.setdefault(
    "FILTER_TOKEN_SECRET",
    "test-filter-token-secret-with-32chars",
)

from src.api.main import app
from src.db.connection import get_db
from src.db.models import Base


@pytest.fixture
def test_db() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = testing_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(test_db: Session) -> Generator[TestClient, None, None]:
    """Create a TestClient with overridden database dependency."""

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    # Mock agent processing to prevent real Claude API calls
    async def _noop_process(
        session_id: str, content: str, run_id: str | None = None
    ) -> None:
        from src.api.routes.conversations import _get_event_queue

        queue = _get_event_queue(session_id)
        await queue.put({"event": "done", "data": {}})

    app.dependency_overrides[get_db] = override_get_db
    with (
        patch(
            "src.api.routes.conversations._process_agent_message",
            _noop_process,
        ),
        TestClient(app) as c,
    ):
        yield c
    app.dependency_overrides.clear()


# ============================================================================
# Runtime Detection
# ============================================================================


def test_bundled_mcp_config_resolves_self():
    """In bundled mode, MCP config uses self-executable."""
    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "executable", "/fake/shipagent-core"):
            from src.orchestrator.agent.config import get_data_mcp_config

            config = get_data_mcp_config()
            assert config["command"] == "/fake/shipagent-core"
            assert config["args"] == ["mcp-data"]


# ============================================================================
# Settings Round-Trip
# ============================================================================


def test_settings_round_trip(client: TestClient):
    """Settings can be saved and loaded."""
    # Save
    resp = client.patch("/api/v1/settings", json={"shipper_name": "Test Inc"})
    assert resp.status_code == 200
    assert resp.json()["shipper_name"] == "Test Inc"

    # Load
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json()["shipper_name"] == "Test Inc"


# ============================================================================
# Credential Status
# ============================================================================


def test_credential_status_endpoint(client: TestClient):
    """Credential status returns booleans, never values."""
    resp = client.get("/api/v1/settings/credentials/status")
    assert resp.status_code == 200
    data = resp.json()
    # All fields are booleans
    for key, value in data.items():
        assert isinstance(value, bool), f"{key} should be bool, got {type(value)}"


# ============================================================================
# Onboarding Flow
# ============================================================================


def test_onboarding_flow(client: TestClient):
    """Onboarding starts incomplete, can be completed."""
    resp = client.get("/api/v1/settings")
    assert resp.json()["onboarding_completed"] is False

    resp = client.post("/api/v1/settings/onboarding/complete")
    assert resp.status_code == 200

    resp = client.get("/api/v1/settings")
    assert resp.json()["onboarding_completed"] is True


# ============================================================================
# Environment Variable Override
# ============================================================================


def test_env_var_override_still_works():
    """DATABASE_URL env var takes priority over platformdirs."""
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///override.db"}):
        from src.db.connection import get_database_url

        assert get_database_url() == "sqlite:///override.db"
