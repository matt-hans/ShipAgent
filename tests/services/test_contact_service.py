"""Tests for ContactService CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
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
    with pytest.raises(IntegrityError):
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


# --- ContactService tests ---


def test_handle_pattern_valid():
    """Valid handles match the pattern."""
    from src.services.contact_service import HANDLE_PATTERN
    assert HANDLE_PATTERN.match("matt")
    assert HANDLE_PATTERN.match("nyc-warehouse")
    assert HANDLE_PATTERN.match("la-office-2")


def test_handle_pattern_invalid():
    """Invalid handles do not match."""
    from src.services.contact_service import HANDLE_PATTERN
    assert not HANDLE_PATTERN.match("")
    assert not HANDLE_PATTERN.match("Matt")  # uppercase
    assert not HANDLE_PATTERN.match("nyc warehouse")  # space
    assert not HANDLE_PATTERN.match("-leading")  # leading hyphen
    assert not HANDLE_PATTERN.match("trailing-")  # trailing hyphen


def test_create_contact(db: Session):
    """ContactService.create_contact creates a valid contact."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="matt",
        display_name="Matt Hans",
        address_line_1="123 Main St",
        city="San Francisco",
        state_province="CA",
        postal_code="94105",
    )
    db.commit()
    assert contact.handle == "matt"
    assert contact.display_name == "Matt Hans"


def test_create_contact_auto_slug(db: Session):
    """Handle is auto-generated from display_name when omitted."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    contact = svc.create_contact(
        display_name="NYC Warehouse LLC",
        address_line_1="456 Broadway",
        city="New York",
        state_province="NY",
        postal_code="10013",
    )
    db.commit()
    assert contact.handle == "nyc-warehouse"


def test_create_contact_duplicate_handle(db: Session):
    """Duplicate handle raises DuplicateHandleError."""
    from src.errors.domain import DuplicateHandleError
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    svc.create_contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    db.commit()
    with pytest.raises(DuplicateHandleError, match="already exists"):
        svc.create_contact(
            handle="matt", display_name="Other", address_line_1="456 Oak",
            city="LA", state_province="CA", postal_code="90001",
        )


def test_create_contact_invalid_handle(db: Session):
    """Invalid handle format raises ValidationError."""
    from src.errors.domain import ValidationError
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    with pytest.raises(ValidationError, match="Invalid handle"):
        svc.create_contact(
            handle="Bad Handle", display_name="Test", address_line_1="123",
            city="SF", state_province="CA", postal_code="94105",
        )


def test_get_by_handle(db: Session):
    """get_by_handle finds contacts case-insensitively."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    svc.create_contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    db.commit()
    assert svc.get_by_handle("matt") is not None
    assert svc.get_by_handle("MATT") is not None
    assert svc.get_by_handle("unknown") is None


def test_search_by_prefix(db: Session):
    """search_by_prefix returns matching candidates."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    svc.create_contact(handle="matt", display_name="Matt", address_line_1="1",
                       city="SF", state_province="CA", postal_code="94105")
    svc.create_contact(handle="mary", display_name="Mary", address_line_1="2",
                       city="SF", state_province="CA", postal_code="94105")
    svc.create_contact(handle="bob", display_name="Bob", address_line_1="3",
                       city="SF", state_province="CA", postal_code="94105")
    db.commit()
    results = svc.search_by_prefix("ma")
    assert len(results) == 2
    handles = {c.handle for c in results}
    assert handles == {"matt", "mary"}


def test_list_contacts_with_search(db: Session):
    """list_contacts filters by search term."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    svc.create_contact(handle="matt", display_name="Matt Hans", address_line_1="1",
                       city="San Francisco", state_province="CA", postal_code="94105")
    svc.create_contact(handle="bob", display_name="Bob Jones", address_line_1="2",
                       city="New York", state_province="NY", postal_code="10001")
    db.commit()
    results = svc.list_contacts(search="matt")
    assert len(results) == 1
    assert results[0].handle == "matt"


def test_update_contact(db: Session):
    """update_contact applies partial updates."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    db.commit()
    updated = svc.update_contact(contact.id, phone="+14155550100")
    assert updated.phone == "+14155550100"
    assert updated.display_name == "Matt"  # unchanged


def test_delete_contact(db: Session):
    """delete_contact removes the contact."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    db.commit()
    assert svc.delete_contact(contact.id) is True
    assert svc.get_by_handle("matt") is None


def test_touch_last_used(db: Session):
    """touch_last_used updates the timestamp."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    db.commit()
    assert contact.last_used_at is None
    svc.touch_last_used("matt")
    db.commit()
    refreshed = svc.get_by_handle("matt")
    assert refreshed.last_used_at is not None


def test_get_mru_contacts(db: Session):
    """get_mru_contacts returns contacts sorted by last_used_at DESC."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    svc.create_contact(handle="old", display_name="Old", address_line_1="1",
                            city="SF", state_province="CA", postal_code="94105")
    svc.create_contact(handle="new", display_name="New", address_line_1="2",
                            city="SF", state_province="CA", postal_code="94105")
    db.commit()
    svc.touch_last_used("old")
    db.commit()
    svc.touch_last_used("new")
    db.commit()
    mru = svc.get_mru_contacts(limit=2)
    assert mru[0].handle == "new"
    assert mru[1].handle == "old"


def test_resolve_handles(db: Session):
    """resolve_handles returns a dict mapping handles to contacts."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    svc.create_contact(handle="matt", display_name="Matt", address_line_1="1",
                       city="SF", state_province="CA", postal_code="94105")
    svc.create_contact(handle="bob", display_name="Bob", address_line_1="2",
                       city="NY", state_province="NY", postal_code="10001")
    db.commit()
    resolved = svc.resolve_handles(["matt", "bob", "unknown"])
    assert "matt" in resolved
    assert "bob" in resolved
    assert "unknown" not in resolved


# --- slugify_display_name tests ---


def test_slugify_display_name_basic():
    """slugify_display_name handles basic names."""
    from src.services.contact_service import slugify_display_name
    assert slugify_display_name("Matt Hans") == "matt-hans"
    assert slugify_display_name("NYC Warehouse") == "nyc-warehouse"


def test_slugify_display_name_strips_suffixes():
    """slugify_display_name strips business suffixes."""
    from src.services.contact_service import slugify_display_name
    assert slugify_display_name("Matt's LLC") == "matts"
    assert slugify_display_name("NYC Warehouse Inc.") == "nyc-warehouse"
    assert slugify_display_name("Acme Corp") == "acme"
    assert slugify_display_name("Big Co Ltd") == "big"


def test_slugify_display_name_preserves_if_all_suffixes():
    """slugify_display_name keeps all parts if stripping would leave nothing."""
    from src.services.contact_service import slugify_display_name
    assert slugify_display_name("LLC Inc") == "llc-inc"


# --- contact_to_order_data mapping tests ---


def test_contact_to_order_data_ship_to(db: Session):
    """contact_to_order_data produces valid ship_to_* keys for build_ship_to()."""
    from src.services.contact_service import ContactService, contact_to_order_data
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="matt", display_name="Matt Hans", address_line_1="123 Main St",
        address_line_2="Suite 4", city="San Francisco", state_province="CA",
        postal_code="94105", country_code="US", phone="+14155550100",
        company="ShipCo", attention_name="Matthew H",
    )
    db.commit()
    data = contact_to_order_data(contact, role="ship_to")
    assert data["ship_to_name"] == "Matt Hans"
    assert data["ship_to_attention_name"] == "Matthew H"
    assert data["ship_to_address1"] == "123 Main St"
    assert data["ship_to_address2"] == "Suite 4"
    assert data["ship_to_city"] == "San Francisco"
    assert data["ship_to_state"] == "CA"
    assert data["ship_to_postal_code"] == "94105"
    assert data["ship_to_country"] == "US"
    assert data["ship_to_phone"] == "+14155550100"
    assert data["ship_to_company"] == "ShipCo"


def test_contact_to_order_data_shipper(db: Session):
    """contact_to_order_data produces valid shipper_* keys when role='shipper'."""
    from src.services.contact_service import ContactService, contact_to_order_data
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="warehouse", display_name="NYC Warehouse",
        address_line_1="456 Broadway", city="New York", state_province="NY",
        postal_code="10013", use_as_shipper=True,
    )
    db.commit()
    data = contact_to_order_data(contact, role="shipper")
    assert data["shipper_name"] == "NYC Warehouse"
    assert data["shipper_address1"] == "456 Broadway"
    assert data["shipper_city"] == "New York"
    assert data["shipper_state"] == "NY"
    assert data["shipper_postal_code"] == "10013"


def test_contact_to_order_data_defaults_attention_to_display_name(db: Session):
    """contact_to_order_data falls back attention_name to display_name."""
    from src.services.contact_service import ContactService, contact_to_order_data
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="bob", display_name="Bob Jones", address_line_1="1 Main",
        city="LA", state_province="CA", postal_code="90001",
    )
    db.commit()
    data = contact_to_order_data(contact, role="ship_to")
    assert data["ship_to_attention_name"] == "Bob Jones"


def test_update_contact_partial_fields(db: Session):
    """update_contact only modifies provided fields, leaving others untouched."""
    from src.services.contact_service import ContactService
    svc = ContactService(db)
    contact = svc.create_contact(
        handle="matt", display_name="Matt Hans", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
        phone="+14155550100", email="matt@example.com",
    )
    db.commit()
    # Only update phone — everything else stays the same
    updated = svc.update_contact(contact.id, phone="+14155550199")
    assert updated.phone == "+14155550199"
    assert updated.email == "matt@example.com"  # untouched
    assert updated.display_name == "Matt Hans"  # untouched
    assert updated.city == "SF"  # untouched
