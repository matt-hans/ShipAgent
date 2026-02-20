"""Tests for ContactService CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Contact, CustomCommand


@pytest.fixture
def db() -> Session:
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_contact_model_creates(db: Session):
    """Contact model can be created with required fields."""
    contact = Contact(
        handle="matt",
        display_name="Matt Hans",
        address_line_1="123 Main St",
        city="San Francisco",
        state_province="CA",
        postal_code="94105",
    )
    db.add(contact)
    db.flush()
    assert contact.id is not None
    assert contact.handle == "matt"
    assert contact.country_code == "US"
    assert contact.use_as_ship_to is True
    assert contact.use_as_shipper is False


def test_contact_tag_list_property(db: Session):
    """tag_list property parses and serializes JSON tags."""
    contact = Contact(
        handle="warehouse",
        display_name="NYC Warehouse",
        address_line_1="456 Broadway",
        city="New York",
        state_province="NY",
        postal_code="10013",
    )
    contact.tag_list = ["warehouse", "east-coast"]
    db.add(contact)
    db.flush()
    assert contact.tag_list == ["warehouse", "east-coast"]
    assert '"warehouse"' in contact.tags


def test_contact_handle_unique(db: Session):
    """Duplicate handles raise IntegrityError."""
    c1 = Contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    c2 = Contact(
        handle="matt", display_name="Other Matt", address_line_1="456 Oak",
        city="LA", state_province="CA", postal_code="90001",
    )
    db.add(c1)
    db.flush()
    db.add(c2)
    with pytest.raises(Exception):  # IntegrityError
        db.flush()


def test_custom_command_model_creates(db: Session):
    """CustomCommand model can be created with required fields."""
    cmd = CustomCommand(
        name="daily-restock",
        body="Ship 3 boxes to @nyc-warehouse via UPS Ground",
    )
    db.add(cmd)
    db.flush()
    assert cmd.id is not None
    assert cmd.name == "daily-restock"
    assert cmd.created_at is not None
