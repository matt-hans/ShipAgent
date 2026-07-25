"""Canonical ShipAgent job lifecycle status definitions."""

from enum import Enum
from types import MappingProxyType


class JobStatusEnum(str, Enum):
    """Status values for batch shipping jobs.

    Lifecycle: pending -> running -> completed/failed/cancelled
               running -> paused -> running (on reconnect)
               running -> completed_with_warnings (write-back failure)
    """

    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    completed_with_warnings = "completed_with_warnings"
    failed = "failed"
    cancelled = "cancelled"


JobStatus = JobStatusEnum


class ProviderJobStatus(str, Enum):
    """Provider-safe status vocabulary for hosted job tools."""

    queued = "queued"
    running = JobStatus.running.value
    completed = JobStatus.completed.value
    completed_with_warnings = JobStatus.completed_with_warnings.value
    failed = JobStatus.failed.value
    cancelled = JobStatus.cancelled.value


BACKEND_TO_PROVIDER_JOB_STATUS = MappingProxyType(
    {
        JobStatus.pending: ProviderJobStatus.queued,
        JobStatus.running: ProviderJobStatus.running,
        JobStatus.completed: ProviderJobStatus.completed,
        JobStatus.completed_with_warnings: ProviderJobStatus.completed_with_warnings,
        JobStatus.failed: ProviderJobStatus.failed,
        JobStatus.cancelled: ProviderJobStatus.cancelled,
    }
)

PROVIDER_JOB_STATUS_CODES = tuple(
    status.value for status in BACKEND_TO_PROVIDER_JOB_STATUS.values()
)


def to_provider_job_status(status: JobStatus | str) -> ProviderJobStatus:
    """Map a backend job status to its provider-safe representation."""
    backend_status = JobStatus(status)
    try:
        return BACKEND_TO_PROVIDER_JOB_STATUS[backend_status]
    except KeyError:
        raise ValueError(
            f"Backend job status {backend_status.value!r} is not provider-visible"
        ) from None
