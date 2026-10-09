"""Bounded private lifecycle metadata, never an upload or public capability."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.source_ingress.csv_snapshot import (
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_NORMALIZED_BYTES,
    MAX_RAW_BYTES,
    PARSER_PROFILE,
)
from src.services.source_ingress.reservation_contracts import (
    ReservationError,
    require_timestamp,
)

MAX_LIFECYCLE_BYTES = 4096
MAX_MANIFEST_BYTES = 8192
MAX_COMPLETED_SNAPSHOTS = 128
MAX_CONTENT_BYTES = 16 * 1024 * 1024
RESERVED_CONTENT_BYTES = MAX_RAW_BYTES + MAX_NORMALIZED_BYTES


def require_private_id(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise ReservationError("invalid_request")


def require_file_identity(value) -> None:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(item) is not int or not 0 <= item < 2**63 for item in value)
    ):
        raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class SnapshotLifecycle:
    reservation_id: str
    attempt_id: str
    generation: int
    state: str
    authorization_expires_at: int
    reserved_content_bytes: int
    raw_basename: str
    normalized_basename: str
    cleanup_pending: bool = True
    raw_identity: tuple[int, int] | None = None
    normalized_identity: tuple[int, int] | None = None
    version: int = 1

    def __post_init__(self) -> None:
        require_private_id(self.reservation_id)
        require_private_id(self.attempt_id)
        require_timestamp(self.generation)
        require_timestamp(self.authorization_expires_at)
        if (
            type(self.state) is not str
            or self.state
            not in {"receiving", "sealed", "parsing", "staged", "complete", "failed"}
            or type(self.reserved_content_bytes) is not int
            or self.reserved_content_bytes != RESERVED_CONTENT_BYTES
            or type(self.raw_basename) is not str
            or self.raw_basename != self.attempt_id + ".raw"
            or type(self.normalized_basename) is not str
            or self.normalized_basename != self.attempt_id + ".normalized"
            or type(self.cleanup_pending) is not bool
            or type(self.version) is not int
            or self.version != 1
        ):
            raise ReservationError("invalid_request")
        for identity in (self.raw_identity, self.normalized_identity):
            if identity is not None:
                require_file_identity(identity)
        if (
            self.raw_identity is not None
            and self.raw_identity == self.normalized_identity
            or self.state in {"sealed", "parsing", "staged", "complete"}
            and (self.raw_identity is None or self.normalized_identity is None)
        ):
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class SnapshotManifest:
    snapshot_id: str
    reservation_id: str
    attempt_id: str
    generation: int
    raw_content_sha256: str
    normalized_sha256: str
    raw_length: int
    normalized_length: int
    row_count: int
    column_count: int
    parser_profile: str
    raw_identity: tuple[int, int]
    normalized_identity: tuple[int, int]
    source_expires_at: int
    version: int = 1

    def __post_init__(self) -> None:
        for value in (self.snapshot_id, self.reservation_id, self.attempt_id):
            require_private_id(value)
        if self.snapshot_id in (self.reservation_id, self.attempt_id):
            raise ReservationError("invalid_request")
        require_timestamp(self.generation)
        require_timestamp(self.source_expires_at)
        for value in (self.raw_content_sha256, self.normalized_sha256):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ReservationError("invalid_request")
        for value, low, high in (
            (self.raw_length, 1, MAX_RAW_BYTES),
            (self.normalized_length, 1, MAX_NORMALIZED_BYTES),
            (self.row_count, 0, MAX_DATA_ROWS),
            (self.column_count, 1, MAX_COLUMNS),
            (self.version, 1, 1),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ReservationError("invalid_request")
        if (
            type(self.parser_profile) is not str
            or self.parser_profile != PARSER_PROFILE
        ):
            raise ReservationError("invalid_request")
        require_file_identity(self.raw_identity)
        require_file_identity(self.normalized_identity)
        if self.raw_identity == self.normalized_identity:
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class SnapshotReceipt:
    snapshot_id: str
    row_count: int
    column_count: int
    source_expires_at: int
    version: int = 1
    format: str = "csv"

    def __post_init__(self):
        require_private_id(self.snapshot_id)
        require_timestamp(self.source_expires_at)
        for value, low, high in (
            (self.row_count, 1, MAX_DATA_ROWS),
            (self.column_count, 1, MAX_COLUMNS),
            (self.version, 1, 1),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ReservationError("invalid_request")
        if type(self.format) is not str or self.format != "csv":
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class AbortReceipt:
    reservation_id: str
    status: str = "aborted"

    def __post_init__(self):
        require_private_id(self.reservation_id)
        if type(self.status) is not str or self.status != "aborted":
            raise ReservationError("invalid_request")


@dataclass(frozen=True, slots=True, repr=False)
class _SnapshotActionValue:
    """Closed immutable facts only; no storage, authority or receiver handle."""

    record: object
    lifecycle: SnapshotLifecycle | None
    manifest: SnapshotManifest | None

    def __post_init__(self):
        from src.services.source_ingress.reservation_contracts import (
            ReservationNamespace,
            ReservationReceipt,
            ReservationRequest,
        )
        from src.services.source_ingress.reservation_store import ReservationRecord

        if type(self.record) is not ReservationRecord:
            raise ReservationError("invalid_request")
        for value, model in (
            (self.record.namespace, ReservationNamespace),
            (self.record.request, ReservationRequest),
            (self.record.receipt, ReservationReceipt),
        ):
            if type(value) is not model:
                raise ReservationError("invalid_request")
            value.__post_init__()
        require_timestamp(self.record.admitted_revision)
        for value, model in (
            (self.lifecycle, SnapshotLifecycle),
            (self.manifest, SnapshotManifest),
        ):
            if value is not None:
                if type(value) is not model:
                    raise ReservationError("invalid_request")
                value.__post_init__()
                if value.reservation_id != self.record.receipt.reservation_id:
                    raise ReservationError("invalid_request")
