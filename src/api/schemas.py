"""Pydantic schemas for API request/response validation.

This module defines the data contracts for the ShipAgent REST API,
including job management and audit log export endpoints.
"""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# Enums for API validation


class JobStatusEnum(str, Enum):
    """Valid job status values for API requests."""

    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobModeEnum(str, Enum):
    """Job execution mode values."""

    confirm = "confirm"
    auto = "auto"


# Job schemas


class JobCreate(BaseModel):
    """Request schema for creating a job."""

    name: str = Field(..., min_length=1, max_length=200)
    original_command: str = Field(..., min_length=1)
    description: str | None = Field(None, max_length=500)
    mode: JobModeEnum = JobModeEnum.confirm


class JobUpdate(BaseModel):
    """Request schema for updating job status."""

    status: JobStatusEnum


class JobRowResponse(BaseModel):
    """Response schema for a job row."""

    id: str
    row_number: int
    status: str
    row_checksum: str
    order_data: str | None = None
    tracking_number: str | None
    label_path: str | None
    cost_cents: int | None
    error_code: str | None
    error_message: str | None
    created_at: str
    processed_at: str | None

    class Config:
        """Pydantic config for ORM model conversion."""

        from_attributes = True


class JobResponse(BaseModel):
    """Response schema for a job."""

    id: str
    name: str
    description: str | None
    original_command: str
    status: str
    mode: str

    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int | None

    error_code: str | None
    error_message: str | None

    created_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str

    class Config:
        """Pydantic config for ORM model conversion."""

        from_attributes = True


class JobSummaryResponse(BaseModel):
    """Response schema for job summary (list view)."""

    id: str
    name: str
    original_command: str
    status: str
    mode: str
    total_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int | None
    created_at: str
    completed_at: str | None

    class Config:
        """Pydantic config for ORM model conversion."""

        from_attributes = True


class JobListResponse(BaseModel):
    """Response schema for paginated job list."""

    jobs: list[JobSummaryResponse]
    total: int
    limit: int
    offset: int


# Audit log schemas


class AuditLogResponse(BaseModel):
    """Response schema for an audit log entry."""

    id: str
    job_id: str
    timestamp: str
    level: str
    event_type: str
    message: str
    details: dict | None
    row_number: int | None

    class Config:
        """Pydantic config for ORM model conversion."""

        from_attributes = True


class LogExportResponse(BaseModel):
    """Response schema for log export metadata."""

    job_id: str
    job_name: str
    log_count: int
    filename: str


# Error response schema


class ErrorResponse(BaseModel):
    """Standard error response."""

    error_code: str
    message: str
    remediation: str | None = None
    details: dict | None = None


# Filter schemas


class JobFilters(BaseModel):
    """Query parameters for job list filtering."""

    status: JobStatusEnum | None = None
    name: str | None = None  # Partial match
    created_after: date | None = None
    created_before: date | None = None


# Command submission schemas


class CommandSubmit(BaseModel):
    """Request schema for submitting a natural language command."""

    command: str = Field(..., min_length=1, description="Natural language shipping command")
    base_command: str | None = Field(None, description="Original command before refinement (if this is a refinement)")
    refinements: list[str] | None = Field(None, description="Ordered list of refinement instructions applied")


class CommandSubmitResponse(BaseModel):
    """Response schema for command submission."""

    job_id: str
    status: str


class CommandHistoryItem(BaseModel):
    """Response schema for a command history entry."""

    id: str
    command: str
    status: str
    created_at: str

    class Config:
        """Pydantic config for ORM model conversion."""

        from_attributes = True


# Preview schemas


class PreviewRowResponse(BaseModel):
    """Response schema for a single row in batch preview."""

    row_number: int
    recipient_name: str
    city_state: str
    service: str
    estimated_cost_cents: int
    warnings: list[str] = Field(default_factory=list)
    order_data: dict | None = Field(
        default=None,
        description="Full order details for expanded view",
    )


class BatchPreviewResponse(BaseModel):
    """Response schema for batch preview before execution."""

    job_id: str
    total_rows: int
    preview_rows: list[PreviewRowResponse]
    additional_rows: int = Field(
        default=0, description="Number of rows not included in preview"
    )
    total_estimated_cost_cents: int
    rows_with_warnings: int = Field(
        default=0, description="Number of rows with warnings"
    )


class SkipRowsRequest(BaseModel):
    """Request schema for marking specific rows as skipped before execution."""

    row_numbers: list[int] = Field(..., min_length=1, description="Row numbers to skip")


class ConfirmRequest(BaseModel):
    """Request schema for confirming a batch for execution."""

    job_id: str


class ConfirmResponse(BaseModel):
    """Response schema for batch confirmation."""

    status: str
    message: str


# Data source schemas


class DataSourceImportRequest(BaseModel):
    """Request schema for importing a local data source."""

    type: Literal["csv", "excel", "database"] = Field(
        ..., description="Data source type"
    )
    file_path: str | None = Field(
        None, description="Path to CSV or Excel file on server"
    )
    delimiter: str = Field(",", description="CSV delimiter character")
    sheet: str | None = Field(None, description="Excel sheet name (default: first)")
    connection_string: str | None = Field(
        None, description="Database connection URL"
    )
    query: str | None = Field(None, description="SQL query for database import")


class DataSourceColumnInfo(BaseModel):
    """Column metadata from schema discovery."""

    name: str
    type: str
    nullable: bool


class DataSourceImportResponse(BaseModel):
    """Response schema for a successful data source import."""

    status: str = Field(..., description="'connected' or 'error'")
    source_type: str
    row_count: int
    columns: list[DataSourceColumnInfo]
    error: str | None = None


class DataSourceStatusResponse(BaseModel):
    """Response schema for data source connection status."""

    connected: bool
    source_type: str | None = None
    file_path: str | None = None
    row_count: int | None = None
    columns: list[DataSourceColumnInfo] | None = None
