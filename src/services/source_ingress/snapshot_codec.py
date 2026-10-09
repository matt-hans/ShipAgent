"""Closed private canonical framing; no storage, source or read authority.

The raw digest is syntax-checked metadata, not verification of absent raw bytes.
Canonical values obey the parser's value profile and retain their exact strings.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from itertools import chain

from src.services.source_ingress.csv_snapshot import (
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_FIELD_BYTES,
    MAX_NORMALIZED_BYTES,
    PARSER_PROFILE,
    CsvSnapshot,
    CsvSnapshotError,
)

_PREFIX = PARSER_PROFILE.encode("ascii")


def _digest(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CsvSnapshotError("content_mismatch")


def _counts(rows: object, columns: object) -> None:
    if type(rows) is not int or type(columns) is not int:
        raise CsvSnapshotError("content_mismatch")
    if rows > MAX_DATA_ROWS or columns > MAX_COLUMNS:
        raise CsvSnapshotError("source_limit_exceeded")
    if rows < 1 or columns < 1:
        raise CsvSnapshotError("invalid_csv")


def _field(value: object) -> bytes:
    if type(value) is not str or "\x00" in value:
        raise CsvSnapshotError("invalid_csv")
    if len(value) > MAX_FIELD_BYTES:
        raise CsvSnapshotError("source_limit_exceeded")
    encoded = None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        pass
    if encoded is None:
        raise CsvSnapshotError("invalid_csv")
    if len(encoded) > MAX_FIELD_BYTES:
        raise CsvSnapshotError("source_limit_exceeded")
    return encoded


def _headers(headers: tuple[str, ...]) -> None:
    normalized = tuple(value.strip().casefold() for value in headers)
    if any(not value for value in normalized) or len(set(normalized)) != len(headers):
        raise CsvSnapshotError("invalid_csv")


def encode_snapshot(snapshot: CsvSnapshot) -> bytes:
    """Validate an exact parser value and emit at most the canonical byte cap."""
    if type(snapshot) is not CsvSnapshot:
        raise CsvSnapshotError("invalid_csv")
    if type(snapshot.headers) is not tuple or type(snapshot.rows) is not tuple:
        raise CsvSnapshotError("invalid_csv")
    _counts(len(snapshot.rows), len(snapshot.headers))
    _digest(snapshot.raw_content_sha256)
    _digest(snapshot.snapshot_identity)
    references = tuple(
        f"column_{index:04d}" for index in range(1, len(snapshot.headers) + 1)
    )
    if (
        type(snapshot.column_references) is not tuple
        or len(snapshot.column_references) != len(references)
        or any(type(value) is not str for value in snapshot.column_references)
        or snapshot.column_references != references
    ):
        raise CsvSnapshotError("invalid_csv")
    content = bytearray(_PREFIX)
    for index, record in enumerate(chain((snapshot.headers,), snapshot.rows)):
        if type(record) is not tuple or len(record) != len(snapshot.headers):
            raise CsvSnapshotError("invalid_csv")
        if len(content) + 4 > MAX_NORMALIZED_BYTES:
            raise CsvSnapshotError("source_limit_exceeded")
        content.extend(len(record).to_bytes(4, "big"))
        for value in record:
            encoded = _field(value)
            if len(content) + 4 + len(encoded) > MAX_NORMALIZED_BYTES:
                raise CsvSnapshotError("source_limit_exceeded")
            content.extend(len(encoded).to_bytes(4, "big"))
            content.extend(encoded)
        if index == 0:
            _headers(record)
    if not hmac.compare_digest(
        hashlib.sha256(content).hexdigest(), snapshot.snapshot_identity
    ):
        raise CsvSnapshotError("content_mismatch")
    return bytes(content)


def decode_snapshot(
    content: bytes,
    *,
    raw_content_sha256: str,
    expected_identity: str,
    row_count: int,
    column_count: int,
) -> CsvSnapshot:
    """Bound every frame before reading it; require exact counts, identity and EOF."""
    if type(content) is not bytes:
        raise CsvSnapshotError("invalid_csv")
    if len(content) > MAX_NORMALIZED_BYTES:
        raise CsvSnapshotError("source_limit_exceeded")
    if not content.startswith(_PREFIX):
        raise CsvSnapshotError("invalid_csv")
    _counts(row_count, column_count)
    _digest(raw_content_sha256)
    _digest(expected_identity)
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_identity):
        raise CsvSnapshotError("content_mismatch")
    offset = len(_PREFIX)

    def read_length() -> int:
        nonlocal offset
        if offset + 4 > len(content):
            raise CsvSnapshotError("invalid_csv")
        value = int.from_bytes(content[offset : offset + 4], "big")
        offset += 4
        return value

    records: list[tuple[str, ...]] = []
    for index in range(row_count + 1):
        width = read_length()
        if width > MAX_COLUMNS:
            raise CsvSnapshotError("source_limit_exceeded")
        if width > (len(content) - offset) // 4:
            raise CsvSnapshotError("invalid_csv")
        if width != column_count:
            raise CsvSnapshotError("invalid_csv")
        values: list[str] = []
        for _ in range(width):
            length = read_length()
            if length > MAX_FIELD_BYTES:
                raise CsvSnapshotError("source_limit_exceeded")
            if offset + length > len(content):
                raise CsvSnapshotError("invalid_csv")
            value = None
            try:
                value = content[offset : offset + length].decode(
                    "utf-8", errors="strict"
                )
            except UnicodeError:
                pass
            if value is None or "\x00" in value:
                raise CsvSnapshotError("invalid_csv")
            offset += length
            values.append(value)
        record = tuple(values)
        if index == 0:
            _headers(record)
        records.append(record)
    if offset != len(content):
        raise CsvSnapshotError("invalid_csv")
    return CsvSnapshot(
        headers=records[0],
        rows=tuple(records[1:]),
        column_references=tuple(
            f"column_{index:04d}" for index in range(1, column_count + 1)
        ),
        raw_content_sha256=raw_content_sha256,
        snapshot_identity=expected_identity,
    )
