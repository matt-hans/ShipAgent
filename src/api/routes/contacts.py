"""API routes for contact book management.

Provides CRUD endpoints for address book contacts used in @handle
resolution. All endpoints use /api/v1/contacts prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from src.db.connection import get_db
from src.errors.domain import (
    ConflictError,
    DuplicateHandleError,
    NotFoundError,
    ValidationError,
)
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
        limit: Max results (default 100).
        offset: Pagination offset.
        service: ContactService (injected).

    Returns:
        List of contacts with total count.
    """
    contacts = service.list_contacts(search=search, tag=tag, limit=limit, offset=offset)
    total = service.count_contacts(search=search, tag=tag)
    return ContactListResponse(
        contacts=[ContactResponse.model_validate(c) for c in contacts],
        total=total,
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
        HTTPException: 400 if validation fails, 409 if handle exists.
    """
    try:
        contact = service.create_contact(**data.model_dump())
        db.commit()
        return ContactResponse.model_validate(contact)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except DuplicateHandleError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Contact with this handle already exists") from None


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
        HTTPException: 404 if not found, 400 if validation fails, 409 if handle conflict.
    """
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        contact = service.update_contact(contact_id, **updates)
        db.commit()
        return ContactResponse.model_validate(contact)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except (DuplicateHandleError, ConflictError) as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Handle already in use") from None


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
