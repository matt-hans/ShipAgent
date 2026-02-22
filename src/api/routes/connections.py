"""API routes for provider connection management.

Handles CRUD operations for provider connections (UPS, Shopify).
Uses Pydantic models for request validation. Credential values are
never echoed in error responses — the custom 422 handler sanitizes them.
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


def _get_service(db: Session = Depends(get_db)) -> ConnectionService:
    """Dependency to provide a ConnectionService instance."""
    return ConnectionService(db=db)


@router.get("/")
def list_connections(service: ConnectionService = Depends(_get_service)):
    """List all provider connections (no credentials exposed)."""
    return service.list_connections()


@router.get("/{connection_key:path}")
def get_connection(
    connection_key: str,
    service: ConnectionService = Depends(_get_service),
):
    """Get a single connection by key (no credentials exposed)."""
    conn = service.get_connection(connection_key)
    if conn is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": f"Connection '{connection_key}' not found"}},
        )
    return conn


@router.post("/{provider}/save")
def save_connection(
    provider: str,
    body: SaveConnectionRequest,
    service: ConnectionService = Depends(_get_service),
):
    """Save or overwrite a provider connection with encrypted credentials."""
    try:
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
        logger.error("Unexpected error saving connection: %s", type(e).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": sanitize_error_message(str(e))}},
        )


@router.delete("/{connection_key:path}")
def delete_connection(
    connection_key: str,
    service: ConnectionService = Depends(_get_service),
):
    """Delete a connection by key."""
    deleted = service.delete_connection(connection_key)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": f"Connection '{connection_key}' not found"}},
        )
    return {"deleted": True, "connection_key": connection_key}


@router.post("/{connection_key:path}/disconnect")
def disconnect_connection(
    connection_key: str,
    service: ConnectionService = Depends(_get_service),
):
    """Set a connection to 'disconnected' status (preserves credentials)."""
    conn = service.disconnect(connection_key)
    if conn is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": f"Connection '{connection_key}' not found"}},
        )
    return conn
