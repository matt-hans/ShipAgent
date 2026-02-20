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
