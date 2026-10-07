"""Persisted priced preview state shared by conversation and HTTP adapters.

Only quote amounts and safe warnings are stored in job-scoped audit metadata.
Recipient data remains in JobRow; reading a preview never grants execution.
"""

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import AuditLog, Job, JobRow
from src.services.audit_service import AuditService, EventType
from src.services.quote_metadata import project_quote_estimates
from src.services.ups_service_codes import SERVICE_CODE_NAMES, ServiceCode

_PREVIEW_RECORD = "batch_priced_preview"


def preview_checksum(rows: list[Any]) -> str:
    """Bind a preview to the deterministic persisted row selection."""
    serialized = "|".join(f"{r.row_number}:{r.row_checksum}" for r in rows)
    return hashlib.sha256(serialized.encode()).hexdigest()


def save_priced_preview(
    db: Session, job: Job, rows: list[Any], result: dict[str, Any]
) -> None:
    """Persist the quote outcome and arm only an explicitly successful quote."""
    estimates = [
        {
            "row_number": item["row_number"],
            "estimated_cost_cents": item["estimated_cost_cents"],
            "warnings": [item["rate_error"]] if item.get("rate_error") else [],
        }
        for item in result.get("preview_rows", [])
    ]
    estimates = project_quote_estimates(estimates)
    ready = result.get("confirmation_ready") is True and estimates is not None
    job.preview_hash = preview_checksum(rows) if ready else None
    estimates = estimates if estimates is not None else []
    AuditService(db).log_info(
        job_id=job.id,
        event_type=EventType.row_event,
        message=_PREVIEW_RECORD,
        details={
            "confirmation_ready": ready,
            "total_rows": result["total_rows"],
            "additional_rows": result["additional_rows"],
            "total_estimated_cost_cents": result["total_estimated_cost_cents"],
            "preview_rows": estimates,
            "rows_with_warnings": sum(bool(row["warnings"]) for row in estimates),
        },
    )


def get_priced_preview(
    db: Session, job: Job, rows: list[JobRow]
) -> dict[str, Any] | None:
    """Project the persisted quote using the current deterministic row details."""
    record = (
        db.query(AuditLog)
        .filter(AuditLog.job_id == job.id, AuditLog.message == _PREVIEW_RECORD)
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    if record is None or not record.details:
        return None
    result = json.loads(record.details)
    estimates = project_quote_estimates(result.get("preview_rows"))
    if estimates is None:
        return None
    result["preview_rows"] = estimates
    result["job_id"] = job.id
    result["confirmation_ready"] = (
        result.get("confirmation_ready") is True
        and bool(job.preview_hash)
        and job.preview_hash == preview_checksum(rows)
    )
    row_map = {row.row_number: row for row in rows}
    for item in result["preview_rows"]:
        row = row_map.get(item["row_number"])
        try:
            order = json.loads(row.order_data) if row and row.order_data else {}
        except (TypeError, json.JSONDecodeError):
            order = {}
        item.update(
            recipient_name=order.get("ship_to_name", f"Row {item['row_number']}"),
            city_state=f"{order.get('ship_to_city', '')}, {order.get('ship_to_state', '')}",
            service=SERVICE_CODE_NAMES.get(
                order.get("service_code", ServiceCode.GROUND.value), "UPS Ground"
            ),
            order_data=order,
        )
    return result
