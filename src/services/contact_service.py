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

    Lowercases, removes apostrophes, replaces non-alphanumeric with hyphens,
    strips business suffixes (LLC, Inc, etc.), and collapses multiple hyphens.

    Args:
        name: The display name to slugify.

    Returns:
        A valid handle slug.
    """
    # Remove apostrophes entirely (Matt's → matts, not matt-s)
    slug = name.lower().replace("'", "")
    # Replace other non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
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
            ValueError: If handle format is invalid, already exists, or required
                        address fields are missing.
        """
        # Validate required address fields
        required_fields = {
            "display_name": display_name,
            "address_line_1": address_line_1,
            "city": city,
            "state_province": state_province,
            "postal_code": postal_code,
        }
        missing = [name for name, value in required_fields.items() if not value or not str(value).strip()]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

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

    def count_contacts(
        self,
        search: str | None = None,
        tag: str | None = None,
    ) -> int:
        """Count contacts matching filters (for pagination total).

        Args:
            search: Filter by handle, display_name, or city (partial match).
            tag: Filter by tag value.

        Returns:
            Total count of matching contacts.
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
        return query.count()

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
