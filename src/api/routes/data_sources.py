"""API routes for local data source management.

Provides endpoints for importing, querying, and disconnecting
local data sources (CSV, Excel, Database).

All endpoints use /api/v1/data-sources prefix.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    DataSourceColumnInfo,
    DataSourceImportRequest,
    DataSourceImportResponse,
    DataSourceStatusResponse,
)
from src.services.data_source_service import DataSourceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


@router.post("/import", response_model=DataSourceImportResponse)
async def import_data_source(
    payload: DataSourceImportRequest,
) -> DataSourceImportResponse:
    """Import a local data source (CSV, Excel, or Database).

    Replaces any previously connected source.

    Args:
        payload: Import configuration with type, file path, and options.

    Returns:
        Import result with schema, row count, and status.
    """
    svc = DataSourceService.get_instance()

    try:
        if payload.type == "csv":
            if not payload.file_path:
                raise HTTPException(
                    status_code=400,
                    detail="file_path is required for CSV import",
                )
            result = await svc.import_csv(
                file_path=payload.file_path,
                delimiter=payload.delimiter,
            )

        elif payload.type == "excel":
            if not payload.file_path:
                raise HTTPException(
                    status_code=400,
                    detail="file_path is required for Excel import",
                )
            result = await svc.import_excel(
                file_path=payload.file_path,
                sheet=payload.sheet,
            )

        elif payload.type == "database":
            if not payload.connection_string or not payload.query:
                raise HTTPException(
                    status_code=400,
                    detail="connection_string and query are required for database import",
                )
            result = await svc.import_database(
                connection_string=payload.connection_string,
                query=payload.query,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported data source type: {payload.type}",
            )

        # result is an ImportResult Pydantic model from the adapter
        columns = [
            DataSourceColumnInfo(
                name=col.name,
                type=col.type,
                nullable=col.nullable,
            )
            for col in result.columns
        ]

        return DataSourceImportResponse(
            status="connected",
            source_type=result.source_type,
            row_count=result.row_count,
            columns=columns,
        )

    except FileNotFoundError as e:
        logger.warning("Data source file not found: %s", e)
        return DataSourceImportResponse(
            status="error",
            source_type=payload.type,
            row_count=0,
            columns=[],
            error=str(e),
        )
    except ValueError as e:
        logger.warning("Data source import validation error: %s", e)
        return DataSourceImportResponse(
            status="error",
            source_type=payload.type,
            row_count=0,
            columns=[],
            error=str(e),
        )
    except Exception as e:
        logger.exception("Data source import failed: %s", e)
        return DataSourceImportResponse(
            status="error",
            source_type=payload.type,
            row_count=0,
            columns=[],
            error=f"Import failed: {e}",
        )


@router.get("/status", response_model=DataSourceStatusResponse)
async def get_data_source_status() -> DataSourceStatusResponse:
    """Get the status of the currently connected data source.

    Returns:
        Connection status with source type, row count, and schema.
    """
    svc = DataSourceService.get_instance()
    info = svc.get_source_info()

    if info is None:
        return DataSourceStatusResponse(connected=False)

    columns = [
        DataSourceColumnInfo(
            name=col.name,
            type=col.type,
            nullable=col.nullable,
        )
        for col in info.columns
    ]

    return DataSourceStatusResponse(
        connected=True,
        source_type=info.source_type,
        file_path=info.file_path,
        row_count=info.row_count,
        columns=columns,
    )


@router.post("/disconnect")
async def disconnect_data_source() -> dict:
    """Disconnect the currently connected data source.

    Returns:
        Status confirmation.
    """
    svc = DataSourceService.get_instance()
    svc.disconnect()
    return {"status": "disconnected"}


@router.get("/schema")
async def get_data_source_schema() -> dict:
    """Get the column schema of the currently connected data source.

    Returns:
        Schema with column names, types, and nullability.

    Raises:
        HTTPException: If no data source is connected.
    """
    svc = DataSourceService.get_instance()
    info = svc.get_source_info()

    if info is None:
        raise HTTPException(
            status_code=404,
            detail="No data source connected",
        )

    return {
        "columns": [
            {
                "name": col.name,
                "type": col.type,
                "nullable": col.nullable,
            }
            for col in info.columns
        ],
        "row_count": info.row_count,
        "source_type": info.source_type,
    }
