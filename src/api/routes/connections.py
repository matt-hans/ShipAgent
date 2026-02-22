"""API routes for provider connection management.

Handles CRUD operations for provider connections (UPS, Shopify).
Uses Pydantic models for request validation. Credential values are
never echoed in error responses -- the custom 422 handler sanitizes them.

ConnectionService is created inside each route handler (not via FastAPI
Depends) so that construction failures (e.g. encryption key issues) are
caught by the route's own try/except and returned as structured JSON
instead of a bare 500 from FastAPI's dependency-injection layer.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from src.db.connection import get_db
from src.services.connection_service import ConnectionService
from src.services.connection_types import ConnectionValidationError
from src.utils.redaction import sanitize_error_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


# --- Pydantic request models ---


class SaveConnectionRequest(BaseModel):
    """Request body for saving a provider connection."""

    auth_mode: str = Field(..., min_length=1, description="Authentication mode")
    credentials: dict[str, str] = Field(default_factory=dict, description="Credential key-value pairs")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Non-secret metadata")
    display_name: str = Field("", description="Human-readable display name")
    environment: str | None = Field(None, description="UPS environment (test/production)")


def _build_service(db: Session) -> ConnectionService:
    """Create a ConnectionService from a DB session.

    Separated from the route handlers so it can be called inside
    try/except blocks, ensuring construction errors are caught.

    Args:
        db: SQLAlchemy session.

    Returns:
        Configured ConnectionService instance.
    """
    return ConnectionService(db=db)


def _internal_error(e: Exception, operation: str) -> JSONResponse:
    """Build a structured 500 response and log the full traceback.

    Args:
        e: The exception that was raised.
        operation: Human-readable operation name for the log message.

    Returns:
        JSONResponse with error envelope.
    """
    logger.error(
        "Unexpected error during %s: %s: %s",
        operation, type(e).__name__, e,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": sanitize_error_message(str(e))}},
    )


@router.get("/")
def list_connections(db: Session = Depends(get_db)):
    """List all provider connections (no credentials exposed)."""
    try:
        service = _build_service(db)
        return service.list_connections()
    except Exception as e:
        return _internal_error(e, "list connections")


@router.get("/{connection_key:path}")
def get_connection(
    connection_key: str,
    db: Session = Depends(get_db),
):
    """Get a single connection by key (no credentials exposed)."""
    try:
        service = _build_service(db)
        conn = service.get_connection(connection_key)
        if conn is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"Connection '{connection_key}' not found"}},
            )
        return conn
    except Exception as e:
        return _internal_error(e, "get connection")


@router.post("/{provider}/save")
def save_connection(
    provider: str,
    body: SaveConnectionRequest,
    db: Session = Depends(get_db),
):
    """Save or overwrite a provider connection with encrypted credentials."""
    try:
        service = _build_service(db)
        result = service.save_connection(
            provider=provider,
            auth_mode=body.auth_mode,
            credentials=body.credentials,
            metadata=body.metadata,
            display_name=body.display_name,
            environment=body.environment,
        )
        status_code = 201 if result["is_new"] else 200
        return JSONResponse(status_code=status_code, content=result)
    except ConnectionValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": e.code, "message": e.message}},
        )
    except Exception as e:
        return _internal_error(e, "save connection")


@router.delete("/{connection_key:path}")
def delete_connection(
    connection_key: str,
    db: Session = Depends(get_db),
):
    """Delete a connection by key."""
    try:
        service = _build_service(db)
        deleted = service.delete_connection(connection_key)
        if not deleted:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"Connection '{connection_key}' not found"}},
            )
        return {"deleted": True, "connection_key": connection_key}
    except Exception as e:
        return _internal_error(e, "delete connection")


@router.post("/{connection_key:path}/validate")
async def validate_connection(
    connection_key: str,
    db: Session = Depends(get_db),
):
    """Validate saved credentials against the real provider API.

    Tests credentials by making a lightweight API call to the provider.
    Updates the connection status to 'connected' on success or 'error'
    on failure with a specific error code and message.
    """
    try:
        service = _build_service(db)
        result = await service.validate_connection(connection_key)
        status_code = 200 if result["valid"] else 422
        return JSONResponse(status_code=status_code, content=result)
    except ConnectionValidationError as e:
        return JSONResponse(
            status_code=404 if e.code == "NOT_FOUND" else 400,
            content={"error": {"code": e.code, "message": e.message}},
        )
    except Exception as e:
        return _internal_error(e, "validate connection")


@router.post("/{connection_key:path}/disconnect")
def disconnect_connection(
    connection_key: str,
    db: Session = Depends(get_db),
):
    """Set a connection to 'disconnected' status (preserves credentials)."""
    try:
        service = _build_service(db)
        conn = service.disconnect(connection_key)
        if conn is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"Connection '{connection_key}' not found"}},
            )
        return conn
    except Exception as e:
        return _internal_error(e, "disconnect connection")
