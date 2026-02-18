"""API routes for saved (persistent) data source management.

Provides endpoints for listing, reconnecting, and deleting saved
data source connections. Sources are auto-saved on every successful
import via gateway hooks.

All endpoints use /api/v1/saved-sources prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    BulkDeleteRequest,
    ReconnectRequest,
    SavedDataSourceListResponse,
    SavedDataSourceResponse,
)
from src.db.connection import get_db
from src.services.gateway_provider import get_data_gateway
from src.services.saved_data_source_service import SavedDataSourceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/saved-sources", tags=["saved-sources"])


@router.get("", response_model=SavedDataSourceListResponse)
def list_saved_sources(
    source_type: str | None = None,
    db: Session = Depends(get_db),
) -> SavedDataSourceListResponse:
    """List all saved data sources, ordered by most recently used.

    Args:
        source_type: Optional filter ('csv', 'excel', 'database').
        db: SQLAlchemy session (injected).

    Returns:
        List of saved sources with total count.
    """
    sources = SavedDataSourceService.list_sources(db, source_type=source_type)
    return SavedDataSourceListResponse(
        sources=[SavedDataSourceResponse.model_validate(s) for s in sources],
        total=len(sources),
    )


@router.get("/{source_id}", response_model=SavedDataSourceResponse)
def get_saved_source(
    source_id: str,
    db: Session = Depends(get_db),
) -> SavedDataSourceResponse:
    """Get a single saved data source by ID.

    Args:
        source_id: UUID of the saved source.
        db: SQLAlchemy session (injected).

    Returns:
        Saved source details.

    Raises:
        HTTPException: If source not found.
    """
    source = SavedDataSourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Saved source not found")
    return SavedDataSourceResponse.model_validate(source)


@router.post("/reconnect")
async def reconnect_saved_source(
    payload: ReconnectRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Reconnect to a previously saved data source.

    CSV/Excel sources reconnect from the stored file path (one click).
    Database sources require the connection_string in the request body
    since credentials are never persisted.

    Args:
        payload: Reconnect request with source_id and optional connection_string.
        db: SQLAlchemy session (injected).

    Returns:
        Dict with status, source_type, row_count, and column_count.

    Raises:
        HTTPException: If source not found or reconnection fails.
    """
    source = SavedDataSourceService.get_source(db, payload.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Saved source not found")

    gw = await get_data_gateway()

    try:
        if source.source_type == "csv":
            if not source.file_path:
                raise HTTPException(
                    status_code=400, detail="No file path stored for this CSV source"
                )
            result = await gw.import_csv(file_path=source.file_path)

        elif source.source_type == "excel":
            if not source.file_path:
                raise HTTPException(
                    status_code=400, detail="No file path stored for this Excel source"
                )
            result = await gw.import_excel(
                file_path=source.file_path, sheet=source.sheet_name
            )

        elif source.source_type == "database":
            if not payload.connection_string:
                raise HTTPException(
                    status_code=400,
                    detail="connection_string is required to reconnect database sources",
                )
            query = source.db_query or "SELECT * FROM shipments"
            result = await gw.import_database(
                connection_string=payload.connection_string,
                query=query,
                row_key_columns=payload.row_key_columns,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported source type: {source.source_type}",
            )

        # Update last_used_at
        SavedDataSourceService.touch(db, payload.source_id)
        db.commit()

        return {
            "status": "connected",
            "source_type": result.get("source_type", source.source_type),
            "row_count": result.get("row_count", 0),
            "column_count": len(result.get("columns", [])),
        }

    except FileNotFoundError as e:
        logger.warning("Reconnect file not found: %s", e)
        raise HTTPException(status_code=404, detail=f"File not found: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Reconnect failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Reconnect failed: {e}")


@router.delete("/{source_id}")
def delete_saved_source(
    source_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a single saved data source.

    Args:
        source_id: UUID of the source to delete.
        db: SQLAlchemy session (injected).

    Returns:
        Status confirmation.

    Raises:
        HTTPException: If source not found.
    """
    deleted = SavedDataSourceService.delete_source(db, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved source not found")
    db.commit()
    return {"status": "deleted", "source_id": source_id}


@router.post("/bulk-delete")
def bulk_delete_saved_sources(
    payload: BulkDeleteRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Delete multiple saved data sources.

    Args:
        payload: Request with list of source IDs.
        db: SQLAlchemy session (injected).

    Returns:
        Number of records deleted.
    """
    count = SavedDataSourceService.bulk_delete(db, payload.source_ids)
    db.commit()
    return {"status": "deleted", "count": count}
