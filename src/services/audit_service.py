"""Audit logging service for ShipAgent.

This module provides job-scoped audit logging with automatic redaction of
sensitive data (PII, credentials). Supports plain text export for debugging
and compliance.

Usage:
    from src.db.connection import get_db, init_db
    from src.services.audit_service import AuditService, LogLevel, EventType

    init_db()
    db = next(get_db())
    audit = AuditService(db)

    audit.log_state_change(job_id, 'pending', 'running')
    audit.log_api_call(job_id, '/v1/shipments', 'POST', request, response, 200)

    # Export logs as plain text
    export = audit.export_logs_text(job_id)
"""

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import AuditLog, EventType, LogLevel


# Re-export enums for convenience
__all__ = [
    "AuditService",
    "redact_sensitive",
    "LogLevel",
    "EventType",
    "REDACT_FIELDS",
    "REDACTED",
]


# Redaction configuration

REDACT_FIELDS = {
    # Address fields
    "address",
    "address1",
    "address2",
    "address_line_1",
    "address_line_2",
    "street",
    "city",
    "state",
    "postal_code",
    "zip",
    "zip_code",
    "country",
    # Personal info
    "name",
    "first_name",
    "last_name",
    "phone",
    "email",
    "company",
    "shipper_name",
    "recipient_name",
    "ship_to",
    "ship_from",
    # Account info
    "account_number",
    "shipper_number",
    "access_token",
    "refresh_token",
    "client_id",
    "client_secret",
    "api_key",
}

REDACTED = "[REDACTED]"


def redact_sensitive(
    data: dict | list | str | None, _depth: int = 0
) -> dict | list | str | None:
    """Recursively redact sensitive fields from data structures.

    Scans dictionaries for keys matching known sensitive field names
    and replaces their values with '[REDACTED]'. Handles nested structures.

    Args:
        data: The data structure to redact (dict, list, str, or None)
        _depth: Internal recursion depth counter (prevents infinite loops)

    Returns:
        A copy of the data with sensitive fields redacted.

    Example:
        >>> redact_sensitive({'name': 'John', 'amount': 100})
        {'name': '[REDACTED]', 'amount': 100}
    """
    if _depth > 10:  # Prevent infinite recursion
        return REDACTED
    if data is None:
        return None
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return [redact_sensitive(item, _depth + 1) for item in data]
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = key.lower().replace("-", "_")
            if any(field in key_lower for field in REDACT_FIELDS):
                result[key] = REDACTED
            else:
                result[key] = redact_sensitive(value, _depth + 1)
        return result
    # For other types (int, float, bool, etc.), return as-is
    return data


def _utc_now_iso() -> str:
    """Generate current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


class AuditService:
    """Service for job-scoped audit logging with sensitive data redaction.

    Provides methods for logging various event types (state changes, API calls,
    row events, errors) with automatic redaction of PII and credentials.
    Supports querying and plain text export of logs.

    Attributes:
        db: SQLAlchemy session for database operations.
    """

    def __init__(self, db: Session) -> None:
        """Initialize the audit service.

        Args:
            db: SQLAlchemy session for database operations.
        """
        self.db = db

    def log(
        self,
        job_id: str,
        level: LogLevel,
        event_type: EventType,
        message: str,
        details: dict[str, Any] | None = None,
        row_number: int | None = None,
    ) -> AuditLog:
        """Create an audit log entry.

        Core logging method that all other log methods delegate to.
        Automatically redacts sensitive data in details before storage.

        Args:
            job_id: UUID of the job this log belongs to.
            level: Severity level (INFO, WARNING, ERROR).
            event_type: Category of event (state_change, api_call, row_event, error).
            message: Human-readable event description.
            details: Optional structured data (will be redacted and JSON-encoded).
            row_number: Optional row number for row-specific events.

        Returns:
            The created AuditLog entry.
        """
        # Redact and serialize details if provided
        details_json: str | None = None
        if details is not None:
            redacted_details = redact_sensitive(details)
            details_json = json.dumps(redacted_details)

        log_entry = AuditLog(
            job_id=job_id,
            timestamp=_utc_now_iso(),
            level=level.value,
            event_type=event_type.value,
            message=message,
            details=details_json,
            row_number=row_number,
        )

        self.db.add(log_entry)
        self.db.commit()
        self.db.refresh(log_entry)

        return log_entry

    # Convenience methods for log levels

    def log_info(
        self,
        job_id: str,
        event_type: EventType,
        message: str,
        details: dict[str, Any] | None = None,
        row_number: int | None = None,
    ) -> AuditLog:
        """Log an INFO level entry.

        Shorthand for log() with level=INFO.
        """
        return self.log(job_id, LogLevel.INFO, event_type, message, details, row_number)

    def log_warning(
        self,
        job_id: str,
        event_type: EventType,
        message: str,
        details: dict[str, Any] | None = None,
        row_number: int | None = None,
    ) -> AuditLog:
        """Log a WARNING level entry.

        Shorthand for log() with level=WARNING.
        """
        return self.log(
            job_id, LogLevel.WARNING, event_type, message, details, row_number
        )

    def log_error(
        self,
        job_id: str,
        event_type: EventType,
        message: str,
        details: dict[str, Any] | None = None,
        row_number: int | None = None,
    ) -> AuditLog:
        """Log an ERROR level entry.

        Shorthand for log() with level=ERROR.
        """
        return self.log(
            job_id, LogLevel.ERROR, event_type, message, details, row_number
        )

    # Event-specific methods

    def log_state_change(self, job_id: str, old_state: str, new_state: str) -> AuditLog:
        """Log a job state transition.

        Args:
            job_id: UUID of the job.
            old_state: Previous state value.
            new_state: New state value.

        Returns:
            The created AuditLog entry.
        """
        return self.log(
            job_id=job_id,
            level=LogLevel.INFO,
            event_type=EventType.state_change,
            message=f"Job state changed: {old_state} -> {new_state}",
            details={"old_state": old_state, "new_state": new_state},
        )

    def log_api_call(
        self,
        job_id: str,
        endpoint: str,
        method: str,
        request: dict[str, Any] | None,
        response: dict[str, Any] | None,
        status_code: int,
        row_number: int | None = None,
    ) -> AuditLog:
        """Log an API call with request/response data.

        Automatically determines log level based on HTTP status code:
        - 2xx/3xx: INFO
        - 4xx: WARNING
        - 5xx: ERROR

        Args:
            job_id: UUID of the job.
            endpoint: API endpoint path (e.g., '/v1/shipments').
            method: HTTP method (GET, POST, etc.).
            request: Request payload (will be redacted).
            response: Response payload (will be redacted).
            status_code: HTTP status code.
            row_number: Optional row number if call was for a specific row.

        Returns:
            The created AuditLog entry.
        """
        # Determine log level based on status code
        if status_code >= 500:
            level = LogLevel.ERROR
        elif status_code >= 400:
            level = LogLevel.WARNING
        else:
            level = LogLevel.INFO

        details = {
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "request": request,
            "response": response,
        }

        return self.log(
            job_id=job_id,
            level=level,
            event_type=EventType.api_call,
            message=f"{method} {endpoint} -> {status_code}",
            details=details,
            row_number=row_number,
        )

    def log_row_event(
        self,
        job_id: str,
        row_number: int,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Log a row processing event.

        Valid events: "started", "completed", "failed", "skipped"

        Args:
            job_id: UUID of the job.
            row_number: 1-based row number.
            event: Event type (started, completed, failed, skipped).
            details: Optional structured event data.

        Returns:
            The created AuditLog entry.
        """
        # Determine log level based on event type
        level = LogLevel.ERROR if event == "failed" else LogLevel.INFO

        return self.log(
            job_id=job_id,
            level=level,
            event_type=EventType.row_event,
            message=f"Row {row_number} {event}",
            details=details,
            row_number=row_number,
        )

    def log_job_error(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Log a job-level error.

        Args:
            job_id: UUID of the job.
            error_code: Error code (e.g., 'E-3001').
            error_message: Human-readable error description.
            details: Optional structured error context.

        Returns:
            The created AuditLog entry.
        """
        error_details = {
            "error_code": error_code,
            "error_message": error_message,
        }
        if details:
            error_details.update(details)

        return self.log(
            job_id=job_id,
            level=LogLevel.ERROR,
            event_type=EventType.error,
            message=f"{error_code}: {error_message}",
            details=error_details,
        )

    # Query methods

    def get_logs(
        self,
        job_id: str,
        level: LogLevel | None = None,
        event_type: EventType | None = None,
        limit: int = 1000,
    ) -> list[AuditLog]:
        """Get audit logs for a job with optional filters.

        Args:
            job_id: UUID of the job.
            level: Optional filter by log level.
            event_type: Optional filter by event type.
            limit: Maximum number of logs to return (default 1000).

        Returns:
            List of AuditLog entries ordered by timestamp (oldest first).
        """
        query = self.db.query(AuditLog).filter(AuditLog.job_id == job_id)

        if level is not None:
            query = query.filter(AuditLog.level == level.value)

        if event_type is not None:
            query = query.filter(AuditLog.event_type == event_type.value)

        return query.order_by(AuditLog.timestamp.asc()).limit(limit).all()

    def get_recent_errors(self, job_id: str, limit: int = 10) -> list[AuditLog]:
        """Get most recent ERROR level logs for a job.

        Args:
            job_id: UUID of the job.
            limit: Maximum number of logs to return (default 10).

        Returns:
            List of ERROR AuditLog entries ordered by timestamp (newest first).
        """
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.job_id == job_id, AuditLog.level == LogLevel.ERROR.value)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .all()
        )

    # Export methods

    def export_logs_text(self, job_id: str) -> str:
        """Export all logs for a job as plain text.

        Formats each log entry with timestamp, level, event type, message,
        and any details. Row-specific events include row number prefix.

        Args:
            job_id: UUID of the job.

        Returns:
            Formatted plain text of all log entries.

        Example output:
            [2024-01-23T10:30:45Z] [INFO] [state_change] Job state changed: pending -> running
            [2024-01-23T10:30:46Z] [INFO] [api_call] POST /v1/shipments -> 200
                Request: {"service": "03", ...}
                Response: {"tracking_number": "TRACK001", ...}
        """
        logs = self.get_logs(job_id)
        lines = []

        for log_entry in logs:
            # Build the main log line
            row_prefix = f"[Row {log_entry.row_number}] " if log_entry.row_number else ""
            line = (
                f"[{log_entry.timestamp}] [{log_entry.level}] "
                f"[{log_entry.event_type}] {row_prefix}{log_entry.message}"
            )
            lines.append(line)

            # Add details if present
            if log_entry.details:
                try:
                    details_dict = json.loads(log_entry.details)
                    details_formatted = json.dumps(details_dict, indent=4)
                    # Indent each line of the details
                    for detail_line in details_formatted.split("\n"):
                        lines.append(f"    {detail_line}")
                except json.JSONDecodeError:
                    # If details aren't valid JSON, include as-is
                    lines.append(f"    {log_entry.details}")

        return "\n".join(lines)

    def export_logs_for_download(
        self, job_id: str, job_name: str
    ) -> tuple[str, str]:
        """Generate filename and content for log download.

        Args:
            job_id: UUID of the job.
            job_name: Name of the job (used in filename).

        Returns:
            Tuple of (filename, content) ready for download.
            Filename format: {job_name}_logs_{timestamp}.txt
        """
        # Clean job_name for filesystem
        clean_name = re.sub(r"[^\w\s-]", "", job_name)  # Remove special chars
        clean_name = re.sub(r"\s+", "_", clean_name)  # Replace spaces with underscores
        clean_name = clean_name.strip("_")  # Remove leading/trailing underscores

        # Generate timestamp for filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        filename = f"{clean_name}_logs_{timestamp}.txt"
        content = self.export_logs_text(job_id)

        return filename, content
