# Contact Book, Custom Commands & Settings Panel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent address book with @handle mentions, user-defined /commands, a settings flyout panel, and syntax-highlighted chat input.

**Architecture:** Backend-first (SQLAlchemy models + services + REST + CLI), then agent tools + system prompt, then frontend components (flyout, modal, rich input). All data persists in SQLite via existing `Base.metadata.create_all()`. Services follow the static-method pattern from `SavedDataSourceService`. Routes follow the dependency-injection pattern from `saved_data_sources.py`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Typer/Rich (CLI), React + TypeScript + Tailwind (frontend)

**Design doc:** `docs/plans/2026-02-19-contacts-commands-settings-design.md`

---

## Phase A: Backend Foundation

### Task 1: Contact + CustomCommand SQLAlchemy Models

**Files:**
- Modify: `src/db/models.py` (append after `SavedDataSource` class, ~line 580)

**Step 1: Write failing test**

Create `tests/services/test_contact_service.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_contact_service.py -v -x`
Expected: FAIL — `ImportError: cannot import name 'Contact'`

**Step 3: Implement Contact + CustomCommand models**

Add to `src/db/models.py` after the `SavedDataSource` class (after line 579):

```python
class Contact(Base):
    """Persistent address book contact for @handle resolution.

    Stores recipient/shipper/third-party address profiles that can be
    referenced via @handle in chat messages and custom commands.

    Attributes:
        handle: Unique lowercase slug for @mention resolution.
        display_name: Human-readable name shown in UI.
        attention_name: UPS AttentionName override (optional).
        use_as_ship_to: Whether this contact can populate ShipTo.
        use_as_shipper: Whether this contact can populate Shipper.
        use_as_third_party: Whether this contact can populate ThirdParty.
        last_used_at: Timestamp for MRU ranking in system prompt injection.
    """

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    handle: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    attention_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state_province: Mapped[str] = mapped_column(String(50), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="US"
    )
    use_as_ship_to: Mapped[bool] = mapped_column(
        nullable=False, server_default="1"
    )
    use_as_shipper: Mapped[bool] = mapped_column(
        nullable=False, server_default="0"
    )
    use_as_third_party: Mapped[bool] = mapped_column(
        nullable=False, server_default="0"
    )
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    # M4 note: CheckConstraint uses GLOB which is SQLite-specific.
    # Service-layer regex (HANDLE_PATTERN) is the primary enforcement.
    # If migrating to PostgreSQL, replace GLOB with a CHECK using ~ regex.
    __table_args__ = (
        Index("idx_contacts_handle", "handle"),
        Index("idx_contacts_last_used_at", "last_used_at"),
    )

    @property
    def tag_list(self) -> list[str]:
        """Parse tags JSON string into a Python list."""
        if not self.tags:
            return []
        import json
        return json.loads(self.tags)

    @tag_list.setter
    def tag_list(self, value: list[str]) -> None:
        """Serialize a Python list into JSON for the tags column."""
        import json
        self.tags = json.dumps(value) if value else None

    def __repr__(self) -> str:
        return f"<Contact(handle={self.handle!r}, name={self.display_name!r})>"


class CustomCommand(Base):
    """User-defined slash command that expands to a shipping instruction.

    Commands are resolved on the frontend before submission. The agent
    receives the expanded body text, not the slash command itself.

    Attributes:
        name: Command slug stored without '/' prefix (e.g. 'daily-restock').
        description: Optional human note about the command's purpose.
        body: Full instruction text that replaces the /command on expansion.
    """

    __tablename__ = "custom_commands"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    def __repr__(self) -> str:
        return f"<CustomCommand(name={self.name!r})>"
```

Also add `CheckConstraint` to the imports at the top of `models.py` (line 12-19):

```python
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_contact_service.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/db/models.py tests/services/test_contact_service.py
git commit -m "feat: add Contact + CustomCommand SQLAlchemy models"
```

---

### Task 2: ContactService

**Files:**
- Create: `src/services/contact_service.py`
- Test: `tests/services/test_contact_service.py` (extend)

**Step 1: Write failing tests**

Append to `tests/services/test_contact_service.py`:

```python
from src.services.contact_service import (
    ContactService,
    HANDLE_PATTERN,
    BUSINESS_SUFFIXES,
    slugify_display_name,
    contact_to_order_data,
)


def test_handle_pattern_valid():
    """Valid handles match the pattern."""
    assert HANDLE_PATTERN.match("matt")
    assert HANDLE_PATTERN.match("nyc-warehouse")
    assert HANDLE_PATTERN.match("la-office-2")


def test_handle_pattern_invalid():
    """Invalid handles do not match."""
    assert not HANDLE_PATTERN.match("")
    assert not HANDLE_PATTERN.match("Matt")  # uppercase
    assert not HANDLE_PATTERN.match("nyc warehouse")  # space
    assert not HANDLE_PATTERN.match("-leading")  # leading hyphen
    assert not HANDLE_PATTERN.match("trailing-")  # trailing hyphen


def test_create_contact(db: Session):
    """ContactService.create_contact creates a valid contact."""
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
    """Duplicate handle raises ValueError."""
    svc = ContactService(db)
    svc.create_contact(
        handle="matt", display_name="Matt", address_line_1="123 Main",
        city="SF", state_province="CA", postal_code="94105",
    )
    db.commit()
    with pytest.raises(ValueError, match="already exists"):
        svc.create_contact(
            handle="matt", display_name="Other", address_line_1="456 Oak",
            city="LA", state_province="CA", postal_code="90001",
        )


def test_create_contact_invalid_handle(db: Session):
    """Invalid handle format raises ValueError."""
    svc = ContactService(db)
    with pytest.raises(ValueError, match="Invalid handle"):
        svc.create_contact(
            handle="Bad Handle", display_name="Test", address_line_1="123",
            city="SF", state_province="CA", postal_code="94105",
        )


def test_get_by_handle(db: Session):
    """get_by_handle finds contacts case-insensitively."""
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
    svc = ContactService(db)
    c1 = svc.create_contact(handle="old", display_name="Old", address_line_1="1",
                            city="SF", state_province="CA", postal_code="94105")
    c2 = svc.create_contact(handle="new", display_name="New", address_line_1="2",
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


# --- C2 FIX: contact_to_order_data mapping tests ---


def test_slugify_display_name_basic():
    """slugify_display_name handles basic names."""
    assert slugify_display_name("Matt Hans") == "matt-hans"
    assert slugify_display_name("NYC Warehouse") == "nyc-warehouse"


def test_slugify_display_name_strips_suffixes():
    """slugify_display_name strips business suffixes."""
    assert slugify_display_name("Matt's LLC") == "matts"
    assert slugify_display_name("NYC Warehouse Inc.") == "nyc-warehouse"
    assert slugify_display_name("Acme Corp") == "acme"
    assert slugify_display_name("Big Co Ltd") == "big"


def test_slugify_display_name_preserves_if_all_suffixes():
    """slugify_display_name keeps all parts if stripping would leave nothing."""
    assert slugify_display_name("LLC Inc") == "llc-inc"


def test_contact_to_order_data_ship_to(db: Session):
    """contact_to_order_data produces valid ship_to_* keys for build_ship_to()."""
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_contact_service.py::test_create_contact -v -x`
Expected: FAIL — `ImportError: cannot import name 'ContactService'`

**Step 3: Implement ContactService**

Create `src/services/contact_service.py`:

```python
"""Service for contact book CRUD and @handle resolution.

Manages persistent address book contacts used for @mention resolution
in chat messages and custom commands. Contacts map directly to UPS
payload ShipTo/Shipper/ThirdParty objects.

Example:
    svc = ContactService(db)
    contact = svc.create_contact(handle="matt", display_name="Matt Hans", ...)
    resolved = svc.get_by_handle("matt")
"""

import logging
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Contact, utc_now_iso

logger = logging.getLogger(__name__)

HANDLE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

BUSINESS_SUFFIXES = frozenset({
    "llc", "inc", "corp", "corporation", "ltd", "co",
    "company", "plc", "gmbh",
})


def slugify_display_name(name: str) -> str:
    """Convert a display name to a handle slug.

    Lowercases, replaces non-alphanumeric with hyphens, strips business
    suffixes (LLC, Inc, etc.), and collapses multiple hyphens.

    Args:
        name: The display name to slugify.

    Returns:
        A valid handle slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    # Strip business suffixes
    parts = slug.split("-")
    filtered = [p for p in parts if p not in BUSINESS_SUFFIXES]
    if not filtered:
        filtered = parts  # Don't strip everything
    slug = "-".join(filtered).strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def contact_to_order_data(contact: "Contact", role: str = "ship_to") -> dict[str, str | None]:
    """Map a Contact model to order_data keys consumed by UPSPayloadBuilder.

    This is the canonical mapping between Contact field names and the
    ship_to_* / shipper_* keys that build_ship_to() and build_shipper() expect.
    Centralised here to avoid duplication across resolve_contact tool,
    batch @handle injection, and preview_interactive_shipment.

    Args:
        contact: A Contact ORM instance.
        role: One of 'ship_to' or 'shipper'. Determines key prefix.

    Returns:
        Dict with prefixed keys ready for build_ship_to() / build_shipper().

    Raises:
        ValueError: If role is not 'ship_to' or 'shipper'.
    """
    if role not in ("ship_to", "shipper"):
        raise ValueError(f"Invalid role: {role!r}. Must be 'ship_to' or 'shipper'.")

    prefix = f"{role}_"
    return {
        f"{prefix}name": contact.display_name,
        f"{prefix}attention_name": contact.attention_name or contact.display_name,
        f"{prefix}address1": contact.address_line_1,
        f"{prefix}address2": contact.address_line_2,
        f"{prefix}city": contact.city,
        f"{prefix}state": contact.state_province,
        f"{prefix}postal_code": contact.postal_code,
        f"{prefix}country": contact.country_code,
        f"{prefix}phone": contact.phone,
        f"{prefix}company": contact.company,
    }


class ContactService:
    """CRUD operations for address book contacts.

    Methods do NOT call db.commit() — the caller (route or CLI) is
    responsible for committing, matching the SavedDataSourceService pattern.
    """

    def __init__(self, db: Session) -> None:
        """Initialize with a SQLAlchemy session.

        Args:
            db: Active database session.
        """
        self.db = db

    def create_contact(
        self,
        display_name: str,
        address_line_1: str,
        city: str,
        state_province: str,
        postal_code: str,
        handle: str | None = None,
        attention_name: str | None = None,
        company: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address_line_2: str | None = None,
        country_code: str = "US",
        use_as_ship_to: bool = True,
        use_as_shipper: bool = False,
        use_as_third_party: bool = False,
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> Contact:
        """Create a new contact with validation.

        Args:
            display_name: Human-readable contact name.
            address_line_1: Street address (required).
            city: City (required).
            state_province: State or province code (required).
            postal_code: Postal/ZIP code (required).
            handle: Unique slug for @mention. Auto-generated from display_name if omitted.
            attention_name: UPS AttentionName override.
            company: Company name for UPS CompanyName.
            phone: Phone number.
            email: Email address.
            address_line_2: Secondary address line.
            country_code: ISO 2-letter country code (default 'US').
            use_as_ship_to: Can populate ShipTo (default True).
            use_as_shipper: Can populate Shipper (default False).
            use_as_third_party: Can populate ThirdParty (default False).
            tags: List of free-form tag strings.
            notes: Optional notes (not sent to UPS).

        Returns:
            The created Contact record.

        Raises:
            ValueError: If handle format is invalid or already exists.
        """
        if handle is None:
            handle = slugify_display_name(display_name)

        handle = handle.lower().strip()
        if not HANDLE_PATTERN.match(handle):
            raise ValueError(
                f"Invalid handle format: '{handle}'. "
                "Must be lowercase alphanumeric with hyphens."
            )

        existing = self.get_by_handle(handle)
        if existing:
            raise ValueError(f"Contact with handle '@{handle}' already exists.")

        contact = Contact(
            handle=handle,
            display_name=display_name,
            attention_name=attention_name,
            company=company,
            phone=phone,
            email=email,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            city=city,
            state_province=state_province,
            postal_code=postal_code,
            country_code=country_code,
            use_as_ship_to=use_as_ship_to,
            use_as_shipper=use_as_shipper,
            use_as_third_party=use_as_third_party,
            notes=notes,
        )
        if tags:
            contact.tag_list = tags
        self.db.add(contact)
        self.db.flush()
        logger.info("Created contact @%s (%s)", handle, display_name)
        return contact

    def get_by_handle(self, handle: str) -> Contact | None:
        """Find a contact by handle (case-insensitive).

        Args:
            handle: The handle to look up (with or without @ prefix).

        Returns:
            Contact if found, None otherwise.
        """
        clean = handle.lstrip("@").lower().strip()
        return (
            self.db.query(Contact)
            .filter(func.lower(Contact.handle) == clean)
            .first()
        )

    def search_by_prefix(self, prefix: str) -> list[Contact]:
        """Find contacts whose handle starts with the given prefix.

        M3 note: LIKE is case-insensitive for ASCII in SQLite by default.
        Since handles are lowercase-normalized on save, LIKE prefix% is safe.
        For display_name search in list_contacts(), we use func.lower()
        explicitly to ensure case-insensitive matching.

        Args:
            prefix: Handle prefix to match (case-insensitive).

        Returns:
            List of matching contacts.
        """
        clean = prefix.lstrip("@").lower().strip()
        return (
            self.db.query(Contact)
            .filter(Contact.handle.like(f"{clean}%"))
            .order_by(Contact.handle)
            .all()
        )

    def list_contacts(
        self,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Contact]:
        """List contacts with optional search and tag filters.

        Args:
            search: Filter by handle, display_name, or city (partial match).
            tag: Filter by tag value.
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            List of matching contacts.
        """
        query = self.db.query(Contact)
        if search:
            term = f"%{search.lower()}%"
            query = query.filter(
                (func.lower(Contact.handle).like(term))
                | (func.lower(Contact.display_name).like(term))
                | (func.lower(Contact.city).like(term))
            )
        if tag:
            query = query.filter(Contact.tags.like(f'%"{tag}"%'))
        return (
            query.order_by(Contact.display_name)
            .limit(limit)
            .offset(offset)
            .all()
        )

    def update_contact(self, contact_id: str, **kwargs) -> Contact:
        """Partially update a contact by ID.

        Args:
            contact_id: UUID of the contact.
            **kwargs: Fields to update (only non-None values are applied).

        Returns:
            The updated Contact record.

        Raises:
            ValueError: If contact not found or handle validation fails.
        """
        contact = self.db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            raise ValueError(f"Contact {contact_id} not found.")

        if "handle" in kwargs and kwargs["handle"] is not None:
            new_handle = kwargs["handle"].lower().strip()
            if not HANDLE_PATTERN.match(new_handle):
                raise ValueError(f"Invalid handle format: '{new_handle}'.")
            if new_handle != contact.handle:
                existing = self.get_by_handle(new_handle)
                if existing:
                    raise ValueError(f"Handle '@{new_handle}' already in use.")
            kwargs["handle"] = new_handle

        if "tags" in kwargs and isinstance(kwargs["tags"], list):
            import json
            kwargs["tags"] = json.dumps(kwargs["tags"])

        for key, value in kwargs.items():
            if value is not None and hasattr(contact, key):
                setattr(contact, key, value)

        contact.updated_at = utc_now_iso()
        self.db.flush()
        logger.info("Updated contact @%s", contact.handle)
        return contact

    def delete_contact(self, contact_id: str) -> bool:
        """Delete a contact by ID.

        Args:
            contact_id: UUID of the contact.

        Returns:
            True if deleted, False if not found.
        """
        contact = self.db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return False
        handle = contact.handle
        self.db.delete(contact)
        self.db.flush()
        logger.info("Deleted contact @%s", handle)
        return True

    def touch_last_used(self, handle: str) -> None:
        """Update last_used_at timestamp for MRU ranking.

        Args:
            handle: Contact handle to touch.
        """
        contact = self.get_by_handle(handle)
        if contact:
            contact.last_used_at = utc_now_iso()
            self.db.flush()

    def get_mru_contacts(self, limit: int = 20) -> list[Contact]:
        """Get most-recently-used contacts for system prompt injection.

        Only returns contacts that have been used at least once
        (last_used_at IS NOT NULL). This naturally handles NULLS LAST
        since NULL rows are excluded entirely.

        Args:
            limit: Maximum contacts to return.

        Returns:
            Contacts sorted by last_used_at DESC (only used contacts).
        """
        return (
            self.db.query(Contact)
            .filter(Contact.last_used_at.isnot(None))
            .order_by(Contact.last_used_at.desc())
            .limit(limit)
            .all()
        )

    def resolve_handles(self, handles: list[str]) -> dict[str, Contact]:
        """Bulk-resolve a list of handles to Contact objects.

        Args:
            handles: List of handles to resolve (with or without @ prefix).

        Returns:
            Dict mapping lowercase handle to Contact (only found handles).
        """
        clean = [h.lstrip("@").lower().strip() for h in handles]
        contacts = (
            self.db.query(Contact)
            .filter(func.lower(Contact.handle).in_(clean))
            .all()
        )
        return {c.handle.lower(): c for c in contacts}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_contact_service.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/services/contact_service.py tests/services/test_contact_service.py
git commit -m "feat: add ContactService with CRUD, auto-slug, and MRU ranking"
```

---

### Task 3: CustomCommandService

**Files:**
- Create: `src/services/custom_command_service.py`
- Create: `tests/services/test_custom_command_service.py`

**Step 1: Write failing tests**

Create `tests/services/test_custom_command_service.py`:

```python
"""Tests for CustomCommandService CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.services.custom_command_service import CustomCommandService


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_create_command(db: Session):
    svc = CustomCommandService(db)
    cmd = svc.create_command(
        name="daily-restock",
        body="Ship 3 boxes to @nyc-warehouse via UPS Ground",
    )
    db.commit()
    assert cmd.name == "daily-restock"
    assert "@nyc-warehouse" in cmd.body


def test_create_command_invalid_name(db: Session):
    svc = CustomCommandService(db)
    with pytest.raises(ValueError, match="Invalid command name"):
        svc.create_command(name="Bad Name", body="test")


def test_create_command_duplicate(db: Session):
    svc = CustomCommandService(db)
    svc.create_command(name="test-cmd", body="body")
    db.commit()
    with pytest.raises(ValueError, match="already exists"):
        svc.create_command(name="test-cmd", body="other body")


def test_get_by_name(db: Session):
    svc = CustomCommandService(db)
    svc.create_command(name="test-cmd", body="body")
    db.commit()
    assert svc.get_by_name("test-cmd") is not None
    assert svc.get_by_name("/test-cmd") is not None  # with prefix
    assert svc.get_by_name("nonexistent") is None


def test_list_commands(db: Session):
    svc = CustomCommandService(db)
    svc.create_command(name="alpha", body="body a")
    svc.create_command(name="beta", body="body b")
    db.commit()
    cmds = svc.list_commands()
    assert len(cmds) == 2


def test_update_command(db: Session):
    svc = CustomCommandService(db)
    cmd = svc.create_command(name="test", body="old body")
    db.commit()
    updated = svc.update_command(cmd.id, body="new body")
    assert updated.body == "new body"


def test_delete_command(db: Session):
    svc = CustomCommandService(db)
    cmd = svc.create_command(name="test", body="body")
    db.commit()
    assert svc.delete_command(cmd.id) is True
    assert svc.get_by_name("test") is None
```

**Step 2: Run to verify failure**

Run: `pytest tests/services/test_custom_command_service.py -v -x`
Expected: FAIL — `ImportError`

**Step 3: Implement CustomCommandService**

Create `src/services/custom_command_service.py`:

```python
"""Service for custom /command CRUD operations.

Manages user-defined slash commands that expand to shipping instructions.
Commands are stored without the '/' prefix; resolution happens on the frontend.

Example:
    svc = CustomCommandService(db)
    cmd = svc.create_command(name="daily-restock", body="Ship 3 boxes to @nyc")
"""

import logging
import re

from sqlalchemy.orm import Session

from src.db.models import CustomCommand, utc_now_iso

logger = logging.getLogger(__name__)

COMMAND_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CustomCommandService:
    """CRUD operations for custom slash commands.

    Methods do NOT call db.commit() — the caller is responsible for committing.
    """

    def __init__(self, db: Session) -> None:
        """Initialize with a SQLAlchemy session.

        Args:
            db: Active database session.
        """
        self.db = db

    def create_command(
        self,
        name: str,
        body: str,
        description: str | None = None,
    ) -> CustomCommand:
        """Create a new custom command.

        Args:
            name: Command slug without '/' prefix.
            body: Full instruction text.
            description: Optional human note.

        Returns:
            The created CustomCommand record.

        Raises:
            ValueError: If name is invalid or already exists.
        """
        clean_name = name.lstrip("/").lower().strip()
        if not COMMAND_NAME_PATTERN.match(clean_name):
            raise ValueError(
                f"Invalid command name: '{clean_name}'. "
                "Must be lowercase alphanumeric with hyphens."
            )

        existing = self.get_by_name(clean_name)
        if existing:
            raise ValueError(f"Command '/{clean_name}' already exists.")

        cmd = CustomCommand(
            name=clean_name,
            body=body,
            description=description,
        )
        self.db.add(cmd)
        self.db.flush()
        logger.info("Created command /%s", clean_name)
        return cmd

    def get_by_name(self, name: str) -> CustomCommand | None:
        """Find a command by name.

        Args:
            name: Command name with or without '/' prefix.

        Returns:
            CustomCommand if found, None otherwise.
        """
        clean = name.lstrip("/").lower().strip()
        return (
            self.db.query(CustomCommand)
            .filter(CustomCommand.name == clean)
            .first()
        )

    def list_commands(self) -> list[CustomCommand]:
        """List all custom commands ordered by name.

        Returns:
            All custom commands.
        """
        return (
            self.db.query(CustomCommand)
            .order_by(CustomCommand.name)
            .all()
        )

    def update_command(self, command_id: str, **kwargs) -> CustomCommand:
        """Partially update a command by ID.

        Args:
            command_id: UUID of the command.
            **kwargs: Fields to update.

        Returns:
            The updated CustomCommand.

        Raises:
            ValueError: If command not found or name validation fails.
        """
        cmd = self.db.query(CustomCommand).filter(CustomCommand.id == command_id).first()
        if not cmd:
            raise ValueError(f"Command {command_id} not found.")

        if "name" in kwargs and kwargs["name"] is not None:
            new_name = kwargs["name"].lstrip("/").lower().strip()
            if not COMMAND_NAME_PATTERN.match(new_name):
                raise ValueError(f"Invalid command name: '{new_name}'.")
            if new_name != cmd.name:
                existing = self.get_by_name(new_name)
                if existing:
                    raise ValueError(f"Command '/{new_name}' already in use.")
            kwargs["name"] = new_name

        for key, value in kwargs.items():
            if value is not None and hasattr(cmd, key):
                setattr(cmd, key, value)

        cmd.updated_at = utc_now_iso()
        self.db.flush()
        logger.info("Updated command /%s", cmd.name)
        return cmd

    def delete_command(self, command_id: str) -> bool:
        """Delete a command by ID.

        Args:
            command_id: UUID of the command.

        Returns:
            True if deleted, False if not found.
        """
        cmd = self.db.query(CustomCommand).filter(CustomCommand.id == command_id).first()
        if not cmd:
            return False
        name = cmd.name
        self.db.delete(cmd)
        self.db.flush()
        logger.info("Deleted command /%s", name)
        return True
```

**Step 4: Run tests**

Run: `pytest tests/services/test_custom_command_service.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/services/custom_command_service.py tests/services/test_custom_command_service.py
git commit -m "feat: add CustomCommandService with CRUD and name validation"
```

---

### Task 4: Pydantic Schemas for REST API

**Files:**
- Modify: `src/api/schemas.py` (append after `BulkDeleteRequest`, ~line 359)

**Step 1: Write failing test**

Create `tests/api/test_contacts_routes.py` (just the import test for now):

```python
"""Tests for contacts REST API routes."""

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
```

**Step 2: Run to verify failure**

Run: `pytest tests/api/test_contacts_routes.py::test_contact_schemas_importable -v`
Expected: FAIL — `ImportError`

**Step 3: Add Pydantic schemas**

Append to `src/api/schemas.py` (after line 359):

```python
# Contact schemas


class ContactCreate(BaseModel):
    """Request schema for creating a contact."""

    handle: str | None = Field(None, max_length=100, description="@mention slug (auto-generated if omitted)")
    display_name: str = Field(..., min_length=1, max_length=200)
    attention_name: str | None = Field(None, max_length=200)
    company: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=255)
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state_province: str = Field(..., min_length=1, max_length=50)
    postal_code: str = Field(..., min_length=1, max_length=20)
    country_code: str = Field("US", max_length=2)
    use_as_ship_to: bool = True
    use_as_shipper: bool = False
    use_as_third_party: bool = False
    tags: list[str] | None = None
    notes: str | None = None


class ContactUpdate(BaseModel):
    """Request schema for partially updating a contact."""

    handle: str | None = None
    display_name: str | None = None
    attention_name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    use_as_ship_to: bool | None = None
    use_as_shipper: bool | None = None
    use_as_third_party: bool | None = None
    tags: list[str] | None = None
    notes: str | None = None


class ContactResponse(BaseModel):
    """Response schema for a contact."""

    id: str
    handle: str
    display_name: str
    attention_name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state_province: str
    postal_code: str
    country_code: str
    use_as_ship_to: bool
    use_as_shipper: bool
    use_as_third_party: bool
    tags: list[str] | None = None
    notes: str | None = None
    last_used_at: str | None = None
    created_at: str
    updated_at: str

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, v: str | list | None) -> list[str] | None:
        """Parse tags from JSON string if stored as text in SQLite."""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    model_config = ConfigDict(from_attributes=True)


class ContactListResponse(BaseModel):
    """Response schema for listing contacts."""

    contacts: list[ContactResponse]
    total: int


# Custom command schemas


class CommandCreate(BaseModel):
    """Request schema for creating a custom command."""

    name: str = Field(..., min_length=1, max_length=100, description="Command slug without /")
    body: str = Field(..., min_length=1, description="Instruction text")
    description: str | None = None


class CommandUpdate(BaseModel):
    """Request schema for partially updating a command."""

    name: str | None = None
    body: str | None = None
    description: str | None = None


class CommandResponse(BaseModel):
    """Response schema for a custom command."""

    id: str
    name: str
    description: str | None = None
    body: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class CommandListResponse(BaseModel):
    """Response schema for listing commands."""

    commands: list[CommandResponse]
    total: int
```

**Step 4: Run test**

Run: `pytest tests/api/test_contacts_routes.py::test_contact_schemas_importable -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/api/schemas.py tests/api/test_contacts_routes.py
git commit -m "feat: add Pydantic schemas for contacts and custom commands"
```

---

### Task 5: Contacts REST Routes

**Files:**
- Create: `src/api/routes/contacts.py`
- Modify: `src/api/main.py` (lines 37-48 — add import + router registration at line 562)
- Test: `tests/api/test_contacts_routes.py` (extend)

**Step 1: Write failing tests**

Extend `tests/api/test_contacts_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.db.connection import get_db
from src.db.models import Base


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_contact_endpoint(client):
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


def test_list_contacts_endpoint(client):
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


def test_get_contact_by_handle(client):
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


def test_update_contact_endpoint(client):
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


def test_delete_contact_endpoint(client):
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
```

**Step 2: Run to verify failure**

Run: `pytest tests/api/test_contacts_routes.py::test_create_contact_endpoint -v -x`
Expected: FAIL — 404 (route doesn't exist yet)

**Step 3: Create contacts route module and register**

Create `src/api/routes/contacts.py`:

```python
"""API routes for contact book management.

Provides CRUD endpoints for address book contacts used in @handle
resolution. All endpoints use /api/v1/contacts prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from src.db.connection import get_db
from src.services.contact_service import ContactService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _get_service(db: Session = Depends(get_db)) -> ContactService:
    """Dependency injector for ContactService."""
    return ContactService(db)


@router.get("", response_model=ContactListResponse)
def list_contacts(
    search: str | None = None,
    tag: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: ContactService = Depends(_get_service),
) -> ContactListResponse:
    """List all contacts with optional search, tag filter, and pagination.

    Args:
        search: Filter by handle, name, or city.
        tag: Filter by tag value.
        limit: Max results (default 100, M5 fix).
        offset: Pagination offset.
        service: ContactService (injected).

    Returns:
        List of contacts with total count.
    """
    contacts = service.list_contacts(search=search, tag=tag, limit=limit, offset=offset)
    return ContactListResponse(
        contacts=[ContactResponse.model_validate(c) for c in contacts],
        total=len(contacts),
    )


@router.get("/by-handle/{handle}", response_model=ContactResponse)
def get_contact_by_handle(
    handle: str,
    service: ContactService = Depends(_get_service),
) -> ContactResponse:
    """Get a contact by handle for autocomplete and resolution.

    Args:
        handle: Contact handle (without @).
        service: ContactService (injected).

    Returns:
        Contact details.

    Raises:
        HTTPException: 404 if not found.
    """
    contact = service.get_by_handle(handle)
    if not contact:
        raise HTTPException(status_code=404, detail=f"Contact @{handle} not found")
    return ContactResponse.model_validate(contact)


@router.post("", response_model=ContactResponse, status_code=201)
def create_contact(
    data: ContactCreate,
    service: ContactService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> ContactResponse:
    """Create a new contact.

    Args:
        data: Contact creation data.
        service: ContactService (injected).
        db: Database session (injected).

    Returns:
        Created contact details.

    Raises:
        HTTPException: 400 if validation fails.
    """
    try:
        contact = service.create_contact(**data.model_dump())
        db.commit()
        return ContactResponse.model_validate(contact)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{contact_id}", response_model=ContactResponse)
def update_contact(
    contact_id: str,
    data: ContactUpdate,
    service: ContactService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> ContactResponse:
    """Partially update a contact.

    Args:
        contact_id: UUID of the contact.
        data: Fields to update.
        service: ContactService (injected).
        db: Database session (injected).

    Returns:
        Updated contact details.

    Raises:
        HTTPException: 404 if not found, 400 if validation fails.
    """
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        contact = service.update_contact(contact_id, **updates)
        db.commit()
        return ContactResponse.model_validate(contact)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: str,
    service: ContactService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a contact.

    Args:
        contact_id: UUID of the contact.
        service: ContactService (injected).
        db: Database session (injected).

    Returns:
        Deletion confirmation.

    Raises:
        HTTPException: 404 if not found.
    """
    if not service.delete_contact(contact_id):
        raise HTTPException(status_code=404, detail="Contact not found")
    db.commit()
    return {"status": "deleted", "contact_id": contact_id}
```

Register in `src/api/main.py` — add `contacts` to the import block (line 37-48) and add `app.include_router` (after line 562):

In the imports (line 37-48), add `contacts`:
```python
from src.api.routes import (
    agent_audit,
    contacts,
    conversations,
    ...
)
```

After line 562 (`app.include_router(agent_audit.router, prefix="/api/v1")`):
```python
app.include_router(contacts.router, prefix="/api/v1")
```

**Step 4: Run tests**

Run: `pytest tests/api/test_contacts_routes.py -v`
Expected: All 5 + 1 schema test PASS

**Step 5: Commit**

```bash
git add src/api/routes/contacts.py src/api/main.py tests/api/test_contacts_routes.py
git commit -m "feat: add contacts REST API routes with CRUD endpoints"
```

---

### Task 6: Commands REST Routes

**Files:**
- Create: `src/api/routes/commands.py`
- Modify: `src/api/main.py` (add import + registration)
- Create: `tests/api/test_commands_routes.py`

**Step 1: Write failing tests**

Create `tests/api/test_commands_routes.py`:

```python
"""Tests for custom commands REST API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.db.connection import get_db
from src.db.models import Base


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_command_endpoint(client):
    resp = client.post("/api/v1/commands", json={
        "name": "daily-restock",
        "body": "Ship 3 boxes to @nyc-warehouse via UPS Ground",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "daily-restock"


def test_list_commands_endpoint(client):
    client.post("/api/v1/commands", json={"name": "alpha", "body": "a"})
    client.post("/api/v1/commands", json={"name": "beta", "body": "b"})
    resp = client.get("/api/v1/commands")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_update_command_endpoint(client):
    create_resp = client.post("/api/v1/commands", json={
        "name": "test", "body": "old",
    })
    cmd_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/commands/{cmd_id}", json={"body": "new"})
    assert resp.status_code == 200
    assert resp.json()["body"] == "new"


def test_delete_command_endpoint(client):
    create_resp = client.post("/api/v1/commands", json={
        "name": "test", "body": "body",
    })
    cmd_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/commands/{cmd_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
```

**Step 2: Run to verify failure**

Run: `pytest tests/api/test_commands_routes.py -v -x`
Expected: FAIL — 404

**Step 3: Create commands route module and register**

Create `src/api/routes/commands.py`:

```python
"""API routes for custom /command management.

Provides CRUD endpoints for user-defined slash commands.
All endpoints use /api/v1/commands prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    CommandCreate,
    CommandListResponse,
    CommandResponse,
    CommandUpdate,
)
from src.db.connection import get_db
from src.services.custom_command_service import CustomCommandService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/commands", tags=["commands"])


def _get_service(db: Session = Depends(get_db)) -> CustomCommandService:
    """Dependency injector for CustomCommandService."""
    return CustomCommandService(db)


@router.get("", response_model=CommandListResponse)
def list_commands(
    service: CustomCommandService = Depends(_get_service),
) -> CommandListResponse:
    """List all custom commands.

    Args:
        service: CustomCommandService (injected).

    Returns:
        List of commands with total count.
    """
    commands = service.list_commands()
    return CommandListResponse(
        commands=[CommandResponse.model_validate(c) for c in commands],
        total=len(commands),
    )


@router.post("", response_model=CommandResponse, status_code=201)
def create_command(
    data: CommandCreate,
    service: CustomCommandService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> CommandResponse:
    """Create a new custom command.

    Args:
        data: Command creation data.
        service: CustomCommandService (injected).
        db: Database session (injected).

    Returns:
        Created command details.

    Raises:
        HTTPException: 400 if validation fails.
    """
    try:
        cmd = service.create_command(**data.model_dump())
        db.commit()
        return CommandResponse.model_validate(cmd)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{command_id}", response_model=CommandResponse)
def update_command(
    command_id: str,
    data: CommandUpdate,
    service: CustomCommandService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> CommandResponse:
    """Partially update a custom command.

    Args:
        command_id: UUID of the command.
        data: Fields to update.
        service: CustomCommandService (injected).
        db: Database session (injected).

    Returns:
        Updated command details.

    Raises:
        HTTPException: 404 if not found, 400 if validation fails.
    """
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        cmd = service.update_command(command_id, **updates)
        db.commit()
        return CommandResponse.model_validate(cmd)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{command_id}")
def delete_command(
    command_id: str,
    service: CustomCommandService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a custom command.

    Args:
        command_id: UUID of the command.
        service: CustomCommandService (injected).
        db: Database session (injected).

    Returns:
        Deletion confirmation.

    Raises:
        HTTPException: 404 if not found.
    """
    if not service.delete_command(command_id):
        raise HTTPException(status_code=404, detail="Command not found")
    db.commit()
    return {"status": "deleted", "command_id": command_id}
```

Register in `src/api/main.py`:

Import: add `commands` to the import block.
Router: add `app.include_router(commands.router, prefix="/api/v1")` after the contacts router.

**Step 4: Run tests**

Run: `pytest tests/api/test_commands_routes.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/api/routes/commands.py src/api/main.py tests/api/test_commands_routes.py
git commit -m "feat: add custom commands REST API routes with CRUD endpoints"
```

---

### Task 7: CLI Sub-Commands (contacts + commands)

**Files:**
- Modify: `src/cli/main.py` (lines 41-49 — add Typer apps + commands)

**Step 1: Write failing test**

Create `tests/cli/test_contacts_cli.py`:

```python
"""Smoke tests for contacts CLI sub-commands."""

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_contacts_list_help():
    result = runner.invoke(app, ["contacts", "list", "--help"])
    assert result.exit_code == 0
    assert "List" in result.stdout or "list" in result.stdout


def test_commands_list_help():
    result = runner.invoke(app, ["commands", "list", "--help"])
    assert result.exit_code == 0
    assert "List" in result.stdout or "list" in result.stdout
```

**Step 2: Run to verify failure**

Run: `pytest tests/cli/test_contacts_cli.py -v -x`
Expected: FAIL — "No such command 'contacts'"

**Step 3: Add CLI sub-commands to `src/cli/main.py`**

After line 49 (`app.add_typer(data_source_app, name="data-source")`), add:

```python
contacts_app = typer.Typer(help="Manage address book contacts")
commands_app = typer.Typer(help="Manage custom /commands")

app.add_typer(contacts_app, name="contacts")
app.add_typer(commands_app, name="commands")
```

Then add the actual commands at the end of the file (before the `if __name__` block if present, otherwise at end):

```python
# --- Contacts CLI ---


@contacts_app.command("list")
def contacts_list():
    """List all saved contacts."""
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        contacts = svc.list_contacts()
        if not contacts:
            console.print("[dim]No contacts saved.[/dim]")
            return
        from rich.table import Table
        table = Table(title="Address Book")
        table.add_column("Handle", style="cyan")
        table.add_column("Name")
        table.add_column("City")
        table.add_column("State")
        table.add_column("Country")
        for c in contacts:
            table.add_row(f"@{c.handle}", c.display_name, c.city, c.state_province, c.country_code)
        console.print(table)


@contacts_app.command("add")
def contacts_add(
    handle: Optional[str] = typer.Option(None, "--handle", "-h", help="@mention handle"),
    name: str = typer.Option(..., "--name", "-n", help="Display name"),
    address: str = typer.Option(..., "--address", "-a", help="Street address"),
    city: str = typer.Option(..., "--city", "-c", help="City"),
    state: str = typer.Option(..., "--state", "-s", help="State/province"),
    zip_code: str = typer.Option(..., "--zip", "-z", help="Postal/ZIP code"),
    country: str = typer.Option("US", "--country", help="Country code"),
    phone: Optional[str] = typer.Option(None, "--phone", "-p", help="Phone number"),
    company: Optional[str] = typer.Option(None, "--company", help="Company name"),
):
    """Add a new contact to the address book."""
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        try:
            contact = svc.create_contact(
                handle=handle, display_name=name, address_line_1=address,
                city=city, state_province=state, postal_code=zip_code,
                country_code=country, phone=phone, company=company,
            )
            db.commit()
            console.print(f"[green]Created contact @{contact.handle}[/green]")
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(code=1)


@contacts_app.command("show")
def contacts_show(handle: str = typer.Argument(..., help="Contact handle (with or without @)")):
    """Show details for a contact."""
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        contact = svc.get_by_handle(handle)
        if not contact:
            console.print(f"[red]Contact @{handle.lstrip('@')} not found[/red]")
            raise typer.Exit(code=1)
        from rich.panel import Panel
        lines = [
            f"Handle:   @{contact.handle}",
            f"Name:     {contact.display_name}",
            f"Company:  {contact.company or '—'}",
            f"Address:  {contact.address_line_1}",
            f"          {contact.address_line_2 or ''}".rstrip(),
            f"City:     {contact.city}, {contact.state_province} {contact.postal_code}",
            f"Country:  {contact.country_code}",
            f"Phone:    {contact.phone or '—'}",
            f"Email:    {contact.email or '—'}",
            f"Use as:   {'ShipTo' if contact.use_as_ship_to else ''} {'Shipper' if contact.use_as_shipper else ''} {'ThirdParty' if contact.use_as_third_party else ''}".strip(),
            f"Tags:     {', '.join(contact.tag_list) if contact.tag_list else '—'}",
        ]
        console.print(Panel("\n".join(lines), title=f"@{contact.handle}"))


@contacts_app.command("delete")
def contacts_delete(
    handle: str = typer.Argument(..., help="Contact handle"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a contact from the address book."""
    from rich.prompt import Confirm

    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    clean = handle.lstrip("@")
    if not yes:
        if not Confirm.ask(f"Delete contact @{clean}?"):
            console.print("[dim]Cancelled[/dim]")
            return

    with get_db_context() as db:
        svc = ContactService(db)
        contact = svc.get_by_handle(clean)
        if not contact:
            console.print(f"[red]Contact @{clean} not found[/red]")
            raise typer.Exit(code=1)
        svc.delete_contact(contact.id)
        db.commit()
        console.print(f"[green]Deleted contact @{clean}[/green]")


@contacts_app.command("export")
def contacts_export(
    output: str = typer.Option("contacts.json", "--output", "-o", help="Output file path"),
):
    """Export all contacts to JSON."""
    import json as _json

    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        contacts = svc.list_contacts()
        data = []
        for c in contacts:
            data.append({
                "handle": c.handle,
                "display_name": c.display_name,
                "attention_name": c.attention_name,
                "company": c.company,
                "phone": c.phone,
                "email": c.email,
                "address_line_1": c.address_line_1,
                "address_line_2": c.address_line_2,
                "city": c.city,
                "state_province": c.state_province,
                "postal_code": c.postal_code,
                "country_code": c.country_code,
                "use_as_ship_to": c.use_as_ship_to,
                "use_as_shipper": c.use_as_shipper,
                "use_as_third_party": c.use_as_third_party,
                "tags": c.tag_list,
                "notes": c.notes,
            })
        Path(output).write_text(_json.dumps(data, indent=2))
        console.print(f"[green]Exported {len(data)} contacts to {output}[/green]")


@contacts_app.command("import")
def contacts_import(file_path: str = typer.Argument(..., help="JSON file to import")):
    """Import contacts from JSON."""
    import json as _json

    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    data = _json.loads(Path(file_path).read_text())
    if not isinstance(data, list):
        console.print("[red]Expected a JSON array of contact objects[/red]")
        raise typer.Exit(code=1)

    with get_db_context() as db:
        svc = ContactService(db)
        created = 0
        updated = 0
        for item in data:
            try:
                # Idempotent import: upsert on handle (DB perf optimization).
                # If handle exists, update fields instead of failing.
                handle = item.get("handle", "").lstrip("@").lower().strip()
                existing = svc.get_by_handle(handle) if handle else None
                if existing:
                    update_fields = {k: v for k, v in item.items() if k != "handle" and v is not None}
                    svc.update_contact(existing.id, **update_fields)
                    updated += 1
                else:
                    svc.create_contact(**item)
                    created += 1
            except ValueError as e:
                console.print(f"[yellow]Skipped: {e}[/yellow]")
        db.commit()
        console.print(f"[green]Imported {created} new, {updated} updated / {len(data)} total[/green]")


# --- Commands CLI ---


@commands_app.command("list")
def commands_list():
    """List all custom commands."""
    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    with get_db_context() as db:
        svc = CustomCommandService(db)
        commands = svc.list_commands()
        if not commands:
            console.print("[dim]No custom commands defined.[/dim]")
            return
        from rich.table import Table
        table = Table(title="Custom Commands")
        table.add_column("Command", style="cyan")
        table.add_column("Description")
        table.add_column("Body", max_width=60)
        for c in commands:
            table.add_row(f"/{c.name}", c.description or "—", c.body[:60])
        console.print(table)


@commands_app.command("add")
def commands_add(
    name: str = typer.Option(..., "--name", "-n", help="Command name without /"),
    body: str = typer.Option(..., "--body", "-b", help="Instruction text"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Description"),
):
    """Add a new custom command."""
    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    with get_db_context() as db:
        svc = CustomCommandService(db)
        try:
            cmd = svc.create_command(name=name, body=body, description=description)
            db.commit()
            console.print(f"[green]Created command /{cmd.name}[/green]")
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(code=1)


@commands_app.command("show")
def commands_show(name: str = typer.Argument(..., help="Command name (with or without /)")):
    """Show a command's body."""
    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    with get_db_context() as db:
        svc = CustomCommandService(db)
        cmd = svc.get_by_name(name)
        if not cmd:
            console.print(f"[red]Command /{name.lstrip('/')} not found[/red]")
            raise typer.Exit(code=1)
        from rich.panel import Panel
        console.print(Panel(
            f"[bold]/{cmd.name}[/bold]\n{cmd.description or ''}\n\n{cmd.body}",
            title=f"/{cmd.name}",
        ))


@commands_app.command("delete")
def commands_delete(
    name: str = typer.Argument(..., help="Command name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a custom command."""
    from rich.prompt import Confirm

    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    clean = name.lstrip("/")
    if not yes:
        if not Confirm.ask(f"Delete command /{clean}?"):
            console.print("[dim]Cancelled[/dim]")
            return

    with get_db_context() as db:
        svc = CustomCommandService(db)
        cmd = svc.get_by_name(clean)
        if not cmd:
            console.print(f"[red]Command /{clean} not found[/red]")
            raise typer.Exit(code=1)
        svc.delete_command(cmd.id)
        db.commit()
        console.print(f"[green]Deleted command /{clean}[/green]")
```

**Step 4: Run tests**

Run: `pytest tests/cli/test_contacts_cli.py -v`
Expected: Both help tests PASS

**Step 5: Commit**

```bash
git add src/cli/main.py tests/cli/test_contacts_cli.py
git commit -m "feat: add contacts and commands CLI sub-commands"
```

---

## Phase B: Agent Tools + System Prompt

### Task 8: Contact Agent Tools (C2 + C3 Integration)

**Files:**
- Create: `src/orchestrator/agent/tools/contacts.py`
- Modify: `src/orchestrator/agent/tools/__init__.py` (lines 19-52 imports + tool definitions)
- Create: `tests/orchestrator/agent/tools/test_contacts_tools.py`

This task creates the 4 contact tools (`resolve_contact`, `save_contact`, `list_contacts`, `delete_contact`), registers them in `get_all_tool_definitions()` (always available — both modes), and tests each.

The tools follow the same pattern as `tracking.py` and `pickup.py`: handler functions that accept `bridge` + kwargs, call the service, and return `_ok(data)` or `_err(message)`.

**SOLID note (Interface Segregation):** `touch_last_used()` is a side-effect that must NOT live inside `get_by_handle()`. The service methods stay pure (no side effects on reads). Instead, `touch_last_used()` is called explicitly in the `resolve_contact` tool handler AFTER a successful lookup. This keeps the service testable and the side-effect visible.

**C2 integration:** `resolve_contact` returns the full contact data PLUS the pre-mapped `order_data` dict from `contact_to_order_data(contact, role)`. The role is inferred from the contact's `use_as_ship_to`/`use_as_shipper` flags (defaulting to `ship_to`). This means the agent and `preview_interactive_shipment` receive ready-to-use `ship_to_*` keys — no field mapping needed downstream.

**C3 integration — Batch @handle detection point:**

> This is documented now (Phase A) but implemented in Phase B alongside the tools.

The batch @handle injection happens in `ship_command_pipeline` (in `tools/pipeline.py`), at a specific point:

```
ship_command_pipeline handler
    ↓
    1. Resolve filter → fetch rows from MCP data source
    2. Build job_row_data list from fetched rows
    ↓
    ★ 3. SCAN rows for @handle tokens in ALL string values
    ★    - Regex: r"@([a-z0-9][a-z0-9-]*[a-z0-9])" per value
    ★    - Collect unique handles across all rows
    ★    - Call ContactService.resolve_handles(unique_handles)
    ★    - For each row with @handle column values:
    ★        Merge contact_to_order_data(contact, "ship_to") into order_data
    ★        (contact fields override the raw @handle string values)
    ↓
    4. BatchEngine.preview() with enriched rows
```

This ensures `resolve_handles()` (designed in Task 2) is called once with all unique handles — avoiding N+1. The `contact_to_order_data()` utility (also Task 2) produces the exact `ship_to_*` keys that `build_ship_to()` expects.

**Implementation detail:** A new helper `_resolve_row_handles(rows: list[dict], db: Session) -> list[dict]` will be added to `tools/pipeline.py` that:
1. Scans all string values in each row dict for `@handle` patterns
2. Collects unique handles
3. Calls `ContactService(db).resolve_handles(unique_handles)`
4. Merges resolved contact fields into each row's data
5. Also calls `touch_last_used()` for each resolved handle (MRU ranking update)

**Step 1: Write tests**

Create `tests/orchestrator/agent/tools/test_contacts_tools.py`:

```python
"""Tests for contact agent tools."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from unittest.mock import MagicMock

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
```

**Step 2: Run to verify failure**

Run: `pytest tests/orchestrator/agent/tools/test_contacts_tools.py -v -x`
Expected: PASS (these test service logic; tool module tests come with implementation)

**Step 3: Implement contact tools module**

Create `src/orchestrator/agent/tools/contacts.py` with 4 handlers:
- `resolve_contact_tool(args, bridge)` — lookup by handle, touch_last_used on success, return contact + order_data
- `save_contact_tool(args, bridge)` — create/update contact via ContactService
- `list_contacts_tool(args, bridge)` — list contacts with optional search/tag filter
- `delete_contact_tool(args, bridge)` — delete by handle

Register in `tools/__init__.py`:
- Add to imports
- Add 4 `ToolDefinition` entries
- Add all 4 to `interactive_allowed` set (contacts available in BOTH modes)

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/tools/test_contacts_tools.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/contacts.py src/orchestrator/agent/tools/__init__.py tests/orchestrator/agent/tools/test_contacts_tools.py
git commit -m "feat: add contact agent tools (resolve, save, list, delete) with C2/C3 integration"
```

---

### Task 9: System Prompt Contact Injection (C1 Fix)

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py` (add `_build_contacts_section()` helper + `contacts` param to `build_system_prompt()`)
- Modify: `src/services/conversation_handler.py` (add MRU contact fetch + contacts_hash to `ensure_agent()`)
- Create: `tests/orchestrator/agent/test_contacts_prompt.py`

> **C1 Critical Fix:** This task defines the full wiring from DB → `build_system_prompt()` → `ensure_agent()`.
> Without this, the top-20 MRU contacts never appear in the prompt and the agent always falls back to `resolve_contact` tool calls.

**Step 1: Write failing tests**

Create `tests/orchestrator/agent/test_contacts_prompt.py`:

```python
"""Tests for contact injection into agent system prompt."""

import pytest

from src.orchestrator.agent.system_prompt import (
    MAX_PROMPT_CONTACTS,
    _build_contacts_section,
    build_system_prompt,
)


def test_build_contacts_section_empty():
    """Empty contact list produces no section."""
    result = _build_contacts_section([])
    assert result == ""


def test_build_contacts_section_formats_correctly():
    """Contacts are formatted as @handle — City, ST (roles)."""
    contacts = [
        {"handle": "matt", "city": "San Francisco", "state_province": "CA",
         "use_as_ship_to": True, "use_as_shipper": False},
        {"handle": "warehouse", "city": "New York", "state_province": "NY",
         "use_as_ship_to": True, "use_as_shipper": True},
    ]
    result = _build_contacts_section(contacts)
    assert "@matt" in result
    assert "San Francisco, CA" in result
    assert "ship_to" in result
    assert "@warehouse" in result
    assert "shipper" in result


def test_build_contacts_section_respects_limit():
    """Only MAX_PROMPT_CONTACTS contacts are included."""
    contacts = [
        {"handle": f"c{i}", "city": "City", "state_province": "ST",
         "use_as_ship_to": True, "use_as_shipper": False}
        for i in range(MAX_PROMPT_CONTACTS + 10)
    ]
    result = _build_contacts_section(contacts)
    assert f"@c{MAX_PROMPT_CONTACTS - 1}" in result
    assert f"@c{MAX_PROMPT_CONTACTS}" not in result


def test_build_system_prompt_includes_contacts():
    """build_system_prompt injects contacts section when provided."""
    prompt = build_system_prompt(
        contacts=[
            {"handle": "matt", "city": "SF", "state_province": "CA",
             "use_as_ship_to": True, "use_as_shipper": False},
        ],
    )
    assert "@matt" in prompt
    assert "Saved Contacts" in prompt
    assert "resolve_contact" in prompt


def test_build_system_prompt_no_contacts():
    """build_system_prompt omits contacts section when None."""
    prompt = build_system_prompt(contacts=None)
    assert "Saved Contacts" not in prompt
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_contacts_prompt.py -v -x`
Expected: FAIL — `ImportError: cannot import name 'MAX_PROMPT_CONTACTS'`

**Step 3a: Add `_build_contacts_section()` + `contacts` param to `system_prompt.py`**

Add constant near the top of `system_prompt.py` (after `_MAX_SCHEMA_SAMPLES = 5`):

```python
MAX_PROMPT_CONTACTS = 20
```

Add new helper function (after `_build_schema_section`):

```python
def _build_contacts_section(contacts: list[dict]) -> str:
    """Build the saved contacts catalogue for the system prompt.

    Accepts raw dicts (not ORM objects) so the module stays free of DB imports.
    The caller (ensure_agent) fetches MRU contacts and serialises them.

    Args:
        contacts: List of contact dicts with keys: handle, city,
            state_province, use_as_ship_to, use_as_shipper.

    Returns:
        Formatted contacts section, or empty string if no contacts.
    """
    if not contacts:
        return ""
    lines = ["## Saved Contacts", ""]
    for c in contacts[:MAX_PROMPT_CONTACTS]:
        roles = []
        if c.get("use_as_ship_to"):
            roles.append("ship_to")
        if c.get("use_as_shipper"):
            roles.append("shipper")
        role_str = ", ".join(roles) if roles else "ship_to"
        lines.append(
            f"@{c['handle']} — {c.get('city', '?')}, "
            f"{c.get('state_province', '?')} ({role_str})"
        )
    lines.append("")
    lines.append(
        "When you see @handle in a user message, check the catalogue above first. "
        "If found, use the contact data directly via resolve_contact. "
        "If not found, call resolve_contact to search the full address book."
    )
    return "\n".join(lines)
```

Modify `build_system_prompt()` signature to accept contacts:

```python
def build_system_prompt(
    source_info: DataSourceInfo | None = None,
    interactive_shipping: bool = False,
    column_samples: dict[str, list] | None = None,
    contacts: list[dict] | None = None,
) -> str:
```

Inject the contacts section in the return template (after `{data_section}`, before `## Filter Generation Rules`):

```python
    contacts_section = _build_contacts_section(contacts or [])
```

And in the return f-string:

```
{contacts_section}

## Filter Generation Rules
```

**Step 3b: Wire MRU contact fetch into `ensure_agent()` in `conversation_handler.py`**

This is the critical wiring that makes C1 work. Modify `ensure_agent()`:

```python
async def ensure_agent(
    session: AgentSession,
    source_info: Any,
    interactive_shipping: bool = False,
) -> bool:
    from src.orchestrator.agent.client import OrchestrationAgent
    from src.orchestrator.agent.system_prompt import build_system_prompt

    source_hash = compute_source_hash(source_info)

    # Fetch MRU contacts for system prompt injection (C1 fix).
    # This is a fast indexed read (~20 rows) that runs every ensure_agent call.
    # Including contacts_hash forces prompt rebuild when MRU list changes.
    contacts_data: list[dict] = []
    contacts_hash = "no-contacts"
    try:
        from src.db.connection import get_db_context
        from src.services.contact_service import ContactService

        with get_db_context() as db:
            svc = ContactService(db)
            mru_contacts = svc.get_mru_contacts(limit=20)
            contacts_data = [
                {
                    "handle": c.handle,
                    "city": c.city,
                    "state_province": c.state_province,
                    "use_as_ship_to": c.use_as_ship_to,
                    "use_as_shipper": c.use_as_shipper,
                }
                for c in mru_contacts
            ]
            # Hash MRU IDs so agent rebuilds when contact list changes
            contacts_hash = hashlib.sha256(
                "|".join(c.id for c in mru_contacts).encode()
            ).hexdigest()[:8]
    except Exception as e:
        logger.warning("Failed to fetch MRU contacts for prompt: %s", e)

    combined_hash = f"{source_hash}|interactive={interactive_shipping}|contacts={contacts_hash}"

    # Reuse existing agent if config hasn't changed
    if session.agent is not None and session.agent_source_hash == combined_hash:
        return False

    # Stop existing agent if config changed mid-conversation
    if session.agent is not None:
        try:
            await session.agent.stop()
        except Exception as e:
            logger.warning("Error stopping old agent: %s", e)

    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=interactive_shipping,
        contacts=contacts_data if contacts_data else None,
    )

    agent = OrchestrationAgent(
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session.session_id,
    )
    await agent.start()

    session.agent = agent
    session.agent_source_hash = combined_hash
    session.interactive_shipping = interactive_shipping

    return True
```

**Key design decisions:**
- MRU contacts are fetched on EVERY `ensure_agent()` call (not cached), because it's a fast indexed read (~20 rows, single `ORDER BY last_used_at DESC LIMIT 20`).
- `contacts_hash` (hash of MRU contact IDs) is included in `combined_hash`. When a user adds, edits, or resolves a contact (changing `last_used_at`), the hash changes, forcing agent rebuild with updated prompt.
- The DB read is wrapped in try/except so contact fetch failures don't break agent creation.
- `_build_contacts_section()` receives raw dicts (not ORM objects), keeping `system_prompt.py` free of DB imports and fully testable with mock data.

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/test_contacts_prompt.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py src/services/conversation_handler.py tests/orchestrator/agent/test_contacts_prompt.py
git commit -m "feat: inject top-20 MRU contacts into agent system prompt (C1 fix)"
```

---

## Phase C: Settings Flyout + Address Book UI

### Task 10: Frontend TypeScript Types + API Client (M2 Fix)

**Files:**
- Modify: `frontend/src/types/api.ts` — Add `Contact`, `ContactCreate`, `ContactUpdate`, `CustomCommand`, `CommandCreate`, `CommandUpdate`, `ContactListResponse`, `CommandListResponse` interfaces
- Modify: `frontend/src/lib/api.ts` — Add `listContacts()`, `createContact()`, `updateContact()`, `deleteContact()`, `getContactByHandle()`, `listCommands()`, `createCommand()`, `updateCommand()`, `deleteCommand()`
- Modify: `frontend/src/hooks/useAppState.tsx` — Add `contacts`, `setContacts`, `customCommands`, `setCustomCommands`, `settingsFlyoutOpen`, `setSettingsFlyoutOpen` + hydration `useEffect` + `refreshContacts()` / `refreshCommands()` helpers

> **M2 Fix (Frontend state invalidation):** After any mutation (create, update, delete), the local state must be refreshed. Two approaches were considered:
> - **Optimistic update:** Mutate the local array immediately after a successful API call.
> - **Refetch:** Call `listContacts()` / `listCommands()` after any mutation to sync.
>
> **Decision:** Use **refetch** (simpler, no stale-state bugs). AppState exposes `refreshContacts()` and `refreshCommands()` functions that call the list API and update state. All mutation callers (AddressBookModal, ContactForm, CustomCommandsSection) call the appropriate refresh function after a successful API response.
>
> Pattern (in any component that mutates contacts):
> ```tsx
> const { refreshContacts } = useAppState();
> const handleSave = async (data: ContactCreate) => {
>     await api.createContact(data);
>     refreshContacts(); // re-fetch full list from API
> };
> ```

**Step 1: Add types, Step 2: Add API functions, Step 3: Add AppState with refresh helpers, Step 4: verify TypeScript compiles (`npx tsc --noEmit`), Step 5: commit.**

Commit message: `feat: add contacts/commands types, API client, and AppState hydration with refetch`

---

### Task 11: Settings Flyout Component

**Files:**
- Create: `frontend/src/components/settings/SettingsFlyout.tsx`
- Create: `frontend/src/components/settings/ShipmentBehaviourSection.tsx`
- Create: `frontend/src/components/settings/AddressBookSection.tsx`
- Create: `frontend/src/components/settings/CustomCommandsSection.tsx`
- Modify: `frontend/src/components/layout/Header.tsx` — Add settings gear button
- Modify: `frontend/src/index.css` — Add flyout CSS, transitions, responsive breakpoint

The flyout is 360px wide, slides in from the right, pushes chat on >=1024px, overlays with backdrop on <1024px. Three collapsible accordion sections. Settings gear icon in Header toggles `settingsFlyoutOpen`.

**Step 1: Create components, Step 2: Wire header button, Step 3: Add CSS, Step 4: verify build (`npm run build`), Step 5: commit.**

Commit message: `feat: add settings flyout panel with shipment/contacts/commands sections`

---

### Task 12: Address Book Modal

**Files:**
- Create: `frontend/src/components/settings/AddressBookModal.tsx`
- Create: `frontend/src/components/settings/ContactForm.tsx`

AddressBookModal: list view with search, tag filter, add/edit/delete. Opens from flyout (flyout closes). Uses shadcn Dialog. ContactForm: add/edit form with handle auto-slug, country dropdown, usage checkboxes, tag chips.

**Step 1: Create components, Step 2: Wire into AddressBookSection, Step 3: verify build, Step 4: commit.**

Commit message: `feat: add Address Book modal with contact list and form editor`

---

## Phase D: Custom Commands UI

### Task 13: Custom Commands UI in Flyout

**Files:**
- Modify: `frontend/src/components/settings/CustomCommandsSection.tsx` — Add inline editor with expandable list, add/edit/delete, name validation

**Step 1: Implement, Step 2: verify build, Step 3: commit.**

Commit message: `feat: add custom commands inline editor in settings flyout`

---

### Task 14: Command Expansion in Chat (N1 Fix)

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx` — Add command expansion logic (two-phase Enter: first expands /command, second submits)

When user types `/command-name` and presses Enter, look up command in AppState `customCommands`. If found, replace input value with expanded body. On next Enter, submit normally.

> **N1 Fix:** Add an `isExpanded: boolean` state flag to track whether the current input text came from a /command expansion.
> - Set `isExpanded = true` after expanding a /command body into the input.
> - Set `isExpanded = false` on submit, on backspace-to-empty, or when user manually clears the input.
> - On Enter press:
>   - If input starts with `/` AND `!isExpanded` AND matches a saved command → expand, set `isExpanded = true`
>   - Otherwise → submit normally
> - This prevents re-expansion of already-expanded text and avoids ambiguity when input contains `/` characters naturally.

**Step 1: Implement, Step 2: verify build, Step 3: commit.**

Commit message: `feat: add two-phase /command expansion in chat input with isExpanded state`

---

## Phase E: Rich Chat Input

### Task 15: Token Highlighting Hook (N3 Fix)

**Files:**
- Create: `frontend/src/hooks/useTokenHighlighter.ts`

Parses input string, detects `@handle` and `/command` tokens, classifies them (known/unknown/incomplete), returns annotated segments for rendering.

> **N3 Fix (Decoupling):** `useTokenHighlighter` must be a pure hook that works with ANY text input — not coupled to `RichChatInput`. It accepts:
> - `text: string` — the input to parse
> - `knownHandles: string[]` — from AppState contacts
> - `knownCommands: string[]` — from AppState commands
>
> It returns `TokenSegment[]` where each segment has `{ text, type, status }`:
> - `type`: `"plain"` | `"handle"` | `"command"`
> - `status`: `"known"` | `"unknown"` | `"incomplete"`
>
> This decoupling allows the hook to be used in:
> - `RichChatInput` (main chat) — mirror div rendering
> - `CustomCommandsSection` (flyout) — command body textarea highlighting
> - Any future text input that needs token awareness
>
> The hook does NOT handle DOM manipulation, cursor management, or event handling — those are the responsibility of the consuming component.

**Step 1: Create hook, Step 2: verify build, Step 3: commit.**

Commit message: `feat: add decoupled useTokenHighlighter hook for @handle and /command parsing`

---

### Task 16: Autocomplete Hooks

**Files:**
- Create: `frontend/src/hooks/useCommandAutocomplete.ts`
- Create: `frontend/src/hooks/useContactAutocomplete.ts`

Both read from AppState. Triggered by `/` or `@` prefix. Return filtered candidates for popover rendering. Selection inserts token + trailing space.

**Step 1: Create hooks, Step 2: verify build, Step 3: commit.**

Commit message: `feat: add autocomplete hooks for @contacts and /commands`

---

### Task 17: RichChatInput Component

**Files:**
- Create: `frontend/src/components/chat/RichChatInput.tsx`
- Modify: `frontend/src/components/CommandCenter.tsx` — Replace plain input with RichChatInput
- Modify: `frontend/src/index.css` — Add token colour CSS vars

Mirror div technique: hidden textarea + styled overlay. Autocomplete popovers. Token colours: teal (OKLCH 185) for @handles, amber (OKLCH 85) for /commands.

**Step 1: Create component, Step 2: Wire into CommandCenter, Step 3: Add CSS, Step 4: verify build, Step 5: commit.**

Commit message: `feat: add RichChatInput with mirror-div syntax highlighting and autocomplete`

---

## Final Verification

After all phases, verify:
```bash
# Backend tests (all new test files)
pytest tests/services/test_contact_service.py tests/services/test_custom_command_service.py tests/api/test_contacts_routes.py tests/api/test_commands_routes.py tests/cli/test_contacts_cli.py tests/orchestrator/agent/test_contacts_prompt.py tests/orchestrator/agent/tools/test_contacts_tools.py -v

# Frontend
cd frontend && npx tsc --noEmit && npm run build
```

All tests pass, frontend compiles and builds.

---

## Review Findings Traceability

This plan addresses all findings from the 2026-02-19 Architectural Review:

| Finding | Severity | Resolution | Task |
|---------|----------|------------|------|
| **C1** System prompt MRU wiring | 🔴 Critical | `ensure_agent()` fetches MRU contacts, includes `contacts_hash` in combined_hash, passes to `build_system_prompt()` | Task 9 |
| **C2** ContactRecord → order_data mapping | 🔴 Critical | `contact_to_order_data(contact, role)` function in `contact_service.py` maps to `ship_to_*`/`shipper_*` keys | Task 2 + Task 8 |
| **C3** Batch @handle integration point | 🔴 Critical | Documented in Task 8: `_resolve_row_handles()` in `pipeline.py` scans rows after fetch, before preview | Task 8 |
| **M1** `ensure_agent` combined_hash staleness | 🟡 Moderate | `contacts_hash` included in combined_hash (addressed by C1) | Task 9 |
| **M2** Frontend state invalidation | 🟡 Moderate | `refreshContacts()`/`refreshCommands()` in AppState, called after every mutation | Task 10 |
| **M3** LIKE case sensitivity | 🟡 Moderate | Handles are lowercase-normalized; display name search uses `func.lower()` | Task 2 (docstring) |
| **M4** GLOB CheckConstraint SQLite-specific | 🟡 Moderate | Service-layer regex is primary enforcement; CheckConstraint is safety net with migration note | Task 1 (comment) |
| **M5** Pagination on GET /contacts | 🟡 Moderate | Default `limit=100`, `offset=0` on REST endpoint | Task 5 |
| **N1** Two-phase Enter `isExpanded` flag | 🟢 Minor | `isExpanded` boolean state tracks command expansion status | Task 14 |
| **N2** Export CSV format | 🟢 Minor | Noted as future enhancement (JSON-only for now) | — |
| **N3** Token highlighter decoupling | 🟢 Minor | `useTokenHighlighter` is a pure hook accepting text + known lists, reusable across components | Task 15 |
| **SOLID: SRP** Slugify extraction | ✅ | `slugify_display_name()` is a standalone function, not embedded in `create_contact()` | Task 2 |
| **SOLID: ISP** Touch separation | ✅ | `touch_last_used()` called in tool handler, not inside `get_by_handle()` | Task 8 |
| **SOLID: DRY** Order data mapping | ✅ | `contact_to_order_data()` centralized, used in resolve_contact tool, batch injection, and interactive preview | Task 2 + Task 8 |
| **SOLID: OCP** Prompt helper | ✅ | `_build_contacts_section()` accepts raw dicts, no DB imports in `system_prompt.py` | Task 9 |
| **Test: slugify** | ✅ | `test_slugify_display_name_*` tests covering basic, suffixes, edge cases | Task 2 |
| **Test: to_order_data** | ✅ | `test_contact_to_order_data_*` tests for ship_to, shipper, attention fallback | Task 2 |
| **Test: partial update** | ✅ | `test_update_contact_partial_fields` verifies untouched fields | Task 2 |
| **Test: prompt injection** | ✅ | `test_build_contacts_section_*` + `test_build_system_prompt_includes_contacts` | Task 9 |
| **Test: idempotent import** | ✅ | CLI import upserts on existing handle instead of failing | Task 7 |
