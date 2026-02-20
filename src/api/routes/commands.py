"""API routes for custom /command management.

Provides CRUD endpoints for user-defined slash commands.
All endpoints use /api/v1/commands prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
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


def _map_value_error(e: ValueError) -> HTTPException:
    """Map ValueError to appropriate HTTP status code.

    - 'not found' → 404
    - 'already exists' / 'already in use' → 409 (conflict)
    - Other validation errors → 400
    """
    msg = str(e).lower()
    if "not found" in msg:
        return HTTPException(status_code=404, detail=str(e))
    if "already exists" in msg or "already in use" in msg:
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


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
        HTTPException: 400 if validation fails, 409 if name conflicts.
    """
    try:
        cmd = service.create_command(**data.model_dump())
        db.commit()
        return CommandResponse.model_validate(cmd)
    except ValueError as e:
        raise _map_value_error(e)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Command with this name already exists")


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
        HTTPException: 404 if not found, 400 if validation fails, 409 if name conflict.
    """
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        cmd = service.update_command(command_id, **updates)
        db.commit()
        return CommandResponse.model_validate(cmd)
    except ValueError as e:
        raise _map_value_error(e)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Command name already in use")


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
