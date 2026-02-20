"""Pydantic schemas for API request/response validation.

This module defines the data contracts for the ShipAgent REST API,
including job management and audit log export endpoints.
"""

from datetime import date
from enum import Enum
from typing import Literal

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    destination_country: str | None = None
    duties_taxes_cents: int | None = None
    charge_breakdown: dict | None = None
    error_code: str | None
    error_message: str | None
    created_at: str
    processed_at: str | None

    @field_validator("charge_breakdown", mode="before")
    @classmethod
    def _parse_charge_breakdown(cls, v: str | dict | None) -> dict | None:
        """Parse charge_breakdown from JSON string if stored as text in SQLite."""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    model_config = ConfigDict(from_attributes=True)


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
    total_duties_taxes_cents: int | None = None
    international_row_count: int = 0

    error_code: str | None
    error_message: str | None

    created_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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
    destination_country: str | None = None
    duties_taxes_cents: int | None = None
    charge_breakdown: dict | None = None


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
    total_duties_taxes_cents: int | None = None
    international_row_count: int = 0


class SkipRowsRequest(BaseModel):
    """Request schema for marking specific rows as skipped before execution."""

    row_numbers: list[int] = Field(..., min_length=1, description="Row numbers to skip")


class ConfirmRequest(BaseModel):
    """Request schema for confirming a batch for execution."""

    write_back_enabled: bool = True
    selected_service_code: str | None = None


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
    row_key_columns: list[str] | None = Field(
        None,
        description=(
            "Optional deterministic row key columns for database imports. "
            "If omitted, server auto-detects PRIMARY KEY/UNIQUE constraints."
        ),
    )


class DataSourceColumnInfo(BaseModel):
    """Column metadata from schema discovery."""

    name: str
    type: str
    nullable: bool


class DataSourceImportResponse(BaseModel):
    """Response schema for a successful data source import."""

    status: str = Field(
        ..., description="'connected', 'error', or 'pending_agent_setup'"
    )
    source_type: str
    row_count: int
    columns: list[DataSourceColumnInfo]
    error: str | None = None
    file_path: str | None = None


class DataSourceStatusResponse(BaseModel):
    """Response schema for data source connection status."""

    connected: bool
    source_type: str | None = None
    file_path: str | None = None
    row_count: int | None = None
    columns: list[DataSourceColumnInfo] | None = None


# Saved data source schemas


class SavedDataSourceResponse(BaseModel):
    """Response schema for a saved data source record."""

    id: str
    name: str
    source_type: str
    file_path: str | None = None
    sheet_name: str | None = None
    db_host: str | None = None
    db_port: int | None = None
    db_name: str | None = None
    db_query: str | None = None
    row_count: int
    column_count: int
    connected_at: str
    last_used_at: str

    model_config = ConfigDict(from_attributes=True)


class SavedDataSourceListResponse(BaseModel):
    """Response schema for listing saved data sources."""

    sources: list[SavedDataSourceResponse]
    total: int


class ReconnectRequest(BaseModel):
    """Request schema for reconnecting to a saved data source."""

    source_id: str = Field(..., description="UUID of the saved data source")
    connection_string: str | None = Field(
        None, description="Database connection string (required for database sources)"
    )
    row_key_columns: list[str] | None = Field(
        None,
        description=(
            "Optional deterministic row key columns for database reconnect imports."
        ),
    )


class BulkDeleteRequest(BaseModel):
    """Request schema for bulk-deleting saved data sources."""

    source_ids: list[str] = Field(..., min_length=1, description="UUIDs to delete")


# Contact schemas


class ContactCreate(BaseModel):
    """Request schema for creating a contact."""

    handle: str | None = Field(None, max_length=100, description="@mention slug (auto-generated if omitted)")
    display_name: str = Field(..., min_length=1, max_length=200)
    attention_name: str | None = Field(None, max_length=200)
    company: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=255)
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state_province: str | None = Field(None, max_length=50)
    postal_code: str = Field(..., min_length=1, max_length=20)
    country_code: str = Field("US", max_length=2)
    use_as_ship_to: bool = True
    use_as_shipper: bool = False
    use_as_third_party: bool = False
    tags: list[str] | None = None
    notes: str | None = None


class ContactUpdate(BaseModel):
    """Request schema for partially updating a contact."""

    handle: str | None = None
    display_name: str | None = None
    attention_name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    use_as_ship_to: bool | None = None
    use_as_shipper: bool | None = None
    use_as_third_party: bool | None = None
    tags: list[str] | None = None
    notes: str | None = None


class ContactResponse(BaseModel):
    """Response schema for a contact."""

    id: str
    handle: str
    display_name: str
    attention_name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state_province: str | None = None
    postal_code: str
    country_code: str
    use_as_ship_to: bool
    use_as_shipper: bool
    use_as_third_party: bool
    tags: list[str] | None = None
    notes: str | None = None
    last_used_at: str | None = None
    created_at: str
    updated_at: str

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, v: str | list | None) -> list[str] | None:
        """Parse tags from JSON string if stored as text in SQLite."""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    model_config = ConfigDict(from_attributes=True)


class ContactListResponse(BaseModel):
    """Response schema for listing contacts."""

    contacts: list[ContactResponse]
    total: int


# Custom command schemas


class CommandCreate(BaseModel):
    """Request schema for creating a custom command."""

    name: str = Field(..., min_length=1, max_length=100, description="Command slug without /")
    body: str = Field(..., min_length=1, description="Instruction text")
    description: str | None = None


class CommandUpdate(BaseModel):
    """Request schema for partially updating a command."""

    name: str | None = None
    body: str | None = None
    description: str | None = None


class CommandResponse(BaseModel):
    """Response schema for a custom command."""

    id: str
    name: str
    description: str | None = None
    body: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class CommandListResponse(BaseModel):
    """Response schema for listing commands."""

    commands: list[CommandResponse]
    total: int
