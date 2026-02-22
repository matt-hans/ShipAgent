"""Tests for SettingsService."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import AppSettings, Base
from src.services.settings_service import SettingsService


@pytest.fixture
def db_session() -> Session:
    """In-memory SQLite for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def service(db_session: Session) -> SettingsService:
    """Create a SettingsService with test DB."""
    return SettingsService(db_session)


def test_get_or_create_returns_singleton(service: SettingsService, db_session: Session):
    """First call creates, second call returns same row."""
    s1 = service.get_or_create()
    s2 = service.get_or_create()
    assert s1.id == s2.id
    # Only one row in table
    assert db_session.query(AppSettings).count() == 1


def test_get_or_create_has_defaults(service: SettingsService):
    """New settings have sensible defaults."""
    s = service.get_or_create()
    assert s.agent_model is None  # Uses env var default
    assert s.batch_concurrency == 5
    assert s.onboarding_completed is False


def test_update_settings_patch_semantics(service: SettingsService, db_session: Session):
    """Only provided fields are updated; others untouched."""
    s = service.get_or_create()
    original_concurrency = s.batch_concurrency

    service.update({"shipper_name": "Acme Corp"})
    db_session.commit()
    db_session.refresh(s)

    assert s.shipper_name == "Acme Corp"
    assert s.batch_concurrency == original_concurrency  # Unchanged


def test_update_settings_rejects_unknown_fields(service: SettingsService):
    """Unknown fields raise ValueError."""
    service.get_or_create()
    with pytest.raises(ValueError, match="Unknown setting"):
        service.update({"nonexistent_field": "value"})


def test_complete_onboarding(service: SettingsService, db_session: Session):
    """Marking onboarding complete persists."""
    s = service.get_or_create()
    assert s.onboarding_completed is False
    service.complete_onboarding()
    db_session.commit()
    db_session.refresh(s)
    assert s.onboarding_completed is True
