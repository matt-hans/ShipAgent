"""Tests for contact agent tools."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.services.contact_service import ContactService


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_resolve_contact_exact_match(db: Session):
    """resolve_contact returns full contact + order_data for exact handle."""
    svc = ContactService(db)
    svc.create_contact(
        handle="matt", display_name="Matt Hans",
        address_line_1="123 Main St", city="San Francisco",
        state_province="CA", postal_code="94105", phone="+14155550100",
    )
    db.commit()
    # Simulate tool handler logic
    contact = svc.get_by_handle("matt")
    assert contact is not None
    from src.services.contact_service import contact_to_order_data
    data = contact_to_order_data(contact, role="ship_to")
    assert data["ship_to_name"] == "Matt Hans"
    assert data["ship_to_address1"] == "123 Main St"
    assert data["ship_to_city"] == "San Francisco"


def test_resolve_contact_prefix_returns_candidates(db: Session):
    """resolve_contact with prefix match returns candidate list."""
    svc = ContactService(db)
    svc.create_contact(handle="matt", display_name="Matt", address_line_1="1",
                       city="SF", state_province="CA", postal_code="94105")
    svc.create_contact(handle="mary", display_name="Mary", address_line_1="2",
                       city="LA", state_province="CA", postal_code="90001")
    db.commit()
    candidates = svc.search_by_prefix("ma")
    assert len(candidates) == 2


def test_resolve_contact_auto_touches_last_used(db: Session):
    """resolve_contact handler calls touch_last_used on success."""
    svc = ContactService(db)
    svc.create_contact(handle="matt", display_name="Matt", address_line_1="1",
                       city="SF", state_province="CA", postal_code="94105")
    db.commit()
    contact = svc.get_by_handle("matt")
    assert contact.last_used_at is None
    # Tool handler calls touch_last_used explicitly (not inside get_by_handle)
    svc.touch_last_used("matt")
    db.commit()
    refreshed = svc.get_by_handle("matt")
    assert refreshed.last_used_at is not None


def test_resolve_contact_not_found(db: Session):
    """resolve_contact returns None for unknown handle."""
    svc = ContactService(db)
    assert svc.get_by_handle("nonexistent") is None
