"""SQLAlchemy ORM models for ShipAgent state database.

This module defines the core data models for job tracking, per-row status,
audit logging, and conversation persistence. Uses SQLAlchemy 2.0 style
with Mapped and mapped_column.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def generate_uuid() -> str:
    """Generate a UUID4 string for primary keys."""
    return str(uuid4())


def utc_now_iso() -> str:
    """Generate current UTC timestamp in ISO8601 format."""
    return datetime.now(UTC).isoformat()


# Enums matching the database schema constraints


class JobStatus(str, Enum):
    """Status values for batch shipping jobs.

    Lifecycle: pending -> running -> completed/failed/cancelled
               running -> paused -> running (on reconnect)
    """

    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RowStatus(str, Enum):
    """Status values for individual rows within a job.

    Lifecycle: pending → in_flight → completed/failed
               in_flight → needs_review (crash recovery, ambiguous outcome)
    """

    pending = "pending"
    in_flight = "in_flight"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    needs_review = "needs_review"


class LogLevel(str, Enum):
    """Severity levels for audit log entries."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class EventType(str, Enum):
    """Categories of events logged in the audit trail."""

    state_change = "state_change"
    api_call = "api_call"
    row_event = "row_event"
    error = "error"


class AgentDecisionRunStatus(str, Enum):
    """Lifecycle status values for agent decision runs."""

    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AgentDecisionPhase(str, Enum):
    """Phase categories for agent decision events."""

    ingress = "ingress"
    intent = "intent"
    resolution = "resolution"
    mapping = "mapping"
    tool_call = "tool_call"
    tool_result = "tool_result"
    pipeline = "pipeline"
    execution = "execution"
    egress = "egress"
    error = "error"


class AgentDecisionActor(str, Enum):
    """Actor categories for agent decision events."""

    api = "api"
    agent = "agent"
    tool = "tool"
    system = "system"


# SQLAlchemy Base


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# Models


class Job(Base):
    """Batch shipping job record.

    Tracks the overall status of a batch processing job, including
    aggregate metrics (row counts, costs) and error information.

    Attributes:
        id: UUID primary key
        name: User-provided job name
        description: Optional job description
        original_command: The natural language command that created this job
        status: Current job status (pending, running, paused, completed, failed, cancelled)
        mode: Execution mode (confirm = wait for approval, auto = immediate)
        total_rows: Total number of rows to process
        processed_rows: Number of rows processed so far
        successful_rows: Number of rows completed successfully
        failed_rows: Number of rows that failed
        total_cost_cents: Total cost in cents (avoids floating point issues)
        created_at: ISO8601 timestamp of job creation
        started_at: ISO8601 timestamp when job started running
        completed_at: ISO8601 timestamp when job finished
        updated_at: ISO8601 timestamp of last update
        error_code: Error code if job failed (E-XXXX format)
        error_message: Human-readable error message if failed
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.pending.value
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="confirm")

    # Row counts
    total_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    processed_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    successful_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    failed_rows: Mapped[int] = mapped_column(default=0, nullable=False)

    # Cost tracking (in cents to avoid float issues)
    total_cost_cents: Mapped[int | None] = mapped_column(nullable=True)

    # International shipping aggregates
    total_duties_taxes_cents: Mapped[int | None] = mapped_column(nullable=True)
    international_row_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Interactive shipment metadata
    shipper_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_interactive: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Write-back preference (tracking numbers written back to source after execution)
    write_back_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="1"
    )

    # Timestamps (ISO8601 strings for SQLite compatibility)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    started_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso, onupdate=utc_now_iso
    )

    # Error info (if failed)
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    rows: Mapped[list["JobRow"]] = relationship(
        "JobRow", back_populates="job", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="job", cascade="all, delete-orphan"
    )
    decision_runs: Mapped[list["AgentDecisionRun"]] = relationship(
        "AgentDecisionRun",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    # Indexes
    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id!r}, name={self.name!r}, status={self.status!r})>"


class JobRow(Base):
    """Individual row within a batch job.

    Tracks per-row processing status to enable retry of failed rows
    without reprocessing successful ones.

    Attributes:
        id: UUID primary key
        job_id: Foreign key to parent job
        row_number: 1-based row number from source data
        row_checksum: MD5 hash of row data for integrity verification
        status: Current row status
        tracking_number: UPS tracking number if shipment created
        label_path: File path to saved shipping label
        cost_cents: Shipping cost in cents
        error_code: Error code if row failed
        error_message: Error description if row failed
        created_at: ISO8601 timestamp of row creation
        processed_at: ISO8601 timestamp when row was processed
    """

    __tablename__ = "job_rows"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(nullable=False)
    row_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RowStatus.pending.value
    )

    # Order data (JSON blob with shipment details for preview)
    order_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result data
    tracking_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    label_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(nullable=True)

    # International shipping data
    destination_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    duties_taxes_cents: Mapped[int | None] = mapped_column(nullable=True)
    charge_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Execution determinism — idempotency and recovery
    idempotency_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    ups_shipment_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    ups_tracking_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    recovery_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Error info (if failed)
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    processed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="rows")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("job_id", "row_number", name="uq_job_row_number"),
        Index("idx_job_rows_job_id", "job_id"),
        Index("idx_job_rows_status", "status"),
        Index("idx_job_rows_idempotency", "idempotency_key"),
        Index("idx_job_rows_tracking", "ups_tracking_number"),
    )

    def __repr__(self) -> str:
        return f"<JobRow(id={self.id!r}, job_id={self.job_id!r}, row={self.row_number}, status={self.status!r})>"


class AuditLog(Base):
    """Audit log entry for job activity tracking.

    Records all significant events during job execution including
    state changes, API calls, row processing events, and errors.

    Attributes:
        id: UUID primary key
        job_id: Foreign key to parent job
        timestamp: ISO8601 timestamp of event
        level: Log severity (INFO, WARNING, ERROR)
        event_type: Category of event (state_change, api_call, row_event, error)
        message: Human-readable event description
        details: JSON blob with structured event data (request/response payloads)
        row_number: Optional row number for row-specific events
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured data (JSON blob for request/response payloads)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Row context (optional, for row-specific events)
    row_number: Mapped[int | None] = mapped_column(nullable=True)

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="audit_logs")

    # Indexes
    __table_args__ = (
        Index("idx_audit_logs_job_id", "job_id"),
        Index("idx_audit_logs_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id!r}, job_id={self.job_id!r}, level={self.level!r}, type={self.event_type!r})>"


class AgentDecisionRun(Base):
    """Canonical run record for one user message decision cycle."""

    __tablename__ = "agent_decision_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    user_message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_message_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    source_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AgentDecisionRunStatus.running.value
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    interactive_shipping: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    completed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    job: Mapped[Optional["Job"]] = relationship("Job", back_populates="decision_runs")
    events: Mapped[list["AgentDecisionEvent"]] = relationship(
        "AgentDecisionEvent",
        back_populates="run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_agent_decision_runs_session", "session_id"),
        Index("idx_agent_decision_runs_job", "job_id"),
        Index("idx_agent_decision_runs_status", "status"),
        Index("idx_agent_decision_runs_started_at", "started_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentDecisionRun(id={self.id!r}, session_id={self.session_id!r}, "
            f"job_id={self.job_id!r}, status={self.status!r})>"
        )


class AgentDecisionEvent(Base):
    """Structured event emitted during an AgentDecisionRun lifecycle."""

    __tablename__ = "agent_decision_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_decision_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    event_name: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    prev_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped["AgentDecisionRun"] = relationship(
        "AgentDecisionRun", back_populates="events"
    )

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_decision_events_run_seq"),
        Index("idx_agent_decision_events_run", "run_id"),
        Index("idx_agent_decision_events_phase", "phase"),
        Index("idx_agent_decision_events_event_name", "event_name"),
        Index("idx_agent_decision_events_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentDecisionEvent(id={self.id!r}, run_id={self.run_id!r}, "
            f"seq={self.seq}, phase={self.phase!r}, event_name={self.event_name!r})>"
        )


class WriteBackTask(Base):
    """Durable write-back task for tracking number persistence.

    Each successful shipment enqueues a task; the worker processes
    them with per-task retry and dead-letter semantics. Survives
    crashes because tasks are DB-persisted before write-back runs.

    Attributes:
        id: UUID primary key.
        job_id: Foreign key to parent job.
        row_number: 1-based row number within the job.
        tracking_number: UPS tracking number to write back.
        shipped_at: ISO8601 timestamp of shipment creation.
        status: Task status (pending, completed, dead_letter).
        retry_count: Number of failed attempts so far.
        created_at: ISO8601 timestamp of task creation.
    """

    __tablename__ = "write_back_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(50), nullable=False)
    shipped_at: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    # Indexes
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "row_number",
            name="uq_write_back_tasks_job_row_number",
        ),
        Index("idx_wb_tasks_status", "status"),
        Index("idx_wb_tasks_job_id", "job_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<WriteBackTask(id={self.id!r}, job_id={self.job_id!r}, "
            f"row={self.row_number}, status={self.status!r})>"
        )


class SavedDataSource(Base):
    """Persistent record of a previously connected data source.

    Stores display metadata for reconnection. File-based sources (CSV/Excel)
    keep the server-side file_path for one-click reconnect. Database sources
    store only display info (host, db_name) — credentials are never persisted.

    Attributes:
        id: UUID primary key.
        name: Human-readable display name (e.g. filename or db name).
        source_type: One of 'csv', 'excel', 'database'.
        file_path: Server-side path for CSV/Excel sources.
        sheet_name: Excel sheet name (if applicable).
        db_host: Database host (display only, no credentials).
        db_port: Database port (display only).
        db_name: Database name (display only).
        db_query: SQL query used for database import.
        row_count: Number of rows at last connection.
        column_count: Number of columns at last connection.
        connected_at: ISO8601 timestamp of first connection.
        last_used_at: ISO8601 timestamp of most recent use.
    """

    __tablename__ = "saved_data_sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # File-based sources
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Database sources (display info only — NO credentials)
    db_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_port: Mapped[int | None] = mapped_column(nullable=True)
    db_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_query: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    row_count: Mapped[int] = mapped_column(default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Timestamps
    connected_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    last_used_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    # Indexes
    __table_args__ = (
        Index("idx_saved_ds_source_type", "source_type"),
        Index("idx_saved_ds_last_used_at", "last_used_at"),
    )

    def __repr__(self) -> str:
        return f"<SavedDataSource(id={self.id!r}, name={self.name!r}, type={self.source_type!r})>"


class Contact(Base):
    """Persistent address book contact for @handle resolution.

    Stores recipient/shipper/third-party address profiles that can be
    referenced via @handle in chat messages and custom commands.

    Attributes:
        handle: Unique lowercase slug for @mention resolution.
        display_name: Human-readable name shown in UI.
        attention_name: UPS AttentionName override (optional).
        use_as_ship_to: Whether this contact can populate ShipTo.
        use_as_shipper: Whether this contact can populate Shipper.
        use_as_third_party: Whether this contact can populate ThirdParty.
        last_used_at: Timestamp for MRU ranking in system prompt injection.
    """

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    handle: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    attention_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state_province: Mapped[str | None] = mapped_column(String(50), nullable=True)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="US"
    )
    use_as_ship_to: Mapped[bool] = mapped_column(
        nullable=False, server_default="1"
    )
    use_as_shipper: Mapped[bool] = mapped_column(
        nullable=False, server_default="0"
    )
    use_as_third_party: Mapped[bool] = mapped_column(
        nullable=False, server_default="0"
    )
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    # M4 note: CheckConstraint uses GLOB which is SQLite-specific.
    # Service-layer regex (HANDLE_PATTERN) is the primary enforcement.
    # If migrating to PostgreSQL, replace GLOB with a CHECK using ~ regex.
    __table_args__ = (
        Index("idx_contacts_handle", "handle"),
        Index("idx_contacts_last_used_at", "last_used_at"),
    )

    @property
    def tag_list(self) -> list[str]:
        """Parse tags JSON string into a Python list."""
        if not self.tags:
            return []
        import json
        return json.loads(self.tags)

    @tag_list.setter
    def tag_list(self, value: list[str]) -> None:
        """Serialize a Python list into JSON for the tags column."""
        import json
        self.tags = json.dumps(value) if value else None

    def __repr__(self) -> str:
        return f"<Contact(handle={self.handle!r}, name={self.display_name!r})>"


class ProviderConnection(Base):
    """Encrypted provider credential storage for UPS and Shopify.

    Stores AES-256-GCM encrypted credentials with versioned envelope,
    AAD binding, and per-row status tracking. Single-user local app —
    no user_id scoping.

    Attributes:
        id: UUID4 text primary key.
        connection_key: Unique key (e.g., 'ups:test', 'shopify:store.myshopify.com').
        provider: Provider identifier ('ups' or 'shopify').
        display_name: Human-readable name for UI display.
        auth_mode: Authentication mode ('client_credentials', 'legacy_token',
            'client_credentials_shopify').
        environment: UPS only — 'test' or 'production'.
        status: Connection status ('configured', 'validating', 'connected',
            'disconnected', 'error', 'needs_reconnect').
        encrypted_credentials: AES-256-GCM JSON envelope string.
        metadata_json: TEXT column (not SQLAlchemy JSON) — parsed via json.loads()
            in service layer. Contains provider-specific metadata.
        last_error_code: Structured error code from last failure.
        error_message: Sanitized error message from last failure.
        schema_version: Envelope schema version (always 1 in Phase 1).
        key_version: Encryption key version (always 1 in Phase 1).
        created_at: ISO8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ).
        updated_at: ISO8601 UTC timestamp, service-managed (no ORM onupdate).
    """

    __tablename__ = "provider_connections"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=generate_uuid
    )
    connection_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    auth_mode: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="configured")
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True, default="{}")
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=utc_now_iso)

    __table_args__ = (
        Index("idx_provider_connections_provider", "provider"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProviderConnection(key={self.connection_key!r}, "
            f"provider={self.provider!r}, status={self.status!r})>"
        )


class CustomCommand(Base):
    """User-defined slash command that expands to a shipping instruction.

    Commands are resolved on the frontend before submission. The agent
    receives the expanded body text, not the slash command itself.

    Attributes:
        name: Command slug stored without '/' prefix (e.g. 'daily-restock').
        description: Optional human note about the command's purpose.
        body: Full instruction text that replaces the /command on expansion.
    """

    __tablename__ = "custom_commands"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    def __repr__(self) -> str:
        return f"<CustomCommand(name={self.name!r})>"


class MessageType(str, Enum):
    """Type classification for conversation messages.

    Used by the visual timeline to determine dot color without
    parsing metadata JSON.
    """

    text = "text"
    system_artifact = "system_artifact"
    error = "error"


class ConversationSession(Base):
    """Persistent conversation session.

    Stores session metadata including mode, title, and context data
    (active data source, source hash) for context-aware resume.

    Attributes:
        id: UUID primary key (same as runtime session_id).
        title: Agent-generated title (nullable until first response).
        mode: Shipping mode — 'batch' or 'interactive'.
        context_data: JSON blob with data source reference and agent_source_hash.
        is_active: Soft delete flag (False = archived).
        created_at: ISO8601 creation timestamp.
        updated_at: ISO8601 last-update timestamp.
    """

    __tablename__ = "conversation_sessions"
    __table_args__ = (
        Index("ix_convsess_active_updated", "is_active", "updated_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="batch"
    )
    context_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.sequence",
    )

    def __repr__(self) -> str:
        return f"<ConversationSession(id={self.id!r}, title={self.title!r})>"


class ConversationMessage(Base):
    """Persistent conversation message.

    Stores rendered messages (user text, agent text, artifacts, errors)
    for history display and agent context re-injection on resume.

    Attributes:
        id: UUID primary key.
        session_id: FK to ConversationSession.
        role: Message role — 'user', 'assistant', or 'system'.
        message_type: Classification for timeline rendering.
        content: Message text content.
        metadata_json: Optional JSON with artifact data (action, preview, etc.).
        sequence: Ordering within session (monotonically increasing).
        created_at: ISO8601 creation timestamp.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_convmsg_session_seq"),
        Index("ix_convmsg_session_seq", "session_id", "sequence"),
        Index("ix_convmsg_session_type", "session_id", "message_type"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MessageType.text.value
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="messages"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage(id={self.id!r}, role={self.role!r}, "
            f"seq={self.sequence})>"
        )
