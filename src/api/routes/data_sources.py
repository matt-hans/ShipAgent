"""API routes for local data source management.

Provides REST API endpoints for importing, querying, and disconnecting
local data sources (CSV, Excel, Database).

All routes are thin HTTP-to-MCP adapters delegating to the
DataSourceMCPClient via gateway_provider, with no local state
management in the route layer.

All endpoints use /api/v1/data-sources prefix.
"""

import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.api.schemas import (
    DataSourceColumnInfo,
    DataSourceImportRequest,
    DataSourceImportResponse,
    DataSourceStatusResponse,
)
from src.services.gateway_provider import get_data_gateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-sources", tags=["data-sources"])

# Directory for uploaded files — resolved relative to project root
UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads"


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
    gw = await get_data_gateway()

    try:
        if payload.type == "csv":
            if not payload.file_path:
                raise HTTPException(
                    status_code=400,
                    detail="file_path is required for CSV import",
                )
            result = await gw.import_csv(
                file_path=payload.file_path,
                delimiter=payload.delimiter,
            )

        elif payload.type == "excel":
            if not payload.file_path:
                raise HTTPException(
                    status_code=400,
                    detail="file_path is required for Excel import",
                )
            result = await gw.import_excel(
                file_path=payload.file_path,
                sheet=payload.sheet,
            )

        elif payload.type == "database":
            if not payload.connection_string or not payload.query:
                raise HTTPException(
                    status_code=400,
                    detail="connection_string and query are required for database import",
                )
            result = await gw.import_database(
                connection_string=payload.connection_string,
                query=payload.query,
                row_key_columns=payload.row_key_columns,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported data source type: {payload.type}",
            )

        # result is a dict from MCP tool (model_dump() of ImportResult)
        columns = [
            DataSourceColumnInfo(
                name=col["name"],
                type=col["type"],
                nullable=col.get("nullable", True),
            )
            for col in result.get("columns", [])
        ]

        return DataSourceImportResponse(
            status="connected",
            source_type=result.get("source_type", payload.type),
            row_count=result.get("row_count", 0),
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


@router.post("/upload", response_model=DataSourceImportResponse)
async def upload_data_source(
    file: UploadFile = File(...),
) -> DataSourceImportResponse:
    """Upload a file and import it as the active data source.

    Supports CSV, TSV, SSV, TXT, DAT, XLSX, XLS, JSON, XML, EDI, X12,
    and FWF formats. Saves the file to the uploads/ directory, then
    delegates to the appropriate adapter. Replaces any previously
    connected source.

    Args:
        file: The uploaded data file.

    Returns:
        Import result with schema, row count, and status.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Extension → source type mapping (mirrors EXTENSION_MAP in import_tools.py)
    _UPLOAD_EXTENSIONS = {
        ".csv": "csv", ".tsv": "delimited", ".ssv": "delimited",
        ".txt": "delimited", ".dat": "delimited",
        ".xlsx": "excel", ".xls": "excel",
        ".json": "json", ".xml": "xml",
        ".edi": "edi", ".x12": "edi", ".edifact": "edi",
        ".fwf": "fixed_width",
    }

    ext = os.path.splitext(file.filename)[1].lower()
    source_type = _UPLOAD_EXTENSIONS.get(ext)
    if source_type is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {ext}. "
                f"Supported: {', '.join(sorted(_UPLOAD_EXTENSIONS.keys()))}"
            ),
        )

    # Save uploaded file to disk
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / file.filename
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except OSError as e:
        logger.exception("Failed to save uploaded file: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    finally:
        await file.close()

    file_path = str(dest)
    gw = await get_data_gateway()

    try:
        if source_type == "csv":
            result = await gw.import_csv(file_path=file_path)
        elif source_type == "excel":
            result = await gw.import_excel(file_path=file_path)
        else:
            # Use the universal import_file tool for all other formats
            result = await gw._call_tool("import_file", {
                "file_path": file_path,
                "format_hint": source_type,
            })

        columns = [
            DataSourceColumnInfo(
                name=col["name"],
                type=col["type"],
                nullable=col.get("nullable", True),
            )
            for col in result.get("columns", [])
        ]

        return DataSourceImportResponse(
            status="connected",
            source_type=result.get("source_type", source_type),
            row_count=result.get("row_count", 0),
            columns=columns,
        )
    except (FileNotFoundError, ValueError) as e:
        logger.warning("Upload import error: %s", e)
        return DataSourceImportResponse(
            status="error",
            source_type=source_type,
            row_count=0,
            columns=[],
            error=str(e),
        )
    except Exception as e:
        logger.exception("Upload import failed: %s", e)
        return DataSourceImportResponse(
            status="error",
            source_type=source_type,
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
    gw = await get_data_gateway()
    info = await gw.get_source_info()

    if info is None:
        return DataSourceStatusResponse(connected=False)

    columns = [
        DataSourceColumnInfo(
            name=col["name"],
            type=col["type"],
            nullable=col.get("nullable", True),
        )
        for col in info.get("columns", [])
    ]

    return DataSourceStatusResponse(
        connected=True,
        source_type=info.get("source_type"),
        file_path=info.get("path"),
        row_count=info.get("row_count", 0),
        columns=columns,
    )


@router.post("/disconnect")
async def disconnect_data_source() -> dict:
    """Disconnect the currently connected data source.

    Returns:
        Status confirmation.
    """
    gw = await get_data_gateway()
    await gw.disconnect()
    return {"status": "disconnected"}


@router.get("/schema")
async def get_data_source_schema() -> dict:
    """Get the column schema of the currently connected data source.

    Returns:
        Schema with column names, types, and nullability.

    Raises:
        HTTPException: If no data source is connected.
    """
    gw = await get_data_gateway()
    info = await gw.get_source_info()

    if info is None:
        raise HTTPException(
            status_code=404,
            detail="No data source connected",
        )

    return {
        "columns": [
            {
                "name": col["name"],
                "type": col["type"],
                "nullable": col.get("nullable", True),
            }
            for col in info.get("columns", [])
        ],
        "row_count": info.get("row_count", 0),
        "source_type": info.get("source_type"),
    }
