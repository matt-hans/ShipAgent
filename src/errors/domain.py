"""Typed domain exceptions for API error mapping.

These exceptions provide stronger API contract guarantees than
string-based error message matching. Routes can catch specific
exception types to return appropriate HTTP status codes.

Usage:
    # In service layer
    raise NotFoundError("Contact", contact_id)

    # In route handler
    try:
        contact = service.get_by_id(contact_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
"""


class DomainError(Exception):
    """Base exception for all domain errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class NotFoundError(DomainError):
    """Resource was not found. Maps to HTTP 404."""

    def __init__(self, resource_type: str, identifier: str) -> None:
        super().__init__(f"{resource_type} '{identifier}' not found")
        self.resource_type = resource_type
        self.identifier = identifier


class ConflictError(DomainError):
    """Resource conflict (e.g., duplicate). Maps to HTTP 409."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ValidationError(DomainError):
    """Validation failure. Maps to HTTP 400."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class DuplicateHandleError(ConflictError):
    """Handle already exists. Maps to HTTP 409."""

    def __init__(self, handle: str) -> None:
        super().__init__(f"Handle '@{handle}' already exists")
        self.handle = handle


class DuplicateCommandNameError(ConflictError):
    """Command name already exists. Maps to HTTP 409."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Command '/{name}' already exists")
        self.name = name
