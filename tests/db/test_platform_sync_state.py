# tests/db/test_platform_sync_state.py
"""Tests for PlatformSyncState model."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.db.models import Base, PlatformSyncState


@pytest.fixture
def db_session(tmp_path):
    """Use temp file DB (not :memory:) so multiple sessions see same data."""
    db_path = str(tmp_path / "test_sync_state.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestPlatformSyncState:
    def test_create_and_read(self, db_session):
        now = datetime.now(timezone.utc)
        state = PlatformSyncState(
            platform_id="shopify",
            credential_ref="primary",
            connection_status="disconnected",
            created_at=now,
            updated_at=now,
        )
        db_session.add(state)
        db_session.commit()

        loaded = db_session.get(PlatformSyncState, ("shopify", "primary"))
        assert loaded is not None
        assert loaded.connection_status == "disconnected"
        assert loaded.consecutive_failure_count == 0

    def test_composite_primary_key(self, db_session):
        now = datetime.now(timezone.utc)
        state1 = PlatformSyncState(
            platform_id="shopify", credential_ref="primary",
            connection_status="connected", created_at=now, updated_at=now,
        )
        state2 = PlatformSyncState(
            platform_id="shopify", credential_ref="sandbox",
            connection_status="disconnected", created_at=now, updated_at=now,
        )
        db_session.add_all([state1, state2])
        db_session.commit()

        assert db_session.query(PlatformSyncState).count() == 2

    def test_update_sync_checkpoint(self, db_session):
        now = datetime.now(timezone.utc)
        state = PlatformSyncState(
            platform_id="amazon", credential_ref="us_store",
            connection_status="connected", created_at=now, updated_at=now,
        )
        db_session.add(state)
        db_session.commit()

        state.resume_cursor = "cursor_page_3"
        state.last_sync_row_count = 150
        db_session.commit()

        loaded = db_session.get(PlatformSyncState, ("amazon", "us_store"))
        assert loaded.resume_cursor == "cursor_page_3"
        assert loaded.last_sync_row_count == 150

    def test_default_values(self, db_session):
        now = datetime.now(timezone.utc)
        state = PlatformSyncState(
            platform_id="test", credential_ref="default",
            created_at=now, updated_at=now,
        )
        db_session.add(state)
        db_session.commit()

        loaded = db_session.get(PlatformSyncState, ("test", "default"))
        assert loaded.connection_status == "disconnected"
        assert loaded.consecutive_failure_count == 0
        assert loaded.resume_cursor is None
        assert loaded.last_completed_watermark is None
