"""Bounded private CSV values, separate from upload/source authority.

The profile accepts UTF-8, one optional BOM, commas, doubled double quotes,
LF/CRLF record separators and quoted embedded newlines. It never evaluates
values or mutates process-wide CSV settings. Header uniqueness compares trimmed,
casefolded spellings without changing stored headers. An otherwise single,
unquoted header containing semicolon, tab or pipe is rejected as ambiguous;
quoted literal headers remain CSV. These byte/shape limits are not
a worker deadline or memory sandbox; a future ingress owner supplies those.
JSON/XML-looking leading text and known archive/document signatures are also
excluded by this narrow profile, not by a claim about all valid CSV dialects.
The stdlib reader still consults its ambient field_size_limit; a lowered limit
can reject otherwise in-profile input with a closed error. It is never raised
or changed here, and complete independence from process configuration is not
claimed.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
from dataclasses import dataclass, field

PARSER_PROFILE = "synthetic_csv_v1"
MAX_RAW_BYTES = 1024 * 1024
MAX_NORMALIZED_BYTES = 2 * 1024 * 1024
MAX_DATA_ROWS = 10000
MAX_COLUMNS = 64
MAX_FIELD_BYTES = 16 * 1024

_ERROR_MESSAGES = {
    "upload_incomplete": "CSV content is incomplete.",
    "content_mismatch": "CSV content does not match its declared identity.",
    "unsupported_media_type": "Only the normalized text/csv profile is supported.",
    "invalid_csv": "CSV content is invalid for the supported profile.",
    "source_limit_exceeded": "CSV content exceeds a supported limit.",
}
_UNSUPPORTED_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"\xd0\xcf\x11\xe0",
    b"SQLite format 3\x00",
    b"%PDF-",
)


class CsvSnapshotError(ValueError):
    """A closed rejection with no parser, header, cell or filename context."""

    def __init__(self, code: str):
        if code not in _ERROR_MESSAGES:
            raise ValueError("Unknown CSV rejection code.")
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class CsvSnapshot:
    """An in-memory private snapshot. Never serialize the whole object to models."""

    headers: tuple[str, ...] = field(repr=False)
    rows: tuple[tuple[str, ...], ...] = field(repr=False)
    column_references: tuple[str, ...]
    raw_content_sha256: str = field(repr=False)
    snapshot_identity: str = field(repr=False)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.headers)

    def public_counts(self) -> dict[str, str | int]:
        """Return fixed aggregate metadata, never private schema or identity.

        This grants no source reference, lifetime, ownership or read authority.
        Header mapping and target-model schema configuration remain separate.
        """
        return {
            "format": "csv",
            "row_count": self.row_count,
            "column_count": self.column_count,
        }


def _validate_structure(text: str) -> None:
    """Bound grammar and canonical byte volume before allocating parsed rows."""
    state = "start"
    field_bytes = 0
    columns = 1
    records = 0
    header_width = None
    record_present = False
    alternate_header_delimiter = False
    normalized_bytes = len(PARSER_PROFILE.encode())

    def value_character(char: str) -> None:
        nonlocal field_bytes
        field_bytes += 1 if ord(char) < 128 else len(char.encode("utf-8"))
        if field_bytes > MAX_FIELD_BYTES:
            raise CsvSnapshotError("source_limit_exceeded")

    def finish_field() -> None:
        nonlocal field_bytes, normalized_bytes
        normalized_bytes += 4 + field_bytes
        field_bytes = 0
        if normalized_bytes > MAX_NORMALIZED_BYTES:
            raise CsvSnapshotError("source_limit_exceeded")

    def finish_record() -> None:
        nonlocal records, columns, header_width, normalized_bytes, record_present
        if not record_present:
            raise CsvSnapshotError("invalid_csv")
        finish_field()
        normalized_bytes += 4
        if normalized_bytes > MAX_NORMALIZED_BYTES or records >= MAX_DATA_ROWS + 1:
            raise CsvSnapshotError("source_limit_exceeded")
        if header_width is None:
            # An unquoted single header with alternate separators is ambiguous
            # delimited input. Quoted literal headers remain ordinary CSV.
            if columns == 1 and alternate_header_delimiter:
                raise CsvSnapshotError("invalid_csv")
            header_width = columns
        elif columns != header_width:
            raise CsvSnapshotError("invalid_csv")
        records += 1
        columns = 1
        record_present = False

    index = 0
    while index < len(text):
        char = text[index]
        if state == "quoted":
            if char == '"':
                state = "after_quote"
            else:
                value_character(char)
        elif state == "after_quote" and char == '"':
            value_character(char)
            state = "quoted"
        elif char == ",":
            finish_field()
            columns += 1
            if columns > MAX_COLUMNS:
                raise CsvSnapshotError("source_limit_exceeded")
            record_present = True
            state = "start"
        elif char in "\r\n":
            if char == "\r":
                if index + 1 >= len(text) or text[index + 1] != "\n":
                    raise CsvSnapshotError("invalid_csv")
                index += 1
            finish_record()
            state = "start"
        elif state == "after_quote":
            raise CsvSnapshotError("invalid_csv")
        elif char == '"':
            if state != "start":
                raise CsvSnapshotError("invalid_csv")
            state = "quoted"
            record_present = True
        else:
            if records == 0 and char in ";\t|":
                alternate_header_delimiter = True
            value_character(char)
            record_present = True
            state = "unquoted"
        index += 1
    if state == "quoted":
        raise CsvSnapshotError("invalid_csv")
    if record_present:
        finish_record()
    if records < 2:
        raise CsvSnapshotError("invalid_csv")


def _records(content: bytes) -> tuple[tuple[str, ...], ...]:
    raw = content.removeprefix(b"\xef\xbb\xbf")
    if raw.lstrip().startswith(_UNSUPPORTED_SIGNATURES):
        raise CsvSnapshotError("invalid_csv")
    text = None
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        pass
    # Raise outside exception handlers: no private parser exception context.
    if text is None or text.startswith("\ufeff") or "\x00" in text:
        raise CsvSnapshotError("invalid_csv")
    if text.lstrip().startswith(("{", "[", "<")):
        raise CsvSnapshotError("invalid_csv")
    _validate_structure(text)
    result = None
    try:
        result = tuple(
            tuple(row) for row in csv.reader(io.StringIO(text, newline=""), strict=True)
        )
    except csv.Error:
        pass
    if result is None:
        raise CsvSnapshotError("invalid_csv")
    headers = [header.strip().casefold() for header in result[0]]
    if any(not header for header in headers) or len(set(headers)) != len(headers):
        raise CsvSnapshotError("invalid_csv")
    return result


def parse_csv_snapshot(
    content: bytes,
    *,
    content_length: int,
    content_sha256: str,
    media_type: str,
) -> CsvSnapshot:
    """Parse complete synthetic CSV bytes into exact private string values."""
    if (
        type(content) is not bytes
        or type(content_length) is not int
        or content_length < 0
    ):
        raise CsvSnapshotError("content_mismatch")
    if type(media_type) is not str or media_type != "text/csv":
        raise CsvSnapshotError("unsupported_media_type")
    if len(content) > MAX_RAW_BYTES or content_length > MAX_RAW_BYTES:
        raise CsvSnapshotError("source_limit_exceeded")
    if len(content) < content_length:
        raise CsvSnapshotError("upload_incomplete")
    if len(content) != content_length:
        raise CsvSnapshotError("content_mismatch")
    if (
        type(content_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
    ):
        raise CsvSnapshotError("content_mismatch")
    actual_hash = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_hash, content_sha256):
        raise CsvSnapshotError("content_mismatch")
    records = _records(content)
    digest = hashlib.sha256(PARSER_PROFILE.encode())
    for record in records:
        digest.update(len(record).to_bytes(4, "big"))
        for value in record:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
    return CsvSnapshot(
        raw_content_sha256=actual_hash,
        snapshot_identity=digest.hexdigest(),
        headers=records[0],
        rows=records[1:],
        column_references=tuple(
            f"column_{index:04d}" for index in range(1, len(records[0]) + 1)
        ),
    )
